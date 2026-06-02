"""
Travel Agent - fetches live rates for flights, hotels, cars, attractions concurrently.
"""
import concurrent.futures
from typing import List
from models import Offer, TripRequest
from tools import fetch_flights, fetch_hotels, fetch_cars, fetch_attractions


def fetch_all_offers(trip: TripRequest) -> List[Offer]:
    tasks = {
        "flights": lambda: fetch_flights(
            trip.origin, trip.destination, trip.check_in, trip.adults, trip.currency
        ),
        "hotels": lambda: fetch_hotels(
            trip.destination, trip.check_in, trip.check_out, trip.adults, trip.currency
        ),
        "cars": lambda: fetch_cars(
            trip.destination, trip.check_in, trip.check_out, trip.currency
        ),
        "attractions": lambda: fetch_attractions(trip.destination, trip.currency),
    }

    results: List[Offer] = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {executor.submit(fn): name for name, fn in tasks.items()}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                results.extend(future.result())
            except Exception as e:
                print(f"[travel_agent] {name} fetch failed: {e}")
    return results
