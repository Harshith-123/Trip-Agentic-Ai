"""
Card Benefits Knowledge Base.

Each card entry stores per-category benefit data:
  effective_pct - net % of spend you keep as value after forex markup
                   = (reward_value_pct + cashback_pct + discount_pct) - forex_markup_pct
  cashback_pct  - direct cashback on category spend
  reward_pct    - reward points value as % of spend
  forex_pct     - foreign-transaction / forex-markup fee (negative for intl spend)
  discount_pct  - portal/bank direct discount on booking
  description   - one-line explanation for the user

The lookup cascades: exact card name → bank average → network default → global fallback.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional

CATEGORIES = ("flight", "hotel", "car", "attraction")


@dataclass
class CardBenefit:
    effective_pct: float   # net benefit % (positive = saving, negative = extra cost)
    cashback_pct: float
    reward_pct: float
    forex_pct: float       # forex markup (will be subtracted for intl spend)
    discount_pct: float
    lounge: str
    travel_insurance: bool
    description: str
    matched_name: str = "" # KB card name if matched, empty if fallback


# ─── Master card database ────────────────────────────────────────────────────
# Keys are (normalised_card_name, normalised_bank) tuples.
# Per category, values are dicts that get unpacked into CardBenefit.

_CARD_DB: dict[tuple[str, str], dict[str, dict]] = {

    # ── HDFC Bank ──────────────────────────────────────────────────────────
    ("hdfc regalia", "hdfc"): {
        "flight":     dict(cashback_pct=0, reward_pct=1.33, forex_pct=2.0, discount_pct=0,
                           description="4 RP per ₹150 ≈ 1.33% value; 2% forex markup nets -0.67% on intl flights. "
                                       "Good for domestic HDFC travel portal (10% off)."),
        "hotel":      dict(cashback_pct=0, reward_pct=1.33, forex_pct=2.0, discount_pct=0,
                           description="Same 1.33% reward rate; 2% forex cuts into savings on international hotels."),
        "car":        dict(cashback_pct=0, reward_pct=1.33, forex_pct=2.0, discount_pct=0,
                           description="Standard reward rate."),
        "attraction": dict(cashback_pct=0, reward_pct=1.33, forex_pct=2.0, discount_pct=0,
                           description="Standard reward rate."),
        "lounge": "6 domestic + 2 international per quarter (Priority Pass)",
        "travel_insurance": True,
    },

    ("hdfc infinia", "hdfc"): {
        "flight":     dict(cashback_pct=0, reward_pct=3.3, forex_pct=1.99, discount_pct=0,
                           description="5 RP per ₹150 ≈ 3.3% value; only 1.99% forex → net +1.31% on intl flights."),
        "hotel":      dict(cashback_pct=0, reward_pct=3.3, forex_pct=1.99, discount_pct=0,
                           description="3.3% reward value; 1.99% forex → net +1.31% on international hotels."),
        "car":        dict(cashback_pct=0, reward_pct=3.3, forex_pct=1.99, discount_pct=0,
                           description="Same rate."),
        "attraction": dict(cashback_pct=0, reward_pct=3.3, forex_pct=1.99, discount_pct=0,
                           description="Same rate."),
        "lounge": "Unlimited domestic + international (Priority Pass)",
        "travel_insurance": True,
    },

    ("hdfc diners black", "hdfc"): {
        "flight":     dict(cashback_pct=0, reward_pct=3.3, forex_pct=0.0, discount_pct=0,
                           description="5 RP per ₹150; Diners network has 0% forex markup → full 3.3% net on flights."),
        "hotel":      dict(cashback_pct=0, reward_pct=3.3, forex_pct=0.0, discount_pct=0,
                           description="3.3% reward, 0% forex → best HDFC card for international hotels."),
        "car":        dict(cashback_pct=0, reward_pct=3.3, forex_pct=0.0, discount_pct=0,
                           description="3.3% net; no forex on Diners."),
        "attraction": dict(cashback_pct=0, reward_pct=3.3, forex_pct=0.0, discount_pct=0,
                           description="3.3% net."),
        "lounge": "Unlimited domestic + international via DreamFolks",
        "travel_insurance": True,
    },

    ("hdfc millennia", "hdfc"): {
        "flight":     dict(cashback_pct=1.0, reward_pct=0, forex_pct=3.5, discount_pct=0,
                           description="1% cashback on other spends; 3.5% forex markup → -2.5% net on intl flights."),
        "hotel":      dict(cashback_pct=1.0, reward_pct=0, forex_pct=3.5, discount_pct=5.0,
                           description="5% cashback when booked via HDFC SmartBuy; 3.5% forex."),
        "car":        dict(cashback_pct=1.0, reward_pct=0, forex_pct=3.5, discount_pct=0,
                           description="1% cashback."),
        "attraction": dict(cashback_pct=1.0, reward_pct=0, forex_pct=3.5, discount_pct=0,
                           description="1% cashback."),
        "lounge": "8 per year domestic (DreamFolks)",
        "travel_insurance": False,
    },

    # ── SBI Cards ──────────────────────────────────────────────────────────
    ("sbi simplyclick", "sbi"): {
        "flight":     dict(cashback_pct=0, reward_pct=0.25, forex_pct=3.5, discount_pct=0,
                           description="1 RP per ₹100 general spend ≈ 0.25% value; 3.5% forex → -3.25% net."),
        "hotel":      dict(cashback_pct=0, reward_pct=0.25, forex_pct=3.5, discount_pct=0,
                           description="Same - poor choice for international hotels."),
        "car":        dict(cashback_pct=0, reward_pct=0.25, forex_pct=3.5, discount_pct=0,
                           description="Same."),
        "attraction": dict(cashback_pct=0, reward_pct=0.25, forex_pct=3.5, discount_pct=0,
                           description="Same."),
        "lounge": "None",
        "travel_insurance": False,
    },

    ("sbi elite", "sbi"): {
        "flight":     dict(cashback_pct=0, reward_pct=0.5, forex_pct=1.99, discount_pct=0,
                           description="2 RP per ₹100 ≈ 0.5% value; 1.99% forex → -1.49% net on intl flights."),
        "hotel":      dict(cashback_pct=0, reward_pct=0.5, forex_pct=1.99, discount_pct=0,
                           description="0.5% rewards, 1.99% forex → -1.49% net."),
        "car":        dict(cashback_pct=0, reward_pct=0.5, forex_pct=1.99, discount_pct=0,
                           description="Same."),
        "attraction": dict(cashback_pct=0, reward_pct=0.5, forex_pct=1.99, discount_pct=0,
                           description="Same."),
        "lounge": "8 per year international + unlimited domestic",
        "travel_insurance": True,
    },

    ("sbi prime", "sbi"): {
        "flight":     dict(cashback_pct=0, reward_pct=0.5, forex_pct=3.5, discount_pct=0,
                           description="2 RP per ₹100 ≈ 0.5% value; 3.5% forex → -3% net on intl."),
        "hotel":      dict(cashback_pct=0, reward_pct=0.5, forex_pct=3.5, discount_pct=0,
                           description="Same."),
        "car":        dict(cashback_pct=0, reward_pct=0.5, forex_pct=3.5, discount_pct=0,
                           description="Same."),
        "attraction": dict(cashback_pct=0, reward_pct=0.5, forex_pct=3.5, discount_pct=0,
                           description="Same."),
        "lounge": "8 per year domestic",
        "travel_insurance": True,
    },

    # ── Axis Bank ──────────────────────────────────────────────────────────
    ("axis magnus", "axis"): {
        "flight":     dict(cashback_pct=0, reward_pct=1.5, forex_pct=2.0, discount_pct=0,
                           description="12 EDGE per ₹200 (₹0.25/pt) ≈ 1.5% value; 2% forex → -0.5% net on intl. "
                                       "Airport lounge + 5x EDGE on Axis Travel EDGE portal."),
        "hotel":      dict(cashback_pct=0, reward_pct=1.5, forex_pct=2.0, discount_pct=0,
                           description="1.5% reward value; 2% forex → -0.5% net on intl."),
        "car":        dict(cashback_pct=0, reward_pct=1.5, forex_pct=2.0, discount_pct=0,
                           description="Same."),
        "attraction": dict(cashback_pct=0, reward_pct=1.5, forex_pct=2.0, discount_pct=0,
                           description="Same."),
        "lounge": "Unlimited domestic + 8 international per year",
        "travel_insurance": True,
    },

    ("axis burgundy private", "axis"): {
        "flight":     dict(cashback_pct=0, reward_pct=3.75, forex_pct=1.5, discount_pct=0,
                           description="30 EDGE per ₹200 ≈ 3.75% value; 1.5% forex → net +2.25% on intl flights."),
        "hotel":      dict(cashback_pct=0, reward_pct=3.75, forex_pct=1.5, discount_pct=0,
                           description="3.75% reward, 1.5% forex → net +2.25%."),
        "car":        dict(cashback_pct=0, reward_pct=3.75, forex_pct=1.5, discount_pct=0,
                           description="Same."),
        "attraction": dict(cashback_pct=0, reward_pct=3.75, forex_pct=1.5, discount_pct=0,
                           description="Same."),
        "lounge": "Unlimited domestic + international",
        "travel_insurance": True,
    },

    ("axis my zone", "axis"): {
        "flight":     dict(cashback_pct=1.5, reward_pct=0, forex_pct=3.5, discount_pct=0,
                           description="1.5% cashback; 3.5% forex → -2% net on intl."),
        "hotel":      dict(cashback_pct=1.5, reward_pct=0, forex_pct=3.5, discount_pct=0,
                           description="Same."),
        "car":        dict(cashback_pct=1.5, reward_pct=0, forex_pct=3.5, discount_pct=0,
                           description="Same."),
        "attraction": dict(cashback_pct=1.5, reward_pct=0, forex_pct=3.5, discount_pct=0,
                           description="Same."),
        "lounge": "4 per year domestic",
        "travel_insurance": False,
    },

    # ── ICICI Bank ─────────────────────────────────────────────────────────
    ("icici amazon pay", "icici"): {
        "flight":     dict(cashback_pct=2.0, reward_pct=0, forex_pct=3.5, discount_pct=0,
                           description="2% cashback (non-Amazon); 3.5% forex → -1.5% net on intl flights."),
        "hotel":      dict(cashback_pct=2.0, reward_pct=0, forex_pct=3.5, discount_pct=0,
                           description="Same."),
        "car":        dict(cashback_pct=2.0, reward_pct=0, forex_pct=3.5, discount_pct=0,
                           description="Same."),
        "attraction": dict(cashback_pct=2.0, reward_pct=0, forex_pct=3.5, discount_pct=0,
                           description="Same."),
        "lounge": "None",
        "travel_insurance": False,
    },

    ("icici emerald", "icici"): {
        "flight":     dict(cashback_pct=0, reward_pct=1.0, forex_pct=1.5, discount_pct=0,
                           description="4 PAYBACK per ₹100 ≈ 1% value; 1.5% forex → -0.5% net on intl."),
        "hotel":      dict(cashback_pct=0, reward_pct=1.0, forex_pct=1.5, discount_pct=0,
                           description="1% rewards, 1.5% forex → -0.5% net."),
        "car":        dict(cashback_pct=0, reward_pct=1.0, forex_pct=1.5, discount_pct=0,
                           description="Same."),
        "attraction": dict(cashback_pct=0, reward_pct=1.0, forex_pct=1.5, discount_pct=0,
                           description="Same."),
        "lounge": "Unlimited domestic + international (Priority Pass)",
        "travel_insurance": True,
    },

    # ── Yes Bank ───────────────────────────────────────────────────────────
    ("yes first exclusive", "yes"): {
        "flight":     dict(cashback_pct=0, reward_pct=1.0, forex_pct=1.75, discount_pct=0,
                           description="12 RPs per ₹200 ≈ 1.5% value minus 1.75% forex → -0.25% net."),
        "hotel":      dict(cashback_pct=0, reward_pct=1.5, forex_pct=1.75, discount_pct=0,
                           description="Same."),
        "car":        dict(cashback_pct=0, reward_pct=1.0, forex_pct=1.75, discount_pct=0,
                           description="Same."),
        "attraction": dict(cashback_pct=0, reward_pct=1.0, forex_pct=1.75, discount_pct=0,
                           description="Same."),
        "lounge": "Unlimited domestic + 4 international per year",
        "travel_insurance": True,
    },

    # ── American Express ───────────────────────────────────────────────────
    ("amex platinum travel", "amex"): {
        "flight":     dict(cashback_pct=0, reward_pct=5.0, forex_pct=0.0, discount_pct=0,
                           description="5x MR points on Amex Travel bookings ≈ 5% value; 0% forex → full 5% net."),
        "hotel":      dict(cashback_pct=0, reward_pct=4.0, forex_pct=0.0, discount_pct=0,
                           description="4x MR on hotel bookings; 0% forex → 4% net."),
        "car":        dict(cashback_pct=0, reward_pct=2.0, forex_pct=0.0, discount_pct=0,
                           description="2x MR; 0% forex → 2% net."),
        "attraction": dict(cashback_pct=0, reward_pct=1.0, forex_pct=0.0, discount_pct=0,
                           description="1x MR; 0% forex."),
        "lounge": "Priority Pass + Amex Centurion Lounges",
        "travel_insurance": True,
    },

    ("amex gold", "amex"): {
        "flight":     dict(cashback_pct=0, reward_pct=1.0, forex_pct=0.0, discount_pct=0,
                           description="1x MR on travel (4x on restaurants); 0% forex → 1% net on flights."),
        "hotel":      dict(cashback_pct=0, reward_pct=1.0, forex_pct=0.0, discount_pct=0,
                           description="1x MR; 0% forex."),
        "car":        dict(cashback_pct=0, reward_pct=1.0, forex_pct=0.0, discount_pct=0,
                           description="1x MR."),
        "attraction": dict(cashback_pct=0, reward_pct=4.0, forex_pct=0.0, discount_pct=0,
                           description="4x MR on dining → good for restaurants/attractions."),
        "lounge": "None included",
        "travel_insurance": False,
    },

    # ── Chase (US cards) ───────────────────────────────────────────────────
    ("chase sapphire preferred", "chase"): {
        "flight":     dict(cashback_pct=0, reward_pct=3.75, forex_pct=0.0, discount_pct=0,
                           description="3x UR points on travel (worth 1.25¢ each via Chase portal) = 3.75% net; 0% forex."),
        "hotel":      dict(cashback_pct=0, reward_pct=3.75, forex_pct=0.0, discount_pct=0,
                           description="3x UR on hotels; 0% forex → 3.75% net."),
        "car":        dict(cashback_pct=0, reward_pct=3.75, forex_pct=0.0, discount_pct=0,
                           description="3x UR on car rentals; 0% forex."),
        "attraction": dict(cashback_pct=0, reward_pct=3.75, forex_pct=0.0, discount_pct=0,
                           description="3x UR on dining → useful for attractions."),
        "lounge": "None (but Priority Pass Add-on available)",
        "travel_insurance": True,
    },

    ("chase sapphire reserve", "chase"): {
        "flight":     dict(cashback_pct=0, reward_pct=4.5, forex_pct=0.0, discount_pct=0,
                           description="3x UR at 1.5¢/pt via Chase portal = 4.5% net; 0% forex + $300 travel credit."),
        "hotel":      dict(cashback_pct=0, reward_pct=4.5, forex_pct=0.0, discount_pct=0,
                           description="3x UR on hotels; 0% forex → 4.5% net."),
        "car":        dict(cashback_pct=0, reward_pct=4.5, forex_pct=0.0, discount_pct=0,
                           description="3x UR; 0% forex."),
        "attraction": dict(cashback_pct=0, reward_pct=4.5, forex_pct=0.0, discount_pct=0,
                           description="3x UR on dining."),
        "lounge": "Priority Pass Select - unlimited",
        "travel_insurance": True,
    },

    # ── Capital One ────────────────────────────────────────────────────────
    ("capital one venture", "capital one"): {
        "flight":     dict(cashback_pct=2.0, reward_pct=0, forex_pct=0.0, discount_pct=0,
                           description="2x miles (2% cash value) on everything; 0% foreign transaction fee."),
        "hotel":      dict(cashback_pct=2.0, reward_pct=0, forex_pct=0.0, discount_pct=0,
                           description="2% on hotels; 0% forex."),
        "car":        dict(cashback_pct=2.0, reward_pct=0, forex_pct=0.0, discount_pct=0,
                           description="2% on car rentals."),
        "attraction": dict(cashback_pct=2.0, reward_pct=0, forex_pct=0.0, discount_pct=0,
                           description="2% on dining/attractions."),
        "lounge": "2 per year Capital One Lounge",
        "travel_insurance": True,
    },

    # ── Citi ───────────────────────────────────────────────────────────────
    ("citi premier", "citi"): {
        "flight":     dict(cashback_pct=0, reward_pct=3.0, forex_pct=0.0, discount_pct=0,
                           description="3x ThankYou pts on air travel (1¢/pt) = 3%; 0% forex."),
        "hotel":      dict(cashback_pct=0, reward_pct=3.0, forex_pct=0.0, discount_pct=0,
                           description="3x TY on hotels; 0% forex."),
        "car":        dict(cashback_pct=0, reward_pct=3.0, forex_pct=0.0, discount_pct=0,
                           description="3x TY on car rentals."),
        "attraction": dict(cashback_pct=0, reward_pct=3.0, forex_pct=0.0, discount_pct=0,
                           description="3x TY on restaurants."),
        "lounge": "None",
        "travel_insurance": False,
    },
}


# ─── Bank-level fallback averages ─────────────────────────────────────────────
_BANK_DEFAULTS: dict[str, dict] = {
    "hdfc":   dict(cashback_pct=0, reward_pct=1.0, forex_pct=2.5, discount_pct=0,
                   lounge="Varies by card", travel_insurance=False,
                   description="Average HDFC card benefit for travel."),
    "sbi":    dict(cashback_pct=0, reward_pct=0.5, forex_pct=3.5, discount_pct=0,
                   lounge="Select cards only", travel_insurance=False,
                   description="Average SBI card benefit for travel."),
    "axis":   dict(cashback_pct=0, reward_pct=1.5, forex_pct=2.5, discount_pct=0,
                   lounge="Select cards only", travel_insurance=False,
                   description="Average Axis card benefit for travel."),
    "icici":  dict(cashback_pct=1.0, reward_pct=0, forex_pct=3.0, discount_pct=0,
                   lounge="Select cards only", travel_insurance=False,
                   description="Average ICICI card benefit for travel."),
    "amex":   dict(cashback_pct=0, reward_pct=2.0, forex_pct=0.0, discount_pct=0,
                   lounge="Varies", travel_insurance=True,
                   description="Amex cards: strong rewards + 0% forex."),
    "chase":  dict(cashback_pct=0, reward_pct=2.0, forex_pct=0.0, discount_pct=0,
                   lounge="Select cards only", travel_insurance=True,
                   description="Average Chase card: good rewards, 0% forex."),
    "citi":   dict(cashback_pct=0, reward_pct=1.0, forex_pct=0.0, discount_pct=0,
                   lounge="None", travel_insurance=False,
                   description="Average Citi card."),
    "capital one": dict(cashback_pct=2.0, reward_pct=0, forex_pct=0.0, discount_pct=0,
                        lounge="None", travel_insurance=True,
                        description="Capital One: 2% on everything, 0% forex."),
    "yes":    dict(cashback_pct=0, reward_pct=1.0, forex_pct=1.75, discount_pct=0,
                   lounge="Select cards only", travel_insurance=False,
                   description="Average Yes Bank card."),
    "kotak":  dict(cashback_pct=0, reward_pct=1.0, forex_pct=3.5, discount_pct=0,
                   lounge="Select cards only", travel_insurance=False,
                   description="Average Kotak card."),
}

# Network defaults (last resort)
_NETWORK_DEFAULTS: dict[str, dict] = {
    "visa":       dict(cashback_pct=0, reward_pct=0.5, forex_pct=3.5, discount_pct=0,
                       lounge="Varies", travel_insurance=False,
                       description="Generic Visa card - minimal travel benefits."),
    "mastercard": dict(cashback_pct=0, reward_pct=0.5, forex_pct=3.5, discount_pct=0,
                       lounge="Varies", travel_insurance=False,
                       description="Generic Mastercard - minimal travel benefits."),
    "amex":       dict(cashback_pct=0, reward_pct=1.0, forex_pct=0.0, discount_pct=0,
                       lounge="Some cards", travel_insurance=False,
                       description="Amex network: 0% forex is a built-in advantage."),
    "rupay":      dict(cashback_pct=0, reward_pct=0.5, forex_pct=3.5, discount_pct=0,
                       lounge="Limited", travel_insurance=False,
                       description="RuPay: limited international acceptance, standard benefits."),
    "diners":     dict(cashback_pct=0, reward_pct=1.5, forex_pct=0.0, discount_pct=0,
                       lounge="Some cards", travel_insurance=False,
                       description="Diners Club: 0% forex markup by design."),
}

_GLOBAL_DEFAULT = dict(cashback_pct=0, reward_pct=0.5, forex_pct=3.5, discount_pct=0,
                       lounge="Unknown", travel_insurance=False,
                       description="Unknown card - using conservative estimate.")


def _normalise(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def _build_benefit(data: dict, category: str, matched_name: str = "") -> CardBenefit:
    cat = data.get(category, data.get("flight", {}))
    lounge = data.get("lounge", "Unknown")
    ti = data.get("travel_insurance", False)
    cashback = cat.get("cashback_pct", 0)
    reward = cat.get("reward_pct", 0)
    forex = cat.get("forex_pct", 3.5)
    discount = cat.get("discount_pct", 0)
    effective = round(cashback + reward + discount - forex, 2)
    return CardBenefit(
        effective_pct=effective,
        cashback_pct=cashback,
        reward_pct=reward,
        forex_pct=forex,
        discount_pct=discount,
        lounge=lounge,
        travel_insurance=ti,
        description=cat.get("description", ""),
        matched_name=matched_name,
    )


def get_card_benefit(card_name: str, bank: str, network: str, category: str) -> CardBenefit:
    """
    Look up card benefits for a given card and category.
    Falls back: exact match → bank default → network default → global default.
    """
    norm_name = _normalise(card_name)
    norm_bank = _normalise(bank)
    norm_net  = _normalise(network)

    # 1. Exact match
    for (db_name, db_bank), data in _CARD_DB.items():
        if db_name in norm_name or norm_name in db_name:
            if db_bank in norm_bank or norm_bank in db_bank:
                return _build_benefit(data, category, db_name.title())

    # 2. Partial name match (any word overlap)
    name_words = set(norm_name.split())
    best_score = 0
    best_data = None
    best_db_name = ""
    for (db_name, db_bank), data in _CARD_DB.items():
        if db_bank not in norm_bank and norm_bank not in db_bank:
            continue
        db_words = set(db_name.split())
        score = len(name_words & db_words)
        if score > best_score:
            best_score = score
            best_data = data
            best_db_name = db_name

    if best_data and best_score > 0:
        return _build_benefit(best_data, category, best_db_name.title())

    # 3. Bank-level default
    for db_bank, bdata in _BANK_DEFAULTS.items():
        if db_bank in norm_bank or norm_bank in db_bank:
            cat_data = dict(
                cashback_pct=bdata["cashback_pct"],
                reward_pct=bdata["reward_pct"],
                forex_pct=bdata["forex_pct"],
                discount_pct=bdata["discount_pct"],
                description=bdata["description"],
            )
            return _build_benefit(
                {category: cat_data, "lounge": bdata["lounge"], "travel_insurance": bdata["travel_insurance"]},
                category,
            )

    # 4. Network default
    for db_net, ndata in _NETWORK_DEFAULTS.items():
        if db_net in norm_net or norm_net in db_net:
            cat_data = dict(
                cashback_pct=ndata["cashback_pct"],
                reward_pct=ndata["reward_pct"],
                forex_pct=ndata["forex_pct"],
                discount_pct=ndata["discount_pct"],
                description=ndata["description"],
            )
            return _build_benefit(
                {category: cat_data, "lounge": ndata["lounge"], "travel_insurance": ndata["travel_insurance"]},
                category,
            )

    # 5. Global fallback
    cat_data = dict(
        cashback_pct=_GLOBAL_DEFAULT["cashback_pct"],
        reward_pct=_GLOBAL_DEFAULT["reward_pct"],
        forex_pct=_GLOBAL_DEFAULT["forex_pct"],
        discount_pct=_GLOBAL_DEFAULT["discount_pct"],
        description=_GLOBAL_DEFAULT["description"],
    )
    return _build_benefit(
        {category: cat_data, "lounge": _GLOBAL_DEFAULT["lounge"],
         "travel_insurance": _GLOBAL_DEFAULT["travel_insurance"]},
        category,
    )
