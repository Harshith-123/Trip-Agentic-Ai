"""
Multi-source flight price scrapers - global coverage.

Primary source:
  Google Flights  - via fast-flights protobuf API (works for ALL world airports)
                    Strategies: direct query, reverse query, date-shift retry

Secondary sources (Playwright + API interception):
  Kayak           - captures XHR responses from their internal API
  Skyscanner      - captures v3 conductor API responses
  MakeMyTrip      - Playwright renders the React SPA and captures API responses

All scrapers run concurrently; failures are isolated.
"""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any

import primp

# ─── Preload system deps for Playwright Chromium ──────────────────────────
# On some Linux systems (e.g. WSL), libasound is missing.
# We bundle it in .playwright_libs/ and add it to the loader path.
_PW_LIBS = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".playwright_libs")
if os.path.isdir(_PW_LIBS):
    old = os.environ.get("LD_LIBRARY_PATH", "")
    if _PW_LIBS not in old:
        os.environ["LD_LIBRARY_PATH"] = f"{_PW_LIBS}:{old}" if old else _PW_LIBS

# ─── Stealth JS - overrides headless browser fingerprints ─────────────────────

_STEALTH_JS = """
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
    window.chrome = {runtime: {}, loadTimes: function(){}, csi: function(){}, app: {}};
    const _origQuery = window.navigator.permissions.query.bind(navigator.permissions);
    window.navigator.permissions.query = (p) =>
        p.name === 'notifications'
            ? Promise.resolve({state: Notification.permission})
            : _origQuery(p);
"""


# ─── HTTP client ──────────────────────────────────────────────────────────────

def _client() -> primp.Client:
    try:
        return primp.Client(impersonate="chrome_127", verify=False,
                            timeout=30, follow_redirects=True)
    except Exception:
        return primp.Client(verify=False, timeout=30, follow_redirects=True)


# ─── Playwright helpers ───────────────────────────────────────────────────────

def _pw_launch(pw: Any):
    """Create a stealth-configured Chromium browser + context. Returns (browser, ctx)."""
    browser = pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox", "--disable-setuid-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ],
    )
    ctx = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="America/New_York",
        viewport={"width": 1920, "height": 1080},
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    ctx.add_init_script(_STEALTH_JS)
    return browser, ctx


def _pw_capture_flight_api(url: str, api_patterns: list[str]) -> list[dict]:
    """
    Load a page with Playwright and capture JSON from API calls matching patterns.
    Returns list of parsed JSON response bodies.
    """
    try:
        from playwright.sync_api import sync_playwright
        captured: list[dict] = []

        with sync_playwright() as pw:
            browser, ctx = _pw_launch(pw)
            page = ctx.new_page()
            page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,ico}",
                       lambda r: r.abort())

            def handle(response: Any) -> None:
                if any(p in response.url for p in api_patterns):
                    try:
                        captured.append(response.json())
                    except Exception:
                        pass

            page.on("response", handle)
            try:
                page.goto(url, wait_until="networkidle", timeout=45_000)
            except Exception:
                pass
            try:
                page.wait_for_timeout(3_000)
            except Exception:
                pass
            browser.close()
        return captured
    except Exception:
        return []


def _pw_get_text(url: str, wait_selector: str | None = None,
                 extra_wait_ms: int = 0) -> str:
    """Render a page with Playwright (stealth mode) and return its full HTML text."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser, ctx = _pw_launch(pw)
            page = ctx.new_page()
            page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,ico}",
                       lambda r: r.abort())
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45_000)
                if wait_selector:
                    try:
                        page.wait_for_selector(wait_selector, timeout=20_000)
                    except Exception:
                        pass
                if extra_wait_ms:
                    page.wait_for_timeout(extra_wait_ms)
                return page.content()
            except Exception:
                try:
                    return page.content()
                except Exception:
                    return ""
            finally:
                browser.close()
    except Exception:
        return ""


def _parse_price(raw: Any) -> float:
    digits = re.sub(r"[^\d.]", "", str(raw))
    try:
        return float(digits) if digits else 0.0
    except ValueError:
        return 0.0


# ─── Google Flights - robust global scraper ───────────────────────────────────

def _gf_fetch_raw(origin: str, destination: str, date: str, _attempt: int = 0) -> list:
    """
    Fetch Google Flights for a given one-way route+date.
    Returns raw fast-flights Flight objects (empty list on failure).
    Retries once if the response contains unnamed flights (Google intermittent issue).
    """
    from fast_flights import FlightData, Passengers, TFSData
    from fast_flights.core import parse_response

    f = TFSData.from_interface(
        flight_data=[FlightData(date=date, from_airport=origin, to_airport=destination)],
        trip="one-way", seat="economy",
        passengers=Passengers(adults=1, children=0,
                              infants_in_seat=0, infants_on_lap=0),
    )
    params = {"tfs": f.as_b64().decode(), "hl": "en",
              "tfu": "EgQIABABIgA", "curr": "USD"}
    res = _client().get("https://www.google.com/travel/flights", params=params)
    if res.status_code != 200:
        return []
    try:
        flights = parse_response(res).flights
        if flights and _attempt == 0:
            named = sum(1 for fl in flights if fl.name and fl.name.strip())
            if named < len(flights) // 2:
                import time
                time.sleep(0.5)
                return _gf_fetch_raw(origin, destination, date, _attempt=1)
        return flights
    except Exception:
        return []


def _gf_to_dicts(raw_flights: list, origin: str, destination: str,
                 currency: str, search_url: str = "") -> list[dict]:
    """Convert fast-flights Flight objects to our standard dict format."""
    out = []
    for idx, f in enumerate(raw_flights, 1):
        price = _parse_price(f.price)
        if price <= 0:
            continue
        airline = f.name.strip() or f"Option {idx}"
        stops_raw = f.stops
        if stops_raw == 0:
            stops = "Nonstop"
        elif isinstance(stops_raw, int):
            stops = f"{stops_raw} stop(s)"
        else:
            stops = str(stops_raw)
        out.append({
            "title": f"{origin} to {destination} - {airline}",
            "provider": f"Google Flights ({airline})",
            "airline": airline,
            "price": price,
            "currency": currency,
            "url": search_url,
            "departure": f.departure or "",
            "arrival": f.arrival or "",
            "duration": f.duration or "",
            "stops": stops,
        })
    return out


def scrape_google_flights(
    origin: str, destination: str, date: str,
    adults: int = 1, currency: str = "USD",
    trip: str = "one-way", return_date: str = "",
) -> list[dict]:
    """
    Scrape Google Flights for ANY world airport pair.
    Round-trip is handled as two independent one-way queries so we always
    get proper airline names, departure/arrival times and durations.
    Strategy per leg: direct -> reverse -> date-shift.
    """
    try:
        outbound = _fetch_leg(origin, destination, date, currency, "Outbound")

        if trip == "round-trip" and return_date:
            inbound = _fetch_leg(destination, origin, return_date, currency, "Return")
            for r in inbound:
                r["title"]    = f"{origin} to {destination} (Return: {destination}→{origin})"
                r["provider"] = r["provider"].replace("Google Flights", "Google Flights Return")
            return outbound + inbound

        return outbound
    except Exception:
        return []


def _fetch_leg(
    origin: str, destination: str, date: str,
    currency: str, label: str = "",
) -> list[dict]:
    """Fetch one flight leg with direct -> reverse -> date-shift fallback."""
    search_url = (
        f"https://www.google.com/travel/flights?hl=en"
        f"#flt={origin}.{destination}.{date};c:{currency};e:1;sd:1;t:f"
    )
    raw = _gf_fetch_raw(origin, destination, date)
    if raw:
        return _gf_to_dicts(raw, origin, destination, currency, search_url)

    raw_rev = _gf_fetch_raw(destination, origin, date)
    if raw_rev:
        return _gf_to_dicts(raw_rev, origin, destination, currency, search_url)

    dt = datetime.strptime(date, "%Y-%m-%d")
    for delta in [7, 14, 21, 30]:
        shifted = (dt + timedelta(days=delta)).strftime("%Y-%m-%d")
        raw_s = _gf_fetch_raw(origin, destination, shifted)
        if not raw_s:
            raw_s = _gf_fetch_raw(destination, origin, shifted)
        if raw_s:
            results = _gf_to_dicts(raw_s, origin, destination, currency, search_url)
            for r in results:
                r["provider"] += " (est.)"
            return results
    return []


# ─── Kayak - Playwright + API interception ────────────────────────────────────

def _kayak_parse_html(text: str, origin: str, destination: str,
                      currency: str, search_url: str) -> list[dict]:
    """Extract flight data from Kayak rendered HTML - multi-strategy fallback."""
    import json as _json
    out: list[dict] = []

    # Strategy 1: Next.js / Redux embedded JSON
    for pat in [
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>([\s\S]*?)</script>',
        r'window\.__REDUX_STATE__\s*=\s*(\{.*?\});',
    ]:
        m = re.search(pat, text, re.DOTALL)
        if not m:
            continue
        try:
            data = _json.loads(m.group(1))
            results = _walk_for_flights(data)
            if results:
                return [
                    {
                        "title": f"{origin} to {destination} - {r['airline']}",
                        "provider": f"Kayak ({r['airline']})",
                        "airline": r["airline"],
                        "price": r["price"],
                        "currency": currency,
                        "url": search_url,
                        "departure": r.get("departure", ""),
                        "arrival": r.get("arrival", ""),
                        "duration": r.get("duration", ""),
                        "stops": r.get("stops", "?"),
                    }
                    for r in results
                ]
        except Exception:
            continue

    # Strategy 2: regex on rendered HTML - try both field orderings
    for pat in [
        (r'"(?:carrierName|airlineName|name|carrier)"\s*:\s*"([A-Za-z][^"]{2,39})"'
         r'[\s\S]{0,500}?"(?:totalPrice|displayPrice|price|amount)"\s*:\s*"?(\d{3,6})"?'),
        (r'"(?:totalPrice|displayPrice|price|amount)"\s*:\s*"?(\d{3,6})"?'
         r'[\s\S]{0,500}?"(?:carrierName|airlineName|name)"\s*:\s*"([A-Za-z][^"]{2,39})"'),
    ]:
        matches = re.findall(pat, text)
        seen: set[str] = set()
        for m in matches[:10]:
            # figure out which group is airline vs price
            a, b = m[0], m[1]
            if b.isdigit() and not a.isdigit():
                airline, price_str = a, b
            elif a.isdigit() and not b.isdigit():
                airline, price_str = b, a
            else:
                continue
            price = float(price_str)
            if price > 0 and airline not in seen:
                seen.add(airline)
                out.append({
                    "title": f"{origin} to {destination} - {airline}",
                    "provider": f"Kayak ({airline})",
                    "airline": airline,
                    "price": price,
                    "currency": currency,
                    "url": search_url,
                    "departure": "", "arrival": "", "duration": "", "stops": "?",
                })
        if out:
            return out
    return out


def scrape_kayak(
    origin: str, destination: str, date: str,
    adults: int = 1, currency: str = "USD",
) -> list[dict]:
    """Kayak - API interception primary, rendered HTML fallback."""
    try:
        search_url = f"https://www.kayak.com/flights/{origin}-{destination}/{date}?sort=price_a"

        # Primary: capture XHR API responses
        captured = _pw_capture_flight_api(
            search_url,
            api_patterns=[
                "api/v3/c/", "flights/results", "/mvm/",
                "kayak.com/api", "flightresults", "searchresults",
                "multicity", "api/flights", "k/f/", "/f/",
                "search/flights",
            ],
        )
        out: list[dict] = []
        for data in captured:
            for f in _walk_for_flights(data)[:10]:
                out.append({
                    "title": f"{origin} to {destination} - {f['airline']}",
                    "provider": f"Kayak ({f['airline']})",
                    "airline": f["airline"],
                    "price": f["price"],
                    "currency": currency,
                    "url": search_url,
                    "departure": f.get("departure", ""),
                    "arrival": f.get("arrival", ""),
                    "duration": f.get("duration", ""),
                    "stops": f.get("stops", "?"),
                })
        if out:
            return out[:10]

        # Fallback: parse rendered HTML after JS executes
        html = _pw_get_text(
            search_url,
            wait_selector=(
                "[class*='result'],[class*='flight'],[class*='price'],"
                "[class*='ResultItem'],[class*='FlightCard']"
            ),
            extra_wait_ms=5_000,
        )
        return _kayak_parse_html(html, origin, destination, currency, search_url)
    except Exception:
        return []


def _walk_for_flights(data: Any, depth: int = 0) -> list[dict]:
    """Recursively walk a JSON structure looking for flight result arrays."""
    if depth > 8:
        return []
    if isinstance(data, dict):
        if "totalPrice" in data or "displayPrice" in data:
            price = _parse_price(data.get("totalPrice") or data.get("displayPrice") or 0)
            carrier = data.get("carrier") or {}
            airline = (
                data.get("carrierName") or data.get("airlineName")
                or (carrier.get("name") if isinstance(carrier, dict) else "")
                or ""
            )
            if price > 100 and airline:
                return [{"airline": airline, "price": price,
                         "departure": str(data.get("departure", "")),
                         "arrival": str(data.get("arrival", "")),
                         "duration": str(data.get("duration", "")),
                         "stops": str(data.get("stops", "?"))}]
        results = []
        for v in data.values():
            results.extend(_walk_for_flights(v, depth + 1))
            if len(results) >= 10:
                break
        return results
    if isinstance(data, list):
        results = []
        for item in data[:20]:
            results.extend(_walk_for_flights(item, depth + 1))
            if len(results) >= 10:
                break
        return results
    return []


# ─── Skyscanner - Playwright + API interception ───────────────────────────────

def _skyscanner_parse_captured(captured: list[dict], origin: str,
                                destination: str, currency: str,
                                search_url: str) -> list[dict]:
    """Parse Skyscanner API JSON responses captured via Playwright."""
    out: list[dict] = []
    seen: set[str] = set()
    for data in captured:
        itineraries = (
            _dig(data, "content", "results", "itineraries")
            or _dig(data, "itineraries")
            or {}
        )
        if isinstance(itineraries, dict):
            itineraries = list(itineraries.values())
        for it in (itineraries or [])[:15]:
            price = _parse_price(
                _dig(it, "pricingOptions", 0, "price", "amount")
                or _dig(it, "price", "raw")
                or 0
            )
            if price <= 0:
                continue
            legs = _dig(it, "legs") or []
            carriers: list[str] = []
            for leg_id in (legs if isinstance(legs, list) else []):
                leg = _dig(data, "content", "results", "legs", leg_id) or {}
                for seg in (leg.get("segments") or []):
                    name = (
                        _dig(data, "content", "results", "carriers",
                             str(seg.get("marketingCarrierId")), "name")
                        or ""
                    )
                    if name and name not in carriers:
                        carriers.append(name)
            airline = ", ".join(carriers) if carriers else "Unknown"
            key = f"{airline}:{price}"
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "title": f"{origin} to {destination} - {airline}",
                "provider": f"Skyscanner ({airline})",
                "airline": airline,
                "price": price,
                "currency": currency,
                "url": search_url,
                "departure": "", "arrival": "", "duration": "",
                "stops": (str(len(legs) - 1) + " stop(s)"
                          if isinstance(legs, list) and len(legs) > 1 else "Nonstop"),
            })
    return sorted(out, key=lambda x: x["price"])[:10]


def scrape_skyscanner(
    origin: str, destination: str, date: str,
    adults: int = 1, currency: str = "USD",
) -> list[dict]:
    """Skyscanner - API interception (conductor v1/fps3) with HTML fallback."""
    try:
        year, month, day = date.split("-")
        ymd = f"{year[2:]}{month}{day}"
        search_url = (
            f"https://www.skyscanner.net/transport/flights/"
            f"{origin.lower()}/{destination.lower()}/{ymd}/"
            f"?adults={adults}&currency={currency}&locale=en-US&cabinclass=economy"
        )

        # Primary: capture API responses - broad patterns to catch v3 or newer
        captured = _pw_capture_flight_api(
            search_url,
            api_patterns=[
                "api/v3/flights", "conductor/v1", "fps3",
                "flight-search", "skyscanner.net/api",
                "itineraries", "live/search", "flights/live",
                "create-poll", "/g/conductor", "poll/",
                "flights/search/create",
            ],
        )
        results = _skyscanner_parse_captured(captured, origin, destination,
                                             currency, search_url)
        if results:
            return results

        # Fallback: rendered HTML parsing
        html = _pw_get_text(
            search_url,
            wait_selector=(
                "[class*='FlightCard'],[data-testid*='flight'],"
                "[class*='flight-card'],[class*='result']"
            ),
            extra_wait_ms=5_000,
        )
        # Extract from embedded JSON
        prices = re.findall(r'"(?:amount|price)"\s*:\s*([\d.]+)', html)
        carriers = re.findall(
            r'"(?:operatingCarrierName|carrierName|iata|name)"\s*:\s*"([A-Za-z][^"]{2,39})"',
            html,
        )
        out: list[dict] = []
        seen_p: set[float] = set()
        for raw_price, carrier in zip(prices, carriers or ["Unknown"] * len(prices)):
            try:
                price = float(raw_price)
            except ValueError:
                continue
            if price <= 100 or price in seen_p:
                continue
            seen_p.add(price)
            out.append({
                "title": f"{origin} to {destination} - {carrier}",
                "provider": f"Skyscanner ({carrier})",
                "airline": carrier,
                "price": price,
                "currency": currency,
                "url": search_url,
                "departure": "", "arrival": "", "duration": "", "stops": "?",
            })
        return out[:8]
    except Exception:
        return []


# ─── MakeMyTrip - Playwright + API interception ───────────────────────────────

def scrape_makemytrip_flights(
    origin: str, destination: str, date: str,
    adults: int = 1, currency: str = "INR",
) -> list[dict]:
    """
    MakeMyTrip - best for Indian routes (BOM, DEL, BLR, MAA, HYD, CCU).
    Uses Playwright to render the React SPA and captures their API responses.
    """
    try:
        date_mmt = date.replace("-", "")
        search_url = (
            f"https://www.makemytrip.com/flight/search"
            f"?itinerary={origin}-{destination}-{date_mmt}"
            f"&tripType=O&paxType=A-{adults}_C-0_I-0&intl=true&cabinClass=E"
        )

        # Primary: API interception (MMT uses apigateway.makemytrip.com)
        captured = _pw_capture_flight_api(
            search_url,
            api_patterns=[
                "apigateway.makemytrip.com", "makemytrip.com/api",
                "restful/web/listing", "airlistingV3", "flightlist",
                "flight/search", "/air/", "flightSearch",
                "intl/search", "listing/air", "airSearch",
            ],
        )
        out: list[dict] = []
        for data in captured:
            flights = (
                _dig(data, "data", "opflst")
                or _dig(data, "flightList")
                or _dig(data, "data", "flightList")
                or _dig(data, "results")
                or []
            )
            if isinstance(flights, list):
                for f in flights[:8]:
                    name = (
                        _dig(f, "al", "alN")
                        or _dig(f, "airlineName")
                        or _dig(f, "carrier", "name")
                        or f.get("carrier", "")
                    )
                    price = _parse_price(
                        _dig(f, "fareInfo", "totalPrice")
                        or _dig(f, "price", "totalPrice")
                        or _dig(f, "totalFare")
                        or f.get("totalPrice", 0)
                    )
                    if name and price > 0:
                        out.append({
                            "title": f"{origin} to {destination} - {name}",
                            "provider": f"MakeMyTrip ({name})",
                            "airline": name, "price": price, "currency": "INR",
                            "url": search_url,
                            "departure": "", "arrival": "", "duration": "", "stops": "?",
                        })
        if out:
            return out[:8]

        # Fallback: parse rendered HTML after Playwright executes the React SPA
        html = _pw_get_text(
            search_url,
            wait_selector=(
                "[class*='fli-'],[class*='flight'],"
                "[data-cy*='flight'],[class*='listingCard']"
            ),
            extra_wait_ms=8_000,
        )
        names = (
            re.findall(r'"airlineName"\s*:\s*"([^"]+)"', html)
            or re.findall(r'"al(?:N|Name)"\s*:\s*"([A-Za-z][^"]{2,39})"', html)
            or re.findall(r'"name"\s*:\s*"([A-Z][A-Za-z ]{4,39})"', html)
        )
        prices = (
            re.findall(r'"totalPrice"\s*:\s*(\d+)', html)
            or re.findall(r'"totalFare"\s*:\s*(\d+)', html)
            or re.findall(r'"price"\s*:\s*(\d{4,6})', html)
        )
        result: list[dict] = []
        seen: set[str] = set()
        for name, p in zip(names, prices):
            price = float(p)
            if price > 0 and name not in seen:
                seen.add(name)
                result.append({
                    "title": f"{origin} to {destination} - {name}",
                    "provider": f"MakeMyTrip ({name})",
                    "airline": name, "price": price, "currency": "INR",
                    "url": search_url,
                    "departure": "", "arrival": "", "duration": "", "stops": "?",
                })
        return result[:8]
    except Exception:
        return []


# ─── Aggregator ───────────────────────────────────────────────────────────────

_SCRAPERS = {
    "Google Flights": scrape_google_flights,
    "Kayak":          scrape_kayak,
    "Skyscanner":     scrape_skyscanner,
    "MakeMyTrip":     scrape_makemytrip_flights,
}


def scrape_all_flights(
    origin: str,
    destination: str,
    date: str,
    adults: int = 1,
    currency: str = "USD",
    trip: str = "one-way",
    return_date: str = "",
) -> tuple[list[dict], dict[str, str]]:
    """
    Run all flight scrapers concurrently and merge results.
    Returns (flights_sorted_cheapest_first, platform_status_dict).
    """
    all_flights: list[dict] = []
    platform_status: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=len(_SCRAPERS)) as pool:
        futures = {
            pool.submit(fn, origin, destination, date, adults, currency,
                        *(  (trip, return_date) if fn is scrape_google_flights else () )): name
            for name, fn in _SCRAPERS.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                results = future.result()
                all_flights.extend(results)
                platform_status[name] = f"✓ {len(results)} results" if results else "⚠ 0 results"
            except Exception as exc:
                platform_status[name] = f"✗ failed: {exc}"

    return _dedup_flights(all_flights), platform_status


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _flight_airline(f: dict) -> str:
    """Extract airline name from whichever key the scraper used."""
    for key in ("airlines", "airline"):
        val = f.get(key, "")
        if val and not str(val).startswith("Option "):
            return str(val).lower().strip()
    # Fall back: pull airline out of "Duffel (Lufthansa)" or similar
    provider = f.get("provider", "")
    m = re.search(r'\((.+?)\)', provider)
    return m.group(1).lower().strip() if m else provider.lower().strip()


def _dedup_flights(flights: list[dict]) -> list[dict]:
    """
    Collapse duplicate flight listings.
    Two flights are the same itinerary if they share:
      (airline, departure-date, stop-count)
    Keep only the cheapest fare per combination.
    Also drops unnamed 'Option X' entries with no schedule data.
    """
    best: dict[tuple, dict] = {}
    for f in flights:
        airline = _flight_airline(f)
        if airline.startswith("option "):
            continue
        dep_day = str(f.get("departure", ""))[:10]
        stops   = f.get("stops", -1)
        key     = (airline, dep_day, stops)
        if key not in best or f["price"] < best[key]["price"]:
            best[key] = f
    return sorted(best.values(), key=lambda x: x["price"])


def _dig(d: Any, *keys) -> Any:
    for k in keys:
        if isinstance(d, list):
            try:
                d = d[int(k)]
            except (IndexError, ValueError, TypeError):
                return None
        elif isinstance(d, dict):
            d = d.get(k)
        else:
            return None
    return d
