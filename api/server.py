"""
FastAPI backend - AI Travel Savings Agent.

Endpoints:
  POST /api/run                       - start pipeline, returns {session_id}
  WS   /ws/{session_id}              - real-time progress stream
  GET  /api/session/{session_id}     - poll status + final report
  GET  /api/health                   - health check
  POST /api/cards                    - validate card payload (helper)

Run with:
  uvicorn api.server:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
import uuid
from typing import Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

app = FastAPI(
    title="AI Travel Savings Agent",
    description=(
        "Agentic AI system using LangGraph that autonomously reasons over real financial "
        "data (Duffel API live flights + 11 hotel sources) to optimise travel decisions."
    ),
    version="2.0",
)


@app.on_event("startup")
async def _startup():
    """Start background task to clean up stale sessions every 5 minutes."""

    async def _cleanup_loop():
        while True:
            await asyncio.sleep(300)
            _cleanup_stale_sessions()

    asyncio.create_task(_cleanup_loop())


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Session store ─────────────────────────────────────────────────────────────

_sessions: dict[str, dict[str, Any]] = {}
_sessions_lock = threading.Lock()
_SESSION_TTL = 1800  # 30 minutes


def _get_session(sid: str) -> Optional[dict]:
    with _sessions_lock:
        return _sessions.get(sid)


def _set_session(sid: str, data: dict) -> None:
    with _sessions_lock:
        _sessions[sid] = data


def _cleanup_stale_sessions() -> None:
    """Remove sessions older than TTL to prevent memory leaks."""
    import time
    now = time.time()
    with _sessions_lock:
        stale = [sid for sid, s in _sessions.items()
                 if now - s.get("_created_at", 0) > _SESSION_TTL]
        for sid in stale:
            _sessions.pop(sid, None)


# ─── Pydantic models ───────────────────────────────────────────────────────────

class CardPayload(BaseModel):
    name: str
    bank: str
    network: str
    card_type: str
    number_last4: str


class TripPayload(BaseModel):
    cards: list[CardPayload]
    origin: str
    destination: str
    check_in: str
    check_out: str
    adults: int = Field(default=1, ge=1, le=9)
    currency: str = "USD"
    trip_type: str = "one-way"
    return_date: str = ""
    hotel_check_in: str = ""
    hotel_check_out: str = ""


# ─── Background worker ─────────────────────────────────────────────────────────

def _run_pipeline_bg(session_id: str, trip_payload: TripPayload) -> None:
    """Runs in a background thread; streams progress via Queue."""
    from agents.graph import run_graph, register_session, unregister_session

    q: queue.Queue = queue.Queue()
    register_session(session_id, q)

    # Build trip dict (cards as plain dicts for graph serialisation)
    trip_dict = trip_payload.model_dump()

    try:
        import time
        _set_session(session_id, {
            "status": "running",
            "queue": q,
            "report": "",
            "recommendations": [],
            "flights": [],
            "hotels": [],
            "errors": [],
            "progress": [],
            "_created_at": time.time(),
        })

        result = run_graph(
            trip_dict=trip_dict,
            session_id=session_id,
            progress_queue=q,
        )

        with _sessions_lock:
            _sessions[session_id].update({
                "status": "complete",
                "report":          result.get("report", ""),
                "recommendations": result.get("recommendations", []),
                "flights":         result.get("flights", []),
                "hotels":          result.get("hotels", []),
                "errors":          result.get("errors", []),
                "progress":        result.get("progress", []),
            })
        q.put({
            "type": "complete",
            "data": result.get("report", ""),
            "extras": {
                "recommendations": result.get("recommendations", []),
                "flights":         result.get("flights", [])[:15],
                "hotels":          result.get("hotels", [])[:15],
            },
        })

    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        with _sessions_lock:
            if session_id in _sessions:
                _sessions[session_id]["status"] = "error"
        q.put({"type": "error", "data": str(exc)})
        print(f"[API] Pipeline error for {session_id}:\n{tb}")
    finally:
        unregister_session(session_id)
        # Clean up session data so stale reconnections return "not found"
        with _sessions_lock:
            _sessions.pop(session_id, None)


# ─── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    import os
    return {
        "status": "ok",
        "duffel":    bool(os.getenv("DUFFEL_API_KEY")),
        "groq":      bool(os.getenv("GROQ_API_KEY")),
        "anthropic": bool(os.getenv("ANTHROPIC_API_KEY")),
        "openai":    bool(os.getenv("OPENAI_API_KEY")),
    }


@app.post("/api/run")
async def run_trip(payload: TripPayload):
    """Start the agentic pipeline. Returns a session_id for WebSocket tracking."""
    origin = payload.origin.upper().strip()
    dest   = payload.destination.upper().strip()

    if origin == dest:
        return {"error": "Origin and destination cannot be the same."}
    if len(origin) != 3 or len(dest) != 3:
        return {"error": "Airport codes must be 3 letters (e.g. BLR, JFK, DXB)."}
    if not payload.cards:
        return {"error": "Add at least one card."}

    payload.origin      = origin
    payload.destination = dest

    session_id = str(uuid.uuid4())
    thread = threading.Thread(
        target=_run_pipeline_bg,
        args=(session_id, payload),
        daemon=True,
    )
    thread.start()

    return {"session_id": session_id}


# ─── Shared WebSocket helpers ──────────────────────────────────────────────────

async def _ws_wait_for_session(get_fn, session_id: str,
                                websocket: WebSocket) -> Optional[dict]:
    """Poll up to 3 s for a session to appear. Sends error + closes on timeout."""
    for _ in range(30):
        s = get_fn(session_id)
        if s:
            return s
        await asyncio.sleep(0.1)
    await websocket.send_json({"type": "error", "data": "Session not found"})
    await websocket.close()
    return None


async def _ws_pump(websocket: WebSocket, q: queue.Queue,
                   loop: asyncio.AbstractEventLoop,
                   build_final_msg) -> None:
    """Drain queue messages into websocket; on empty queue call build_final_msg()."""
    try:
        while True:
            try:
                msg = await loop.run_in_executor(None, lambda: q.get(timeout=0.5))
                await websocket.send_json(msg)
                if msg.get("type") in ("complete", "error"):
                    return
            except queue.Empty:
                final = build_final_msg()
                if final:
                    await websocket.send_json(final)
                    return
            except WebSocketDisconnect:
                return
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ─── Agentic WebSocket ─────────────────────────────────────────────────────────

@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """Real-time progress stream via WebSocket."""
    await websocket.accept()
    session = await _ws_wait_for_session(_get_session, session_id, websocket)
    if not session:
        return

    q: queue.Queue = session["queue"]
    loop = asyncio.get_event_loop()

    def _build_final() -> Optional[dict]:
        s = _get_session(session_id)
        if s and s.get("status") in ("complete", "error"):
            return {
                "type":   s["status"],
                "data":   s.get("report", ""),
                "extras": {
                    "recommendations": s.get("recommendations", []),
                    "flights":         s.get("flights", [])[:10],
                    "hotels":          s.get("hotels", [])[:10],
                },
            }
        return None

    await _ws_pump(websocket, q, loop, _build_final)


@app.get("/api/session/{session_id}")
async def get_session(session_id: str):
    """Poll session status and retrieve final report."""
    session = _get_session(session_id)
    if not session:
        return {"status": "not_found"}
    return {k: v for k, v in session.items() if k != "queue"}


@app.post("/api/cards")
async def validate_cards(cards: list[CardPayload]):
    """Validate card payloads (helper for frontend)."""
    return {"ok": True, "count": len(cards)}


# ─── Scraper-only pipeline (no LangGraph / LLM) ────────────────────────────────

_scraper_sessions: dict[str, dict[str, Any]] = {}
_scraper_lock = threading.Lock()


class ScrapePayload(BaseModel):
    origin: str
    destination: str
    date: str
    city: str
    check_in: str
    check_out: str
    adults: int = Field(default=1, ge=1, le=9)
    currency: str = "USD"
    trip_type: str = "one-way"
    return_date: str = ""


def _emit_platform_statuses(emit_fn, tag: str, status_dict: dict) -> None:
    """Emit one progress line per platform, then a summary line."""
    for platform, st in sorted(status_dict.items()):
        icon = "✓" if st.startswith("✓") else "✗"
        emit_fn(f"[{tag}] {icon} {platform}: {st.lstrip('✓✗ ')}")


def _collect_scrape_results(f_fut, h_fut, emit_fn) -> tuple[list, list]:
    """Collect flight + hotel futures as they complete and emit platform progress."""
    from concurrent.futures import as_completed
    flights: list = []
    hotels:  list = []
    for done in as_completed([f_fut, h_fut]):
        if done is f_fut:
            flights, f_status = done.result()
            _emit_platform_statuses(emit_fn, "FLIGHTS", f_status)
            emit_fn(f"[FLIGHTS] Done - {len(flights)} flights found")
        else:
            hotels, h_status = done.result()
            _emit_platform_statuses(emit_fn, "HOTELS ", h_status)
            emit_fn(f"[HOTELS]  Done - {len(hotels)} hotels found")
    return flights, hotels


def _run_scraper_bg(session_id: str, payload: ScrapePayload) -> None:
    """Runs flight + hotel scrapers concurrently, streams progress via Queue."""
    from concurrent.futures import ThreadPoolExecutor
    from flight_scrapers import scrape_all_flights
    from hotel_scrapers import scrape_all_hotels

    q: queue.Queue = queue.Queue()
    import time
    with _scraper_lock:
        _scraper_sessions[session_id] = {"status": "running", "queue": q,
                                         "flights": [], "hotels": [],
                                         "_created_at": time.time()}

    def emit(msg: str) -> None:
        q.put({"type": "progress", "data": msg})

    try:
        emit("[FLIGHTS] Searching Google Flights, Kayak, Skyscanner, MakeMyTrip…")
        emit("[HOTELS]  Searching Booking.com, Expedia, Agoda, Airbnb + chain sites…")

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_fut = pool.submit(scrape_all_flights,
                payload.origin, payload.destination, payload.date,
                payload.adults, payload.currency,
                payload.trip_type, payload.return_date)
            h_fut = pool.submit(scrape_all_hotels,
                payload.city, payload.check_in, payload.check_out,
                payload.adults, payload.currency)
            flights, hotels = _collect_scrape_results(f_fut, h_fut, emit)

        with _scraper_lock:
            _scraper_sessions[session_id].update(
                {"status": "complete", "flights": flights, "hotels": hotels}
            )
        q.put({"type": "complete",
               "data": f"Found {len(flights)} flights and {len(hotels)} hotels.",
               "extras": {"flights": flights[:30], "hotels": hotels[:30]}})

    except Exception as exc:
        import traceback
        print(f"[Scraper] Error for {session_id}:\n{traceback.format_exc()}")
        with _scraper_lock:
            if session_id in _scraper_sessions:
                _scraper_sessions[session_id]["status"] = "error"
        q.put({"type": "error", "data": str(exc)})
    finally:
        # Clean up scraper session so stale reconnections return "not found"
        with _scraper_lock:
            _scraper_sessions.pop(session_id, None)


@app.post("/api/scrape/run")
async def run_scrape(payload: ScrapePayload):
    """Start the scraper-only pipeline (no LangGraph, no LLM). Returns session_id."""
    origin = payload.origin.upper().strip()
    dest   = payload.destination.upper().strip()
    if origin == dest:
        return {"error": "Origin and destination cannot be the same."}
    if len(origin) != 3 or len(dest) != 3:
        return {"error": "Airport codes must be 3 letters (e.g. DEL, JFK)."}
    if not payload.city.strip():
        return {"error": "Hotel city name is required."}

    payload.origin      = origin
    payload.destination = dest

    session_id = str(uuid.uuid4())
    threading.Thread(
        target=_run_scraper_bg,
        args=(session_id, payload),
        daemon=True,
    ).start()
    return {"session_id": session_id}


@app.websocket("/ws/scrape/{session_id}")
async def scrape_websocket(websocket: WebSocket, session_id: str):
    """Real-time progress stream for the scraper pipeline."""
    await websocket.accept()

    def _get_scrape(sid: str) -> Optional[dict]:
        with _scraper_lock:
            return _scraper_sessions.get(sid)

    session = await _ws_wait_for_session(_get_scrape, session_id, websocket)
    if not session:
        return

    q: queue.Queue = session["queue"]
    loop = asyncio.get_event_loop()

    def _build_final() -> Optional[dict]:
        with _scraper_lock:
            s = _scraper_sessions.get(session_id, {})
        if s.get("status") not in ("complete", "error"):
            return None
        fl, ht = s.get("flights", []), s.get("hotels", [])
        return {
            "type":   s["status"],
            "data":   f"Found {len(fl)} flights and {len(ht)} hotels.",
            "extras": {"flights": fl[:30], "hotels": ht[:30]},
        }

    await _ws_pump(websocket, q, loop, _build_final)


@app.get("/api/scrape/session/{session_id}")
async def get_scrape_session(session_id: str):
    """Poll scraper session status and results."""
    with _scraper_lock:
        session = _scraper_sessions.get(session_id)
    if not session:
        return {"status": "not_found"}
    return {k: v for k, v in session.items() if k != "queue"}


# ─── Root ──────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "app": "AI Travel Savings Agent v2",
        "docs": "/docs",
        "modes": {
            "agent":   "POST /api/run  (LangGraph + LLM pipeline)",
            "scraper": "POST /api/scrape/run  (direct scraping, no LLM)",
        },
    }
