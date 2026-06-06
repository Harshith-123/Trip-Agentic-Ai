"""
Trip Agentic Pipeline - pure Python, no LLM API required.

Stages:
  PLAN    → decide which data sources to query
  FETCH   → concurrently scrape/call all live sources
  ANALYZE → apply knowledge_base card-benefit rules to live prices
  REPORT  → render a rich terminal + markdown report
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from models import Card, TripRequest, Offer, Recommendation
from knowledge_base import get_card_benefit, CardBenefit
from scrapers import get_weather, get_attractions, get_exchange_rate, get_city_info


# ─── Internal result types ────────────────────────────────────────────────────

@dataclass
class FlightResult:
    title: str
    provider: str
    price: float
    currency: str
    details: dict = field(default_factory=dict)
    url: str = ""


@dataclass
class HotelResult:
    title: str
    provider: str
    price: float
    currency: str
    details: dict = field(default_factory=dict)
    url: str = ""


@dataclass
class CardRec:
    category: str
    item_title: str
    item_price: float
    currency: str
    card: Card
    benefit: CardBenefit
    savings: float
    effective_price: float


# ─── Agent state ──────────────────────────────────────────────────────────────

@dataclass
class AgentState:
    flights: list[FlightResult] = field(default_factory=list)
    hotels:  list[HotelResult]  = field(default_factory=list)
    hotels_per_night: list[dict] = field(default_factory=list)
    hotel_option_a: dict         = field(default_factory=dict)
    hotel_option_b: list[dict]   = field(default_factory=list)
    flight_platform_status: dict = field(default_factory=dict)
    hotel_platform_status: dict  = field(default_factory=dict)
    weather: dict = field(default_factory=dict)
    attractions: dict = field(default_factory=dict)
    exchange_rate: dict = field(default_factory=dict)
    city_info: dict = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


# ─── The Agent ────────────────────────────────────────────────────────────────

class TripAgent:
    """
    Self-contained agentic pipeline.
    Decides what to fetch, fetches it concurrently, applies card KB, outputs report.
    """

    def __init__(self, trip: TripRequest, progress_callback=None):
        self.trip = trip
        self.state = AgentState()
        self._step = 0
        self._progress_callback = progress_callback

    # ── Logging ──────────────────────────────────────────────────────────────

    def _log(self, msg: str, symbol: str = "→"):
        self._step += 1
        line = f"  [{self._step:02d}] {symbol} {msg}"
        if self._progress_callback:
            self._progress_callback(line)
        else:
            print(line)

    def _ok(self, msg: str):
        self._log(msg, "✓")

    def _warn(self, msg: str):
        self._log(msg, "⚠")

    def _err(self, msg: str):
        self._log(msg, "✗")
        self.state.errors.append(msg)

    # ── Stage 1: PLAN ─────────────────────────────────────────────────────────

    def plan(self) -> list[tuple[str, Any]]:
        """Determine which tasks to run and return a task list."""
        t = self.trip
        tasks: list[tuple[str, Any]] = []

        self._log(f"Planning data collection: {t.origin} → {t.destination} "
                  f"({t.check_in} to {t.check_out}), {t.adults} adult(s), {t.currency}")

        tasks.append(("weather",     lambda: get_weather(self._city_name(t.destination))))
        self._log("Queued: live weather data (wttr.in)")

        tasks.append(("attractions", lambda: get_attractions(self._city_name(t.destination))))
        self._log("Queued: top attractions (Wikipedia)")

        tasks.append(("city_info",   lambda: get_city_info(self._city_name(t.destination))))
        self._log("Queued: destination overview (Wikipedia)")

        if t.currency.upper() != "USD":
            tasks.append(("exchange_rate", lambda: get_exchange_rate(t.currency, "USD")))
            self._log(f"Queued: exchange rate {t.currency} → USD")

        tasks.append(("flights", self._fetch_flights))
        self._log("Queued: flights from Google Flights + Kayak + Skyscanner + MakeMyTrip")

        tasks.append(("hotels", self._fetch_hotels))
        self._log("Queued: hotels (all OTAs + chain sites) + per-night breakdown")

        self._log(f"Plan complete: {len(tasks)} tasks scheduled")
        return tasks

    # ── Stage 2: FETCH ────────────────────────────────────────────────────────

    def fetch(self, tasks: list[tuple[str, Any]]):
        """Execute all tasks concurrently and store results in self.state."""
        self._log(f"Fetching {len(tasks)} data sources concurrently...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(fn): name for name, fn in tasks}
            for future in concurrent.futures.as_completed(futures):
                name = futures[future]
                try:
                    result = future.result()
                    setattr(self.state, name, result)
                    count = len(result) if isinstance(result, list) else "✓"
                    self._ok(f"{name}: received ({count})")
                except Exception as exc:
                    self._err(f"{name}: failed - {exc}")

    # ── Stage 3: ANALYZE ──────────────────────────────────────────────────────

    def analyze(self) -> list[CardRec]:
        """Apply card knowledge base to live prices and rank recommendations."""
        recs: list[CardRec] = []

        # --- Flights: use cheapest OUTBOUND only for card recommendation ---
        if self.state.flights:
            outbound = [f for f in self.state.flights if "Return" not in f.provider]
            pool = outbound if outbound else self.state.flights
            best = min(pool, key=lambda f: f.price)
            self._log(f"Best outbound flight across {len(pool)} results: "
                      f"{best.title} via {best.provider} @ {best.currency} {best.price:.2f}")
            rec = self._best_card_rec("flight", best.title, best.price, best.currency)
            if rec:
                recs.append(rec)
                verb = "save" if rec.savings >= 0 else "costs"
                self._ok(f"Flight card: {rec.card.name} -> effective {rec.currency} "
                         f"{rec.effective_price:.2f} ({verb} {rec.currency} {abs(rec.savings):.2f})")

        # --- Hotels Option A: same hotel, full stay ---
        if self.state.hotels:
            best = min(self.state.hotels, key=lambda h: h.price)
            nights = max(1, self._nights())
            total = round(best.price * nights, 2)
            self._log(f"Best hotel (Option A) across {len(self.state.hotels)} results: "
                      f"{best.title} via {best.provider} @ {best.currency} "
                      f"{best.price:.2f}/night × {nights} = {total:.2f}")
            rec = self._best_card_rec("hotel", best.title, total, best.currency)
            if rec:
                recs.append(rec)
                verb = "save" if rec.savings >= 0 else "costs"
                self._ok(f"Hotel card (Option A): {rec.card.name} → effective "
                         f"{rec.currency} {rec.effective_price:.2f} "
                         f"({verb} {rec.currency} {abs(rec.savings):.2f})")
            self._analyze_hotel_option_a(best, nights, rec)

        # --- Hotels Option B: per-night best ---
        if self.state.hotels_per_night:
            self._analyze_hotel_option_b()
            opt_b_total = sum(n["price"] for n in self.state.hotel_option_b if n.get("price"))
            if opt_b_total > 0:
                self._ok(f"Option B total (per-night bookings): "
                         f"{self.trip.currency} {opt_b_total:.2f} "
                         f"over {len(self.state.hotel_option_b)} night(s)")

        if not recs:
            if self.state.flights or self.state.hotels:
                self._warn("None of your cards provide net savings on this trip "
                           "(forex/reward ratio unfavorable). Showing best available anyway.")
            else:
                self._warn("No live price data - recommendations use knowledge base only.")
            recs = self._fallback_recommendations()

        return sorted(recs, key=lambda r: r.savings, reverse=True)

    def _analyze_hotel_option_a(
        self,
        best_hotel: HotelResult,
        nights: int,
        card_rec: Optional[CardRec],
    ):
        from hotel_scrapers import _detect_chain
        from hotel_benefits import best_hotel_perk

        chain = _detect_chain(best_hotel.title)
        total_price = round(best_hotel.price * nights, 2)

        best_perk_saving = 0.0
        best_perk = None
        best_perk_card = None
        for card in self.trip.cards:
            saving, perk = best_hotel_perk(
                card.name, card.bank, card.network, chain, total_price
            )
            if saving > best_perk_saving:
                best_perk_saving = saving
                best_perk = perk
                best_perk_card = card

        if best_perk and best_perk_card:
            self._ok(
                f"Hotel perk (Option A): {best_perk_card.name} → "
                f"{best_perk.status_level or 'extra perks'} at "
                f"{chain or 'this property'} "
                f"(≈{best_perk.extra_saving_pct:.1f}% + "
                f"${best_perk.flat_credit:.0f} credit)"
            )

        self.state.hotel_option_a = {
            "hotel": best_hotel,
            "nights": nights,
            "total_price": total_price,
            "currency": best_hotel.currency,
            "best_card": card_rec,
            "chain": chain,
            "hotel_perk": best_perk,
            "perk_saving": best_perk_saving,
            "perk_card": best_perk_card,
        }

    def _analyze_hotel_option_b(self):
        from hotel_scrapers import _detect_chain
        from hotel_benefits import best_hotel_perk

        analyzed: list[dict] = []
        for night_data in self.state.hotels_per_night:
            cheapest = night_data.get("cheapest_hotel")
            if not cheapest:
                analyzed.append({
                    "night": night_data.get("night"),
                    "check_in": night_data.get("check_in"),
                    "check_out": night_data.get("check_out"),
                    "error": "No hotel found for this night",
                })
                continue

            hotel_name = cheapest.get("title", "")
            price = float(cheapest.get("price", 0))
            currency = cheapest.get("currency", self.trip.currency)
            provider = cheapest.get("provider", "")
            chain = _detect_chain(hotel_name)

            rec = self._best_card_rec("hotel", hotel_name, price, currency)

            best_perk_saving = 0.0
            best_perk = None
            best_perk_card = None
            for card in self.trip.cards:
                saving, perk = best_hotel_perk(
                    card.name, card.bank, card.network, chain, price
                )
                if saving > best_perk_saving:
                    best_perk_saving = saving
                    best_perk = perk
                    best_perk_card = card

            analyzed.append({
                "night": night_data.get("night"),
                "check_in": night_data.get("check_in"),
                "check_out": night_data.get("check_out"),
                "hotel_name": hotel_name,
                "provider": provider,
                "price": price,
                "currency": currency,
                "chain": chain,
                "best_card": rec,
                "hotel_perk": best_perk,
                "perk_saving": best_perk_saving,
                "perk_card": best_perk_card,
                "all_options": night_data.get("all_options", []),
                "url": cheapest.get("url", "") or self._hotel_search_url(provider),
            })

        self.state.hotel_option_b = analyzed

    def _best_card_rec(
        self, category: str, title: str, price: float, currency: str
    ) -> Optional[CardRec]:
        if not self.trip.cards:
            return None

        best_rec: Optional[CardRec] = None
        for card in self.trip.cards:
            benefit = get_card_benefit(card.name, card.bank, card.network, category)
            effective = round(price * (1 - benefit.effective_pct / 100), 2)
            savings = round(price - effective, 2)
            if best_rec is None or savings > best_rec.savings:
                # Use KB matched name for display when available
                if benefit.matched_name:
                    card = Card(
                        name=benefit.matched_name,
                        bank=card.bank,
                        network=card.network,
                        card_type=card.card_type,
                        number_last4=card.number_last4,
                    )
                best_rec = CardRec(
                    category=category,
                    item_title=title,
                    item_price=price,
                    currency=currency,
                    card=card,
                    benefit=benefit,
                    savings=savings,
                    effective_price=effective,
                )
        return best_rec

    def _fallback_recommendations(self) -> list[CardRec]:
        recs = []
        dummy_prices = {"flight": 500.0, "hotel": 150.0}
        for category, price in dummy_prices.items():
            rec = self._best_card_rec(
                category, f"Estimated {category}", price, self.trip.currency
            )
            if rec:
                recs.append(rec)
        return recs

    # ── Stage 4: REPORT ───────────────────────────────────────────────────────

    def report(self, recs: list[CardRec], llm_insights: dict | None = None) -> str:
        lines: list[str] = []
        t = self.trip
        nights = max(1, self._nights())
        h_in  = t.hotel_check_in  or t.check_in
        h_out = t.hotel_check_out or t.check_out

        trip_label = "Round-Trip" if t.trip_type == "round-trip" else "One-Way"
        lines.append(f"# Trip Report: {t.origin} to {t.destination} ({trip_label})")
        if t.trip_type == "round-trip":
            flight_dates = f"{t.check_in} (out) / {t.return_date or t.check_out} (return)"
        else:
            flight_dates = t.check_in
        lines.append(
            f"**Flight:** {flight_dates}  |  "
            f"**Hotel:** {h_in} to {h_out} ({nights} nights)  |  "
            f"**Adults:** {t.adults}  |  **Currency:** {t.currency}"
        )
        lines.append("")

        # --- Destination overview ---
        if self.state.city_info and not self.state.city_info.get("error"):
            lines.append("## Destination Overview")
            lines.append(self.state.city_info.get("summary", ""))
            lines.append("")

        # --- Weather ---
        w = self.state.weather
        if w and not w.get("error"):
            lines.append("## Weather at Destination")
            lines.append(
                f"- **Now:** {w.get('description', '?')}  "
                f"{w.get('temp_c', '?')}°C / {w.get('temp_f', '?')}°F  "
                f"(feels like {w.get('feels_like_c', '?')}°C)"
            )
            lines.append(
                f"- Humidity: {w.get('humidity_pct', '?')}%  |  "
                f"Wind: {w.get('wind_kmph', '?')} km/h"
            )
            forecast = w.get("forecast_3day", [])
            if forecast:
                lines.append("- **3-Day Forecast:**")
                for day in forecast:
                    lines.append(
                        f"  - {day['date']}: {day['desc']}, "
                        f"{day['min_c']}–{day['max_c']}°C"
                    )
            lines.append("")

        # --- Exchange rate ---
        er = self.state.exchange_rate
        if er and not er.get("error") and er.get("rate"):
            lines.append("## Exchange Rate")
            lines.append(f"- {er['example']}")
            lines.append("")

        # --- Flight sources ---
        if self.state.flight_platform_status:
            lines.append("## Flight Sources Checked")
            for platform, st in self.state.flight_platform_status.items():
                url = self._flight_search_url(platform)
                link = f" - [Search ↗]({url})" if url else ""
                lines.append(f"- **{platform}**: {st}{link}")
            lines.append("")

        # --- Flights tables ---
        if self.state.flights:
            is_rt = self.trip.trip_type == "round-trip"
            outbound = sorted(
                [f for f in self.state.flights if "Return" not in f.provider],
                key=lambda x: x.price
            )
            returns = sorted(
                [f for f in self.state.flights if "Return" in f.provider],
                key=lambda x: x.price
            )

            def _flight_table(flights: list[FlightResult], heading: str):
                if not flights:
                    return
                best_f = flights[0]
                lines.append(f"## {heading} (cheapest first)")
                lines.append(f"**Best deal: {best_f.provider.split('(')[-1].rstrip(')')} @ "
                             f"{best_f.currency} {best_f.price:.2f}**")
                lines.append("")
                lines.append("| # | Airlines | Price | Departs | Arrives | Duration | Stops | Book |")
                lines.append("|---|----------|-------|---------|---------|----------|-------|------|")
                for i, f in enumerate(flights, 1):
                    airline = f.provider.split("(")[-1].rstrip(")")
                    dep = f.details.get("departure", "-")
                    arr = f.details.get("arrival", "-")
                    dur = f.details.get("duration", "-")
                    stp = f.details.get("stops", "-")
                    book = f"[Search ↗]({f.url})" if f.url else "-"
                    lines.append(
                        f"| {i} | {airline[:45]} | "
                        f"{f.currency} {f.price:.2f} | {dep} | {arr} | {dur} | {stp} | {book} |"
                    )
                lines.append("")

            if is_rt:
                t = self.trip
                _flight_table(outbound,
                    f"Outbound Flights: {t.origin} to {t.destination} on {t.check_in}")
                _flight_table(returns,
                    f"Return Flights: {t.destination} to {t.origin} on {t.return_date or t.check_out}")
            else:
                _flight_table(outbound or returns,
                    f"Live Flight Prices: {self.trip.origin} to {self.trip.destination}")
        else:
            lines.append("## Flights")
            lines.append("_No results from any source - check your internet connection._")
            lines.append("")

        # --- Hotel sources (show all platforms with search links) ---
        if self.state.hotel_platform_status:
            lines.append("## Hotel Sources Checked")
            for platform, st in self.state.hotel_platform_status.items():
                url = self._hotel_search_url(platform)
                link = f" - [Search ↗]({url})" if url else ""
                lines.append(f"- **{platform}**: {st}{link}")
            lines.append("")

        # --- Hotel Option A ---
        self._report_hotel_option_a(lines, nights)

        # --- Hotel Option B ---
        self._report_hotel_option_b(lines)

        # --- Comparison A vs B ---
        self._report_option_comparison(lines)

        # --- Flight card recommendation ---
        flight_recs = [r for r in recs if r.category == "flight"]
        if flight_recs:
            rec = flight_recs[0]
            leg_note = " (Outbound)" if self.trip.trip_type == "round-trip" else ""
            lines.append(f"## Best Card for Flights{leg_note}")
            lines.append(f"- **Card:** {rec.card.name}  ({rec.card.bank}, "
                         f"{rec.card.network.upper()} {rec.card.card_type})")
            b = rec.benefit
            lines.append(
                f"- **Benefits:** Reward {b.reward_pct}% + "
                f"Cashback {b.cashback_pct}% + "
                f"Discount {b.discount_pct}% − "
                f"Forex {b.forex_pct}% = **{b.effective_pct:+.2f}% net**"
            )
            verb = "save" if rec.savings >= 0 else "costs"
            suffix = " more" if rec.savings < 0 else ""
            lines.append(
                f"- **Effective price:** {rec.currency} {rec.effective_price:.2f}  "
                f"({verb} {rec.currency} {abs(rec.savings):.2f}{suffix})"
            )
            lines.append(f"- **Why:** {b.description}")
            lines.append(f"- **Lounge:** {b.lounge}")
            lines.append(
                f"- **Travel insurance:** {'Yes' if b.travel_insurance else 'No'}"
            )
            lines.append("")

        # --- All cards summary ---
        if self.trip.cards:
            lines.append("## Your Cards - Travel Benefit Summary")
            lines.append(
                "| Card | Bank | Network | Flight Net% | Hotel Net% | Forex | Lounge |"
            )
            lines.append(
                "|------|------|---------|-------------|------------|-------|--------|"
            )
            for card in self.trip.cards:
                fb = get_card_benefit(card.name, card.bank, card.network, "flight")
                hb = get_card_benefit(card.name, card.bank, card.network, "hotel")
                lines.append(
                    f"| {card.name} | {card.bank} | {card.network.upper()} | "
                    f"{fb.effective_pct:+.1f}% | {hb.effective_pct:+.1f}% | "
                    f"{fb.forex_pct}% | {fb.lounge[:30]} |"
                )
            lines.append("")

        # --- Attractions ---
        att = self.state.attractions
        if att and not att.get("error") and att.get("attractions"):
            lines.append("## Top Attractions")
            for a in att["attractions"][:6]:
                snippet = a.get("snippet", "")[:120]
                lines.append(f"- **{a['name']}** - {snippet}…")
            lines.append("")

        # --- AI Insights ---
        if llm_insights and not llm_insights.get("error"):
            lines.append("## AI Travel Insights")
            if llm_insights.get("executive_summary"):
                lines.append(f"**Executive Summary:** {llm_insights['executive_summary']}")
                lines.append("")
            tips_parts = []
            if llm_insights.get("best_flight_tip"): tips_parts.append(f"✈️ {llm_insights['best_flight_tip']}")
            if llm_insights.get("best_hotel_tip"): tips_parts.append(f"🏨 {llm_insights['best_hotel_tip']}")
            if llm_insights.get("optimal_card_strategy"): tips_parts.append(f"💳 {llm_insights['optimal_card_strategy']}")
            for tip in tips_parts:
                lines.append(f"- {tip}")
            if llm_insights.get("money_saving_tips"):
                for tip in llm_insights["money_saving_tips"]:
                    lines.append(f"- 💰 {tip}")
            lines.append("")

        # --- Tips ---
        lines.append("## Travel Money Tips")
        lines.append(
            "- Always pay in local currency when abroad (avoid dynamic currency conversion)."
        )
        lines.append(
            "- Use a card with 0% forex markup for international transactions "
            "(Amex, Diners Black, US cards)."
        )
        lines.append(
            "- Book flights and hotels via your bank travel portal for extra rewards."
        )
        lines.append(
            "- Check if your card includes trip-cancellation or medical insurance "
            "to skip separate travel insurance purchases."
        )

        if self.state.errors:
            lines.append("")
            lines.append("## Warnings")
            for e in self.state.errors:
                lines.append(f"- {e}")

        import html as _html
        return _html.unescape("\n".join(lines))

    # ── Report sub-sections ───────────────────────────────────────────────────

    def _report_hotel_option_a(self, lines: list[str], nights: int):
        if not self.state.hotels:
            lines.append("## Hotels")
            lines.append(
                "_No hotel results - hotel sites may have blocked the request. "
                "Try Booking.com or Expedia directly._"
            )
            lines.append("")
            return

        lines.append(
            f"## Option A - Same Hotel for Full Stay ({nights} night(s))"
        )

        sorted_hotels = sorted(self.state.hotels, key=lambda x: x.price)
        best_h = sorted_hotels[0]
        total_best = round(best_h.price * nights, 2)

        lines.append(
            f"**Cheapest option: {best_h.title} via {best_h.provider} "
            f"@ {best_h.currency} {best_h.price:.2f}/night "
            f"= {best_h.currency} {total_best:.2f} total**"
        )
        lines.append("")
        lines.append(
            f"| # | Hotel | Platform | Per Night | {nights}-Night Total | Book |"
        )
        lines.append("|---|-------|----------|-----------|-------------|------|")
        for i, h in enumerate(sorted_hotels[:15], 1):
            total = round(h.price * nights, 2)
            book = f"[Book ↗]({h.url})" if h.url else "-"
            lines.append(
                f"| {i} | {h.title[:45]} | {h.provider} | "
                f"{h.currency} {h.price:.2f} | {h.currency} {total:.2f} | {book} |"
            )
        lines.append("")

        # Best card for Option A
        opt_a = self.state.hotel_option_a
        rec: Optional[CardRec] = opt_a.get("best_card")
        if rec:
            lines.append("### Best Card for Option A")
            lines.append(
                f"- **Card:** {rec.card.name}  ({rec.card.bank}, "
                f"{rec.card.network.upper()} {rec.card.card_type})"
            )
            b = rec.benefit
            lines.append(
                f"- **Benefits:** Reward {b.reward_pct}% + "
                f"Cashback {b.cashback_pct}% + "
                f"Discount {b.discount_pct}% − "
                f"Forex {b.forex_pct}% = **{b.effective_pct:+.2f}% net**"
            )
            verb = "save" if rec.savings >= 0 else "costs"
            suffix = " more" if rec.savings < 0 else ""
            lines.append(
                f"- **Effective total:** {rec.currency} {rec.effective_price:.2f}  "
                f"({verb} {rec.currency} {abs(rec.savings):.2f}{suffix})"
            )
            lines.append(f"- **Why:** {b.description}")
            lines.append("")

        # Hotel chain perks
        chain = opt_a.get("chain")
        perk = opt_a.get("hotel_perk")
        perk_card = opt_a.get("perk_card")
        if perk and perk_card:
            lines.append("### Hotel Chain Benefits")
            if chain:
                lines.append(f"- **Detected chain:** {chain}")
            lines.append(
                f"- **Your card with chain perks:** {perk_card.name}"
            )
            if perk.status_level:
                lines.append(f"- **Status:** {perk.status_level}")
            for item in perk.perks_list:
                lines.append(f"  - {item}")
            perk_save = opt_a.get("perk_saving", 0)
            if perk_save > 0:
                lines.append(
                    f"- **Estimated perk value:** "
                    f"{rec.currency if rec else self.trip.currency} {perk_save:.2f}"
                )
            lines.append(f"- **Booking tip:** {perk.booking_tip}")
            lines.append("")
        elif chain:
            lines.append("### Hotel Chain Benefits")
            lines.append(f"- **Detected chain:** {chain}")
            lines.append(
                "- None of your cards have special co-brand perks for this chain."
            )
            lines.append("")

    def _report_hotel_option_b(self, lines: list[str]):
        nights_data = self.state.hotel_option_b
        if not nights_data:
            return

        # Suppress entirely if no night has any hotel data
        has_data = any(n.get("hotel_name") for n in nights_data)
        if not has_data:
            return

        lines.append("## Option B - Best Hotel Each Night (Book Separately)")
        lines.append(
            "_Book a different hotel each night to get the absolute cheapest rate per night._"
        )
        lines.append("")

        lines.append(
            "| Night | Date | Best Hotel | Platform | Price/Night | "
            "Best Card | Card Saving | Book |"
        )
        lines.append(
            "|-------|------|------------|----------|-------------|-----------|-------------|------|"
        )

        opt_b_total = 0.0
        opt_b_savings = 0.0
        currency = self.trip.currency

        for i, n in enumerate(nights_data, 1):
            if n.get("error"):
                lines.append(
                    f"| {i} | {n.get('check_in', '?')} | "
                    "_not found_ | - | - | - | - |"
                )
                continue

            night_date = n.get("check_in", n.get("night", "?"))
            hotel_name = n.get("hotel_name", "?")[:40]
            provider = n.get("provider", "?")
            price = n.get("price", 0.0)
            currency = n.get("currency", self.trip.currency)
            rec: Optional[CardRec] = n.get("best_card")
            card_name = rec.card.name if rec else "-"
            card_saving = rec.savings if rec else 0.0
            night_url = n.get("url", "")
            book = f"[Book ↗]({night_url})" if night_url else "-"

            opt_b_total += price
            opt_b_savings += card_saving

            lines.append(
                f"| {i} | {night_date} | {hotel_name} | {provider} | "
                f"{currency} {price:.2f} | {card_name} | "
                f"{currency} {card_saving:.2f} | {book} |"
            )

        lines.append(
            f"| **Total** | | | | "
            f"**{currency} {opt_b_total:.2f}** | | "
            f"**{currency} {opt_b_savings:.2f}** | |"
        )
        lines.append("")

        # Per-night perk details
        perk_nights = [
            n for n in nights_data
            if n.get("hotel_perk") and n.get("perk_card")
        ]
        if perk_nights:
            lines.append("### Chain Perks - Option B")
            for n in perk_nights:
                perk = n["hotel_perk"]
                card = n["perk_card"]
                lines.append(
                    f"- **Night {n.get('check_in', '?')} · {n.get('hotel_name', '')[:35]}**"
                )
                lines.append(f"  - Card: {card.name}")
                if perk.status_level:
                    lines.append(f"  - Status: {perk.status_level}")
                for item in perk.perks_list[:3]:
                    lines.append(f"    - {item}")
                lines.append(f"  - Tip: {perk.booking_tip}")
            lines.append("")

    def _report_option_comparison(self, lines: list[str]):
        opt_a = self.state.hotel_option_a
        opt_b = self.state.hotel_option_b

        total_a = opt_a.get("total_price")
        total_b = (
            sum(n["price"] for n in opt_b if n.get("price"))
            if opt_b else None
        )

        # Suppress entirely if no real data
        if (total_a is None or total_a == 0) and (total_b is None or total_b == 0):
            return

        currency = opt_a.get("currency", self.trip.currency)
        lines.append("## Hotel Options Summary")

        if total_a is not None:
            card_a: Optional[CardRec] = opt_a.get("best_card")
            eff_a = card_a.effective_price if card_a else total_a
            lines.append(
                f"- **Option A (same hotel, {opt_a.get('nights', 1)} nights):** "
                f"{currency} {total_a:.2f} list  →  "
                f"{currency} {eff_a:.2f} after best card"
            )

        if total_b is not None:
            opt_b_savings = sum(
                n["best_card"].savings for n in opt_b
                if n.get("best_card")
            )
            eff_b = total_b - opt_b_savings
            lines.append(
                f"- **Option B (per-night bookings):** "
                f"{currency} {total_b:.2f} list  →  "
                f"{currency} {eff_b:.2f} after best cards"
            )

        if total_a is not None and total_b is not None:
            diff = total_a - total_b
            if diff > 0:
                lines.append(
                    f"\n> **Option B saves {currency} {diff:.2f} "
                    f"({diff / total_a * 100:.1f}%) vs Option A** - "
                    f"worth booking separately if you do not mind different hotels each night."
                )
            elif diff < 0:
                lines.append(
                    f"\n> **Option A saves {currency} {abs(diff):.2f} "
                    f"({abs(diff) / total_b * 100:.1f}%) vs Option B** - "
                    f"staying in one hotel is cheaper (and more convenient)."
                )
            else:
                lines.append("\n> Both options cost the same - choose for convenience.")
        lines.append("")

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _city_name(iata_or_city: str) -> str:
        _MAP = {
            # ── Middle East ──
            "DXB": "Dubai", "AUH": "Abu Dhabi", "DOH": "Doha",
            "RUH": "Riyadh", "JED": "Jeddah", "BAH": "Bahrain",
            "MCT": "Muscat", "AMM": "Amman", "BEY": "Beirut",
            "CAI": "Cairo", "TLV": "Tel Aviv", "KWI": "Kuwait City",
            # ── Europe ──
            "LHR": "London", "LGW": "London", "STN": "London", "LTN": "London",
            "CDG": "Paris", "ORY": "Paris",
            "AMS": "Amsterdam", "FRA": "Frankfurt", "ZRH": "Zurich",
            "BCN": "Barcelona", "MAD": "Madrid", "FCO": "Rome", "MXP": "Milan",
            "VIE": "Vienna", "MUC": "Munich", "BER": "Berlin", "TXL": "Berlin",
            "HAM": "Hamburg", "DUS": "Dusseldorf", "CPH": "Copenhagen",
            "ARN": "Stockholm", "HEL": "Helsinki", "OSL": "Oslo",
            "LIS": "Lisbon", "ATH": "Athens", "WAW": "Warsaw",
            "PRG": "Prague", "BUD": "Budapest", "BRU": "Brussels",
            "GVA": "Geneva", "NCE": "Nice", "EDI": "Edinburgh",
            "MAN": "Manchester", "BHX": "Birmingham", "GLA": "Glasgow",
            # ── USA ──
            "JFK": "New York", "LGA": "New York", "EWR": "Newark",
            "LAX": "Los Angeles", "BUR": "Burbank", "LGB": "Long Beach", "SNA": "Orange County",
            "ORD": "Chicago", "MDW": "Chicago",
            "SFO": "San Francisco", "OAK": "Oakland", "SJC": "San Jose",
            "MIA": "Miami", "FLL": "Fort Lauderdale", "PBI": "West Palm Beach",
            "BOS": "Boston", "ATL": "Atlanta", "DFW": "Dallas", "DAL": "Dallas",
            "SEA": "Seattle", "PDX": "Portland", "DEN": "Denver",
            "LAS": "Las Vegas", "PHX": "Phoenix", "TUS": "Tucson",
            "MCO": "Orlando", "TPA": "Tampa", "RSW": "Fort Myers", "JAX": "Jacksonville",
            "MSP": "Minneapolis", "DTW": "Detroit", "PHL": "Philadelphia",
            "CLT": "Charlotte", "IAH": "Houston", "HOU": "Houston",
            "IAD": "Washington DC", "DCA": "Washington DC", "BWI": "Baltimore",
            "SAN": "San Diego", "MSY": "New Orleans", "SLC": "Salt Lake City",
            "BNA": "Nashville", "AUS": "Austin", "SAT": "San Antonio",
            "RDU": "Raleigh", "IND": "Indianapolis", "CMH": "Columbus",
            "MKE": "Milwaukee", "STL": "St. Louis", "CLE": "Cleveland",
            "PIT": "Pittsburgh", "BUF": "Buffalo", "ABQ": "Albuquerque",
            "SMF": "Sacramento", "HNL": "Honolulu", "OGG": "Maui",
            "KOA": "Kona", "ANC": "Anchorage",
            # ── Canada ──
            "YYZ": "Toronto", "YVR": "Vancouver", "YUL": "Montreal",
            "YYC": "Calgary", "YEG": "Edmonton",
            # ── India ──
            "DEL": "Delhi", "BOM": "Mumbai", "MAA": "Chennai",
            "BLR": "Bangalore", "HYD": "Hyderabad", "CCU": "Kolkata",
            "GOI": "Goa", "COK": "Kochi", "AMD": "Ahmedabad",
            "PNQ": "Pune", "JAI": "Jaipur", "LKO": "Lucknow",
            "ATQ": "Amritsar", "IXC": "Chandigarh", "NAG": "Nagpur",
            "BBI": "Bhubaneswar", "VTZ": "Visakhapatnam", "TRV": "Thiruvananthapuram",
            "CJB": "Coimbatore", "IDR": "Indore", "VNS": "Varanasi",
            "IXE": "Mangalore", "GAU": "Guwahati", "PAT": "Patna",
            # ── Asia ──
            "SIN": "Singapore", "BKK": "Bangkok", "KUL": "Kuala Lumpur",
            "HKG": "Hong Kong", "NRT": "Tokyo", "HND": "Tokyo",
            "KIX": "Osaka", "ICN": "Seoul", "GMP": "Seoul",
            "PVG": "Shanghai", "PEK": "Beijing", "PKX": "Beijing",
            "CAN": "Guangzhou", "CTU": "Chengdu",
            "MNL": "Manila", "CGK": "Jakarta", "DPS": "Bali",
            "HAN": "Hanoi", "SGN": "Ho Chi Minh City",
            "CMB": "Colombo", "DAC": "Dhaka", "KTM": "Kathmandu",
            "RGN": "Yangon", "REP": "Siem Reap", "PNH": "Phnom Penh",
            # ── Australia / NZ ──
            "SYD": "Sydney", "MEL": "Melbourne", "BNE": "Brisbane",
            "PER": "Perth", "ADL": "Adelaide",
            "AKL": "Auckland", "CHC": "Christchurch",
            # ── Africa ──
            "JNB": "Johannesburg", "CPT": "Cape Town", "NBO": "Nairobi",
            "ADD": "Addis Ababa", "LOS": "Lagos", "ACC": "Accra",
            "CMN": "Casablanca", "RAK": "Marrakech",
            # ── Latin America ──
            "GRU": "Sao Paulo", "GIG": "Rio de Janeiro", "EZE": "Buenos Aires",
            "BOG": "Bogota", "LIM": "Lima", "SCL": "Santiago",
            "MEX": "Mexico City", "CUN": "Cancun", "GDL": "Guadalajara",
        }
        return _MAP.get(iata_or_city.upper(), iata_or_city)

    def _nights(self) -> int:
        try:
            fmt = "%Y-%m-%d"
            h_in  = self.trip.hotel_check_in  or self.trip.check_in
            h_out = self.trip.hotel_check_out or self.trip.check_out
            return max(1, (datetime.strptime(h_out, fmt) - datetime.strptime(h_in, fmt)).days)
        except ValueError:
            return 1

    def _flight_search_url(self, provider: str) -> str:
        """Return a search URL for the given flight provider string."""
        t = self.trip
        p = provider.lower()
        origin, dest, date = t.origin, t.destination, t.check_in
        ret = t.return_date or ""
        ymd = date.replace("-", "")[2:]   # YYMMDD for Skyscanner
        if "google" in p:
            return (f"https://www.google.com/travel/flights?hl=en"
                    f"#flt={origin}.{dest}.{date};c:{t.currency};e:1;sd:1;t:f")
        if "kayak" in p:
            base = f"https://www.kayak.com/flights/{origin}-{dest}/{date}"
            return base + (f"/{ret}" if t.trip_type == "round-trip" and ret else "")
        if "skyscanner" in p:
            return (f"https://www.skyscanner.net/transport/flights/"
                    f"{origin.lower()}/{dest.lower()}/{ymd}/")
        if "makemytrip" in p or "mmt" in p:
            return (f"https://www.makemytrip.com/flight/search"
                    f"?itinerary={origin}-{dest}-{date.replace('-', '')}&tripType=O")
        return ""

    def _hotel_search_url(self, provider: str) -> str:
        """Return a search URL for the given hotel provider string."""
        t = self.trip
        h_in  = t.hotel_check_in  or t.check_in
        h_out = t.hotel_check_out or t.check_out
        city  = self._city_name(t.destination)
        p = provider.lower()
        if "booking" in p:
            return (f"https://www.booking.com/searchresults.html"
                    f"?ss={city}&checkin={h_in}&checkout={h_out}&group_adults={t.adults}")
        if "expedia" in p:
            return (f"https://www.expedia.com/Hotel-Search"
                    f"?destination={city}&startDate={h_in}&endDate={h_out}&adults={t.adults}")
        if "hotels.com" in p:
            return (f"https://www.hotels.com/Hotel-Search"
                    f"?destination={city}&startDate={h_in}&endDate={h_out}&adults={t.adults}")
        if "agoda" in p:
            return (f"https://www.agoda.com/search"
                    f"?city={city}&checkIn={h_in}&checkOut={h_out}&adults={t.adults}")
        if "airbnb" in p:
            return (f"https://www.airbnb.com/s/{city.replace(' ', '-')}/homes"
                    f"?checkin={h_in}&checkout={h_out}&adults={t.adults}")
        if "marriott" in p:
            return (f"https://www.marriott.com/search/default.mi"
                    f"?cityName={city}&checkinDate={h_in}&checkoutDate={h_out}")
        if "hilton" in p:
            return (f"https://www.hilton.com/en/hotels/"
                    f"?search={city}&checkIn={h_in}&checkOut={h_out}&numAdults={t.adults}")
        if "ihg" in p:
            return f"https://www.ihg.com/hotels/us/en/find-hotels/hotel/list?qDest={city}"
        if "hyatt" in p:
            return (f"https://www.hyatt.com/en-US/search"
                    f"?destination={city}&checkinDate={h_in}&checkoutDate={h_out}")
        if "accor" in p:
            return (f"https://all.accor.com/hotel/index.en.shtml"
                    f"?search={city}&dateIn={h_in}&dateOut={h_out}")
        if "radisson" in p:
            return (f"https://www.radissonhotels.com/en-us/search"
                    f"?destination={city}&checkIn={h_in}&checkOut={h_out}")
        return ""

    def _fetch_flights(self) -> list[FlightResult]:
        from flight_scrapers import scrape_all_flights
        t = self.trip
        rows, status = scrape_all_flights(
            t.origin, t.destination, t.check_in,
            t.adults, t.currency,
            trip=t.trip_type,
            return_date=t.return_date or "",
        )
        self.state.flight_platform_status = status
        hits   = [(p, s) for p, s in status.items() if s.startswith("✓") and "0 results" not in s]
        misses = [p for p, s in status.items() if not s.startswith("✓") or "0 results" in s]
        for platform, st in hits:
            self._ok(f"Flights / {platform}: {st}")
        if misses:
            self._log(f"Flights / no results: {', '.join(misses)}")
        return [
            FlightResult(
                title=r["title"], provider=r["provider"],
                price=r["price"], currency=r["currency"],
                details={
                    k: r[k]
                    for k in ("departure", "arrival", "duration", "stops")
                    if k in r
                },
                url=r.get("url", "") or self._flight_search_url(r["provider"]),
            )
            for r in rows
        ]

    def _fetch_hotels(self) -> list[HotelResult]:
        from hotel_scrapers import scrape_all_hotels, scrape_hotels_per_night

        city = self._city_name(self.trip.destination)
        # Use custom hotel dates if provided, else fall back to flight dates
        h_in  = self.trip.hotel_check_in  or self.trip.check_in
        h_out = self.trip.hotel_check_out or self.trip.check_out

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f_all = pool.submit(
                scrape_all_hotels,
                city, h_in, h_out,
                self.trip.adults, self.trip.currency,
            )
            f_per = pool.submit(
                scrape_hotels_per_night,
                city, h_in, h_out,
                self.trip.adults, self.trip.currency,
            )
            rows, status = f_all.result()
            per_night = f_per.result()

        self.state.hotel_platform_status = status
        self.state.hotels_per_night = per_night

        hits   = [(p, s) for p, s in status.items() if s.startswith("✓") and "0 results" not in s]
        misses = [p for p, s in status.items() if not s.startswith("✓") or "0 results" in s]
        for platform, st in hits:
            self._ok(f"Hotels / {platform}: {st}")
        if misses:
            self._log(f"Hotels / no results: {', '.join(misses)}")

        if per_night:
            self._ok(f"Per-night breakdown: {len(per_night)} night(s) fetched")
        else:
            self._warn("Per-night hotel data unavailable")

        return [
            HotelResult(
                title=r["title"], provider=r["provider"],
                price=r["price"], currency=r["currency"],
                url=r.get("url", "") or self._hotel_search_url(r["provider"]),
            )
            for r in rows
        ]


# ─── Public entry point ───────────────────────────────────────────────────────

def run_pipeline(trip: TripRequest, progress_callback=None) -> str:
    """
    Run the full agentic pipeline and return the markdown report string.
    Prints step-by-step progress to stdout.
    If progress_callback is provided, it is called with each progress line.
    """
    agent = TripAgent(trip, progress_callback=progress_callback)

    print("\n" + "━" * 60)
    print("  STAGE 1 - PLAN")
    print("━" * 60)
    tasks = agent.plan()

    print("\n" + "━" * 60)
    print("  STAGE 2 - FETCH  (live data)")
    print("━" * 60)
    agent.fetch(tasks)

    print("\n" + "━" * 60)
    print("  STAGE 3 - ANALYZE  (card knowledge base)")
    print("━" * 60)
    recs = agent.analyze()

    print("\n" + "━" * 60)
    print("  STAGE 4 - REPORT")
    print("━" * 60)
    return agent.report(recs)
