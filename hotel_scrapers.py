"""
Multi-platform hotel price scrapers.

OTAs (JS-rendered, Playwright + API interception):
  Booking.com, Expedia, Hotels.com, Agoda, Airbnb

Hotel chain direct websites (Playwright + API interception):
  Marriott, Hilton, IHG, Hyatt, Accor, Radisson

Each function returns:
  [{"title", "provider", "chain", "price", "currency", "per_night"}, ...]

Supports two search modes:
  scrape_all_hotels()       → full stay (check_in → check_out), Option A
  scrape_hotels_per_night() → each night individually,           Option B
"""

from __future__ import annotations

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any

import httpx
import primp

# ─── Preload system deps for Playwright Chromium ──────────────────────────
# On some Linux systems (e.g. WSL), libasound is missing.
# We bundle it in .playwright_libs/ and add it to the loader path.
_PW_LIBS = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".playwright_libs")
if os.path.isdir(_PW_LIBS):
    old = os.environ.get("LD_LIBRARY_PATH", "")
    if _PW_LIBS not in old:
        os.environ["LD_LIBRARY_PATH"] = f"{_PW_LIBS}:{old}" if old else _PW_LIBS

# ─── Stealth JS - override headless fingerprints ──────────────────────────────

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


# ─── HTTP client (for chain API calls) ───────────────────────────────────────

def _client() -> primp.Client:
    # Use a known impersonation string or fall back to no impersonation
    try:
        return primp.Client(impersonate="chrome_127", verify=False,
                            timeout=30, follow_redirects=True)
    except Exception:
        return primp.Client(verify=False, timeout=30, follow_redirects=True)


def _parse_price(raw: Any) -> float:
    digits = re.sub(r"[^\d.]", "", str(raw))
    try:
        return float(digits) if digits else 0.0
    except ValueError:
        return 0.0


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


_JSON = "application/json"
_HTML_PARSER = "html.parser"
_RE_HOTEL_NAME = r'"hotelName"\s*:\s*"([^"]+)"'
_RE_PRICE_DIGITS = re.compile(r"[\d,]{3,}")


def _night_dates(check_in: str, check_out: str) -> list[tuple[str, str]]:
    fmt = "%Y-%m-%d"
    cur = datetime.strptime(check_in, fmt)
    end = datetime.strptime(check_out, fmt)
    result = []
    while cur < end:
        nxt = cur + timedelta(days=1)
        result.append((cur.strftime(fmt), nxt.strftime(fmt)))
        cur = nxt
    return result


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
        viewport={"width": 1920, "height": 1080},
        locale="en-US",
        timezone_id="America/New_York",
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
    )
    ctx.add_init_script(_STEALTH_JS)
    return browser, ctx


def _http_get_text(url: str, timeout: int = 30_000) -> str:
    """Fetch page HTML using primp HTTP client (no JS rendering)."""
    try:
        client = primp.Client(verify=False, timeout=timeout // 1000,
                              follow_redirects=True,
                              headers={"Accept-Language": "en-US,en;q=0.9"})
        resp = client.get(url)
        return resp.text
    except Exception:
        return ""


def _pw_available() -> bool:
    """Check if Playwright chromium can launch (system deps available)."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, timeout=10_000)
            browser.close()
        return True
    except Exception:
        return False


def _pw_get_html(
    url: str,
    *,
    wait_selector: str | None = None,
    extra_wait_ms: int = 0,
    click_selector: str | None = None,
    timeout: int = 30_000,
    try_http_first: bool = False,
) -> str:
    """Fetch a fully JS-rendered page using Playwright Chromium (stealth mode).
    
    If try_http_first is True, attempts a lightweight primp HTTP request first.
    Falls back to Playwright if the HTTP request fails or returns empty.
    Note: try_http_first defaults to False because many sites return bot
    challenge pages via plain HTTP, and Playwright stealth mode handles them better.
    """
    if try_http_first:
        html = _http_get_text(url, timeout)
        if html:
            return html

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser, ctx = _pw_launch(pw)
        page = ctx.new_page()

        page.route(
            "**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,ico}",
            lambda r: r.abort(),
        )

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout)

            for btn in [
                "#onetrust-accept-btn-handler",
                '[data-testid="accept-button"]',
                'button[id*="accept"]',
                'button[class*="accept"]',
            ]:
                try:
                    page.click(btn, timeout=2_000)
                    break
                except Exception:
                    pass

            if click_selector:
                try:
                    page.click(click_selector, timeout=3_000)
                except Exception:
                    pass

            if wait_selector:
                try:
                    page.wait_for_selector(wait_selector, timeout=timeout // 2)
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


def _pw_capture_hotel_api(url: str, api_patterns: list[str],
                           timeout: int = 45_000) -> list[dict]:
    """Load a hotel search page and capture JSON API responses matching patterns."""
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
                page.goto(url, wait_until="networkidle", timeout=timeout)
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


def _extract_next_data(html: str) -> dict:
    """Extract Next.js __NEXT_DATA__ from rendered HTML."""
    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>([\s\S]*?)</script>',
        html,
    )
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
#  Booking.com - Playwright + BeautifulSoup (working)
# ---------------------------------------------------------------------------

def _bk_name(card: Any) -> str | None:
    el = (
        card.find("div", attrs={"data-testid": "title"})
        or card.find("h3")
        or card.find("strong")
    )
    return el.get_text(strip=True) if el else None


def _bk_price(card: Any) -> float:
    for testid in ["price-and-discounted-price", "taxes-and-charges", "price"]:
        el = card.find(attrs={"data-testid": testid})
        if el:
            p = _parse_price(el.get_text())
            if p > 0:
                return p
    for candidate in card.find_all(True):
        text = candidate.get_text()
        if _RE_PRICE_DIGITS.search(text):
            p = _parse_price(text)
            if 10 < p < 100_000:
                return p
    return 0.0


def _bk_url(card: Any, fallback: str) -> str:
    for a in card.find_all("a", href=True):
        href = a["href"]
        if "/hotel/" in href:
            if not href.startswith("http"):
                href = "https://www.booking.com" + href
            return href.split("?")[0]
    return fallback


def scrape_booking(
    city: str, check_in: str, check_out: str, adults: int, currency: str
) -> list[dict]:
    """Booking.com - Playwright renders the React page, BeautifulSoup parses results."""
    try:
        from bs4 import BeautifulSoup

        search_url = (
            "https://www.booking.com/searchresults.html"
            f"?ss={city}&checkin={check_in}&checkout={check_out}"
            f"&group_adults={adults}&no_rooms=1"
            f"&selected_currency={currency}&lang=en-us&offset=0"
        )
        html = _pw_get_html(
            search_url,
            wait_selector='[data-testid="property-card"]',
            timeout=35_000,
        )
        soup = BeautifulSoup(html, _HTML_PARSER)
        out: list[dict] = []
        for card in soup.find_all("div", attrs={"data-testid": "property-card"})[:15]:
            name = _bk_name(card)
            if not name:
                continue
            price = _bk_price(card)
            if price > 0:
                hotel_url = _bk_url(card, search_url)
                out.append({
                    "title": name,
                    "provider": "Booking.com",
                    "chain": _detect_chain(name),
                    "price": price,
                    "currency": currency,
                    "per_night": True,
                    "url": hotel_url,
                })
        return out
    except Exception:
        return []


# ---------------------------------------------------------------------------
#  Expedia - API interception + multi-strategy HTML parser
# ---------------------------------------------------------------------------

def _parse_expedia_captured(captured: list[dict], city: str, currency: str,
                             search_url: str, provider: str = "Expedia") -> list[dict]:
    """Parse API responses intercepted from Expedia/Hotels.com."""
    out: list[dict] = []
    for data in captured:
        props = (
            _dig(data, "data", "propertySearch", "properties")
            or _dig(data, "propertySearch", "properties")
            or _dig(data, "data", "properties")
            or _dig(data, "properties")
            or []
        )
        if not isinstance(props, list):
            props = []
        for p in props[:12]:
            name = (
                p.get("name") or p.get("hotelName")
                or _dig(p, "headingSection", "heading") or ""
            )
            price = _parse_price(
                _dig(p, "price", "lead", "amount")
                or _dig(p, "price", "perNight", "amount")
                or _dig(p, "ratePlan", "price", "current")
                or _dig(p, "offers", 0, "price", "lead", "amount")
                or 0
            )
            if name and price > 0:
                out.append({
                    "title": name, "provider": provider,
                    "chain": _detect_chain(name),
                    "price": price, "currency": currency,
                    "per_night": True, "url": search_url,
                })
        if out:
            return out
    return out


def _expedia_parse_html(html: str, city: str, check_in: str, check_out: str,
                        currency: str, search_url: str,
                        provider: str = "Expedia") -> list[dict]:
    """Extract hotels from Expedia rendered HTML - tries multiple strategies."""
    out: list[dict] = []

    # Strategy 1: __NEXT_DATA__ with multiple known paths
    data = _extract_next_data(html)
    for path in [
        ("props", "pageProps", "propertySearch", "properties"),
        ("props", "pageProps", "results"),
        ("props", "pageProps", "hotels"),
        ("props", "initialState", "hotels", "results"),
    ]:
        props = _dig(data, *path) or []
        if not isinstance(props, list):
            props = list(props.values()) if isinstance(props, dict) else []
        for p in props[:12]:
            name = (p.get("name") or p.get("hotelName")
                    or _dig(p, "headingSection", "heading") or "")
            price = _parse_price(
                _dig(p, "price", "lead", "amount")
                or _dig(p, "price", "perNight", "amount")
                or _dig(p, "ratePlan", "price", "current")
                or 0
            )
            if name and price > 0:
                out.append({
                    "title": name, "provider": provider,
                    "chain": _detect_chain(name),
                    "price": price, "currency": currency,
                    "per_night": True, "url": search_url,
                })
        if out:
            return out

    # Strategy 2: Inline JSON blobs
    for m in re.finditer(r'"properties"\s*:\s*(\[[\s\S]{10,8000}?\])', html):
        try:
            props = json.loads(m.group(1))
            for p in props[:12]:
                if not isinstance(p, dict):
                    continue
                name = p.get("name") or p.get("hotelName") or ""
                price = _parse_price(
                    _dig(p, "price", "lead", "amount")
                    or _dig(p, "price", "perNight", "amount")
                    or 0
                )
                if name and price > 0:
                    out.append({
                        "title": name, "provider": provider,
                        "chain": _detect_chain(name),
                        "price": price, "currency": currency,
                        "per_night": True, "url": search_url,
                    })
            if out:
                return out
        except Exception:
            continue

    # Strategy 3: BeautifulSoup DOM
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, _HTML_PARSER)
    for card in (
        soup.find_all(attrs={"data-stid": re.compile(r"lodging-card", re.I)})
        or soup.find_all(attrs={"data-testid": re.compile(r"property|hotel", re.I)})
    )[:12]:
        h = card.find(["h3", "h2"])
        name = h.get_text(strip=True) if h else ""
        price_el = (card.find(attrs={"data-stid": re.compile(r"price", re.I)})
                    or card.find(attrs={"data-testid": re.compile(r"price", re.I)}))
        price = _parse_price(price_el.get_text() if price_el else "0")
        if name and price > 0:
            out.append({
                "title": name, "provider": provider,
                "chain": _detect_chain(name),
                "price": price, "currency": currency,
                "per_night": True, "url": search_url,
            })
    return out


def _expedia_date(d: str) -> str:
    """Convert YYYY-MM-DD to MM/DD/YYYY as required by Expedia/Hotels.com URLs."""
    try:
        from datetime import datetime
        return datetime.strptime(d, "%Y-%m-%d").strftime("%m/%d/%Y")
    except Exception:
        return d


def scrape_expedia(
    city: str, check_in: str, check_out: str, adults: int, currency: str
) -> list[dict]:
    """Expedia - API interception primary, HTML parser fallback."""
    try:
        search_url = (
            "https://www.expedia.com/Hotel-Search"
            f"?destination={city}&startDate={_expedia_date(check_in)}&endDate={_expedia_date(check_out)}"
            f"&rooms=1&adults={adults}&currency={currency}&sort=PRICE_LOW_TO_HIGH"
        )

        # Primary: capture API responses
        captured = _pw_capture_hotel_api(
            search_url,
            api_patterns=[
                "hotel-search", "lodging-search", "propertySearch",
                "graphql", "api/store", "hotel/list",
                "expedia.com/api", "hotels/search",
                "propertySearch", "lodging/search",
            ],
        )
        results = _parse_expedia_captured(captured, city, currency, search_url, "Expedia")
        if results:
            return results

        # Fallback: rendered HTML
        html = _pw_get_html(
            search_url,
            wait_selector=(
                '[data-stid="lodging-card-responsive"],'
                '[data-testid="property-listing"],'
                '[class*="hotel-listing"]'
            ),
            extra_wait_ms=5_000,
            timeout=40_000,
        )
        return _expedia_parse_html(html, city, check_in, check_out,
                                   currency, search_url, "Expedia")
    except Exception:
        return []


def scrape_hotels_com(
    city: str, check_in: str, check_out: str, adults: int, currency: str
) -> list[dict]:
    """Hotels.com - sister site of Expedia, API capture + HTML fallback."""
    try:
        search_url = (
            "https://www.hotels.com/Hotel-Search"
            f"?destination={city}&startDate={_expedia_date(check_in)}&endDate={_expedia_date(check_out)}"
            f"&rooms=1&adults={adults}&currency={currency}&sort=PRICE_LOW_TO_HIGH"
        )

        captured = _pw_capture_hotel_api(
            search_url,
            api_patterns=[
                "hotel-search", "lodging-search", "propertySearch",
                "graphql", "api/store", "hotels.com/api",
                "propertySearch", "lodging/search", "hotel/list",
            ],
        )
        results = _parse_expedia_captured(captured, city, currency, search_url, "Hotels.com")
        if results:
            return results

        html = _pw_get_html(
            search_url,
            wait_selector=(
                '[data-stid="lodging-card-responsive"],'
                '[data-testid="property-listing"]'
            ),
            extra_wait_ms=5_000,
            timeout=40_000,
        )
        results = _expedia_parse_html(html, city, check_in, check_out,
                                      currency, search_url, "Hotels.com")
        return results
    except Exception:
        return []


# ---------------------------------------------------------------------------
#  Agoda - JSON API + Playwright fallback
# ---------------------------------------------------------------------------

def _agoda_pw_fallback(city: str, check_in: str, check_out: str,
                       adults: int, currency: str) -> list[dict]:
    from bs4 import BeautifulSoup
    # Use searchText instead of city= (city= requires a numeric ID which is no longer resolvable)
    search_url = (
        f"https://www.agoda.com/search?searchText={city.replace(' ', '+')}"
        f"&checkIn={check_in}&checkOut={check_out}&rooms=1&adults={adults}&currency={currency}"
    )
    html = _pw_get_html(
        search_url,
        wait_selector="[data-selenium='hotel-item'],[class*='hotel-item'],[class*='PropertyCard']",
        extra_wait_ms=4_000,
        timeout=30_000,
    )
    out: list[dict] = []
    soup = BeautifulSoup(html, _HTML_PARSER)
    for card in soup.find_all(attrs={"data-selenium": "hotel-item"})[:12]:
        name_el = card.find(attrs={"data-selenium": "hotel-name"})
        price_el = card.find(attrs={"data-selenium": "display-price"})
        name = name_el.get_text(strip=True) if name_el else ""
        price = _parse_price(price_el.get_text() if price_el else "0")
        if name and price > 0:
            out.append({"title": name, "provider": "Agoda",
                        "chain": _detect_chain(name),
                        "price": price, "currency": currency,
                        "per_night": True, "url": search_url})
    if not out:
        # Regex fallback on JSON embedded in page
        names = re.findall(r'"propertyName"\s*:\s*"([^"]+)"', html)
        prices = re.findall(r'"(?:price|amount|displayPrice)"\s*:\s*([\d.]+)', html)
        seen: set[str] = set()
        for name, p in zip(names[:12], prices[:12]):
            price = float(p)
            if 5 < price < 50_000 and name not in seen:
                seen.add(name)
                out.append({"title": name, "provider": "Agoda",
                            "chain": _detect_chain(name),
                            "price": price, "currency": currency,
                            "per_night": True, "url": search_url})
    return out


def scrape_agoda(
    city: str, check_in: str, check_out: str, adults: int, currency: str
) -> list[dict]:
    """Agoda - Playwright search (direct API endpoints are no longer active)."""
    try:
        return _agoda_pw_fallback(city, check_in, check_out, adults, currency)
    except Exception:
        return []


# ---------------------------------------------------------------------------
#  Airbnb - Playwright + API capture
# ---------------------------------------------------------------------------

def scrape_airbnb(
    city: str, check_in: str, check_out: str, adults: int, currency: str
) -> list[dict]:
    """Airbnb - API interception with HTML regex fallback."""
    try:
        search_url = (
            f"https://www.airbnb.com/s/{city.replace(' ', '-')}/homes"
            f"?checkin={check_in}&checkout={check_out}&adults={adults}&currency={currency}"
        )

        # Primary: API capture
        captured = _pw_capture_hotel_api(
            search_url,
            api_patterns=[
                "airbnb.com/api", "airbnb.com/graphql",
                "airbnb.com/s/", "airbnb.com/rooms",
                "ExploreSearch", "staysSearch",
            ],
        )
        out: list[dict] = []
        for data in captured:
            listings = (
                _dig(data, "data", "presentation", "explore", "sections", 0, "items")
                or _dig(data, "data", "staysSearch", "results", "searchResults")
                or _dig(data, "data", "ExploreSearch", "sections", 0, "listings")
                or []
            )
            for item in listings[:10]:
                listing = _dig(item, "listing") or item
                name = listing.get("name") or listing.get("title") or ""
                price = _parse_price(
                    _dig(item, "pricingQuote", "rate", "amount")
                    or _dig(item, "price", "amount")
                    or _dig(listing, "price", "rate", "amount")
                    or 0
                )
                if name and price > 0:
                    out.append({
                        "title": name, "provider": "Airbnb", "chain": None,
                        "price": price, "currency": currency,
                        "per_night": True, "url": search_url,
                    })
        if out:
            return out[:10]

        # Fallback: HTML regex
        html = _pw_get_html(
            search_url,
            wait_selector='[data-testid="card-container"],[itemprop="itemListElement"]',
            extra_wait_ms=3_000,
            timeout=30_000,
        )
        names = (
            re.findall(r'"listingName"\s*:\s*"([^"]{5,80})"', html)
            or re.findall(r'"name"\s*:\s*"([A-Z][^"]{5,79})"', html)
        )
        prices = (
            re.findall(r'"localizedAmount"\s*:\s*"([^"]+)"', html)
            or re.findall(r'"amount"\s*:\s*([\d.]+)', html)
        )
        out = []
        seen: set[str] = set()
        for name, raw_price in zip(names, prices):
            if name in seen:
                continue
            price = _parse_price(raw_price)
            if price > 0:
                seen.add(name)
                out.append({
                    "title": name, "provider": "Airbnb", "chain": None,
                    "price": price, "currency": currency,
                    "per_night": True, "url": search_url,
                })
            if len(out) >= 10:
                break
        return out
    except Exception:
        return []


# ---------------------------------------------------------------------------
#  Marriott - API interception via Playwright
# ---------------------------------------------------------------------------

def _marriott_parse_hotel(h: dict, currency: str, search_url: str = "") -> dict | None:
    name = h.get("propertyName") or h.get("hotelName") or h.get("name", "")
    price = _parse_price(
        h.get("lowestAvailableRate")
        or _dig(h, "rates", 0, "totalRate")
        or _dig(h, "price", "amount")
        or _dig(h, "lowestRate", "amount")
        or 0
    )
    if not name or price <= 0:
        return None
    return {"title": name, "provider": "Marriott.com (Direct)", "chain": "Marriott",
            "price": price, "currency": currency, "per_night": True, "url": search_url}


def _marriott_parse_captured(captured: list[dict], currency: str,
                              search_url: str = "") -> list[dict]:
    out: list[dict] = []
    for data in captured:
        props = (
            _dig(data, "properties")
            or _dig(data, "data", "properties")
            or _dig(data, "hotelList")
            or _dig(data, "data", "hotelList")
            or _dig(data, "results")
            or []
        )
        if not isinstance(props, list):
            continue
        for h in props[:10]:
            entry = _marriott_parse_hotel(h, currency, search_url)
            if entry:
                out.append(entry)
    return out


def scrape_marriott(
    city: str, check_in: str, check_out: str, adults: int, currency: str
) -> list[dict]:
    """Marriott.com - API interception via Playwright network listener."""
    try:
        search_url = (
            "https://www.marriott.com/search/default.mi"
            f"?cityName={city}&checkinDate={check_in}&checkoutDate={check_out}"
            f"&numAdultsPerRoom={adults}&numRooms=1&currencyCode={currency}"
        )

        # Capture all relevant Marriott API calls
        captured = _pw_capture_hotel_api(
            search_url,
            api_patterns=[
                "findHotels", "webapi", "marriott.com/api",
                "availabilitySearch", "hotel/search",
                "mi3/lookup", "property/list",
                "search/default", "hotelSearch",
            ],
            timeout=45_000,
        )
        results = _marriott_parse_captured(captured, currency, search_url)
        if results:
            return _deduplicate(results)

        # Regex fallback on page source
        html = _pw_get_html(
            search_url,
            wait_selector="[class*='hotel-card'],[class*='property-card'],[data-hotelid]",
            extra_wait_ms=5_000,
            timeout=35_000,
        )
        names = re.findall(_RE_HOTEL_NAME, html)
        if not names:
            names = re.findall(
                r'"name"\s*:\s*"((?:Marriott|Courtyard|Sheraton|Westin|Renaissance'
                r'|Ritz.Carlton|W Hotel|Aloft|Element|Autograph|Four Points)[^"]{0,60})"',
                html,
            )
        prices = re.findall(r'"(?:lowestAvailableRate|totalRate|amount)"\s*:\s*([\d.]+)', html)
        out: list[dict] = []
        seen: set[str] = set()
        for name, p in zip(names[:10], prices[:10]):
            if name in seen:
                continue
            price = float(p)
            if price > 0:
                seen.add(name)
                out.append({"title": name, "provider": "Marriott.com (Direct)",
                            "chain": "Marriott", "price": price,
                            "currency": currency, "per_night": True, "url": search_url})
        return out
    except Exception:
        return []


# ---------------------------------------------------------------------------
#  Hilton - API interception via Playwright
# ---------------------------------------------------------------------------

def _hilton_parse_captured(captured: list[dict], currency: str,
                            search_url: str) -> list[dict]:
    out: list[dict] = []
    for data in captured:
        hotels = (
            _dig(data, "hotels")
            or _dig(data, "data", "hotels")
            or _dig(data, "results")
            or _dig(data, "properties")
            or []
        )
        if not isinstance(hotels, list):
            continue
        for h in hotels[:12]:
            name = h.get("name") or h.get("hotelName") or ""
            price = _parse_price(
                _dig(h, "lowestPrice", "amount")
                or _dig(h, "rates", 0, "price", "amount")
                or _dig(h, "grossAmount")
                or h.get("price") or 0
            )
            if name and price > 0:
                out.append({"title": name, "provider": "Hilton.com (Direct)",
                            "chain": "Hilton", "price": price,
                            "currency": currency, "per_night": True, "url": search_url})
    return out


def scrape_hilton(
    city: str, check_in: str, check_out: str, adults: int, currency: str
) -> list[dict]:
    """Hilton.com - API interception with HTML regex fallback."""
    try:
        search_url = (
            "https://www.hilton.com/en/hotels/"
            f"?search={city}&checkIn={check_in}&checkOut={check_out}"
            f"&numAdults={adults}&numRooms=1&currency={currency}"
        )

        captured = _pw_capture_hotel_api(
            search_url,
            api_patterns=[
                "hilton.com/api", "hiltonhotels.com/api",
                "property-list", "hotel-search", "availability",
                "hiltonstatic.com", "ws/", "findHotels",
                "/hotels/search", "hilton/search",
            ],
            timeout=45_000,
        )
        results = _hilton_parse_captured(captured, currency, search_url)
        if results:
            return _deduplicate(results)

        # Fallback: parse rendered HTML
        html = _pw_get_html(
            search_url,
            wait_selector="[class*='hotel-card'],[data-testid='hotel-card'],[class*='property']",
            extra_wait_ms=5_000,
            timeout=35_000,
        )
        names = re.findall(r'"hotelName"\s*:\s*"([^"]+)"', html)
        if not names:
            names = re.findall(
                r'"name"\s*:\s*"((?:Hilton|DoubleTree|Hampton|Waldorf|Embassy'
                r'|Curio|Tapestry|Canopy|Motto|Tempo|Signia|Homewood|Home2|Tru)[^"]{0,60})"',
                html,
            )
        rates = re.findall(r'"grossAmount"\s*:\s*([\d.]+)', html)
        if not rates:
            rates = re.findall(r'"(?:lowestRate|amount|price)"\s*:\s*([\d.]+)', html)

        out: list[dict] = []
        seen: set[str] = set()
        for name, rate in zip(names[:10], rates[:10]):
            if name in seen:
                continue
            price = float(rate)
            if price > 0:
                seen.add(name)
                out.append({"title": name, "provider": "Hilton.com (Direct)",
                            "chain": "Hilton", "price": price,
                            "currency": currency, "per_night": True, "url": search_url})
        return out
    except Exception:
        return []


# ---------------------------------------------------------------------------
#  IHG - JSON API + Playwright fallback
# ---------------------------------------------------------------------------

def _ihg_api(city: str, check_in: str, check_out: str,
             adults: int, currency: str) -> list[dict]:
    search_url = f"https://www.ihg.com/hotels/us/en/find-hotels/hotel/list?qDest={city}"

    for url, params in [
        (
            "https://apis.ihg.com/hotels/v1/search",
            {"cityName": city, "checkInDate": check_in, "checkOutDate": check_out,
             "numRooms": 1, "numAdults": adults, "radius": 50, "unit": "km",
             "currency": currency, "locale": "en_US", "limit": 10},
        ),
        (
            "https://apis.ihg.com/hotels/v1/search/available",
            {"destination": city, "arrivalDate": check_in, "departureDate": check_out,
             "rooms": 1, "adults": adults, "currency": currency, "locale": "en_US"},
        ),
    ]:
        try:
            r = _client().get(
                url, params=params,
                headers={"Accept": _JSON, "Referer": "https://www.ihg.com/"},
            )
            if r.status_code != 200:
                continue
            data = r.json()
            hotels_raw = (
                data.get("hotels") or data.get("results")
                or _dig(data, "data", "hotels") or []
            )
            out: list[dict] = []
            for h in hotels_raw[:10]:
                name = h.get("name") or h.get("hotelName", "")
                price = _parse_price(
                    _dig(h, "rates", 0, "lowestAvailableRate", "amount")
                    or _dig(h, "lowestRate", "amount")
                    or h.get("price") or 0
                )
                if name and price > 0:
                    out.append({"title": name, "provider": "IHG.com (Direct)", "chain": "IHG",
                                "price": price, "currency": currency, "per_night": True,
                                "url": search_url})
            if out:
                return out
        except Exception:
            continue
    return []


def _ihg_pw_fallback(city: str, check_in: str, check_out: str,
                     adults: int, currency: str) -> list[dict]:
    ci = check_in.split("-")
    co = check_out.split("-")
    search_url = (
        f"https://www.ihg.com/hotels/us/en/find-hotels/hotel/list"
        f"?qDest={city}&qCiD={ci[2]}&qCiMy={ci[1]}{ci[0]}"
        f"&qCoD={co[2]}&qCoMy={co[1]}{co[0]}&qAdlt={adults}&qRms=1"
    )

    # Try API capture first
    captured = _pw_capture_hotel_api(
        search_url,
        api_patterns=[
            "ihg.com/api", "apis.ihg.com", "findHotels",
            "hotel/list", "availableHotels", "ihg/search",
        ],
        timeout=40_000,
    )
    for data in captured:
        hotels_raw = (
            data.get("hotels") or data.get("results")
            or _dig(data, "data", "hotels") or []
        )
        out: list[dict] = []
        for h in hotels_raw[:10]:
            name = h.get("name") or h.get("hotelName", "")
            price = _parse_price(
                _dig(h, "rates", 0, "lowestAvailableRate", "amount")
                or h.get("price") or 0
            )
            if name and price > 0:
                out.append({"title": name, "provider": "IHG.com (Direct)", "chain": "IHG",
                            "price": price, "currency": currency, "per_night": True,
                            "url": search_url})
        if out:
            return out

    # HTML regex fallback
    html = _pw_get_html(
        search_url,
        wait_selector=".propertyCard,[data-hotelcode],[class*='hotel-card']",
        extra_wait_ms=4_000, timeout=30_000,
    )
    names = re.findall(_RE_HOTEL_NAME, html)
    prices = (
        re.findall(r'"totalRate"\s*:\s*\{[^}]*"amount"\s*:\s*([\d.]+)', html)
        or re.findall(r'"price"\s*:\s*([\d.]+)', html)
        or re.findall(r'"amount"\s*:\s*([\d.]+)', html)
    )
    out: list[dict] = []
    seen: set[str] = set()
    for name, p in zip(names[:10], prices[:10]):
        if name in seen:
            continue
        price = float(p)
        if price > 0:
            seen.add(name)
            out.append({"title": name, "provider": "IHG.com (Direct)", "chain": "IHG",
                        "price": price, "currency": currency, "per_night": True,
                        "url": search_url})
    return out


def scrape_ihg(
    city: str, check_in: str, check_out: str, adults: int, currency: str
) -> list[dict]:
    """IHG - public JSON API first, Playwright + API capture fallback."""
    try:
        result = _ihg_api(city, check_in, check_out, adults, currency)
        return result if result else _ihg_pw_fallback(
            city, check_in, check_out, adults, currency
        )
    except Exception:
        return []


# ---------------------------------------------------------------------------
#  Hyatt - API interception + HTML regex fallback
# ---------------------------------------------------------------------------

def scrape_hyatt(
    city: str, check_in: str, check_out: str, adults: int, currency: str
) -> list[dict]:
    """Hyatt - API interception with HTML regex fallback."""
    try:
        search_url = (
            f"https://www.hyatt.com/en-US/search"
            f"?destination={city}&checkinDate={check_in}&checkoutDate={check_out}"
            f"&adults={adults}&rooms=1&currencyCode={currency}"
        )

        captured = _pw_capture_hotel_api(
            search_url,
            api_patterns=[
                "hyatt.com/api", "hyattws.gohyatt.com",
                "hotel-search", "availableRates", "/search",
                "hyatt/search", "properties", "availability",
            ],
            timeout=40_000,
        )
        for data in captured:
            hotels = (
                _dig(data, "results", "hotels")
                or _dig(data, "hotels")
                or _dig(data, "data", "hotels")
                or _dig(data, "properties")
                or []
            )
            if isinstance(hotels, list) and hotels:
                out: list[dict] = []
                for h in hotels[:10]:
                    name = h.get("name") or h.get("hotelName") or ""
                    price = _parse_price(
                        _dig(h, "lowestRate", "amount")
                        or _dig(h, "price", "amount")
                        or h.get("price") or 0
                    )
                    if name and price > 0:
                        out.append({"title": name, "provider": "Hyatt.com (Direct)",
                                    "chain": "Hyatt", "price": price,
                                    "currency": currency, "per_night": True,
                                    "url": search_url})
                if out:
                    return out

        # Fallback: rendered HTML
        html = _pw_get_html(
            search_url,
            wait_selector="[class*='property-card'],[data-testid='hotel-card'],[class*='hotel']",
            extra_wait_ms=5_000,
            timeout=35_000,
        )
        names = re.findall(_RE_HOTEL_NAME, html)
        if not names:
            names = re.findall(
                r'"name"\s*:\s*"((?:Hyatt|Park Hyatt|Grand Hyatt|Andaz|Alila'
                r'|Thompson|Joie de Vivre|Unbound|Miraval)[^"]{0,60})"',
                html,
            )
        prices = re.findall(
            r'"(?:displayPrice|lowestRate|amount|price)"\s*:\s*"?([\d.]+)"?', html
        )
        out = []
        seen: set[str] = set()
        for name, p in zip(names[:10], prices[:10]):
            if name in seen:
                continue
            price = float(p)
            if 10 < price < 100_000:
                seen.add(name)
                out.append({"title": name, "provider": "Hyatt.com (Direct)",
                            "chain": "Hyatt", "price": price,
                            "currency": currency, "per_night": True, "url": search_url})
        return out
    except Exception:
        return []


# ---------------------------------------------------------------------------
#  Accor Hotels - API + Playwright fallback
# ---------------------------------------------------------------------------

def scrape_accor(
    city: str, check_in: str, check_out: str, adults: int, currency: str
) -> list[dict]:
    """Accor Hotels - JSON API first, Playwright fallback."""
    try:
        search_url = (
            f"https://all.accor.com/ssr/app/accor/rates"
            f"?destination={city}&checkin={check_in}&checkout={check_out}"
            f"&adults={adults}&rooms=1&currency={currency}"
        )
        fallback_url = (
            f"https://all.accor.com/hotel/index.en.shtml"
            f"?search={city}&dateIn={check_in}&dateOut={check_out}&adults={adults}"
        )

        # Try multiple Accor API endpoints
        for api_url, params in [
            (
                "https://all.accor.com/api/accor/v1/search",
                {"destination": city, "arrivalDate": check_in,
                 "departureDate": check_out, "adults": adults,
                 "currency": currency, "limit": 10},
            ),
            (
                "https://all.accor.com/api/hotels/search",
                {"destination": city, "checkIn": check_in, "checkOut": check_out,
                 "adults": adults, "currency": currency},
            ),
        ]:
            try:
                r = _client().get(api_url, params=params,
                                  headers={"Accept": _JSON, "Referer": "https://all.accor.com/"})
                if r.status_code == 200:
                    data = r.json()
                    hotels_raw = (
                        data.get("hotels") or data.get("results")
                        or _dig(data, "data", "hotels") or []
                    )
                    out: list[dict] = []
                    for h in hotels_raw[:8]:
                        name = h.get("name") or h.get("hotelName", "")
                        price = _parse_price(
                            _dig(h, "offers", 0, "price", "amount")
                            or _dig(h, "lowestPrice", "amount")
                            or h.get("price") or 0
                        )
                        if name and price > 0:
                            out.append({"title": name, "provider": "Accor.com (Direct)",
                                        "chain": "Accor", "price": price,
                                        "currency": currency, "per_night": True,
                                        "url": fallback_url})
                    if out:
                        return out
            except Exception:
                continue

        # Playwright fallback with API capture
        captured = _pw_capture_hotel_api(
            fallback_url,
            api_patterns=[
                "all.accor.com/api", "accor.com/api",
                "hotel/search", "availability", "rates",
                "accor/search", "hotels/list",
            ],
            timeout=40_000,
        )
        for data in captured:
            hotels_raw = data.get("hotels") or data.get("results") or []
            out = []
            for h in hotels_raw[:8]:
                name = h.get("name") or h.get("hotelName", "")
                price = _parse_price(
                    _dig(h, "offers", 0, "price", "amount")
                    or h.get("price") or 0
                )
                if name and price > 0:
                    out.append({"title": name, "provider": "Accor.com (Direct)",
                                "chain": "Accor", "price": price,
                                "currency": currency, "per_night": True,
                                "url": fallback_url})
            if out:
                return out

        # HTML regex fallback
        html = _pw_get_html(
            fallback_url,
            wait_selector="[class*='hotel-card'],[class*='property-card'],[class*='HotelCard']",
            extra_wait_ms=4_000, timeout=30_000,
        )
        names = re.findall(r'"(?:hotelName|name)"\s*:\s*"([^"]{3,80})"', html)
        prices = re.findall(r'"(?:lowestPrice|price|amount)"\s*:\s*([\d.]+)', html)
        result: list[dict] = []
        seen: set[str] = set()
        for name, p in zip(names[:8], prices[:8]):
            if name in seen:
                continue
            price = float(p)
            if 10 < price < 100_000:
                seen.add(name)
                result.append({"title": name, "provider": "Accor.com (Direct)",
                               "chain": "Accor", "price": price,
                               "currency": currency, "per_night": True, "url": fallback_url})
        return result
    except Exception:
        return []


# ---------------------------------------------------------------------------
#  Radisson Hotels - API capture + __NEXT_DATA__ + Playwright fallback
# ---------------------------------------------------------------------------

def scrape_radisson(
    city: str, check_in: str, check_out: str, adults: int, currency: str
) -> list[dict]:
    """Radisson Hotels - API interception + Next.js data extraction."""
    try:
        search_url = (
            "https://www.radissonhotels.com/en-us/search"
            f"?destination={city}&checkIn={check_in}&checkOut={check_out}"
            f"&adults={adults}&rooms=1&currency={currency}"
        )

        # Primary: API capture (Radisson is Next.js and makes API calls)
        captured = _pw_capture_hotel_api(
            search_url,
            api_patterns=[
                "radissonhotels.com/api", "radisson/api",
                "hotel-search", "availability", "hotels/search",
                "property-list", "search/hotels",
            ],
            timeout=40_000,
        )
        for data in captured:
            props = (
                _dig(data, "hotels")
                or _dig(data, "results")
                or _dig(data, "properties")
                or _dig(data, "data", "hotels")
                or []
            )
            if isinstance(props, list) and props:
                out: list[dict] = []
                for p in props[:8]:
                    name = p.get("name") or p.get("hotelName", "")
                    price = _parse_price(
                        _dig(p, "price", "amount")
                        or _dig(p, "lowestRate")
                        or _dig(p, "offers", 0, "price")
                        or 0
                    )
                    if name and price > 0:
                        out.append({"title": name, "provider": "Radisson.com (Direct)",
                                    "chain": "Radisson", "price": price,
                                    "currency": currency, "per_night": True,
                                    "url": search_url})
                if out:
                    return out

        # Fallback: __NEXT_DATA__ extraction
        html = _pw_get_html(
            search_url,
            wait_selector="[data-testid='hotel-card'],.hotel-card,[class*='PropertyCard']",
            extra_wait_ms=4_000,
            timeout=35_000,
        )
        data = _extract_next_data(html)
        for path in [
            ("props", "pageProps", "hotels"),
            ("props", "pageProps", "searchResults", "hotels"),
            ("props", "pageProps", "results"),
        ]:
            props = _dig(data, *path) or []
            if isinstance(props, list):
                out = []
                for p in props[:8]:
                    name = p.get("name") or p.get("hotelName", "")
                    price = _parse_price(
                        _dig(p, "price", "amount") or _dig(p, "lowestRate") or 0
                    )
                    if name and price > 0:
                        out.append({"title": name, "provider": "Radisson.com (Direct)",
                                    "chain": "Radisson", "price": price,
                                    "currency": currency, "per_night": True,
                                    "url": search_url})
                if out:
                    return out

        # Last resort: regex on raw HTML
        names = re.findall(r'"(?:name|hotelName)"\s*:\s*"([^"]{3,80})"', html)
        prices = re.findall(r'"(?:price|amount|lowestRate)"\s*:\s*([\d.]+)', html)
        out = []
        seen: set[str] = set()
        for name, p in zip(names[:8], prices[:8]):
            if name in seen:
                continue
            price = float(p)
            if 10 < price < 100_000:
                seen.add(name)
                out.append({"title": name, "provider": "Radisson.com (Direct)",
                            "chain": "Radisson", "price": price,
                            "currency": currency, "per_night": True, "url": search_url})
        return out
    except Exception:
        return []


# ---------------------------------------------------------------------------
#  Chain Detection
# ---------------------------------------------------------------------------

_CHAIN_MAP: dict[str, list[str]] = {
    "Marriott": [
        "marriott", "courtyard", "sheraton", "westin", "renaissance",
        "ritz-carlton", "ritz carlton", "w hotel", "aloft", "element",
        "st. regis", "st regis", "autograph", "le méridien", "meridien",
        "four points", "tribute portfolio",
    ],
    "Hilton": [
        "hilton", "hampton", "doubletree", "double tree", "embassy suites",
        "waldorf", "waldorf astoria", "curio", "tapestry", "canopy", "motto",
        "tempo", "signia", "homewood", "home2", "tru by hilton",
    ],
    "IHG": [
        "intercontinental", "holiday inn", "crowne plaza", "kimpton",
        "voco", "indigo", "staybridge", "candlewood", "six senses",
        "even hotels", "avid hotels", "regent",
    ],
    "Hyatt": [
        "hyatt", "park hyatt", "grand hyatt", "andaz", "alila",
        "thompson hotels", "joie de vivre", "destination", "unbound",
        "miraval", "exhale",
    ],
    "Accor": [
        "ibis", "novotel", "sofitel", "pullman", "mercure", "fairmont",
        "raffles", "swissotel", "mgallery", "mantis", "25hours",
    ],
    "Wyndham": [
        "wyndham", "ramada", "days inn", "super 8", "la quinta",
        "travelodge", "microtel", "wingate", "baymont",
    ],
    "Radisson": ["radisson", "park inn", "park plaza", "prizeotel"],
    "BW":       ["best western", "sure hotel", "executive residency"],
    "Taj":      ["taj ", "seleqtions", "vivanta", "ama stays"],
    "Oberoi":   ["oberoi", "trident"],
    "ITC":      ["itc ", "welcomhotel", "mementos"],
    "Leela":    ["leela", "raviz"],
}


def _detect_chain(hotel_name: str) -> str | None:
    lower = hotel_name.lower()
    for chain, keywords in _CHAIN_MAP.items():
        if any(kw in lower for kw in keywords):
            return chain
    return None


# ---------------------------------------------------------------------------
#  Aggregators
# ---------------------------------------------------------------------------

_OTA_SCRAPERS: dict[str, Any] = {
    "Booking.com": scrape_booking,
    "Expedia":     scrape_expedia,
    "Hotels.com":  scrape_hotels_com,
    "Agoda":       scrape_agoda,
    "Airbnb":      scrape_airbnb,
}

_CHAIN_SCRAPERS: dict[str, Any] = {
    "Marriott.com": scrape_marriott,
    "Hilton.com":   scrape_hilton,
    "IHG.com":      scrape_ihg,
    "Hyatt.com":    scrape_hyatt,
    "Accor.com":    scrape_accor,
    "Radisson.com": scrape_radisson,
}

_ALL_SCRAPERS = {**_OTA_SCRAPERS, **_CHAIN_SCRAPERS}


def scrape_all_hotels(
    city: str,
    check_in: str,
    check_out: str,
    adults: int = 1,
    currency: str = "USD",
) -> tuple[list[dict], dict[str, str]]:
    """
    Run ALL hotel scrapers concurrently.
    API-based scrapers (SerpAPI / RapidAPI) run first — faster and more reliable.
    Playwright scrapers (Booking.com etc.) run in parallel as fallback/supplement.
    Returns (sorted_hotels, platform_status).
    """
    api_scrapers: dict[str, Any] = {
        "Google Hotels":     scrape_serpapi,
        "Booking.com (API)": scrape_rapidapi_booking,
        "TripAdvisor":       scrape_rapidapi_tripadvisor,
        "Priceline":         scrape_rapidapi_priceline,
    }

    all_hotels: list[dict] = []
    status: dict[str, str] = {}

    # Build the combined scraper map: API scrapers + Playwright scrapers
    combined: dict[str, Any] = {}
    for name, fn in api_scrapers.items():
        combined[name] = fn
    pw_ok = _pw_available()
    for name, fn in _ALL_SCRAPERS.items():
        if pw_ok:
            combined[name] = fn
        else:
            status[name] = "⚠ Playwright unavailable"

    with ThreadPoolExecutor(max_workers=len(combined)) as pool:
        futures = {
            pool.submit(fn, city, check_in, check_out, adults, currency): name
            for name, fn in combined.items()
        }
        for future in as_completed(futures):
            name = futures[future]
            try:
                results = future.result()
                all_hotels.extend(results)
                if results:
                    status[name] = f"✓ {len(results)} results"
                elif name == "Priceline":
                    status[name] = (
                        "⚠ 0 parsed results - verify manually: "
                        f"{_priceline_search_url(city, check_in, check_out, adults)}"
                    )
                else:
                    status[name] = "⚠ 0 results"
            except Exception as exc:
                if name == "Priceline":
                    status[name] = (
                        f"✗ failed: {exc}. Direct check: "
                        f"{_priceline_search_url(city, check_in, check_out, adults)}"
                    )
                else:
                    status[name] = f"✗ failed: {exc}"

    return _deduplicate(all_hotels), status


def scrape_hotels_per_night(
    city: str,
    check_in: str,
    check_out: str,
    adults: int = 1,
    currency: str = "USD",
) -> list[dict]:
    """
    For each individual night of the stay, find the cheapest available hotel.
    Uses Booking.com + Expedia + Agoda (fastest reliable sources).
    """
    nights = _night_dates(check_in, check_out)
    if not nights:
        return []

    if not _pw_available():
        return []

    fast_scrapers = [scrape_booking, scrape_expedia, scrape_agoda]

    def _search_one_night(night_in: str, night_out: str) -> list[dict]:
        results: list[dict] = []
        with ThreadPoolExecutor(max_workers=len(fast_scrapers)) as pool:
            futs = [
                pool.submit(fn, city, night_in, night_out, adults, currency)
                for fn in fast_scrapers
            ]
            for f in as_completed(futs):
                try:
                    results.extend(f.result())
                except Exception:
                    pass
        return _deduplicate(results)

    night_results: list[dict] = []
    with ThreadPoolExecutor(max_workers=min(len(nights), 2)) as pool:
        futures = {
            pool.submit(_search_one_night, n_in, n_out): (n_in, n_out)
            for n_in, n_out in nights
        }
        for future in as_completed(futures):
            n_in, n_out = futures[future]
            try:
                options = future.result()
                night_results.append({
                    "night": n_in,
                    "check_in": n_in,
                    "check_out": n_out,
                    "cheapest_hotel": options[0] if options else None,
                    "all_options": options[:5],
                })
            except Exception:
                night_results.append({
                    "night": n_in,
                    "check_in": n_in,
                    "check_out": n_out,
                    "cheapest_hotel": None,
                    "all_options": [],
                })

    return sorted(night_results, key=lambda x: x["night"])


# ---------------------------------------------------------------------------
#  SerpAPI – Google Hotels  (needs SERPAPI_KEY, 100 free/month)
# ---------------------------------------------------------------------------

def scrape_serpapi(
    city: str, check_in: str, check_out: str, adults: int, currency: str
) -> list[dict]:
    api_key = os.getenv("SERPAPI_KEY", "")
    if not api_key:
        return []
    try:
        r = httpx.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_hotels",
                "q": f"hotels in {city}",
                "check_in_date": check_in,
                "check_out_date": check_out,
                "adults": adults,
                "currency": currency,
                "hl": "en",
                "gl": "us",
                "api_key": api_key,
            },
            timeout=30,
        )
        if r.status_code != 200:
            return []
        out: list[dict] = []
        for prop in r.json().get("properties", [])[:15]:
            name = prop.get("name", "")
            price = float(prop.get("rate_per_night", {}).get("extracted_lowest", 0) or 0)
            if name and price > 0:
                out.append({
                    "title": name,
                    "provider": "Google Hotels",
                    "chain": _detect_chain(name),
                    "price": price,
                    "currency": currency,
                    "per_night": True,
                    "url": prop.get("link", ""),
                })
        return out
    except Exception:
        return []


# ---------------------------------------------------------------------------
#  RapidAPI – Booking.com  (needs RAPIDAPI_KEY, 500 free/month)
# ---------------------------------------------------------------------------

def _rapidapi_headers(host: str) -> dict:
    return {
        "X-RapidAPI-Key":  os.getenv("RAPIDAPI_KEY", ""),
        "X-RapidAPI-Host": host,
    }


def _rapidapi_booking_dest_id(city: str) -> str | None:
    try:
        r = httpx.get(
            "https://booking-com15.p.rapidapi.com/api/v1/hotels/searchDestination",
            params={"query": city},
            headers=_rapidapi_headers("booking-com15.p.rapidapi.com"),
            timeout=15,
        )
        if r.status_code != 200:
            return None
        for item in r.json().get("data", []):
            if item.get("search_type") in ("city", "district", "region"):
                return str(item["dest_id"])
    except Exception:
        pass
    return None


def scrape_rapidapi_booking(
    city: str, check_in: str, check_out: str, adults: int, currency: str
) -> list[dict]:
    if not os.getenv("RAPIDAPI_KEY"):
        return []
    try:
        dest_id = _rapidapi_booking_dest_id(city)
        if not dest_id:
            return []
        r = httpx.get(
            "https://booking-com15.p.rapidapi.com/api/v1/hotels/searchHotels",
            params={
                "dest_id": dest_id,
                "search_type": "CITY",
                "arrival_date": check_in,
                "departure_date": check_out,
                "adults": str(adults),
                "currency_code": currency,
                "sort_by": "popularity",
                "page_number": "1",
                "units": "metric",
            },
            headers=_rapidapi_headers("booking-com15.p.rapidapi.com"),
            timeout=30,
        )
        if r.status_code != 200:
            return []
        search_url = (
            f"https://www.booking.com/searchresults.html"
            f"?ss={city.replace(' ', '+')}&checkin={check_in}&checkout={check_out}"
        )
        out: list[dict] = []
        for h in r.json().get("data", {}).get("hotels", [])[:15]:
            prop = h.get("property", {})
            name = prop.get("name", "")
            price_obj = prop.get("priceBreakdown", {}).get("grossPrice", {})
            price = float(price_obj.get("value", 0) or 0)
            if name and price > 0:
                out.append({
                    "title": name,
                    "provider": "Booking.com (API)",
                    "chain": _detect_chain(name),
                    "price": price,
                    "currency": price_obj.get("currency", currency),
                    "per_night": True,
                    "url": search_url,
                })
        return out
    except Exception:
        return []


# ---------------------------------------------------------------------------
#  RapidAPI – TripAdvisor  (same RAPIDAPI_KEY, 500 free/month)
# ---------------------------------------------------------------------------

def _rapidapi_tripadvisor_geo_id(city: str) -> str | None:
    try:
        r = httpx.get(
            "https://tripadvisor16.p.rapidapi.com/api/v1/hotels/searchLocation",
            params={"query": city},
            headers=_rapidapi_headers("tripadvisor16.p.rapidapi.com"),
            timeout=15,
        )
        if r.status_code != 200:
            return None
        for item in r.json().get("data", []):
            geo_id = item.get("geoId") or item.get("locationId")
            if geo_id:
                return str(geo_id)
    except Exception:
        pass
    return None


def scrape_rapidapi_tripadvisor(
    city: str, check_in: str, check_out: str, adults: int, currency: str
) -> list[dict]:
    if not os.getenv("RAPIDAPI_KEY"):
        return []
    try:
        geo_id = _rapidapi_tripadvisor_geo_id(city)
        if not geo_id:
            return []
        r = httpx.get(
            "https://tripadvisor16.p.rapidapi.com/api/v1/hotels/searchHotels",
            params={
                "geoId": geo_id,
                "checkIn": check_in,
                "checkOut": check_out,
                "adults": str(adults),
                "currencyCode": currency,
                "sort": "POPULARITY",
                "limit": "15",
            },
            headers=_rapidapi_headers("tripadvisor16.p.rapidapi.com"),
            timeout=30,
        )
        if r.status_code != 200:
            return []
        search_url = f"https://www.tripadvisor.com/Hotels-g-{city.replace(' ', '_')}-Hotels.html"
        out: list[dict] = []
        for h in (r.json().get("data", {}).get("data", []) or [])[:12]:
            name = h.get("title", "")
            price = _parse_price(
                _dig(h, "priceDetails", "price")
                or _dig(h, "commerceInfo", "priceForDisplay", "text")
                or 0
            )
            if name and price > 0:
                link = _dig(h, "cardLink", "route", "url") or search_url
                out.append({
                    "title": name,
                    "provider": "TripAdvisor",
                    "chain": _detect_chain(name),
                    "price": price,
                    "currency": currency,
                    "per_night": True,
                    "url": f"https://www.tripadvisor.com{link}" if link.startswith("/") else link,
                })
        return out
    except Exception:
        return []


# ---------------------------------------------------------------------------
#  RapidAPI – Priceline  (same RAPIDAPI_KEY)
# ---------------------------------------------------------------------------

def scrape_rapidapi_priceline(
    city: str, check_in: str, check_out: str, adults: int, currency: str
) -> list[dict]:
    public_url = _priceline_search_url(city, check_in, check_out, adults)
    if not os.getenv("RAPIDAPI_KEY"):
        return scrape_priceline_public(city, check_in, check_out, adults, currency)
    errors: list[str] = []
    for host in _priceline_rapidapi_hosts():
        try:
            out = _scrape_priceline_rapidapi_host(
                host, city, check_in, check_out, adults, currency, public_url
            )
            if out:
                return out
        except RuntimeError as exc:
            errors.append(f"{host}: {exc}")
            continue
        except Exception as exc:
            errors.append(f"{host}: {type(exc).__name__}")
            continue

    public_results = scrape_priceline_public(city, check_in, check_out, adults, currency)
    if public_results:
        return public_results
    if errors:
        raise RuntimeError("; ".join(errors))
    return []


def _priceline_rapidapi_hosts() -> list[str]:
    configured = os.getenv("PRICELINE_RAPIDAPI_HOSTS") or os.getenv("PRICELINE_RAPIDAPI_HOST")
    if configured:
        return [h.strip() for h in configured.split(",") if h.strip()]
    return [
        "priceline-com2.p.rapidapi.com",
        "priceline-com-provider.p.rapidapi.com",
        "priceline-com.p.rapidapi.com",
    ]


def _scrape_priceline_rapidapi_host(
    host: str,
    city: str,
    check_in: str,
    check_out: str,
    adults: int,
    currency: str,
    public_url: str,
) -> list[dict]:
    try:
        if host == "priceline-com2.p.rapidapi.com":
            return _scrape_priceline_com2_host(
                host, city, check_in, check_out, adults, currency, public_url
            )

        headers = _rapidapi_headers(host)

        # Step 1: resolve location ID
        loc_r = httpx.get(
            f"https://{host}/v1/hotels/locations",
            params={"name": city, "search_type": "ALL"},
            headers=headers,
            timeout=15,
        )
        if loc_r.status_code != 200:
            raise RuntimeError(_rapidapi_priceline_error(loc_r.status_code, loc_r.text))
        loc_data = loc_r.json()
        city_id = None
        for item in (loc_data.get("getHotelAutoSuggestV2", {})
                     .get("results", {}).get("result", []) or []):
            if item.get("type") in ("CITY", "DESTINATION", "NEIGHBORHOOD"):
                city_id = item.get("id") or item.get("cityID")
                if city_id:
                    break

        if not city_id:
            return []

        # Step 2: search hotels
        r = httpx.get(
            f"https://{host}/v1/hotels/search",
            params={
                "location_id": city_id,
                "date_checkin": check_in,
                "date_checkout": check_out,
                "rooms_number": "1",
                "adults_number": str(adults),
                "order_by": "HDR_HOTELSCORE",
                "currency": currency,
                "page_number": "1",
                "page_size": "15",
            },
            headers=headers,
            timeout=30,
        )
        if r.status_code != 200:
            raise RuntimeError(_rapidapi_priceline_error(r.status_code, r.text))

        hotels_raw = (
            _dig(r.json(), "getHotelResults", "results", "hotels")
            or _dig(r.json(), "results", "hotels")
            or []
        )
        out: list[dict] = []
        for h in hotels_raw[:12]:
            name = h.get("hotelName") or h.get("name", "")
            price = _parse_price(
                _dig(h, "ratesSummary", "minPrice") or
                _dig(h, "ratesSummary", "minRate") or
                _dig(h, "pricing", "price") or 0
            )
            if name and price > 0:
                out.append({
                    "title": name,
                    "provider": "Priceline",
                    "chain": _detect_chain(name),
                    "price": price,
                    "currency": currency,
                    "per_night": True,
                    "url": public_url,
                })
        return out
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Priceline API request failed: {type(exc).__name__}") from exc


def _scrape_priceline_com2_host(
    host: str,
    city: str,
    check_in: str,
    check_out: str,
    adults: int,
    currency: str,
    public_url: str,
) -> list[dict]:
    """Priceline com2 RapidAPI variant.

    The known endpoint is /hotels/auto-complete?query=<city>. The hotel search
    endpoint path can be overridden once the RapidAPI docs expose the exact curl.
    """
    headers = _rapidapi_headers(host)
    loc_r = httpx.get(
        f"https://{host}/hotels/auto-complete",
        params={"query": city},
        headers=headers,
        timeout=15,
    )
    if loc_r.status_code != 200:
        raise RuntimeError(_rapidapi_priceline_error(loc_r.status_code, loc_r.text))

    loc_data = loc_r.json()
    location_id, location_payload = _extract_priceline_com2_location(loc_data)
    if not location_id and not location_payload:
        raise RuntimeError("Priceline com2 autocomplete returned no usable hotel location")

    search_path = os.getenv("PRICELINE_COM2_HOTEL_SEARCH_PATH", "/hotels/search")
    # priceline-com2 docs currently show only: /hotels/search?locationId=<id>
    # Keep this minimal so RapidAPI does not reject unknown query params.
    search_params = {}
    if location_id:
        search_params["locationId"] = location_id

    r = httpx.get(
        f"https://{host}{search_path}",
        params=search_params,
        headers=headers,
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(
            _rapidapi_priceline_error(r.status_code, r.text)
            + f"; set PRICELINE_COM2_HOTEL_SEARCH_PATH if this API uses a different hotel search endpoint"
        )

    out = _extract_priceline_hotels(r.json(), currency, public_url)
    if not out:
        raise RuntimeError("Priceline com2 hotel search returned no parsable hotel prices")
    return out


def _extract_priceline_com2_location(data: Any) -> tuple[str, dict[str, str]]:
    """Extract a location id and useful location fields from com2 autocomplete."""
    candidates: list[dict] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if any(k in node for k in ("id", "locationId", "cityID", "cityId", "destId")):
                candidates.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    if not candidates:
        return "", {}

    first = candidates[0]
    location_id = str(
        first.get("locationId")
        or first.get("id")
        or first.get("cityID")
        or first.get("cityId")
        or first.get("destId")
        or ""
    )
    payload: dict[str, str] = {}
    for src, dest in [
        ("cityId", "cityId"),
        ("cityID", "cityID"),
        ("destId", "destId"),
        ("type", "type"),
        ("displayName", "displayName"),
        ("name", "name"),
    ]:
        value = first.get(src)
        if value:
            payload[dest] = str(value)
    return location_id, payload


def _rapidapi_priceline_error(status_code: int, body: str) -> str:
    if status_code == 403 and "not subscribed" in body.lower():
        return (
            "Priceline API subscription missing for PRICELINE_RAPIDAPI_HOST "
            "(subscribe this RapidAPI app or set PRICELINE_RAPIDAPI_HOST to your subscribed Priceline provider)"
        )
    if status_code == 429:
        return "Priceline RapidAPI rate limit exceeded; wait for quota reset or upgrade the RapidAPI plan"
    return f"Priceline API returned HTTP {status_code}"


def _priceline_search_url(city: str, check_in: str, check_out: str, adults: int) -> str:
    from urllib.parse import urlencode

    return "https://www.priceline.com/hotel/search?" + urlencode({
        "searchType": "CITY",
        "location": city,
        "checkIn": check_in,
        "checkOut": check_out,
        "adults": adults,
        "rooms": 1,
    })


def _priceline_relax_url(city: str, check_in: str, check_out: str, adults: int) -> str:
    from urllib.parse import quote_plus

    city_slug = quote_plus(city.strip().replace(",", ""))
    start = check_in.replace("-", "")
    end = check_out.replace("-", "")
    return (
        f"https://www.priceline.com/relax/in/{city_slug}/from/{start}/to/{end}/rooms/1"
        f"?adults={adults}"
    )


def scrape_priceline_public(
    city: str, check_in: str, check_out: str, adults: int, currency: str
) -> list[dict]:
    """Priceline public-site fallback using API capture + embedded JSON parsing."""
    search_url = _priceline_search_url(city, check_in, check_out, adults)
    relax_url = _priceline_relax_url(city, check_in, check_out, adults)
    try:
        api_patterns = [
            "priceline.com/pws/", "priceline.com/pws/v0", "priceline.com/pws/v1",
            "priceline.com/relax/", "/api/", "/hotel/",
            "hotels/search", "hotel/listing", "hotel/results", "hotel-retail",
            "getHotelResults", "hotelResults", "searchResults", "propertySearch",
        ]
        for url in (search_url, relax_url):
            captured = _pw_capture_hotel_api(url, api_patterns=api_patterns, timeout=45_000)
            for data in captured:
                out = _extract_priceline_hotels(data, currency, url)
                if out:
                    return out

        html = ""
        for url in (search_url, relax_url):
            html = _pw_get_html(
                url,
                wait_selector="[data-testid*='hotel'],[class*='hotel'],[class*='Hotel'],[class*='property']",
                extra_wait_ms=6_000,
                timeout=45_000,
            )
            out = _extract_priceline_hotels(_extract_next_data(html), currency, url)
            if out:
                return out
            out = _extract_priceline_html(html, currency, url)
            if out:
                return out

        return _extract_priceline_html(html, currency, search_url)
    except Exception:
        return []


def _extract_priceline_hotels(data: Any, currency: str, search_url: str) -> list[dict]:
    """Walk nested Priceline JSON and pull plausible hotel cards."""
    out: list[dict] = []
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if len(out) >= 15:
            return
        if isinstance(node, dict):
            name = (
                node.get("hotelName") or node.get("name") or node.get("propertyName")
                or node.get("displayName") or node.get("hotel_name")
            )
            price = _parse_price(
                _dig(node, "ratesSummary", "minPrice")
                or _dig(node, "ratesSummary", "minRate")
                or _dig(node, "price", "amount")
                or _dig(node, "pricing", "price")
                or node.get("minPrice")
                or node.get("rate")
                or node.get("price")
                or 0
            )
            if name and 10 <= price <= 5000:
                key = str(name).strip().lower()
                if key not in seen:
                    seen.add(key)
                    out.append({
                        "title": str(name).strip(),
                        "provider": "Priceline",
                        "chain": _detect_chain(str(name)),
                        "price": price,
                        "currency": currency,
                        "per_night": True,
                        "url": search_url,
                    })
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(data)
    return sorted(out, key=lambda h: h["price"])


def _extract_priceline_html(html: str, currency: str, search_url: str) -> list[dict]:
    names = re.findall(r'"(?:hotelName|propertyName|name|displayName)"\s*:\s*"([^"{}]{3,100})"', html)
    prices = re.findall(r'"(?:minPrice|minRate|amount|price)"\s*:\s*([\d.]{2,8})', html)
    out: list[dict] = []
    seen: set[str] = set()
    for name, raw_price in zip(names, prices):
        clean = name.encode("utf-8", "ignore").decode("unicode_escape", "ignore").strip()
        price = _parse_price(raw_price)
        if clean.lower() in seen or not clean or not (10 <= price <= 5000):
            continue
        seen.add(clean.lower())
        out.append({
            "title": clean,
            "provider": "Priceline",
            "chain": _detect_chain(clean),
            "price": price,
            "currency": currency,
            "per_night": True,
            "url": search_url,
        })
        if len(out) >= 15:
            break
    return sorted(out, key=lambda h: h["price"])


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _deduplicate(hotels: list[dict]) -> list[dict]:
    """Sort cheapest-first and remove near-duplicate (same title prefix + platform)."""
    seen: set[tuple] = set()
    out: list[dict] = []
    for h in sorted(hotels, key=lambda x: x.get("price", 0)):
        key = (h.get("provider", ""), h.get("title", "")[:40].lower())
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out
