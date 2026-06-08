"""
LangChain tools for the ReAct agent.

Design for token efficiency:
- Tools return compact PLAIN TEXT, not JSON.
- Full structured data is saved in `captured` for the frontend.
- The LLM only sees summaries — just enough to write the report.
"""
from __future__ import annotations

from datetime import date
from typing import Any

try:
    from langchain_core.tools import tool
except ImportError:  # Allows iata_to_city() to work without LangChain installed.
    tool = None


# ── IATA → city name ──────────────────────────────────────────────────────────

_IATA: dict[str, str] = {
    "PHX": "Phoenix", "LAX": "Los Angeles", "JFK": "New York", "LGA": "New York",
    "EWR": "Newark", "ORD": "Chicago", "MDW": "Chicago", "ATL": "Atlanta",
    "DFW": "Dallas", "DAL": "Dallas", "DEN": "Denver", "SFO": "San Francisco",
    "OAK": "Oakland", "SJC": "San Jose", "SEA": "Seattle", "LAS": "Las Vegas",
    "MIA": "Miami", "FLL": "Fort Lauderdale", "BOS": "Boston", "DCA": "Washington DC",
    "IAD": "Washington DC", "BWI": "Baltimore", "IAH": "Houston", "HOU": "Houston",
    "MSP": "Minneapolis", "DTW": "Detroit", "CLT": "Charlotte", "PHL": "Philadelphia",
    "SLC": "Salt Lake City", "PDX": "Portland", "AUS": "Austin", "SAN": "San Diego",
    "TPA": "Tampa", "MCO": "Orlando", "MSY": "New Orleans", "STL": "St. Louis",
    "BNA": "Nashville", "RDU": "Raleigh", "CMH": "Columbus", "HNL": "Honolulu",
    "ANC": "Anchorage", "YYZ": "Toronto", "YVR": "Vancouver", "YUL": "Montreal",
    "MEX": "Mexico City",
    "BLR": "Bengaluru", "DEL": "New Delhi", "BOM": "Mumbai", "HYD": "Hyderabad",
    "MAA": "Chennai", "CCU": "Kolkata", "AMD": "Ahmedabad", "PNQ": "Pune",
    "COK": "Kochi", "GOI": "Goa", "JAI": "Jaipur", "ATQ": "Amritsar",
    "LHR": "London", "LGW": "London", "CDG": "Paris", "ORY": "Paris",
    "AMS": "Amsterdam", "FRA": "Frankfurt", "MUC": "Munich", "ZRH": "Zurich",
    "VIE": "Vienna", "FCO": "Rome", "MXP": "Milan", "BCN": "Barcelona",
    "MAD": "Madrid", "LIS": "Lisbon", "BRU": "Brussels", "CPH": "Copenhagen",
    "ARN": "Stockholm", "OSL": "Oslo", "HEL": "Helsinki", "WAW": "Warsaw",
    "PRG": "Prague", "BUD": "Budapest", "ATH": "Athens", "IST": "Istanbul",
    "DXB": "Dubai", "AUH": "Abu Dhabi", "DOH": "Doha", "KWI": "Kuwait City",
    "BAH": "Bahrain", "RUH": "Riyadh", "JED": "Jeddah",
    "SIN": "Singapore", "KUL": "Kuala Lumpur", "BKK": "Bangkok", "HKG": "Hong Kong",
    "NRT": "Tokyo", "HND": "Tokyo", "KIX": "Osaka", "ICN": "Seoul",
    "PEK": "Beijing", "PVG": "Shanghai", "CGK": "Jakarta", "MNL": "Manila",
    "SGN": "Ho Chi Minh City", "HAN": "Hanoi",
    "SYD": "Sydney", "MEL": "Melbourne", "BNE": "Brisbane", "PER": "Perth",
    "AKL": "Auckland",
    "JNB": "Johannesburg", "CPT": "Cape Town", "CAI": "Cairo", "NBO": "Nairobi",
    "GRU": "São Paulo", "EZE": "Buenos Aires", "BOG": "Bogotá", "SCL": "Santiago",
}


def iata_to_city(code: str) -> str:
    return _IATA.get(code.upper(), code)


# ── Tool factory ───────────────────────────────────────────────────────────────

def make_trip_tools(trip: dict, cards: list[dict], captured: dict[str, Any]) -> list:
    """
    Returns 6 tools bound to this trip's context.
    `captured` is mutated during execution to store full data for the frontend.
    All tools return compact plain text — not JSON — to minimise input tokens.
    """
    if tool is None:
        raise RuntimeError("LangChain is required for dynamic tool creation. Install langchain-core.")

    currency = trip.get("currency", "USD")
    adults   = int(trip.get("adults", 1))

    # ── 1. Flights ────────────────────────────────────────────────────────────

    @tool
    def search_flights(
        origin: str,
        destination: str,
        departure_date: str,
        trip_type: str = "one-way",
        return_date: str = "",
    ) -> str:
        """Search for flights. Returns a compact text summary.

        Args:
            origin: IATA code e.g. 'BLR'
            destination: IATA code e.g. 'PHX'
            departure_date: YYYY-MM-DD
            trip_type: 'one-way' or 'round-trip'
            return_date: YYYY-MM-DD for round-trip, else empty
        """
        from flight_scrapers import scrape_all_flights
        flights, status = scrape_all_flights(
            origin.upper(), destination.upper(), departure_date,
            adults, currency, trip_type, return_date,
        )
        captured["flights"]        = flights
        captured["flight_status"]  = status

        ob = [f for f in flights if "Return" not in str(f.get("provider", ""))]
        rt = [f for f in flights if "Return"     in str(f.get("provider", ""))]

        def _line(f: dict) -> str:
            airline = f.get("airlines") or f.get("airline") or f.get("provider", "")
            dep = str(f.get("departure", ""))[:16].replace("T", " ")
            arr = str(f.get("arrival",   ""))[:16].replace("T", " ")
            return (f"{airline}: {currency} {f['price']:.0f} | "
                    f"dep {dep} arr {arr} | {f.get('duration','?')} | {f.get('stops',0)} stop(s)")

        sources_ok = [p for p, s in status.items() if str(s).startswith("✓") and "0 results" not in str(s)]
        lines = [f"Flights found: {len(flights)} ({len(ob)} outbound, {len(rt)} return)"]
        lines.append(f"Sources with results: {', '.join(sources_ok) or 'none'}")
        if ob:
            lines.append(f"\nOutbound {origin}→{destination} (cheapest first):")
            lines += [f"  {i+1}. {_line(f)}" for i, f in enumerate(ob[:10])]
        if rt:
            lines.append(f"\nReturn {destination}→{origin} (cheapest first):")
            lines += [f"  {i+1}. {_line(f)}" for i, f in enumerate(rt[:6])]
        return "\n".join(lines)

    # ── 2. Hotels ─────────────────────────────────────────────────────────────

    @tool
    def search_hotels(city: str, check_in: str, check_out: str) -> str:
        """Search for hotels. Returns a compact text summary.

        Args:
            city: City name NOT airport code e.g. 'Phoenix'
            check_in: YYYY-MM-DD
            check_out: YYYY-MM-DD
        """
        from hotel_scrapers import scrape_all_hotels
        hotels, status = scrape_all_hotels(city, check_in, check_out, adults, currency)
        captured["hotels"]       = hotels
        captured["hotel_status"] = status

        try:
            nights = (date.fromisoformat(check_out) - date.fromisoformat(check_in)).days
        except Exception:
            nights = 1

        sources_ok = [p for p, s in status.items() if str(s).startswith("✓") and "0 results" not in str(s)]
        lines = [f"Hotels found: {len(hotels)} in {city} ({nights} night(s))"]
        lines.append(f"Sources with results: {', '.join(sources_ok) or 'none'}")
        if hotels:
            lines.append("Top options (cheapest first):")
            for i, h in enumerate(hotels[:10]):
                pn = h.get("price", 0)
                lines.append(f"  {i+1}. {h.get('title','')} via {h.get('provider','')}: "
                             f"{currency} {pn:.0f}/night = {pn*nights:.0f} total")
        return "\n".join(lines)

    # ── 3. Weather ────────────────────────────────────────────────────────────

    @tool
    def get_destination_weather(city: str) -> str:
        """Get current weather + 3-day forecast as a single compact text.

        Args:
            city: City name e.g. 'Phoenix'
        """
        from scrapers import get_weather
        d = get_weather(city)
        if "error" in d:
            return f"Weather unavailable for {city}."
        fc = "; ".join(
            f"{f['date']}: {f['desc']} {f['min_c']}–{f['max_c']}°C"
            for f in d.get("forecast_3day", [])
        )
        return (f"{city}: {d.get('temp_f','?')}°F/{d.get('temp_c','?')}°C, "
                f"{d.get('description','')}, humidity {d.get('humidity_pct','?')}%, "
                f"wind {d.get('wind_kmph','?')} km/h. Forecast: {fc}")

    # ── 4. City info + attractions ────────────────────────────────────────────

    @tool
    def get_destination_info(city: str) -> str:
        """Get a brief city overview and list of top tourist attractions.

        Args:
            city: City name e.g. 'Phoenix'
        """
        from scrapers import get_city_info, get_attractions
        info = get_city_info(city)
        attr = get_attractions(city)
        summary = info.get("summary", "")[:300].replace("\n", " ")
        places  = [a["name"] for a in attr.get("attractions", [])[:6]]
        return f"Overview: {summary}\nTop attractions: {', '.join(places)}"

    # ── 5. Exchange rate ──────────────────────────────────────────────────────

    @tool
    def get_exchange_rate(from_currency: str, to_currency: str) -> str:
        """Get live exchange rate between two currencies.

        Args:
            from_currency: e.g. 'INR'
            to_currency: e.g. 'USD'
        """
        from scrapers import get_exchange_rate as _rate
        d = _rate(from_currency, to_currency)
        return d.get("example", f"Rate unavailable for {from_currency}→{to_currency}")

    # ── 6. Card analysis ──────────────────────────────────────────────────────

    @tool
    def analyze_card_benefits(
        cheapest_flight_price: float,
        cheapest_hotel_price_per_night: float,
        hotel_nights: int,
    ) -> str:
        """Analyze which cards give best savings. Call AFTER search_flights and search_hotels.

        Args:
            cheapest_flight_price: Cheapest flight price found (total, in trip currency)
            cheapest_hotel_price_per_night: Cheapest hotel per night found
            hotel_nights: Number of hotel nights
        """
        from models import Card
        from agents.card_agent import fetch_card_offers

        card_objs = [
            Card(
                name=c.get("name", ""),
                bank=c.get("bank", ""),
                network=c.get("network", "visa"),
                card_type=c.get("card_type", "credit"),
                number_last4=c.get("number_last4", "0000"),
            )
            for c in cards
        ]
        offers     = fetch_card_offers(card_objs, trip.get("destination", ""))
        card_meta  = {c.get("name", ""): c for c in cards}
        hotel_tot  = cheapest_hotel_price_per_night * hotel_nights
        trip_total = cheapest_flight_price + hotel_tot

        recs  = []
        lines = [f"Trip total: {currency} {trip_total:.0f} (flight {cheapest_flight_price:.0f} + hotel {hotel_tot:.0f})"]
        for offer in offers:
            meta    = card_meta.get(offer.card_name, {})
            disc    = float(offer.discount_pct or 0)
            cash    = float(offer.cashback_pct or 0)
            reward  = float(offer.reward_points_multiplier or 1)
            net_pct = disc + cash + reward
            savings = round(trip_total * net_pct / 100, 2)

            recs.append({
                "category":        "flight + hotel",
                "item_title":      f"Full trip — {offer.card_name}",
                "item_price":      round(trip_total, 2),
                "currency":        currency,
                "card":            {"name": offer.card_name, "bank": meta.get("bank", ""), "network": meta.get("network", "visa")},
                "savings":         savings,
                "effective_price": round(trip_total - savings, 2),
                "benefit": {
                    "reward_pct":   round(reward, 2),
                    "cashback_pct": round(cash, 2),
                    "discount_pct": round(disc, 2),
                    "forex_pct":    0.0,
                    "effective_pct": round(net_pct, 2),
                },
            })
            lines.append(f"  {offer.card_name} ({meta.get('bank','')}): saves {currency} {savings:.0f} ({net_pct:.1f}% net)")

        recs.sort(key=lambda r: r["savings"], reverse=True)
        captured["recommendations"] = recs
        return "\n".join(lines)

    return [
        search_flights,
        search_hotels,
        get_destination_weather,
        get_destination_info,
        get_exchange_rate,
        analyze_card_benefits,
    ]
