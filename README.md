# AI Travel Savings Agent

A production-grade agentic AI system that autonomously reasons over real financial data to optimize travel decisions. Built with **LangGraph**, **Duffel API** (live flights), **LangChain**, and a **FastAPI + React/Next.js** full-stack interface.

---

## What It Does

Enter your credit/debit cards and trip details. The system:

1. **Fetches live flights** from Duffel API + Google Flights / Kayak / Skyscanner / MakeMyTrip
2. **Scrapes hotels** across 11 platforms (Booking.com, Expedia, Agoda, Marriott, Hilton, IHG, Hyatt, Accor, Radisson, Hotels.com, Airbnb)
3. **Analyzes your cards** using a structured rewards database (25+ cards, effective-cost formula)
4. **Calculates effective cost** per card: `Base Price − Card Reward − Cashback − Discount − Statement Credits − Promo Discounts + Forex + Fees`
5. **Generates AI insights** via Groq / Claude / OpenAI (LLM with structured output)
6. **Produces a rich report** - Markdown + interactive web dashboard with booking links

---

## Architecture

```
LangGraph Pipeline (agents/graph.py)
│
├── plan_node          - log trip + schedule tasks
│
├── fetch_flights_node - [parallel] Duffel API (live) + web scrapers
├── fetch_hotels_node  - [parallel] 11 hotel platforms (Playwright + primp)
├── fetch_context_node - [parallel] weather (wttr.in), attractions (Wikipedia),
│                        city info, exchange rate
│     ↓ fan-in: analyze waits for all three
├── analyze_node       - financial engine + card KB + hotel co-brand perks
│
├── llm_insights_node  - Groq llama-3.3-70b / Claude Haiku / GPT-4o-mini
│                        → structured TravelInsights (Pydantic)
│
└── END → report (Markdown) + recommendations + llm_insights

FastAPI (api/server.py)
├── POST /api/run            → start pipeline, returns session_id
├── WS   /ws/{session_id}   → real-time progress stream (WebSocket)
└── GET  /api/session/{id}  → final report + structured data

Next.js Frontend (frontend/)
├── Step 1: Add cards (name, bank, network, last 4)
├── Step 2: Trip details (origin/destination, dates, currency, hotel dates)
├── Step 3: Live agent progress (WebSocket) → results
│           ├── Full Report (rendered Markdown)
│           ├── AI Insights tab (LLM structured output)
│           ├── Cards tab (effective-cost breakdown per card)
│           └── Flights tab (Duffel live + scrapers with booking links)

CLI (main.py)  ← still works, no web server needed
```

---

## Project Structure

```
trip_agent/
├── agents/
│   ├── graph.py          # LangGraph 6-node pipeline
│   ├── llm.py            # Groq → Claude → OpenAI fallback factory
│   ├── card_agent.py     # Claude-based card offer evaluator
│   ├── travel_agent.py   # Legacy concurrent fetch agent
│   └── comparison_agent.py
├── tools/
│   └── duffel_client.py  # Duffel API (live flight search)
├── financial/
│   └── engine.py         # Effective-cost formula engine
├── api/
│   └── server.py         # FastAPI backend + WebSocket
├── frontend/             # Next.js 14 + Tailwind CSS
│   └── src/
│       ├── app/
│       └── components/
│           ├── TripForm.tsx
│           ├── AgentProgress.tsx
│           └── ReportViewer.tsx
├── pipeline.py           # TripAgent - 4-stage PLAN→FETCH→ANALYZE→REPORT
├── flight_scrapers.py    # Google Flights (fast-flights) + Kayak + Skyscanner + MakeMyTrip
├── hotel_scrapers.py     # Booking.com, Expedia, Agoda, Marriott, Hilton, IHG, Hyatt, …
├── hotel_benefits.py     # Co-brand perk database (Amex FHR, Marriott Bonvoy, Hilton Honors, …)
├── knowledge_base.py     # 25+ card rewards DB (HDFC, SBI, Axis, Chase, Amex, Citi, …)
├── scrapers.py           # Weather (wttr.in), attractions (Wikipedia), exchange rates
├── models.py             # Dataclass models (TripRequest, Card, Offer, …)
├── app.py                # Legacy Flask web frontend
├── main.py               # CLI entry point
├── .env.example          # Environment variable template
└── requirements.txt
```

---

## Quick Start

### 1. Clone and install

```bash
git clone <repo-url>
cd trip_agent
pip install -r requirements.txt
```

Install Playwright browsers (used for JS-rendered scraping):

```bash
playwright install chromium
```

### 2. Set environment variables

Copy the template and fill in the keys you have:

```bash
cp .env.example .env
```

```env
# Required for live flight data
DUFFEL_API_KEY=duffel_live_xxxxxxxxxxxxxxxxxxxx

# At least one LLM key recommended (for AI insights)
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxx        # free tier - fastest
ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxx
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxx
```

> The system works without any LLM key - AI insights section will be skipped.
> Flight scraping works without Duffel - it falls back to Google Flights + other scrapers.

---

## Running

### Option A - Web App (FastAPI + Next.js)

**Terminal 1 - Backend:**

```bash
uvicorn api.server:app --reload --port 8000
```

**Terminal 2 - Frontend:**

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000**

API docs (Swagger): **http://localhost:8000/docs**

---

### Option B - Legacy Flask UI

```bash
python app.py        # → http://localhost:5000
```

---

### Option C - CLI

```bash
python main.py
```

Prompts for cards and trip details interactively, saves `trip_report.md`.

---

### Option D - Google ADK Agent

The project also exposes the same deterministic travel pipeline as a Google ADK agent.
Use this when you want an agent runtime around the existing scrapers/card engine without changing the web app.

```bash
pip install -r requirements.txt
adk web
```

Then select `adk_travel_agent` in the ADK web UI.

Set this in `.env` for Gemini-backed ADK runs:

```env
GOOGLE_API_KEY=AIza-xxxxxxxxxxxxxxxxxxxx
GOOGLE_ADK_MODEL=gemini-flash-latest
```

If ADK returns `429 RESOURCE_EXHAUSTED`, your Google API project has no quota for the selected Gemini model. Fix one of these:

- Enable billing or request quota for the project used by `GOOGLE_API_KEY`.
- Wait for quota reset if the error includes a retry delay.
- Change `GOOGLE_ADK_MODEL` to a model your project has quota for.
- Keep using the normal FastAPI/Next app, which can run with Groq/Anthropic/OpenAI or deterministic fallback instead of Gemini.

ADK tools provided:

| Tool | Purpose |
|------|---------|
| `run_complete_trip_analysis` | Runs the full scraper + card optimizer + report pipeline |
| `search_flights` | Searches flight sources only |
| `search_hotels` | Searches hotel sources only, including Priceline when configured |
| `analyze_card_savings` | Runs deterministic card KB + effective-cost math |

The ADK agent does not replace the current app. It reuses the same backend logic so prices, source status, card savings, and verified tables stay deterministic.

Priceline note: Priceline blocks public headless scraping with captcha in many environments. Actual Priceline hotel prices require a RapidAPI subscription for `PRICELINE_RAPIDAPI_HOST` in `.env`. If that subscription is missing, reports include a direct Priceline search link for manual verification.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/run` | Start pipeline. Body: `TripPayload`. Returns `{session_id}` |
| `WS` | `/ws/{session_id}` | Real-time progress stream. Receives `{type, data}` messages |
| `GET` | `/api/session/{session_id}` | Poll status + full report |
| `GET` | `/api/health` | Returns API key configuration status |
| `POST` | `/api/cards` | Validate card payload |

### `POST /api/run` payload

```json
{
  "cards": [
    {
      "name": "HDFC Regalia",
      "bank": "HDFC",
      "network": "visa",
      "card_type": "credit",
      "number_last4": "1234"
    }
  ],
  "origin": "BLR",
  "destination": "JFK",
  "check_in": "2026-07-01",
  "check_out": "2026-07-15",
  "trip_type": "round-trip",
  "return_date": "2026-07-15",
  "adults": 1,
  "currency": "USD",
  "hotel_check_in": "",
  "hotel_check_out": ""
}
```

> Leave `hotel_check_in` / `hotel_check_out` empty to auto-compute:
> check-in = departure + 1 day (long-haul arrival), check-out = return date.

### WebSocket message types

```
{ "type": "progress", "data": "[FLIGHTS] ✓ Duffel: 18 live results" }
{ "type": "complete",  "data": "<markdown report>",
  "extras": { "llm_insights": {...}, "recommendations": [...], "flights": [...], "hotels": [...] } }
{ "type": "error",     "data": "error message" }
```

---

## Financial Engine

Effective cost formula (`financial/engine.py`):

```
Effective Cost = Base Price
  − Card Reward Value      (reward_pct % of base)
  − Cashback               (cashback_pct % of base)
  − Discount               (discount_pct % of base)
  − Statement Credits      (flat amount)
  − Promo Discounts        (flat amount)
  + Forex / FX Cost        (forex_pct % of base)
  + Fees                   (flat amount)
```

The card knowledge base (`knowledge_base.py`) covers:

- **India:** HDFC Regalia, Infinia, Diners Black, Millennia · SBI Elite, Prime, SimplyClick · Axis Magnus, Burgundy Private · ICICI Emerald, Amazon Pay · Yes First Exclusive
- **US:** Chase Sapphire Preferred / Reserve · Amex Platinum Travel / Gold · Capital One Venture · Citi Premier
- **Fallback:** bank-level averages → network defaults → global conservative estimate

---

## Hotel Co-Brand Perks

`hotel_benefits.py` covers card-chain combinations including:

- Amex Platinum → FHR $100 credit + breakfast + 4 PM checkout (all hotels)
- Amex Platinum → Marriott Bonvoy Gold, Hilton Honors Gold
- Hilton Honors Amex Surpass → 12x points + Gold status
- Marriott Bonvoy Amex → 6x points + Silver Elite
- Chase Sapphire Reserve/Preferred → Chase Travel portal bonuses
- IHG Rewards Premier → Platinum Elite + 4th night free
- HDFC Infinia → Taj Epicure Plus (25% off room rates)
- Capital One Venture X → 10x miles via portal

---

## LLM Agents

All LLM calls use structured output (Pydantic `BaseModel`) for reliable, deterministic responses:

```python
class TravelInsights(BaseModel):
    executive_summary: str
    best_flight_tip: str
    best_hotel_tip: str
    optimal_card_strategy: str
    money_saving_tips: list[str]
    risk_factors: list[str]
```

Provider fallback order: **Groq** (free, 70B model) → **Anthropic Claude Haiku** → **OpenAI GPT-4o-mini**

---

## Flight Sources

| Source | Method | Notes |
|--------|--------|-------|
| Duffel API | REST API | Live fares, real booking, requires API key |
| Google Flights | `fast-flights` (protobuf) | No key needed |
| Kayak | Playwright (headless) | JS-rendered |
| Skyscanner | Playwright + network intercept | API v3 capture |
| MakeMyTrip | Playwright | JS-rendered |

---

## Hotel Sources

Booking.com · Expedia · Hotels.com · Agoda · Airbnb · Marriott · Hilton · IHG · Hyatt · Accor · Radisson

All scrapers use `primp` (TLS fingerprint impersonation) or Playwright where JS rendering is required.

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DUFFEL_API_KEY` | Recommended | Live flight search via Duffel API |
| `GROQ_API_KEY` | Optional | LLM insights (free tier, fastest) |
| `ANTHROPIC_API_KEY` | Optional | LLM insights via Claude |
| `OPENAI_API_KEY` | Optional | LLM insights via GPT-4o-mini |

Get a free Duffel sandbox key at [duffel.com](https://duffel.com).
Get a free Groq key at [console.groq.com](https://console.groq.com/keys).
