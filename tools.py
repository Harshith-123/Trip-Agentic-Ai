"""
Live API tool wrappers.
Set these env vars:
  AMADEUS_API_KEY, AMADEUS_API_SECRET  -> flights, hotels, cars
  SERPAPI_KEY                          -> Google Flights/Hotels scraping fallback
  OPENAI_API_KEY                       -> LLM reasoning
"""
import os
import httpx
from typing import List
from models import Offer

AMADEUS_BASE = "https://test.api.amadeus.com/v1"
AMADEUS_AUTH = "https://test.api.amadeus.com/v1/security/oauth2/token"


def _amadeus_token() -> str:
    resp = httpx.post(AMADEUS_AUTH, data={
        "grant_type": "client_credentials",
        "client_id": os.environ["AMADEUS_API_KEY"],
        "client_secret": os.environ["AMADEUS_API_SECRET"],
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def fetch_flights(origin: str, destination: str, date: str, adults: int, currency: str) -> List[Offer]:
    token = _amadeus_token()
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "originLocationCode": origin,
        "destinationLocationCode": destination,
        "departureDate": date,
        "adults": adults,
        "currencyCode": currency,
        "max": 5,
    }
    resp = httpx.get(f"{AMADEUS_BASE.replace('v1','v2')}/shopping/flight-offers", headers=headers, params=params)
    resp.raise_for_status()
    offers = []
    for item in resp.json().get("data", []):
        price = float(item["price"]["total"])
        carrier = item["validatingAirlineCodes"][0] if item.get("validatingAirlineCodes") else "Unknown"
        offers.append(Offer(
            category="flight",
            provider=carrier,
            title=f"{origin} → {destination} ({carrier})",
            base_price=price,
            currency=currency,
            url="https://www.amadeus.com",
            details={"itineraries": item.get("itineraries", [])},
        ))
    return offers


def fetch_hotels(city_code: str, check_in: str, check_out: str, adults: int, currency: str) -> List[Offer]:
    token = _amadeus_token()
    headers = {"Authorization": f"Bearer {token}"}
    # Step 1: get hotel IDs
    hotel_resp = httpx.get(f"{AMADEUS_BASE}/reference-data/locations/hotels/by-city",
                           headers=headers, params={"cityCode": city_code})
    hotel_resp.raise_for_status()
    hotel_ids = [h["hotelId"] for h in hotel_resp.json().get("data", [])[:10]]
    if not hotel_ids:
        return []
    # Step 2: get offers
    offers_resp = httpx.get(f"{AMADEUS_BASE.replace('v1','v3')}/shopping/hotel-offers",
                            headers=headers, params={
                                "hotelIds": ",".join(hotel_ids),
                                "checkInDate": check_in,
                                "checkOutDate": check_out,
                                "adults": adults,
                                "currencyCode": currency,
                            })
    offers_resp.raise_for_status()
    offers = []
    for item in offers_resp.json().get("data", []):
        hotel_name = item["hotel"]["name"]
        for o in item.get("offers", [])[:1]:
            price = float(o["price"]["total"])
            offers.append(Offer(
                category="hotel",
                provider=hotel_name,
                title=f"{hotel_name}",
                base_price=price,
                currency=currency,
                url="https://www.amadeus.com",
                details={"room": o.get("room", {})},
            ))
    return offers


def fetch_cars(origin: str, pick_up_date: str, drop_off_date: str, currency: str) -> List[Offer]:
    token = _amadeus_token()
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "originLocationCode": origin,
        "pickUpDateTime": f"{pick_up_date}T10:00:00",
        "returnDateTime": f"{drop_off_date}T10:00:00",
        "currencyCode": currency,
    }
    resp = httpx.get(f"{AMADEUS_BASE}/shopping/transfer-offers", headers=headers, params=params)
    # transfer-offers may not always return cars; graceful fallback
    if resp.status_code != 200:
        return []
    offers = []
    for item in resp.json().get("data", [])[:5]:
        price = float(item.get("quotation", {}).get("monetaryAmount", 0))
        provider = item.get("transferType", "Car Rental")
        offers.append(Offer(
            category="car",
            provider=provider,
            title=f"Car rental in {origin} ({provider})",
            base_price=price,
            currency=currency,
            url="https://www.amadeus.com",
            details={},
        ))
    return offers


def fetch_attractions(city_code: str, currency: str) -> List[Offer]:
    """Uses Amadeus Points of Interest API."""
    token = _amadeus_token()
    headers = {"Authorization": f"Bearer {token}"}
    # Need lat/lon for POI - first resolve via location search
    loc_resp = httpx.get(f"{AMADEUS_BASE}/reference-data/locations",
                         headers=headers,
                         params={"keyword": city_code, "subType": "CITY"})
    if loc_resp.status_code != 200 or not loc_resp.json().get("data"):
        return []
    geo = loc_resp.json()["data"][0]["geoCode"]
    poi_resp = httpx.get(f"{AMADEUS_BASE}/reference-data/locations/pois",
                         headers=headers,
                         params={"latitude": geo["latitude"], "longitude": geo["longitude"], "radius": 20})
    if poi_resp.status_code != 200:
        return []
    offers = []
    for poi in poi_resp.json().get("data", [])[:5]:
        offers.append(Offer(
            category="attraction",
            provider=poi.get("category", "Attraction"),
            title=poi["name"],
            base_price=0.0,  # POI API doesn't return ticket prices
            currency=currency,
            url="https://www.amadeus.com",
            details={"tags": poi.get("tags", [])},
        ))
    return offers
