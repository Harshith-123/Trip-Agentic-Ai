"""
Duffel API client for live flight search.
Docs: https://duffel.com/docs/api

Set DUFFEL_API_KEY environment variable to enable.
"""
from __future__ import annotations

import os
import re
from typing import Optional

import httpx


class DuffelClient:
    BASE_URL = "https://api.duffel.com"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("DUFFEL_API_KEY", "")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Duffel-Version": "v2",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def search_flights(
        self,
        origin: str,
        destination: str,
        date: str,
        adults: int = 1,
        currency: str = "USD",
        return_date: str = "",
        cabin_class: str = "economy",
    ) -> list[dict]:
        """
        Search live flights via Duffel API.
        Returns list of dicts compatible with pipeline.FlightResult.
        """
        if not self.api_key:
            return []

        slices = [{"origin": origin, "destination": destination, "departure_date": date}]
        if return_date:
            slices.append({
                "origin": destination,
                "destination": origin,
                "departure_date": return_date,
            })

        payload = {
            "data": {
                "slices": slices,
                "passengers": [{"type": "adult"} for _ in range(max(1, adults))],
                "cabin_class": cabin_class,
            }
        }

        try:
            with httpx.Client(timeout=45) as client:
                # Use return_offers=true for synchronous response
                r = client.post(
                    f"{self.BASE_URL}/air/offer_requests?return_offers=true",
                    json=payload,
                    headers=self.headers,
                )
                r.raise_for_status()
                data = r.json().get("data", {})

            offers = data.get("offers", [])
            # Sort by total_amount ascending
            offers.sort(key=lambda o: float(o.get("total_amount", 9999999)))

            results = []
            for offer in offers[:25]:
                parsed = self._parse_offer(offer, origin, destination, currency)
                if parsed:
                    results.append(parsed)

            return results

        except httpx.HTTPStatusError as e:
            raise RuntimeError(f"Duffel API error {e.response.status_code}: {e.response.text[:200]}") from e
        except Exception as e:
            raise RuntimeError(f"Duffel request failed: {e}") from e

    def _parse_offer(
        self, offer: dict, origin: str, destination: str, currency: str
    ) -> Optional[dict]:
        slices = offer.get("slices", [])
        if not slices:
            return None

        first_slice = slices[0]
        segments = first_slice.get("segments", [])
        if not segments:
            return None

        # Collect all marketing carriers across all slices
        carriers: list[str] = []
        for sl in slices:
            for seg in sl.get("segments", []):
                name = (
                    seg.get("marketing_carrier", {}).get("name", "")
                    or seg.get("operating_carrier", {}).get("name", "")
                )
                if name and name not in carriers:
                    carriers.append(name)

        airline = ", ".join(carriers) or "Unknown"
        dep_raw = segments[0].get("departing_at", "")
        arr_raw = segments[-1].get("arriving_at", "")
        dep = dep_raw[:16] if dep_raw else "-"
        arr = arr_raw[:16] if arr_raw else "-"
        stops = max(0, len(segments) - 1)

        # Parse ISO 8601 duration, e.g. "PT14H30M"
        duration_raw = first_slice.get("duration", "")
        duration = self._fmt_duration(duration_raw)

        price = float(offer.get("total_amount", 0))
        offer_currency = offer.get("total_currency", currency)
        offer_id = offer.get("id", "")

        # Duffel checkout deep-link (requires Duffel Accounts / Links)
        # Fall back to a generic Duffel search link
        url = f"https://book.duffel.com/offers/{offer_id}" if offer_id else ""

        return {
            "title": f"{airline} ({origin}→{destination})",
            "provider": f"Duffel ({airline})",
            "price": price,
            "currency": offer_currency,
            "departure": dep,
            "arrival": arr,
            "duration": duration,
            "stops": str(stops),
            "url": url,
            "source": "duffel",
            "offer_id": offer_id,
        }

    @staticmethod
    def _fmt_duration(raw: str) -> str:
        """Convert ISO 8601 duration PT14H30M → '14h 30m'."""
        if not raw:
            return "-"
        h = re.search(r"(\d+)H", raw)
        m = re.search(r"(\d+)M", raw)
        h_val = int(h.group(1)) if h else 0
        m_val = int(m.group(1)) if m else 0
        if h_val and m_val:
            return f"{h_val}h {m_val}m"
        if h_val:
            return f"{h_val}h"
        if m_val:
            return f"{m_val}m"
        return raw
