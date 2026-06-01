"""
Financial Effective-Cost Engine.

Formula:
  Effective Cost = Base Price
    − Card Reward Value     (reward_pct % of base)
    − Cashback              (cashback_pct % of base)
    − Discount              (discount_pct % of base)
    − Statement Credits     (flat amount)
    − Promo Discounts       (flat amount)
    + Forex / FX Cost       (forex_pct % of base)
    + Fees                  (flat amount)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EffectiveCost:
    base_price: float
    currency: str
    card_reward_value: float
    cashback: float
    discount: float
    statement_credit: float
    forex_cost: float
    promo_discount: float
    fees: float
    effective_cost: float
    savings: float
    net_saving_pct: float
    breakdown: dict[str, str]


def compute_effective_cost(
    base_price: float,
    currency: str = "USD",
    reward_pct: float = 0.0,
    cashback_pct: float = 0.0,
    discount_pct: float = 0.0,
    statement_credit: float = 0.0,
    forex_pct: float = 0.0,
    promo_discount: float = 0.0,
    fees: float = 0.0,
) -> EffectiveCost:
    """
    Compute the effective cost of a purchase after all card benefits.

    All percentage arguments are in % (e.g. 5.0 = 5%).
    statement_credit, promo_discount, fees are flat amounts in `currency`.
    """
    card_reward_value = round(base_price * reward_pct / 100, 2)
    cashback          = round(base_price * cashback_pct  / 100, 2)
    discount          = round(base_price * discount_pct  / 100, 2)
    forex_cost        = round(base_price * forex_pct      / 100, 2)

    effective = round(
        base_price
        - card_reward_value
        - cashback
        - discount
        - statement_credit
        - promo_discount
        + forex_cost
        + fees,
        2,
    )
    savings   = round(base_price - effective, 2)
    net_pct   = round(savings / base_price * 100, 2) if base_price else 0.0

    sym = currency

    breakdown: dict[str, str] = {
        "Base Price":          f"{sym} {base_price:.2f}",
        "− Card Reward Value": f"{sym} {card_reward_value:.2f}  ({reward_pct:.2f}%)",
        "− Cashback":          f"{sym} {cashback:.2f}  ({cashback_pct:.2f}%)",
        "− Discount":          f"{sym} {discount:.2f}  ({discount_pct:.2f}%)",
        "− Statement Credits": f"{sym} {statement_credit:.2f}",
        "− Promo Discounts":   f"{sym} {promo_discount:.2f}",
        "+ Forex / FX Cost":   f"{sym} {forex_cost:.2f}  ({forex_pct:.2f}%)",
        "+ Fees":              f"{sym} {fees:.2f}",
        "= Effective Cost":    f"{sym} {effective:.2f}",
        "  Net Saving":        f"{sym} {savings:.2f}  ({net_pct:.1f}%)",
    }

    return EffectiveCost(
        base_price=base_price,
        currency=currency,
        card_reward_value=card_reward_value,
        cashback=cashback,
        discount=discount,
        statement_credit=statement_credit,
        forex_cost=forex_cost,
        promo_discount=promo_discount,
        fees=fees,
        effective_cost=effective,
        savings=savings,
        net_saving_pct=net_pct,
        breakdown=breakdown,
    )


def best_card_effective_cost(
    base_price: float,
    currency: str,
    cards_benefits: list[dict],
) -> tuple[dict, EffectiveCost]:
    """
    Given a list of card-benefit dicts (each with keys matching compute_effective_cost params),
    return (best_card_dict, EffectiveCost) for the card that yields the lowest effective cost.
    """
    best_card = None
    best_ec: EffectiveCost | None = None

    for cb in cards_benefits:
        ec = compute_effective_cost(
            base_price=base_price,
            currency=currency,
            reward_pct=cb.get("reward_pct", 0),
            cashback_pct=cb.get("cashback_pct", 0),
            discount_pct=cb.get("discount_pct", 0),
            statement_credit=cb.get("statement_credit", 0),
            forex_pct=cb.get("forex_pct", 0),
            promo_discount=cb.get("promo_discount", 0),
            fees=cb.get("fees", 0),
        )
        if best_ec is None or ec.effective_cost < best_ec.effective_cost:
            best_ec = ec
            best_card = cb

    return best_card or {}, best_ec or compute_effective_cost(base_price, currency)
