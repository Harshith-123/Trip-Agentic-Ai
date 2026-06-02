"""
Card Agent - uses Claude to analyze real card benefits for a destination.
Claude draws on its knowledge of actual card terms (lounge access, forex markup,
reward multipliers, cashback) rather than fabricating random numbers.
"""
import json
import os
from typing import List

import anthropic

from models import Card, CardOffer

CATEGORIES = ["flight", "hotel", "car", "attraction"]

_SYSTEM = """\
You are a credit card benefits expert with deep knowledge of Indian and international
bank cards - HDFC, SBI, ICICI, Axis, Amex, Chase, Citi, etc.

Given a card and destination, return REALISTIC benefit estimates for each travel category
as a JSON array. Base the numbers on the card's actual known benefits:
  - Foreign transaction / forex markup fee (reduces savings)
  - Travel portal or airline booking discounts
  - Cashback or reward points multiplier on travel spend
  - Lounge access value (apportion ~$30/visit into a per-trip cashback equivalent)
  - Travel insurance coverage value

Return ONLY a valid JSON array (no markdown fences) with one object per category:
[
  {
    "card_name": "<card name>",
    "category": "<flight|hotel|car|attraction>",
    "discount_pct": <0-15>,
    "cashback_pct": <0-10>,
    "reward_points_multiplier": <1-10>,
    "description": "<one sentence explaining the benefit>"
  },
  ...
]
"""


def fetch_card_offers(cards: List[Card], destination: str) -> List[CardOffer]:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    client = anthropic.Anthropic(api_key=api_key)
    all_offers: List[CardOffer] = []

    for card in cards:
        prompt = (
            f"Card: {card.name} ({card.bank}, {card.network.upper()} {card.card_type})\n"
            f"Destination: {destination}\n"
            f"Categories: {CATEGORIES}\n"
            "Return one offer object per category."
        )
        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            # Strip markdown fences if model adds them
            if raw.startswith("```"):
                lines = raw.split("\n")
                raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            items = json.loads(raw)
        except Exception:
            continue

        for item in items:
            all_offers.append(
                CardOffer(
                    card_name=card.name,
                    category=item.get("category", ""),
                    discount_pct=float(item.get("discount_pct", 0)),
                    cashback_pct=float(item.get("cashback_pct", 0)),
                    reward_points_multiplier=float(item.get("reward_points_multiplier", 1)),
                    description=item.get("description", ""),
                )
            )

    return all_offers
