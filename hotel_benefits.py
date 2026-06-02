"""
Card-specific hotel perks and co-brand benefit database.

For a given card + hotel chain, returns extra benefits beyond the base reward rate:
  - Co-brand multiplier bonus (e.g. Hilton Amex = 12x on Hilton)
  - Flat credits (e.g. Amex FHR $100 property credit)
  - Status perks (free breakfast, room upgrade, late checkout)
  - Extra effective saving % that should be layered on top of the base card benefit

Usage:
  from hotel_benefits import get_hotel_perks
  perks = get_hotel_perks(card_name, bank, network, hotel_chain)
  # perks is a HotelPerk dataclass or None
"""

from __future__ import annotations
import re
from dataclasses import dataclass


@dataclass
class HotelPerk:
    card_name: str
    chain: str
    extra_saving_pct: float       # extra % off the hotel price (points + status value)
    flat_credit: float            # one-time flat credit in USD (e.g. Amex FHR $100)
    status_level: str             # Gold, Platinum, etc.
    perks_list: list[str]         # human-readable list of perks
    booking_tip: str              # where/how to book to unlock this benefit


# ---------------------------------------------------------------------------
# Co-brand and program benefit database
# ---------------------------------------------------------------------------

_PERKS_DB: list[dict] = [

    # ── Amex Platinum ──────────────────────────────────────────────────────
    {
        "card_keywords": ["platinum"],
        "bank_keywords": ["amex", "american express"],
        "chain": "ALL",
        "extra_saving_pct": 0,
        "flat_credit": 100,
        "status_level": "",
        "perks_list": [
            "Fine Hotels & Resorts (FHR): $100 property credit per stay",
            "Room upgrade when available at check-in",
            "Complimentary breakfast for two daily",
            "Guaranteed 4 PM late checkout",
            "3 PM early check-in when available",
            "12x Membership Rewards on Amex Travel bookings",
        ],
        "booking_tip": "Book via Amex Travel (amextravel.com) to activate FHR benefits.",
    },
    {
        "card_keywords": ["platinum"],
        "bank_keywords": ["amex", "american express"],
        "chain": "Marriott",
        "extra_saving_pct": 5.0,
        "flat_credit": 0,
        "status_level": "Marriott Bonvoy Gold",
        "perks_list": [
            "Automatic Marriott Bonvoy Gold Elite status",
            "25% bonus points on Marriott stays",
            "Room upgrade when available",
            "2 PM late checkout",
        ],
        "booking_tip": "Book directly on Marriott.com with linked Bonvoy account.",
    },
    {
        "card_keywords": ["platinum"],
        "bank_keywords": ["amex", "american express"],
        "chain": "Hilton",
        "extra_saving_pct": 3.0,
        "flat_credit": 0,
        "status_level": "Hilton Honors Gold",
        "perks_list": [
            "Complimentary Hilton Honors Gold status",
            "Free daily breakfast or 1,000 bonus points per night",
            "Space-available room upgrades",
            "80% bonus points on stays",
        ],
        "booking_tip": "Book on Hilton.com with linked Honors account.",
    },

    # ── Hilton Honors Amex Surpass ─────────────────────────────────────────
    {
        "card_keywords": ["hilton", "honors", "surpass"],
        "bank_keywords": ["amex", "american express"],
        "chain": "Hilton",
        "extra_saving_pct": 6.0,
        "flat_credit": 0,
        "status_level": "Hilton Honors Gold",
        "perks_list": [
            "12x Hilton Honors points on Hilton stays (≈ 4.8% value)",
            "Automatic Gold status - free breakfast / bonus points per night",
            "Space-available room upgrade",
            "Earn Diamond status after $40k spend",
        ],
        "booking_tip": "Always book direct on Hilton.com; OTA bookings earn fewer points.",
    },

    # ── Hilton Honors Amex Business ────────────────────────────────────────
    {
        "card_keywords": ["hilton", "business"],
        "bank_keywords": ["amex", "american express"],
        "chain": "Hilton",
        "extra_saving_pct": 5.0,
        "flat_credit": 0,
        "status_level": "Hilton Honors Gold",
        "perks_list": [
            "12x Hilton points on Hilton stays (≈ 4.8% value)",
            "Automatic Gold status",
        ],
        "booking_tip": "Book direct on Hilton.com.",
    },

    # ── Marriott Bonvoy Amex ───────────────────────────────────────────────
    {
        "card_keywords": ["marriott", "bonvoy"],
        "bank_keywords": ["amex", "american express"],
        "chain": "Marriott",
        "extra_saving_pct": 4.8,
        "flat_credit": 0,
        "status_level": "Marriott Bonvoy Silver",
        "perks_list": [
            "6x Marriott Bonvoy points on Marriott stays (≈ 3.6% value)",
            "Automatic Silver Elite status - 10% bonus points, priority late checkout",
            "Annual free night certificate (up to 35k points)",
        ],
        "booking_tip": "Book direct on Marriott.com; use member rate for extra 10% off.",
    },

    # ── Chase Sapphire Reserve ────────────────────────────────────────────
    {
        "card_keywords": ["sapphire", "reserve"],
        "bank_keywords": ["chase"],
        "chain": "ALL",
        "extra_saving_pct": 1.5,
        "flat_credit": 0,
        "status_level": "",
        "perks_list": [
            "3x Chase UR on all hotels (worth 4.5% via Chase Travel at 1.5¢/pt)",
            "$300 annual travel credit applies to hotel purchases",
            "DoorDash + Lyft perks that offset travel costs",
        ],
        "booking_tip": "Book via Chase Travel portal for 10x UR; or use card anywhere for 3x.",
    },

    # ── Chase Sapphire Preferred ──────────────────────────────────────────
    {
        "card_keywords": ["sapphire", "preferred"],
        "bank_keywords": ["chase"],
        "chain": "ALL",
        "extra_saving_pct": 1.0,
        "flat_credit": 0,
        "status_level": "",
        "perks_list": [
            "3x Chase UR on hotels (worth 3.75% via Chase Travel at 1.25¢/pt)",
            "$50 annual hotel credit via Chase Travel",
        ],
        "booking_tip": "Book via Chase Travel for the annual $50 credit.",
    },

    # ── IHG Rewards Premier Visa ──────────────────────────────────────────
    {
        "card_keywords": ["ihg", "rewards", "premier"],
        "bank_keywords": ["chase", "ihg"],
        "chain": "IHG",
        "extra_saving_pct": 7.0,
        "flat_credit": 0,
        "status_level": "IHG Platinum Elite",
        "perks_list": [
            "10x IHG points on IHG stays (≈ 5% value)",
            "Automatic Platinum Elite - lounge access, room upgrade, bonus points",
            "4th night free on award redemptions",
            "Global Entry / TSA PreCheck credit",
        ],
        "booking_tip": "Book direct on IHG.com using member rate for best earning.",
    },

    # ── HDFC Infinia ──────────────────────────────────────────────────────
    {
        "card_keywords": ["infinia"],
        "bank_keywords": ["hdfc"],
        "chain": "Taj",
        "extra_saving_pct": 3.0,
        "flat_credit": 0,
        "status_level": "Taj Epicure Plus",
        "perks_list": [
            "Taj Epicure Plus membership - up to 25% off room rates",
            "Complimentary room upgrade at Taj properties",
            "Early check-in / late checkout",
            "Complimentary buffet breakfast",
        ],
        "booking_tip": "Book via Taj's website using HDFC Infinia Epicure code.",
    },
    {
        "card_keywords": ["infinia"],
        "bank_keywords": ["hdfc"],
        "chain": "Marriott",
        "extra_saving_pct": 1.5,
        "flat_credit": 0,
        "status_level": "Marriott Bonvoy",
        "perks_list": [
            "HDFC Infinia earns 5 RP per ₹150 on Marriott (≈ 3.3% value)",
            "1.99% forex markup on international Marriott stays",
        ],
        "booking_tip": "Use HDFC Infinia for Marriott; net benefit after forex ≈ +1.3%.",
    },

    # ── HDFC Diners Black ─────────────────────────────────────────────────
    {
        "card_keywords": ["diners", "black"],
        "bank_keywords": ["hdfc"],
        "chain": "ALL",
        "extra_saving_pct": 3.3,
        "flat_credit": 0,
        "status_level": "",
        "perks_list": [
            "5 RP per ₹150 on all hotels (≈ 3.3% value)",
            "0% forex markup on Diners network - full saving on international hotels",
            "Complimentary stays at partner luxury properties (varies by offer)",
            "Unlimited lounge access worldwide",
        ],
        "booking_tip": "Always pay in local currency; Diners has 0% forex so you keep full reward.",
    },

    # ── Axis Magnus ───────────────────────────────────────────────────────
    {
        "card_keywords": ["magnus"],
        "bank_keywords": ["axis"],
        "chain": "ALL",
        "extra_saving_pct": 0.5,
        "flat_credit": 0,
        "status_level": "",
        "perks_list": [
            "12 EDGE Reward Points per ₹200 on hotels (≈ 1.5% value)",
            "2% forex markup - net +0.5% on international hotels after forex",
            "Travel EDGE portal: 5x EDGE on portal hotel bookings",
        ],
        "booking_tip": "Book via Axis Travel EDGE portal for 5x rewards on eligible hotels.",
    },

    # ── Capital One Venture X ─────────────────────────────────────────────
    {
        "card_keywords": ["venture", "x"],
        "bank_keywords": ["capital one", "capital"],
        "chain": "ALL",
        "extra_saving_pct": 2.0,
        "flat_credit": 0,
        "status_level": "",
        "perks_list": [
            "10x miles on hotels via Capital One Travel (= 10% back)",
            "2x on all other hotel purchases (= 2%)",
            "$300 annual travel credit",
            "0% foreign transaction fee",
        ],
        "booking_tip": "Book via Capital One Travel portal to earn 10x miles.",
    },
]


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

def _normalise(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def get_hotel_perks(
    card_name: str,
    bank: str,
    network: str,
    hotel_chain: str | None,
) -> list[HotelPerk]:
    """
    Return all HotelPerk entries that apply to this card + hotel chain.
    A perk applies when:
      - card_keywords match the card name
      - bank_keywords match the bank
      - chain == hotel_chain OR chain == 'ALL'
    Returns an empty list if no specific perks found.
    """
    norm_card = _normalise(card_name)
    norm_bank  = _normalise(bank)
    norm_chain = _normalise(hotel_chain or "")

    matches: list[HotelPerk] = []
    for entry in _PERKS_DB:
        card_ok = any(kw in norm_card for kw in entry["card_keywords"])
        bank_ok  = any(kw in norm_bank  for kw in entry["bank_keywords"])
        chain_ok = (entry["chain"] == "ALL" or
                    _normalise(entry["chain"]) in norm_chain or
                    norm_chain in _normalise(entry["chain"]))
        if card_ok and bank_ok and chain_ok:
            matches.append(HotelPerk(
                card_name=card_name,
                chain=entry["chain"],
                extra_saving_pct=entry["extra_saving_pct"],
                flat_credit=entry["flat_credit"],
                status_level=entry["status_level"],
                perks_list=entry["perks_list"],
                booking_tip=entry["booking_tip"],
            ))
    return matches


def best_hotel_perk(
    card_name: str, bank: str, network: str, hotel_chain: str | None, price: float
) -> tuple[float, HotelPerk | None]:
    """
    Return (total_saving, best_perk) for the given card at this hotel.
    total_saving = (extra_saving_pct / 100) * price + flat_credit
    """
    perks = get_hotel_perks(card_name, bank, network, hotel_chain)
    if not perks:
        return 0.0, None
    best = max(perks, key=lambda p: (p.extra_saving_pct / 100) * price + p.flat_credit)
    saving = round((best.extra_saving_pct / 100) * price + best.flat_credit, 2)
    return saving, best
