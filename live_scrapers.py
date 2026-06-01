"""
live_scrapers.py - thin re-export layer.
The actual multi-source logic lives in flight_scrapers.py and hotel_scrapers.py.
This module is kept for import compatibility.
"""

from flight_scrapers import scrape_google_flights, scrape_all_flights
from hotel_scrapers import scrape_booking as scrape_hotels, scrape_all_hotels

__all__ = [
    "scrape_google_flights",
    "scrape_all_flights",
    "scrape_hotels",
    "scrape_all_hotels",
]
