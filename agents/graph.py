"""
LangGraph Agentic Pipeline - AI Travel Savings Agent.

Graph topology:

  User Trip Request
          │
          ▼
  Trip Planner / Orchestrator Agent
          │
          ▼
  Runs specialized agents in parallel
          │
  ┌──────────────────────┬──────────────────────┬──────────────────────┐
  │ Flight Agent          │ Hotel Agent           │ Context Agent         │
  │ Finds flights         │ Finds hotels          │ Weather, attractions  │
  │ Compares fares        │ Compares prices       │ city info, forex      │
  └──────────────────────┴──────────────────────┴──────────────────────┘
          │
          ▼
  Card Rewards Agent
  Calculates best card savings for flights/hotels
          │
          ▼
  Validation / Fact-Check Agent
  Checks missing data, invalid prices, weak sources
          │
          ▼
  Final Report Agent
  Combines everything into clean final output
          │
          ▼
        END
"""
from __future__ import annotations

import concurrent.futures
import dataclasses
import json
import operator
import os
import queue
import threading
from typing import Annotated, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

# Module-level session progress registry:  session_id → Queue
_session_queues: dict[str, queue.Queue] = {}
_lock = threading.Lock()


def register_session(session_id: str, q: queue.Queue) -> None:
    with _lock:
        _session_queues[session_id] = q


def unregister_session(session_id: str) -> None:
    with _lock:
        _session_queues.pop(session_id, None)


def _emit(session_id: str, msg: str) -> None:
    with _lock:
        q = _session_queues.get(session_id)
    if q:
        q.put({"type": "progress", "data": msg})
    print(msg)


# ─── State ────────────────────────────────────────────────────────────────────

class TripState(TypedDict):
    # Input
    trip: dict                              # TripRequest fields as dict (includes cards)
    session_id: str                         # For progress streaming

    # Fetched data (populated by flight/hotel/context agents)
    flights: list[dict]
    hotels: list[dict]
    hotels_per_night: list[dict]
    flight_status: dict
    hotel_status: dict
    weather: dict
    attractions: dict
    exchange_rate: dict
    city_info: dict

    # Analysis output (populated by card_rewards_agent node)
    hotel_option_a: dict
    hotel_option_b: list[dict]
    recommendations: list[dict]

    # Validation output (populated by validation_agent node)
    validation_results: dict

    # Report output (populated by final_report_agent node)
    report: str

    # Accumulated progress messages & errors
    progress: Annotated[list[str], operator.add]
    errors:   Annotated[list[str], operator.add]


# ─── Node helpers ─────────────────────────────────────────────────────────────

def _p(state: TripState, msg: str) -> None:
    _emit(state.get("session_id", ""), msg)


# ─── Node: orchestrator ───────────────────────────────────────────────────────

def orchestrator_node(state: TripState) -> dict:
    t = state["trip"]
    msg = (
        f"[ORCHESTRATOR] Trip: {t.get('origin')} → {t.get('destination')}  "
        f"| {t.get('check_in')} → {t.get('check_out')}  "
        f"| {t.get('adults', 1)} adult(s)  | {t.get('currency', 'USD')}"
    )
    _p(state, msg)
    _p(state, "[ORCHESTRATOR] Dispatching flight, hotel, and context agents...")
    return {"progress": [msg]}


# ─── Node: flight_agent ───────────────────────────────────────────────────────

def flight_agent_node(state: TripState) -> dict:
    from tools.duffel_client import DuffelClient
    from flight_scrapers import scrape_all_flights

    t = state["trip"]
    sid = state.get("session_id", "")
    all_flights: list[dict] = []
    status: dict = {}
    errors: list[str] = []

    _emit(sid, "[FLIGHT AGENT] Starting Duffel API + web scrapers...")

    duffel_key = os.getenv("DUFFEL_API_KEY", "")
    if duffel_key:
        try:
            client = DuffelClient(duffel_key)
            duffel_results = client.search_flights(
                t["origin"], t["destination"], t["check_in"],
                adults=t.get("adults", 1),
                currency=t.get("currency", "USD"),
                return_date=t.get("return_date", ""),
            )
            all_flights.extend(duffel_results)
            status["Duffel"] = f"✓ {len(duffel_results)} live results"
            _emit(sid, f"[FLIGHT AGENT] ✓ Duffel: {len(duffel_results)} results")
        except Exception as exc:
            msg = f"Duffel API: {exc}"
            status["Duffel"] = f"✗ {exc}"
            errors.append(msg)
            _emit(sid, f"[FLIGHT AGENT] ✗ Duffel: {exc}")
    else:
        status["Duffel"] = "⚠ DUFFEL_API_KEY not set"
        _emit(sid, "[FLIGHT AGENT] ⚠ Duffel: DUFFEL_API_KEY not set - skipping live API")

    try:
        rows, scraper_status = scrape_all_flights(
            t["origin"], t["destination"], t["check_in"],
            t.get("adults", 1), t.get("currency", "USD"),
            trip=t.get("trip_type", "one-way"),
            return_date=t.get("return_date", ""),
        )
        all_flights.extend(rows)
        status.update(scraper_status)
        total_scraper = sum(
            1 for s in scraper_status.values() if s.startswith("✓")
        )
        _emit(sid, f"[FLIGHT AGENT] ✓ Scrapers: {len(rows)} results from {total_scraper}/{len(scraper_status)} sources")
    except Exception as exc:
        errors.append(f"Flight scrapers: {exc}")
        _emit(sid, f"[FLIGHT AGENT] ✗ Scrapers failed: {exc}")

    _emit(sid, f"[FLIGHT AGENT] Complete - {len(all_flights)} total flights found")
    return {
        "flights": all_flights,
        "flight_status": status,
        "progress": [f"Flights fetched: {len(all_flights)}"],
        "errors": errors,
    }


# ─── Node: hotel_agent ────────────────────────────────────────────────────────

def hotel_agent_node(state: TripState) -> dict:
    from hotel_scrapers import scrape_all_hotels, scrape_hotels_per_night
    from pipeline import TripAgent

    t = state["trip"]
    sid = state.get("session_id", "")
    city = TripAgent._city_name(t["destination"])
    h_in  = t.get("hotel_check_in")  or t["check_in"]
    h_out = t.get("hotel_check_out") or t["check_out"]

    _emit(sid, f"[HOTEL AGENT] Searching {city} ({h_in} → {h_out}) across 11 platforms...")

    errors: list[str] = []
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f_all = pool.submit(
                scrape_all_hotels, city, h_in, h_out,
                t.get("adults", 1), t.get("currency", "USD"),
            )
            f_per = pool.submit(
                scrape_hotels_per_night, city, h_in, h_out,
                t.get("adults", 1), t.get("currency", "USD"),
            )
            rows, status = f_all.result()
            per_night = f_per.result()

        hits = sum(1 for s in status.values() if s.startswith("✓"))
        _emit(sid, f"[HOTEL AGENT] ✓ {len(rows)} options from {hits}/{len(status)} platforms")
        _emit(sid, f"[HOTEL AGENT] ✓ Per-night breakdown: {len(per_night)} night(s)")
    except Exception as exc:
        rows, status, per_night = [], {}, []
        errors.append(f"Hotel scrapers: {exc}")
        _emit(sid, f"[HOTEL AGENT] ✗ {exc}")

    return {
        "hotels": rows,
        "hotels_per_night": per_night,
        "hotel_status": status,
        "progress": [f"Hotels fetched: {len(rows)}"],
        "errors": errors,
    }


# ─── Node: context_agent ──────────────────────────────────────────────────────

def context_agent_node(state: TripState) -> dict:
    from scrapers import get_weather, get_attractions, get_exchange_rate, get_city_info
    from pipeline import TripAgent

    t = state["trip"]
    sid = state.get("session_id", "")
    city = TripAgent._city_name(t["destination"])

    _emit(sid, f"[CONTEXT AGENT] Fetching weather, attractions, city info for {city}...")

    results: dict = {"weather": {}, "attractions": {}, "city_info": {}, "exchange_rate": {}}
    tasks = {
        "weather":     lambda: get_weather(city),
        "attractions": lambda: get_attractions(city),
        "city_info":   lambda: get_city_info(city),
    }
    if t.get("currency", "USD").upper() != "USD":
        tasks["exchange_rate"] = lambda: get_exchange_rate(t["currency"], "USD")

    errors: list[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(fn): key for key, fn in tasks.items()}
        for fut in concurrent.futures.as_completed(futs):
            key = futs[fut]
            try:
                results[key] = fut.result()
            except Exception as exc:
                results[key] = {"error": str(exc)}
                errors.append(f"{key}: {exc}")

    _emit(sid, f"[CONTEXT AGENT] ✓ Weather, attractions, city info loaded")
    return {
        "weather":       results["weather"],
        "attractions":   results["attractions"],
        "city_info":     results["city_info"],
        "exchange_rate": results["exchange_rate"],
        "progress": ["Context data fetched"],
        "errors": errors,
    }


# ─── Node: data_merge ─────────────────────────────────────────────────────────

# ─── Node: card_rewards_agent ─────────────────────────────────────────────────

def card_rewards_agent_node(state: TripState) -> dict:
    from models import TripRequest, Card
    from pipeline import TripAgent, CardRec

    t = state["trip"]
    sid = state.get("session_id", "")

    total_flights = len(state.get("flights", []))
    total_hotels  = len(state.get("hotels", []))
    flight_sources = sum(1 for s in state.get("flight_status", {}).values() if s.startswith("✓"))
    hotel_sources  = sum(1 for s in state.get("hotel_status", {}).values() if s.startswith("✓"))
    _emit(sid, f"[CARD REWARDS AGENT] Processing {total_flights} flights from {flight_sources} sources, "
               f"{total_hotels} hotels from {hotel_sources} sources...")
    _emit(sid, "[CARD REWARDS AGENT] Applying financial engine + card knowledge base...")

    trip = TripRequest(
        cards=[Card(**c) for c in t.get("cards", [])],
        origin=t["origin"],
        destination=t["destination"],
        check_in=t["check_in"],
        check_out=t["check_out"],
        adults=t.get("adults", 1),
        currency=t.get("currency", "USD"),
        trip_type=t.get("trip_type", "one-way"),
        return_date=t.get("return_date", ""),
        hotel_check_in=t.get("hotel_check_in", ""),
        hotel_check_out=t.get("hotel_check_out", ""),
    )

    def _cb(msg: str) -> None:
        _emit(sid, msg)

    agent = TripAgent(trip, progress_callback=_cb)
    from pipeline import FlightResult, HotelResult

    agent.state.flights = [
        FlightResult(
            title=r.get("title", ""),
            provider=r.get("provider", ""),
            price=float(r.get("price", 0)),
            currency=r.get("currency", trip.currency),
            details={k: r[k] for k in ("departure", "arrival", "duration", "stops") if k in r},
            url=r.get("url", ""),
        )
        for r in state.get("flights", [])
    ]
    agent.state.hotels = [
        HotelResult(
            title=r.get("title", ""),
            provider=r.get("provider", ""),
            price=float(r.get("price", 0)),
            currency=r.get("currency", trip.currency),
            url=r.get("url", ""),
        )
        for r in state.get("hotels", [])
    ]
    agent.state.hotels_per_night      = state.get("hotels_per_night", [])
    agent.state.flight_platform_status = state.get("flight_status", {})
    agent.state.hotel_platform_status  = state.get("hotel_status", {})
    agent.state.weather       = state.get("weather", {})
    agent.state.attractions   = state.get("attractions", {})
    agent.state.exchange_rate = state.get("exchange_rate", {})
    agent.state.city_info     = state.get("city_info", {})

    recs = agent.analyze()

    recs_dicts = [
        {
            "category":       rec.category,
            "item_title":     rec.item_title,
            "item_price":     rec.item_price,
            "currency":       rec.currency,
            "card":           dataclasses.asdict(rec.card),
            "savings":        rec.savings,
            "effective_price": rec.effective_price,
            "benefit":        dataclasses.asdict(rec.benefit),
        }
        for rec in recs
    ]

    def _safe(v):
        if hasattr(v, "__dataclass_fields__"):
            return dataclasses.asdict(v)
        return v

    opt_a = {k: _safe(v) for k, v in agent.state.hotel_option_a.items()} \
        if agent.state.hotel_option_a else {}

    _emit(sid, f"[CARD REWARDS AGENT] ✓ {len(recs)} card recommendations generated")
    return {
        "recommendations": recs_dicts,
        "hotel_option_a": opt_a,
        "hotel_option_b": agent.state.hotel_option_b,
        "progress": [f"Card rewards analysis complete: {len(recs)} recommendations"],
    }


# ─── Node: validation_agent ───────────────────────────────────────────────────

def validation_agent_node(state: TripState) -> dict:
    sid = state.get("session_id", "")
    errors: list[str] = list(state.get("errors", []))
    warnings: list[str] = []

    if len(state.get("flights", [])) == 0:
        warnings.append("No flight results found - check internet or airport codes")
    if len(state.get("hotels", [])) == 0:
        hotel_status = state.get("hotel_status", {})
        pw_missing = any("Playwright" in v for v in hotel_status.values())
        if pw_missing:
            warnings.append("Hotel scrapers require Playwright + system deps (libnspr4, libnss3). Run: playwright install chromium")
        else:
            warnings.append("No hotel results found - check internet or city name")
    weather = state.get("weather", {})
    if not weather or weather.get("error"):
        warnings.append("Weather data unavailable")
    if not state.get("recommendations"):
        warnings.append("No card recommendations generated - check your card list")
    else:
        _emit(sid, f"[VALIDATION AGENT] ✓ {len(state['recommendations'])} recommendations validated")

    validation = {
        "status": "passed" if not errors else "has_errors",
        "error_count": len(errors),
        "warning_count": len(warnings),
        "warnings": warnings,
        "errors": errors,
    }

    if warnings:
        for w in warnings:
            _emit(sid, f"[VALIDATION AGENT] ⚠ {w}")

    if errors:
        _emit(sid, f"[VALIDATION AGENT] ✗ {len(errors)} error(s) found")
    else:
        _emit(sid, "[VALIDATION AGENT] ✓ All data validated successfully")

    return {
        "validation_results": validation,
        "progress": [f"Validation: {validation['status']} ({len(warnings)} warnings, {len(errors)} errors)"],
    }


# ─── Node: final_report_agent ─────────────────────────────────────────────────

def final_report_agent_node(state: TripState) -> dict:
    from models import TripRequest, Card
    from pipeline import TripAgent, CardRec, FlightResult, HotelResult
    from knowledge_base import CardBenefit
    from agents.llm import get_llm, available_provider

    sid = state.get("session_id", "")
    _emit(sid, "[FINAL REPORT AGENT] Generating final trip report...")

    t = state["trip"]

    trip = TripRequest(
        cards=[Card(**c) for c in t.get("cards", [])],
        origin=t["origin"],
        destination=t["destination"],
        check_in=t["check_in"],
        check_out=t["check_out"],
        adults=t.get("adults", 1),
        currency=t.get("currency", "USD"),
        trip_type=t.get("trip_type", "one-way"),
        return_date=t.get("return_date", ""),
        hotel_check_in=t.get("hotel_check_in", ""),
        hotel_check_out=t.get("hotel_check_out", ""),
    )

    agent = TripAgent(trip)
    agent.state.flights = [
        FlightResult(
            title=r.get("title", ""),
            provider=r.get("provider", ""),
            price=float(r.get("price", 0)),
            currency=r.get("currency", trip.currency),
            details={k: r[k] for k in ("departure", "arrival", "duration", "stops") if k in r},
            url=r.get("url", ""),
        )
        for r in state.get("flights", [])
    ]
    agent.state.hotels = [
        HotelResult(
            title=r.get("title", ""),
            provider=r.get("provider", ""),
            price=float(r.get("price", 0)),
            currency=r.get("currency", trip.currency),
            url=r.get("url", ""),
        )
        for r in state.get("hotels", [])
    ]
    agent.state.hotels_per_night      = state.get("hotels_per_night", [])
    agent.state.flight_platform_status = state.get("flight_status", {})
    agent.state.hotel_platform_status  = state.get("hotel_status", {})
    agent.state.weather       = state.get("weather", {})
    agent.state.attractions   = state.get("attractions", {})
    agent.state.exchange_rate = state.get("exchange_rate", {})
    agent.state.city_info     = state.get("city_info", {})

    # Reconstruct CardRec objects from serialized dicts
    recs: list[CardRec] = []
    for rd in state.get("recommendations", []):
        try:
            benefit_dict = rd.get("benefit", {})
            benefit = CardBenefit(
                reward_pct=float(benefit_dict.get("reward_pct", 0)),
                cashback_pct=float(benefit_dict.get("cashback_pct", 0)),
                discount_pct=float(benefit_dict.get("discount_pct", 0)),
                forex_pct=float(benefit_dict.get("forex_pct", 0)),
                effective_pct=float(benefit_dict.get("effective_pct", 0)),
                lounge=benefit_dict.get("lounge", ""),
                travel_insurance=bool(benefit_dict.get("travel_insurance", False)),
                description=benefit_dict.get("description", ""),
                matched_name=benefit_dict.get("matched_name", ""),
            )
            card_dict = rd.get("card", {})
            card = Card(
                name=card_dict.get("name", ""),
                bank=card_dict.get("bank", ""),
                network=card_dict.get("network", ""),
                card_type=card_dict.get("card_type", "credit"),
                number_last4=card_dict.get("number_last4", ""),
            )
            rec = CardRec(
                category=rd.get("category", ""),
                item_title=rd.get("item_title", ""),
                item_price=float(rd.get("item_price", 0)),
                currency=rd.get("currency", trip.currency),
                card=card,
                benefit=benefit,
                savings=float(rd.get("savings", 0)),
                effective_price=float(rd.get("effective_price", 0)),
            )
            recs.append(rec)
        except (ValueError, TypeError) as e:
            _emit(sid, f"[FINAL REPORT AGENT] ⚠ Skipping malformed recommendation: {e}")

    # Generate AI insights (if LLM available)
    provider = available_provider()
    llm_insights = {}
    if provider != "none":
        _emit(sid, f"[FINAL REPORT AGENT] Generating AI travel insights via {provider}...")
        try:
            from pydantic import BaseModel
            class TravelInsights(BaseModel):
                executive_summary: str
                best_flight_tip: str
                best_hotel_tip: str
                optimal_card_strategy: str
                money_saving_tips: list[str]
                risk_factors: list[str]
            llm = get_llm()
            if llm:
                flights_sample = state.get("flights", [])[:5]
                hotels_sample  = state.get("hotels", [])[:5]
                prompt = f"""You are a financial travel advisor specializing in credit card optimization.
    TRIP: {t.get('origin')} → {t.get('destination')}
    DATES: {t.get('check_in')} → {t.get('check_out')}
    ADULTS: {t.get('adults', 1)} | CURRENCY: {t.get('currency', 'USD')}
    TOP FLIGHTS: {json.dumps([{k: v for k, v in f.items() if k in ('provider','price','currency','stops')} for f in flights_sample], indent=2)}
    TOP HOTELS: {json.dumps([{k: v for k, v in h.items() if k in ('title','provider','price')} for h in hotels_sample], indent=2)}
    Be concise. Focus on savings."""
                structured = llm.with_structured_output(TravelInsights)
                llm_insights = structured.invoke(prompt).model_dump()
                _emit(sid, f"[FINAL REPORT AGENT] ✓ AI insights generated via {provider}")
        except Exception as exc:
            _emit(sid, f"[FINAL REPORT AGENT] ⚠ LLM insights skipped: {exc}")
    else:
        _emit(sid, "[FINAL REPORT AGENT] ⚠ No LLM API key - skipping AI insights")

    report = agent.report(recs, llm_insights)

    _emit(sid, f"[FINAL REPORT AGENT] ✓ Report generated ({len(report)} chars)")
    return {
        "report": report,
        "progress": ["Final report generated"],
    }


# ─── Build and compile the graph ──────────────────────────────────────────────

def _build_graph() -> StateGraph:
    builder = StateGraph(TripState)

    builder.add_node("orchestrator",       orchestrator_node)
    builder.add_node("flight_agent",       flight_agent_node)
    builder.add_node("hotel_agent",        hotel_agent_node)
    builder.add_node("context_agent",      context_agent_node)
    builder.add_node("card_rewards_agent", card_rewards_agent_node)
    builder.add_node("validation_agent",   validation_agent_node)
    builder.add_node("final_report_agent", final_report_agent_node)

    # Orchestrator → parallel agents
    builder.add_edge(START,              "orchestrator")
    builder.add_edge("orchestrator",     "flight_agent")
    builder.add_edge("orchestrator",     "hotel_agent")
    builder.add_edge("orchestrator",     "context_agent")

    # Fan-in: all three parallel agents → card_rewards_agent
    builder.add_edge("flight_agent",      "card_rewards_agent")
    builder.add_edge("hotel_agent",       "card_rewards_agent")
    builder.add_edge("context_agent",     "card_rewards_agent")

    # Sequential pipeline
    builder.add_edge("card_rewards_agent", "validation_agent")
    builder.add_edge("validation_agent",   "final_report_agent")
    builder.add_edge("final_report_agent", END)

    return builder.compile()


trip_graph = _build_graph()


# ─── Public entry point ───────────────────────────────────────────────────────

def run_graph(
    trip_dict: dict,
    session_id: str = "",
    progress_queue: Optional[queue.Queue] = None,
) -> dict:
    """
    Run the LangGraph agentic pipeline.

    Args:
        trip_dict       - TripRequest fields as a dict (must include 'cards' list)
        session_id      - used to route progress events; auto-generated if not given
        progress_queue  - optional Queue; progress events pushed as {"type":"progress","data":msg}

    Returns the final TripState dict (includes 'report', 'recommendations', 'llm_insights', …).
    """
    import uuid
    sid = session_id or str(uuid.uuid4())

    if progress_queue is not None:
        register_session(sid, progress_queue)

    initial: TripState = {
        "trip":          trip_dict,
        "session_id":    sid,
        "flights":       [],
        "hotels":        [],
        "hotels_per_night": [],
        "flight_status": {},
        "hotel_status":  {},
        "weather":       {},
        "attractions":   {},
        "exchange_rate": {},
        "city_info":     {},
        "hotel_option_a": {},
        "hotel_option_b": [],
        "recommendations": [],
        "validation_results": {},
        "report":        "",
        "progress":      [],
        "errors":        [],
    }

    try:
        final = trip_graph.invoke(initial)
    finally:
        if progress_queue is not None:
            unregister_session(sid)

    return dict(final)
