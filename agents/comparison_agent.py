"""
Comparison Agent - for each category, picks the cheapest live offer
then finds which card gives the best effective price (discount + cashback).
"""
from typing import List, Dict
from models import Card, Offer, CardOffer, Recommendation


def _effective_price(price: float, card_offer: CardOffer) -> float:
    after_discount = price * (1 - card_offer.discount_pct / 100)
    after_cashback = after_discount * (1 - card_offer.cashback_pct / 100)
    return round(after_cashback, 2)


def _best_offer_for_category(offers: List[Offer], category: str) -> Offer | None:
    cat_offers = [o for o in offers if o.category == category]
    return min(cat_offers, key=lambda o: o.base_price) if cat_offers else None


def compare_and_recommend(
    cards: List[Card],
    live_offers: List[Offer],
    card_offers: List[CardOffer],
) -> List[Recommendation]:
    categories = list({o.category for o in live_offers})
    recommendations: List[Recommendation] = []

    for category in categories:
        best_live = _best_offer_for_category(live_offers, category)
        if not best_live:
            continue

        # find card offers for this category
        cat_card_offers = [co for co in card_offers if co.category == category]
        if not cat_card_offers:
            continue

        # score each card offer
        best_card_offer = min(cat_card_offers, key=lambda co: _effective_price(best_live.base_price, co))
        final_price = _effective_price(best_live.base_price, best_card_offer)
        savings = round(best_live.base_price - final_price, 2)

        # find the Card object
        card_obj = next((c for c in cards if c.name == best_card_offer.card_name), cards[0])

        reason = (
            f"Use {best_card_offer.card_name}: "
            f"{best_card_offer.discount_pct}% discount + "
            f"{best_card_offer.cashback_pct}% cashback = "
            f"save {savings} {best_live.currency}. "
            f"{best_card_offer.description}"
        )

        recommendations.append(Recommendation(
            category=category,
            best_offer=best_live,
            best_card=card_obj,
            card_offer=best_card_offer,
            final_price=final_price,
            savings=savings,
            reason=reason,
        ))

    return sorted(recommendations, key=lambda r: r.savings, reverse=True)
