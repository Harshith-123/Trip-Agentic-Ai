from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Card:
    name: str
    network: str  # visa, mastercard, amex, etc.
    bank: str
    card_type: str  # credit, debit
    number_last4: str


@dataclass
class TripRequest:
    cards: List[Card]
    origin: str
    destination: str
    check_in: str    # flight outbound date YYYY-MM-DD
    check_out: str   # flight return date (or end of trip) YYYY-MM-DD
    adults: int = 1
    currency: str = "USD"
    trip_type: str = "one-way"   # "one-way" | "round-trip"
    return_date: str = ""        # return flight date (round-trip only)
    hotel_check_in: str = ""     # hotel check-in  (defaults to check_in)
    hotel_check_out: str = ""    # hotel check-out (defaults to check_out)


@dataclass
class Offer:
    category: str       # flight, hotel, car, attraction
    provider: str
    title: str
    base_price: float
    currency: str
    url: str
    details: dict = field(default_factory=dict)


@dataclass
class CardOffer:
    card_name: str
    category: str
    discount_pct: float
    cashback_pct: float
    reward_points_multiplier: float
    description: str


@dataclass
class Recommendation:
    category: str
    best_offer: Offer
    best_card: Card
    card_offer: CardOffer
    final_price: float
    savings: float
    reason: str
