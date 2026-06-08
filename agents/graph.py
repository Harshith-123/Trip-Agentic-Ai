"""
Optimised agentic pipeline — maximum token efficiency.

Architecture:
  1. Parallel data collection  (threads, ZERO LLM calls)
     - Flights, Hotels, Weather, City info, Attractions run simultaneously
  2. Rule-based card analysis  (ZERO LLM calls)
  3. ONE LLM call              (compact summary → full markdown report)

Total tokens per run: ~1,800–2,500  (vs ~17,000 with ReAct loop)
Total LLM API calls: 1              (vs 6+ with ReAct loop)

Public API (unchanged — api/server.py needs no edits):
  register_session / unregister_session / run_graph
"""
from __future__ import annotations

import queue
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Any, Optional

from agents.llm import get_llm
from agents.tools import iata_to_city

# ── Session registry ──────────────────────────────────────────────────────────

_session_queues: dict[str, queue.Queue] = {}
_lock = threading.Lock()


def register_session(session_id: str, q: queue.Queue) -> None:
    with _lock:
        _session_queues[session_id] = q


def unregister_session(session_id: str) -> None:
    with _lock:
        _session_queues.pop(session_id, None)


# ── Phase 1: Parallel data collection ────────────────────────────────────────

def _collect_data(trip: dict, captured: dict, emit) -> None:
    """Run all scrapers + context fetchers concurrently. No LLM involved."""
    orig      = trip.get("origin", "")
    dest      = trip.get("destination", "")
    dest_city = iata_to_city(dest)
    dep_date  = trip.get("check_in", "")
    ret_date  = trip.get("return_date", "")
    hotel_in  = trip.get("hotel_check_in")  or dep_date
    hotel_out = trip.get("hotel_check_out") or ret_date or trip.get("check_out", "")
    adults    = int(trip.get("adults", 1))
    currency  = trip.get("currency", "USD")
    t_type    = trip.get("trip_type", "one-way")

    emit(f"[ORCHESTRATOR] Trip: {orig} → {dest} | {dep_date} → {ret_date or trip.get('check_out','')} | {adults} adult(s) | {currency}")
    emit(f"[ORCHESTRATOR] Dispatching flight, hotel, and context agents in parallel...")

    def fetch_flights():
        from flight_scrapers import scrape_all_flights
        emit(f"[FLIGHT AGENT] Starting Duffel API + web scrapers...")
        flights, status = scrape_all_flights(
            orig, dest, dep_date, adults, currency, t_type, ret_date
        )
        captured["flights"]       = flights
        captured["flight_status"] = status
        ob = [f for f in flights if "Return" not in str(f.get("provider", ""))]
        rt = [f for f in flights if "Return"     in str(f.get("provider", ""))]
        emit(f"[FLIGHT AGENT] ✓ {len(flights)} flights ({len(ob)} outbound, {len(rt)} return)")
        for plat, st in status.items():
            icon = "✓" if str(st).startswith("✓") else "✗"
            emit(f"[FLIGHT AGENT] {icon} {plat}: {str(st).lstrip('✓✗ ')}")

    def fetch_hotels():
        from hotel_scrapers import scrape_all_hotels
        emit(f"[HOTEL AGENT] Searching {dest_city} across all platforms...")
        hotels, status = scrape_all_hotels(dest_city, hotel_in, hotel_out, adults, currency)
        captured["hotels"]       = hotels
        captured["hotel_status"] = status
        best = f"{currency} {hotels[0].get('price',0):.0f}/night" if hotels else "none"
        emit(f"[HOTEL AGENT] ✓ {len(hotels)} hotels — cheapest: {best}")
        for plat, st in status.items():
            icon = "✓" if str(st).startswith("✓") else "✗"
            emit(f"[HOTEL AGENT] {icon} {plat}: {str(st).lstrip('✓✗ ')}")

    def fetch_context():
        from scrapers import get_weather, get_city_info, get_attractions, get_exchange_rate
        emit(f"[CONTEXT AGENT] Fetching weather, city info, attractions for {dest_city}...")
        # Call each separately so one failure doesn't block the others
        try:
            captured["weather"] = get_weather(dest_city)
            temp = captured["weather"].get("temp_f", "?")
            emit(f"[CONTEXT AGENT] ✓ Weather: {dest_city} {temp}°F")
        except Exception as e:
            emit(f"[CONTEXT AGENT] ⚠ Weather fetch failed: {e}")
        try:
            captured["city_info"] = get_city_info(dest_city)
            ok = bool(captured["city_info"].get("summary"))
            emit(f"[CONTEXT AGENT] {'✓' if ok else '⚠'} City info {'loaded' if ok else 'unavailable (LLM will use own knowledge)'}")
        except Exception as e:
            emit(f"[CONTEXT AGENT] ⚠ City info failed: {e}")
        try:
            captured["attractions"] = get_attractions(dest_city)
            n = len(captured["attractions"].get("attractions", []))
            emit(f"[CONTEXT AGENT] {'✓' if n else '⚠'} Attractions: {n} found")
        except Exception as e:
            emit(f"[CONTEXT AGENT] ⚠ Attractions fetch failed: {e}")
        if currency.upper() != "USD":
            try:
                captured["exchange_rate"] = get_exchange_rate(currency, "USD")
                rate = captured["exchange_rate"].get("example", "rate unavailable")
                emit(f"[CONTEXT AGENT] ✓ Exchange rate: {rate}")
            except Exception as e:
                emit(f"[CONTEXT AGENT] ⚠ Exchange rate failed: {e}")

    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [pool.submit(fetch_flights), pool.submit(fetch_hotels), pool.submit(fetch_context)]
        for f in as_completed(futs):
            try:
                f.result()
            except Exception as e:
                emit(f"[AGENT] ⚠ Collection error: {e}")


# ── Phase 2: Rule-based card analysis (no LLM) ───────────────────────────────

def _card_net_pct(card: dict) -> float:
    """Estimate net travel benefit % from card metadata — no LLM call."""
    network   = card.get("network", "visa").lower()
    name      = card.get("name", "").lower()
    bank      = card.get("bank", "").lower()
    card_type = card.get("card_type", "credit").lower()
    combined  = f"{name} {bank}"  # check both for network hints

    if card_type == "debit":
        return 0.5

    # Infer network from name/bank when user left dropdown at default "visa"
    if network in ("visa", "mastercard"):
        if any(k in combined for k in ("amex", "american express")):
            network = "amex"
        elif any(k in combined for k in ("diners",)):
            network = "diners"
        elif "rupay" in combined:
            network = "rupay"

    # AMEX — tiered by card level
    if network == "amex":
        if any(k in name for k in ("platinum", "centurion")):       return 5.0
        if any(k in name for k in ("gold", "mrcc")):                return 3.0
        return 2.0

    # Diners Club
    if network == "diners":
        if any(k in name for k in ("black", "premium", "miles")):   return 4.0
        return 2.0

    # RuPay
    if network == "rupay":
        if any(k in name for k in ("select", "platinum")):          return 2.0
        return 1.0

    # Premium Visa / Mastercard — check by well-known card names (most specific first)
    if any(k in name for k in ("infinia", "sapphire reserve", "infinite", "world elite", "atlas", "reserve")):
        return 3.5
    if any(k in name for k in ("regalia", "platinum", "prime", "elite", "signature", "preferred", "sapphire")):
        return 2.5
    if any(k in name for k in ("gold", "premium", "select", "travel", "miles", "air", "freedom")):
        return 2.0

    # Bank-level premium inference (HDFC, Axis, ICICI flagship products)
    if any(k in bank for k in ("hdfc", "axis", "icici", "sbi", "kotak")):
        return 1.5  # Most Indian bank cards have better-than-base rewards

    return 1.0  # standard


def _analyze_cards(trip: dict, captured: dict) -> None:
    """Build structured card recommendations with deterministic KB + math."""
    from financial.engine import compute_effective_cost
    from hotel_benefits import best_hotel_perk
    from knowledge_base import get_card_benefit

    cards      = trip.get("cards", [])
    currency   = trip.get("currency", "USD")
    hotels     = captured.get("hotels", [])
    flights    = captured.get("flights", [])
    hotel_in   = trip.get("hotel_check_in")  or trip.get("check_in", "")
    hotel_out  = trip.get("hotel_check_out") or trip.get("return_date") or trip.get("check_out", "")

    try:
        nights = (date.fromisoformat(hotel_out) - date.fromisoformat(hotel_in)).days
    except Exception:
        nights = 1

    nights = max(1, nights)
    ob = [f for f in flights if "Return" not in str(f.get("provider", ""))]
    rt = [f for f in flights if "Return" in str(f.get("provider", ""))]
    flight_pool = ob or flights
    best_flight = min(flight_pool, key=lambda f: float(f.get("price", 0) or 0), default={})
    best_return = min(rt, key=lambda f: float(f.get("price", 0) or 0), default={})
    best_hotel = hotels[0] if hotels else {}
    outbound_price = float(best_flight.get("price", 0) or 0)
    return_price = float(best_return.get("price", 0) or 0)
    cheapest_flight = round(outbound_price + return_price, 2)
    cheapest_hotel = float(best_hotel.get("price", 0) or 0)
    hotel_total = round(cheapest_hotel * nights, 2)
    trip_total = round(cheapest_flight + hotel_total, 2)
    hotel_chain = _detect_hotel_chain(best_hotel.get("title", "")) if best_hotel else None

    recs = []
    for card in cards:
        name = card.get("name", "")
        bank = card.get("bank", "")
        network = card.get("network", "visa")
        flight_benefit = get_card_benefit(name, bank, network, "flight")
        hotel_benefit = get_card_benefit(name, bank, network, "hotel")
        flight_ec = compute_effective_cost(
            cheapest_flight,
            currency=currency,
            reward_pct=flight_benefit.reward_pct,
            cashback_pct=flight_benefit.cashback_pct,
            discount_pct=flight_benefit.discount_pct,
            forex_pct=flight_benefit.forex_pct,
        )
        hotel_ec = compute_effective_cost(
            hotel_total,
            currency=currency,
            reward_pct=hotel_benefit.reward_pct,
            cashback_pct=hotel_benefit.cashback_pct,
            discount_pct=hotel_benefit.discount_pct,
            forex_pct=hotel_benefit.forex_pct,
        )
        perk_saving, perk = best_hotel_perk(name, bank, network, hotel_chain, hotel_total)
        savings = round(flight_ec.savings + hotel_ec.savings + perk_saving, 2)
        effective_price = round(max(0, trip_total - savings), 2)
        net_pct = round((savings / trip_total) * 100, 2) if trip_total else 0.0
        recs.append({
            "category":        "flight + hotel",
            "item_title":      f"Full trip - {name}",
            "item_price":      round(trip_total, 2),
            "currency":        currency,
            "card":            {"name": name, "bank": bank, "network": network},
            "savings":         savings,
            "effective_price": effective_price,
            "benefit": {
                "reward_pct":    round((flight_benefit.reward_pct + hotel_benefit.reward_pct) / 2, 2),
                "cashback_pct":  round((flight_benefit.cashback_pct + hotel_benefit.cashback_pct) / 2, 2),
                "discount_pct":  round((flight_benefit.discount_pct + hotel_benefit.discount_pct) / 2, 2),
                "forex_pct":     round((flight_benefit.forex_pct + hotel_benefit.forex_pct) / 2, 2),
                "effective_pct": net_pct,
            },
            "components": {
                "flight": {
                    "base_price": cheapest_flight,
                    "outbound_price": outbound_price,
                    "return_price": return_price,
                    "savings": flight_ec.savings,
                    "effective_price": flight_ec.effective_cost,
                    "benefit_pct": flight_benefit.effective_pct,
                    "description": flight_benefit.description,
                    "matched_name": flight_benefit.matched_name,
                },
                "hotel": {
                    "base_price": hotel_total,
                    "per_night": cheapest_hotel,
                    "nights": nights,
                    "savings": hotel_ec.savings,
                    "effective_price": hotel_ec.effective_cost,
                    "benefit_pct": hotel_benefit.effective_pct,
                    "description": hotel_benefit.description,
                    "chain": hotel_chain or "Unknown",
                },
                "hotel_perk": {
                    "savings": perk_saving,
                    "status_level": perk.status_level if perk else "",
                    "perks": perk.perks_list if perk else [],
                    "booking_tip": perk.booking_tip if perk else "",
                },
                "travel_protection": {
                    "lounge": flight_benefit.lounge or hotel_benefit.lounge,
                    "travel_insurance": flight_benefit.travel_insurance or hotel_benefit.travel_insurance,
                },
            },
        })

    captured["recommendations"] = sorted(recs, key=lambda r: r["savings"], reverse=True)


def _detect_hotel_chain(title: str) -> str | None:
    """Lightweight chain detector used by card analysis without importing scrapers."""
    name = title.lower()
    chains = {
        "Marriott": ["marriott", "jw ", "renaissance", "westin", "sheraton", "ritz"],
        "Hilton": ["hilton", "waldorf", "conrad", "doubletree", "hampton"],
        "IHG": ["ihg", "intercontinental", "holiday inn", "crowne plaza"],
        "Hyatt": ["hyatt", "andaz", "park hyatt", "grand hyatt"],
        "Accor": ["accor", "sofitel", "novotel", "ibis", "pullman", "fairmont"],
        "Radisson": ["radisson", "park plaza", "country inn"],
        "Taj": ["taj", "vivanta", "seleqtions"],
    }
    for chain, keywords in chains.items():
        if any(keyword in name for keyword in keywords):
            return chain
    return None


_CURATED_ATTRACTIONS: dict[str, list[str]] = {
    "Chicago": [
        "Millennium Park and Cloud Gate",
        "Art Institute of Chicago",
        "Chicago Architecture River Cruise",
        "Navy Pier",
        "Willis Tower Skydeck",
        "Museum of Science and Industry",
    ],
    "Phoenix": [
        "Desert Botanical Garden",
        "Camelback Mountain",
        "Heard Museum",
        "Papago Park",
        "Musical Instrument Museum",
        "Phoenix Zoo",
    ],
    "Dubai": [
        "Burj Khalifa",
        "Dubai Mall",
        "Museum of the Future",
        "Dubai Creek and Al Fahidi Historical District",
        "Jumeirah Beach",
        "Dubai Marina",
    ],
    "New York": [
        "Central Park",
        "Metropolitan Museum of Art",
        "Statue of Liberty and Ellis Island",
        "Times Square and Broadway",
        "Empire State Building",
        "Brooklyn Bridge",
    ],
}


def _clean_time_text(value: Any) -> str:
    text = str(value or "")
    if len(text) > 10 and text[4:5] == "-" and text[10:11] == "T":
        return text.replace("T", " ", 1)
    return text


# ── Phase 3: Build compact data summary ──────────────────────────────────────

def _build_summary(trip: dict, captured: dict) -> str:
    """Compact plain-text summary of all collected data — fed to the LLM."""
    orig      = trip.get("origin", "")
    dest      = trip.get("destination", "")
    dest_city = iata_to_city(dest)
    currency  = trip.get("currency", "USD")
    t_type    = trip.get("trip_type", "one-way")
    dep_date  = trip.get("check_in", "")
    ret_date  = trip.get("return_date", "")
    hotel_in  = trip.get("hotel_check_in")  or dep_date
    hotel_out = trip.get("hotel_check_out") or ret_date or trip.get("check_out", "")
    adults    = trip.get("adults", 1)

    flights = captured.get("flights", [])
    hotels  = captured.get("hotels",  [])
    weather = captured.get("weather",  {})
    city    = captured.get("city_info",{})
    attr    = captured.get("attractions", {})
    fx      = captured.get("exchange_rate", {})
    recs    = captured.get("recommendations", [])
    f_stat  = captured.get("flight_status", {})
    h_stat  = captured.get("hotel_status",  {})

    try:
        nights = (date.fromisoformat(hotel_out) - date.fromisoformat(hotel_in)).days
    except Exception:
        nights = 1

    ob = [f for f in flights if "Return" not in str(f.get("provider", ""))]
    rt = [f for f in flights if "Return"     in str(f.get("provider", ""))]

    def fmt_flight(f):
        a = f.get("airlines") or f.get("airline") or f.get("provider","")
        d = _clean_time_text(f.get("departure", ""))
        r = _clean_time_text(f.get("arrival", ""))
        return f"{a}|{currency} {f.get('price',0):.0f}|dep {d}|arr {r}|{f.get('duration','?')}|{f.get('stops',0)} stop(s)|{f.get('url','')}"

    def fmt_hotel(h):
        pn = h.get("price", 0)
        return f"{h.get('title','')}|{h.get('provider','')}|{currency} {pn:.0f}/night|total {pn*nights:.0f}|{h.get('url','')}"

    def source_summary(status: dict[str, str]) -> str:
        ok = sum(1 for s in status.values() if str(s).startswith("✓") and "0 results" not in str(s))
        total = len(status)
        return f"{ok}/{total} sources returned usable results" if total else "No source status available"

    # City info — fall back to "use your knowledge" if Wikipedia failed
    city_summary = city.get("summary", "")
    if city_summary and not city_summary.startswith("No info") and "error" not in city:
        city_line = f"CITY: {city_summary[:300]}"
    else:
        city_line = f"CITY_FALLBACK: Use your own knowledge about {dest_city} for the overview."

    # Filter out Wikipedia article names that aren't real attractions
    # (e.g. "Phoenix", "Arizona", "East Valley (Phoenix metropolitan area)")
    _skip = {
        "metropolitan", "area", "county", "state", "province", "region", "district",
        "rat hole", "trolley", "double decker", "company", "list of", "timeline",
    }
    raw_attrs = attr.get("attractions", [])
    curated_attrs = _CURATED_ATTRACTIONS.get(dest_city, [])
    scraped_attrs = [
        a["name"] for a in raw_attrs
        if (
            len(a["name"].split()) >= 2
            and a["name"].lower() != dest_city.lower()
            and not any(w in a["name"].lower() for w in _skip)
        )
    ]
    good_attrs = (curated_attrs or scraped_attrs)[:6]

    if good_attrs:
        attr_line = f"ATTRACTIONS: {', '.join(good_attrs)}"
    else:
        attr_line = f"ATTRACTIONS_FALLBACK: Use your own knowledge to list top 6 real tourist attractions in {dest_city}."

    lines = [
        f"TRIP: {orig}→{dest} ({dest_city}), {t_type}, dep {dep_date}" + (f", ret {ret_date}" if ret_date else ""),
        f"HOTEL: {hotel_in}→{hotel_out} ({nights} nights), {adults} adult(s), {currency}",
        "",
        city_line,
        attr_line,
        "",
        f"CURRENT_WEATHER: {weather.get('temp_f','?')}°F/{weather.get('temp_c','?')}°C, {weather.get('description','')}, humidity {weather.get('humidity_pct','?')}%. Forecast is from the weather source's current 3-day window, not guaranteed trip-date weather.",
        f"FX: {fx.get('example', 'Trip currency is USD or exchange rate unavailable')}",
        f"SOURCE_HEALTH: flights {source_summary(f_stat)}; hotels {source_summary(h_stat)}",
    ]

    # 3-day forecast compact
    for d in weather.get("forecast_3day", []):
        lines.append(f"  {d['date']}: {d['desc']} {d['min_c']}–{d['max_c']}°C")

    # Flight sources — include actual counts so LLM can reproduce them
    lines += ["", "FLIGHT SOURCES:"]
    for p, s in f_stat.items():
        raw = str(s)
        icon = "✓" if raw.startswith("✓") else "⚠" if raw.startswith("⚠") else "✗"
        detail = raw.lstrip("✓⚠✗ ")
        lines.append(f"  {icon} {p}: {detail}")

    # Outbound flights
    lines += ["", f"OUTBOUND FLIGHTS {orig}→{dest} ({len(ob)} found, cheapest first):"]
    lines += [f"  {i+1}. {fmt_flight(f)}" for i, f in enumerate(ob[:10])]

    # Return flights
    if rt:
        lines += ["", f"RETURN FLIGHTS {dest}→{orig} ({len(rt)} found, cheapest first):"]
        lines += [f"  {i+1}. {fmt_flight(f)}" for i, f in enumerate(rt[:6])]

    # Hotel sources — include actual counts
    lines += ["", "HOTEL SOURCES:"]
    for p, s in h_stat.items():
        raw = str(s)
        icon = "✓" if raw.startswith("✓") else "⚠" if raw.startswith("⚠") else "✗"
        detail = raw.lstrip("✓⚠✗ ")
        lines.append(f"  {icon} {p}: {detail}")

    # Hotels
    lines += ["", f"HOTELS IN {dest_city} ({len(hotels)} found, cheapest first):"]
    lines += [f"  {i+1}. {fmt_hotel(h)}" for i, h in enumerate(hotels[:10])]

    # Card analysis
    if recs:
        lines += ["", "CARD ANALYSIS (deterministic KB + effective-cost engine):"]
        for r in recs:
            comp = r.get("components", {})
            flight = comp.get("flight", {})
            hotel = comp.get("hotel", {})
            perk = comp.get("hotel_perk", {})
            protection = comp.get("travel_protection", {})
            lines.append(
                f"  {r['card']['name']} ({r['card']['bank']}): {r['benefit']['effective_pct']:.1f}% net; "
                f"base trip {currency} {r['item_price']:.0f}; saves {currency} {r['savings']:.0f}; "
                f"effective {currency} {r['effective_price']:.0f}; "
                f"flight base {currency} {flight.get('base_price', 0):.0f} "
                f"(outbound {currency} {flight.get('outbound_price', 0):.0f}, return {currency} {flight.get('return_price', 0):.0f}); "
                f"flight save {currency} {flight.get('savings', 0):.0f}; "
                f"hotel save {currency} {hotel.get('savings', 0):.0f}; "
                f"hotel perk save {currency} {perk.get('savings', 0):.0f}; "
                f"lounge {protection.get('lounge', 'Unknown')}; insurance {protection.get('travel_insurance', False)}"
            )
            if flight.get("description"):
                lines.append(f"    Flight logic: {flight['description']}")
            if hotel.get("description"):
                lines.append(f"    Hotel logic: {hotel['description']}")
            if perk.get("booking_tip"):
                lines.append(f"    Hotel perk tip: {perk['booking_tip']}")

    return "\n".join(lines)


# ── Phase 3: Single LLM call ─────────────────────────────────────────────────

_REPORT_PROMPT = """\
You are an autonomous travel-planning and travel-savings agent. Your job is to produce a complete, useful decision report, not a short summary.

Rules:
- Use the DATA below as the source of truth for live prices, source status, dates, card savings, and effective costs.
- Do not invent flight or hotel prices. If a source failed or returned zero results, say that clearly.
- Do not abbreviate with "...".
- Do not generate detailed flight, hotel, or card tables; verified deterministic tables will be appended after your narrative.
- The deterministic system already handled scraping, de-duplication, card math, forex, and hotel perk calculations. Explain those results in plain English.
- Do not recommend Amex FHR/Hotel Collection credits unless CARD ANALYSIS explicitly shows a positive hotel perk saving or eligibility.
- For attractions and itineraries, prefer mainstream traveler-relevant sights. Avoid obscure memes, minor companies, or novelty articles unless the user asks for offbeat attractions.
- Use your own travel knowledge for destination overview, neighborhood/area guidance, visa notes, local transport, booking strategy, safety, and trip tips.
- Be practical and specific. Prefer actionable tradeoffs over generic advice.
- If data is thin, include a confidence note and a concrete next action.

DATA:
{data}

Write the full report now:

# Trip Report: {orig} to {dest} ({ttype})
_{header}_

## Destination Overview
3-5 sentences about {dest_city}: why travelers visit, best areas to stay, and what kind of trip it suits.

## Agent Decision Summary
- Best overall booking path: [state flight/hotel/card combination from DATA]
- Why this is best: [price + card effective cost + source confidence]
- Main risk or uncertainty: [source failures, no return options, thin hotel data, etc.]
- Next action: [what user should book/check first]

## Weather at Destination
Current conditions: [from CURRENT_WEATHER data]. Short forecast from weather source:
[from forecast lines in WEATHER data]
If travel dates are outside the 3-day forecast window, say this is current-season context, not a guaranteed trip-date forecast.

## Data Confidence & Source Health
[Use SOURCE_HEALTH, FLIGHT SOURCES, and HOTEL SOURCES. Explain what was automated, what returned usable results, and where the user should manually verify before paying.]

## Hotel Strategy
- Best value option: [same hotel vs cheapest available options]
- Direct-booking vs OTA advice: [when to prefer direct booking for points/status/perks]
- Area guidance: [best neighborhoods/areas in {dest_city} for first-time visitors, budget, nightlife/business/family as applicable]

## Best Card for This Trip
[Based on CARD ANALYSIS: name the best card, state net benefit%, exact savings in {cur}, effective cost, flight/hotel/perk components, lounge/insurance value, and one sentence why]

## Booking Automation Logic
Explain which parts were deterministic/hardcoded and which parts used AI:
- Deterministic: live scraping/API calls, source status, de-duplication, cheapest ranking, card KB lookup, effective-cost formula, hotel perk calculation.
- AI: destination explanation, tradeoff reasoning, trip strategy, tips, and final narrative.

## Top Attractions in {dest_city}
[6 bullet points with one useful note each — use ATTRACTIONS data if provided, otherwise use your own knowledge of {dest_city}]

## Suggested Mini Itinerary
Create a realistic 2-3 day outline using arrival/departure context if possible. Include morning/afternoon/evening ideas and avoid overpacking the days.

## Travel Tips for {dest_city}
Write 7 specific, actionable tips using your own knowledge:
- Best time to book: [specific advice for {orig}→{dest} route]
- Currency/forex: [specific advice for Indians traveling to {dest_city} with {cur}]
- Weather/packing: based on {cur_weather} — what to pack
- Visa: [Indian passport visa requirements for this destination, if any]
- Getting around: [transport options at {dest_city}]
- Payments/connectivity: [cards, cash, SIM/eSIM]
- Safety/scams: [one destination-specific caution]

## Final Recommendation
End with a concise ranked recommendation: book now / monitor / change dates / check another airport, and why."""


def _generate_report(trip: dict, captured: dict, llm, emit) -> str:
    from langchain_core.messages import HumanMessage

    orig      = trip.get("origin", "")
    dest      = trip.get("destination", "")
    dest_city = iata_to_city(dest)
    currency  = trip.get("currency", "USD")
    t_type    = trip.get("trip_type", "one-way").replace("-", " ").title()
    dep_date  = trip.get("check_in", "")
    ret_date  = trip.get("return_date", "")
    hotel_in  = trip.get("hotel_check_in")  or dep_date
    hotel_out = trip.get("hotel_check_out") or ret_date or trip.get("check_out", "")
    adults    = trip.get("adults", 1)

    try:
        nights = (date.fromisoformat(hotel_out) - date.fromisoformat(hotel_in)).days
    except Exception:
        nights = 1

    weather = captured.get("weather", {})
    cur_weather = f"{weather.get('temp_f','?')}°F, {weather.get('description','')}"

    header = (f"Flight: {dep_date}" + (f" / {ret_date} (return)" if ret_date else "") +
              f" | Hotel: {hotel_in} to {hotel_out} | Adults: {adults} | Currency: {currency}")

    return_section = ""
    if ret_date:
        return_section = (
            f"## Return Flights: {dest} to {orig} on {ret_date} (cheapest first)\n"
            "| # | Airlines | Price | Departs | Arrives | Duration | Stops | Book |\n"
            "|---|----------|-------|---------|---------|----------|-------|------|\n"
            "[rows from RETURN FLIGHTS]\n\n"
        )

    data_summary = _build_summary(trip, captured)

    prompt = _REPORT_PROMPT.format(
        data=data_summary, orig=orig, dest=dest, ttype=t_type,
        header=header, dep=dep_date, cur=currency, nights=nights,
        return_section=return_section, dest_city=dest_city, cur_weather=cur_weather,
    )

    emit("[AGENT] All data collected — generating report with single LLM call...")
    response = llm.invoke([HumanMessage(content=prompt)])
    emit("[AGENT] ✓ Report generated")
    return f"{str(response.content).rstrip()}\n\n{_build_verified_tables(trip, captured)}"


def _md_cell(value: Any) -> str:
    return str(value or "-").replace("|", "/").replace("\n", " ").strip()


def _money(currency: str, value: Any) -> str:
    try:
        return f"{currency} {float(value):.0f}"
    except (TypeError, ValueError):
        return f"{currency} 0"


def _build_verified_tables(trip: dict, captured: dict) -> str:
    """Build factual Markdown tables in code so the LLM cannot omit rows or links."""
    orig = trip.get("origin", "")
    dest = trip.get("destination", "")
    currency = trip.get("currency", "USD")
    dep_date = trip.get("check_in", "")
    ret_date = trip.get("return_date", "")
    hotel_in = trip.get("hotel_check_in") or dep_date
    hotel_out = trip.get("hotel_check_out") or ret_date or trip.get("check_out", "")
    flights = captured.get("flights", [])
    hotels = captured.get("hotels", [])
    recs = captured.get("recommendations", [])
    flight_status = captured.get("flight_status", {})
    hotel_status = captured.get("hotel_status", {})

    try:
        nights = max(1, (date.fromisoformat(hotel_out) - date.fromisoformat(hotel_in)).days)
    except Exception:
        nights = 1

    outbound = [f for f in flights if "Return" not in str(f.get("provider", ""))]
    returns = [f for f in flights if "Return" in str(f.get("provider", ""))]

    def source_lines(status: dict[str, str]) -> list[str]:
        return [f"- {_md_cell(name)}: {_md_cell(state)}" for name, state in status.items()] or ["- No source status available."]

    def flight_row(i: int, f: dict) -> str:
        airline = f.get("airlines") or f.get("airline") or f.get("provider", "")
        dep = _clean_time_text(f.get("departure", "")) or "-"
        arr = _clean_time_text(f.get("arrival", "")) or "-"
        url = f.get("url") or ""
        link = f"[Search ↗]({url})" if url else "Search ↗"
        return (
            f"| {i} | {_md_cell(airline)} | {_money(currency, f.get('price', 0))} | "
            f"{_md_cell(dep)} | {_md_cell(arr)} | {_md_cell(f.get('duration', '-'))} | "
            f"{_md_cell(f.get('stops', 0))} | {link} |"
        )

    def hotel_row(i: int, h: dict) -> str:
        price = float(h.get("price", 0) or 0)
        url = h.get("url") or ""
        link = f"[Book ↗]({url})" if url else "Search ↗"
        return (
            f"| {i} | {_md_cell(h.get('title', ''))} | {_md_cell(h.get('provider', ''))} | "
            f"{_money(currency, price)} | {_money(currency, price * nights)} | {link} |"
        )

    lines = [
        "## Verified Source Results",
        "These tables are generated directly by the application from scraper and card-engine output.",
        "",
        "### Flight Sources Checked",
        *source_lines(flight_status),
        "",
        f"### Outbound Flights: {orig} to {dest} on {dep_date}",
        "| # | Airlines | Price | Departs | Arrives | Duration | Stops | Book |",
        "|---|----------|-------|---------|---------|----------|-------|------|",
    ]
    lines += [flight_row(i, f) for i, f in enumerate(outbound[:15], 1)] or ["| - | No outbound flights found | - | - | - | - | - | - |"]

    if ret_date:
        lines += [
            "",
            f"### Return Flights: {dest} to {orig} on {ret_date}",
            "| # | Airlines | Price | Departs | Arrives | Duration | Stops | Book |",
            "|---|----------|-------|---------|---------|----------|-------|------|",
        ]
        lines += [flight_row(i, f) for i, f in enumerate(returns[:15], 1)] or ["| - | No return flights found | - | - | - | - | - | - |"]

    lines += [
        "",
        "### Hotel Sources Checked",
        *source_lines(hotel_status),
        "",
        f"### Hotels ({nights} night{'s' if nights != 1 else ''})",
        "| # | Hotel | Platform | Per Night | Total | Book |",
        "|---|-------|----------|-----------|-------|------|",
    ]
    lines += [hotel_row(i, h) for i, h in enumerate(hotels[:15], 1)] or ["| - | No hotels found | - | - | - | - |"]

    lines += ["", "### Verified Card Ranking"]
    if recs:
        lines += [
            "| Rank | Card | Bank | Net Benefit | Savings | Effective Cost | Flight Base | Hotel Base | Hotel Perks |",
            "|------|------|------|-------------|---------|----------------|-------------|------------|-------------|",
        ]
        for i, r in enumerate(recs, 1):
            comp = r.get("components", {})
            flight = comp.get("flight", {})
            hotel = comp.get("hotel", {})
            perk = comp.get("hotel_perk", {})
            lines.append(
                f"| {i} | {_md_cell(r['card']['name'])} | {_md_cell(r['card']['bank'])} | "
                f"{r['benefit']['effective_pct']:.1f}% | {_money(currency, r['savings'])} | "
                f"{_money(currency, r['effective_price'])} | {_money(currency, flight.get('base_price', 0))} | "
                f"{_money(currency, hotel.get('base_price', 0))} | {_money(currency, perk.get('savings', 0))} |"
            )
    else:
        lines.append("No card recommendations generated.")

    return "\n".join(lines)


def _generate_fallback_report(trip: dict, captured: dict, emit) -> str:
    """Generate a deterministic Markdown report when no LLM key is configured."""
    orig = trip.get("origin", "")
    dest = trip.get("destination", "")
    dest_city = iata_to_city(dest)
    currency = trip.get("currency", "USD")
    dep_date = trip.get("check_in", "")
    ret_date = trip.get("return_date", "")
    hotel_in = trip.get("hotel_check_in") or dep_date
    hotel_out = trip.get("hotel_check_out") or ret_date or trip.get("check_out", "")
    flights = captured.get("flights", [])
    hotels = captured.get("hotels", [])
    recs = captured.get("recommendations", [])
    weather = captured.get("weather", {})
    attractions = captured.get("attractions", {}).get("attractions", [])
    city_info = captured.get("city_info", {})
    flight_status = captured.get("flight_status", {})
    hotel_status = captured.get("hotel_status", {})
    fx = captured.get("exchange_rate", {})

    try:
        nights = max(1, (date.fromisoformat(hotel_out) - date.fromisoformat(hotel_in)).days)
    except Exception:
        nights = 1

    outbound = [f for f in flights if "Return" not in str(f.get("provider", ""))]
    returns = [f for f in flights if "Return" in str(f.get("provider", ""))]
    top_rec = recs[0] if recs else None

    def flight_row(i: int, f: dict) -> str:
        airline = f.get("airlines") or f.get("airline") or f.get("provider", "")
        dep = str(f.get("departure", ""))[:16].replace("T", " ") or "-"
        arr = str(f.get("arrival", ""))[:16].replace("T", " ") or "-"
        url = f.get("url") or ""
        link = f"[Book]({url})" if url else "Search"
        return f"| {i} | {airline} | {currency} {float(f.get('price', 0)):.0f} | {dep} | {arr} | {f.get('duration', '-')} | {f.get('stops', 0)} | {link} |"

    def hotel_row(i: int, h: dict) -> str:
        price = float(h.get("price", 0))
        url = h.get("url") or ""
        link = f"[Book]({url})" if url else "Search"
        return f"| {i} | {h.get('title', '')} | {h.get('provider', '')} | {currency} {price:.0f} | {currency} {price * nights:.0f} | {link} |"

    lines = [
        f"# Trip Report: {orig} to {dest}",
        f"_{dep_date}{f' to {ret_date}' if ret_date else ''} | Hotel: {hotel_in} to {hotel_out} | {currency}_",
        "",
        "## Agent Decision Summary",
        f"Found {len(outbound)} outbound flights, {len(returns)} return flights, and {len(hotels)} hotel options for {dest_city}.",
    ]

    if top_rec:
        lines.append(
            f"Best card: **{top_rec['card']['name']}** saves about **{currency} {top_rec['savings']:.0f}** "
            f"on an estimated trip cost of {currency} {top_rec['item_price']:.0f}."
        )
    else:
        lines.append("No card recommendation could be calculated from the available price data.")

    if city_info.get("summary"):
        lines += ["", "## Destination Overview", city_info["summary"]]

    lines += [
        "",
        "## Weather & Currency",
        f"Current weather: {weather.get('temp_f', '?')}°F / {weather.get('temp_c', '?')}°C, {weather.get('description', 'unavailable')}.",
        f"Exchange rate: {fx.get('example', 'trip currency is USD or exchange rate unavailable')}.",
    ]
    for day in weather.get("forecast_3day", []):
        lines.append(f"- {day.get('date')}: {day.get('desc')} {day.get('min_c')}-{day.get('max_c')}°C")

    lines += ["", "## Data Confidence & Source Health", "### Flight Sources"]
    lines += [f"- {name}: {status}" for name, status in flight_status.items()] or ["- No flight source status available."]
    lines += ["", "### Hotel Sources"]
    lines += [f"- {name}: {status}" for name, status in hotel_status.items()] or ["- No hotel source status available."]

    lines += [
        "",
        "## Outbound Flights",
        "| # | Airline | Price | Departs | Arrives | Duration | Stops | Book |",
        "|---|---------|-------|---------|---------|----------|-------|------|",
    ]
    lines += [flight_row(i, f) for i, f in enumerate(outbound[:10], 1)] or ["| - | No outbound flights found | - | - | - | - | - | - |"]

    if returns:
        lines += [
            "",
            "## Return Flights",
            "| # | Airline | Price | Departs | Arrives | Duration | Stops | Book |",
            "|---|---------|-------|---------|---------|----------|-------|------|",
        ]
        lines += [flight_row(i, f) for i, f in enumerate(returns[:10], 1)]

    lines += [
        "",
        f"## Hotels ({nights} night{'s' if nights != 1 else ''})",
        "| # | Hotel | Platform | Per Night | Total | Book |",
        "|---|-------|----------|-----------|-------|------|",
    ]
    lines += [hotel_row(i, h) for i, h in enumerate(hotels[:10], 1)] or ["| - | No hotels found | - | - | - | - |"]

    lines += ["", "## Card Ranking"]
    if recs:
        lines += [
            "| Rank | Card | Bank | Net Benefit | Savings | Effective Cost | Details |",
            "|------|------|------|-------------|---------|----------------|---------|",
        ]
        for i, r in enumerate(recs, 1):
            comp = r.get("components", {})
            flight = comp.get("flight", {})
            hotel = comp.get("hotel", {})
            perk = comp.get("hotel_perk", {})
            lines.append(
                f"| {i} | {r['card']['name']} | {r['card']['bank']} | {r['benefit']['effective_pct']:.1f}% | "
                f"{currency} {r['savings']:.0f} | {currency} {r['effective_price']:.0f} | "
                f"Flight {currency} {flight.get('savings', 0):.0f}; hotel {currency} {hotel.get('savings', 0):.0f}; perks {currency} {perk.get('savings', 0):.0f} |"
            )
    else:
        lines.append("No cards were available for ranking.")

    lines += ["", f"## Top Attractions in {dest_city}"]
    if attractions:
        for item in attractions[:6]:
            lines.append(f"- **{item.get('name', '')}**: {item.get('snippet', '')}")
    else:
        lines.append("- Attraction data unavailable. Re-run with internet access or verify manually.")

    lines += [
        "",
        "## Booking Automation Logic",
        "- Deterministic: scraping/API calls, source status, cheapest ranking, card KB lookup, effective-cost formula, and hotel perk calculation.",
        "- AI: skipped in this run because no LLM key is configured.",
        "",
        "## Final Recommendation",
        "Verify the top live fare/hotel once on the booking site, then use the highest-ranked card above for payment. If many sources returned zero results, re-run with nearby dates or another airport before booking.",
    ]

    lines += [
        "",
        "> LLM report generation was skipped because no `GROQ_API_KEY`, `ANTHROPIC_API_KEY`, or `OPENAI_API_KEY` is configured.",
    ]
    emit("[REPORT AGENT] ✓ Fallback report generated without LLM")
    return "\n".join(lines)


# ── Main entry point ──────────────────────────────────────────────────────────

def run_graph(
    trip_dict: dict,
    session_id: str = "",
    progress_queue: Optional[queue.Queue] = None,
) -> dict:
    if progress_queue is None:
        progress_queue = queue.Queue()

    llm = get_llm()

    captured: dict[str, Any] = {
        "flights": [], "hotels": [], "recommendations": [],
        "flight_status": {}, "hotel_status": {},
        "weather": {}, "city_info": {}, "attractions": {}, "exchange_rate": {},
    }

    def emit(msg: str) -> None:
        progress_queue.put({"type": "progress", "data": msg})

    errors: list[str] = []

    try:
        # 1. Collect all data in parallel (no LLM)
        _collect_data(trip_dict, captured, emit)

        # 2. Rule-based card analysis (no LLM)
        _analyze_cards(trip_dict, captured)

        # 3. Single LLM call for the full report, or deterministic fallback.
        if llm is None:
            emit("[LLM INSIGHTS] ⚠ No LLM key configured; using rule-based report fallback")
            final_report = _generate_fallback_report(trip_dict, captured, emit)
        else:
            final_report = _generate_report(trip_dict, captured, llm, emit)

    except Exception as exc:
        import traceback
        errors.append(str(exc))
        emit(f"[AGENT] ✗ Error: {exc}")
        print(f"[Agent] Error for {session_id}:\n{traceback.format_exc()}")
        raise

    return {
        "report":          final_report,
        "recommendations": captured["recommendations"],
        "flights":         captured["flights"][:30],
        "hotels":          captured["hotels"][:30],
        "errors":          errors,
        "progress":        [],
    }
