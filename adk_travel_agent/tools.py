"""Tool functions exposed to Google ADK.

These functions keep ADK simple and effective by reusing the project's existing
deterministic code instead of creating a second implementation.
"""
from __future__ import annotations

import queue
from typing import Any

from agents.tools import iata_to_city


def _top(items: list[dict], limit: int = 10) -> list[dict]:
    return items[:limit] if isinstance(items, list) else []


def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    trip_type: str = "one-way",
    return_date: str = "",
    adults: int = 1,
    currency: str = "USD",
) -> dict[str, Any]:
    """Search flight sources and return cheapest verified results.

    Args:
        origin: 3-letter IATA airport code, e.g. BLR.
        destination: 3-letter IATA airport code, e.g. ORD.
        departure_date: Outbound date in YYYY-MM-DD format.
        trip_type: one-way or round-trip.
        return_date: Return date in YYYY-MM-DD format for round trips.
        adults: Number of adult passengers.
        currency: Currency code, e.g. USD or INR.
    """
    from flight_scrapers import scrape_all_flights

    flights, status = scrape_all_flights(
        origin.upper().strip(),
        destination.upper().strip(),
        departure_date,
        adults,
        currency.upper().strip(),
        trip_type,
        return_date,
    )
    outbound = [f for f in flights if "Return" not in str(f.get("provider", ""))]
    returns = [f for f in flights if "Return" in str(f.get("provider", ""))]
    return {
        "status": status,
        "count": len(flights),
        "outbound_count": len(outbound),
        "return_count": len(returns),
        "top_outbound": _top(outbound, 10),
        "top_return": _top(returns, 10),
    }


def search_hotels(
    city: str,
    check_in: str,
    check_out: str,
    adults: int = 1,
    currency: str = "USD",
) -> dict[str, Any]:
    """Search hotel sources and return cheapest verified hotel results.

    Args:
        city: Hotel city name, e.g. Chicago.
        check_in: Hotel check-in date in YYYY-MM-DD format.
        check_out: Hotel check-out date in YYYY-MM-DD format.
        adults: Number of adult guests.
        currency: Currency code, e.g. USD or INR.
    """
    from hotel_scrapers import scrape_all_hotels

    hotels, status = scrape_all_hotels(
        city.strip(),
        check_in,
        check_out,
        adults,
        currency.upper().strip(),
    )
    return {
        "status": status,
        "count": len(hotels),
        "top_hotels": _top(hotels, 15),
    }


def analyze_card_savings(
    cards: list[dict],
    flights: list[dict],
    hotels: list[dict],
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str = "",
    hotel_check_in: str = "",
    hotel_check_out: str = "",
    currency: str = "USD",
) -> dict[str, Any]:
    """Analyze cards with the deterministic card KB and effective-cost engine.

    Args:
        cards: Cards with name, bank, network, card_type, and optional number_last4.
        flights: Flight result dictionaries from search_flights.
        hotels: Hotel result dictionaries from search_hotels.
        origin: Origin airport code.
        destination: Destination airport code.
        departure_date: Outbound flight date.
        return_date: Return flight date for round trips.
        hotel_check_in: Hotel check-in date.
        hotel_check_out: Hotel check-out date.
        currency: Currency code.
    """
    from agents.graph import _analyze_cards

    captured = {"flights": flights or [], "hotels": hotels or [], "recommendations": []}
    trip = {
        "cards": cards or [],
        "origin": origin.upper().strip(),
        "destination": destination.upper().strip(),
        "check_in": departure_date,
        "check_out": return_date or departure_date,
        "return_date": return_date,
        "hotel_check_in": hotel_check_in or departure_date,
        "hotel_check_out": hotel_check_out or return_date or departure_date,
        "currency": currency.upper().strip(),
    }
    _analyze_cards(trip, captured)
    return {
        "recommendations": captured["recommendations"],
        "best_card": captured["recommendations"][0] if captured["recommendations"] else None,
    }


def run_complete_trip_analysis(trip: dict) -> dict[str, Any]:
    """Run the complete existing travel pipeline and return the final report.

    Args:
        trip: Full trip dictionary. Required keys: cards, origin, destination,
            check_in, check_out, adults, currency. Optional keys: trip_type,
            return_date, hotel_check_in, hotel_check_out.
    """
    from agents.graph import run_graph

    normalized = dict(trip or {})
    normalized["origin"] = str(normalized.get("origin", "")).upper().strip()
    normalized["destination"] = str(normalized.get("destination", "")).upper().strip()
    normalized.setdefault("cards", [])
    normalized.setdefault("adults", 1)
    normalized.setdefault("currency", "USD")
    normalized.setdefault("trip_type", "round-trip" if normalized.get("return_date") else "one-way")
    normalized.setdefault("check_out", normalized.get("return_date") or normalized.get("check_in", ""))
    normalized.setdefault("hotel_check_in", normalized.get("check_in", ""))
    normalized.setdefault("hotel_check_out", normalized.get("return_date") or normalized.get("check_out", ""))

    result = run_graph(
        trip_dict=normalized,
        session_id="adk",
        progress_queue=queue.Queue(),
    )
    return {
        "destination_city": iata_to_city(normalized["destination"]),
        "report": result.get("report", ""),
        "recommendations": result.get("recommendations", []),
        "flights": result.get("flights", []),
        "hotels": result.get("hotels", []),
        "errors": result.get("errors", []),
    }
