"""
Free live scrapers - no API keys required.
  wttr.in       → weather
  Wikipedia API → attractions + city info
  exchangerate-api.com → currency rates
"""
import httpx

_HTTP = httpx.Client(
    timeout=10, follow_redirects=True,
    headers={"User-Agent": "AITravelSavingsAgent/2.0 (trip optimizer; contact@example.com)"},
)


def get_weather(city: str) -> dict:
    """Current weather + 3-day forecast via wttr.in."""
    try:
        r = _HTTP.get(f"https://wttr.in/{city}?format=j1")
        r.raise_for_status()
        data = r.json()
        cur = data["current_condition"][0]
        forecast = [
            {
                "date": w["date"],
                "max_c": w["maxtempC"],
                "min_c": w["mintempC"],
                "desc": w["hourly"][4]["weatherDesc"][0]["value"],
            }
            for w in data["weather"][:3]
        ]
        return {
            "city": city,
            "temp_c": cur["temp_C"],
            "temp_f": cur["temp_F"],
            "feels_like_c": cur["FeelsLikeC"],
            "description": cur["weatherDesc"][0]["value"],
            "humidity_pct": cur["humidity"],
            "wind_kmph": cur["windspeedKmph"],
            "forecast_3day": forecast,
        }
    except Exception as e:
        return {"error": str(e), "city": city}


def _disambiguate(city: str) -> str:
    """Return a more specific Wikipedia title for cities that are ambiguous."""
    _SPECIFICS = {
        "Phoenix":      "Phoenix, Arizona",
        "Denver":       "Denver, Colorado",
        "Austin":       "Austin, Texas",
        "Portland":     "Portland, Oregon",
        "Charlotte":    "Charlotte, North Carolina",
        "Nashville":    "Nashville, Tennessee",
        "Columbus":     "Columbus, Ohio",
        "Memphis":      "Memphis, Tennessee",
        "Richmond":     "Richmond, Virginia",
        "Springfield":  "Springfield, Illinois",
        "Cambridge":    "Cambridge, England",
        "Nice":         "Nice, France",
        "Florence":     "Florence, Italy",
        "Rome":         "Rome, Italy",
        "Milan":        "Milan, Italy",
        "Venice":       "Venice, Italy",
    }
    return _SPECIFICS.get(city, city)


def get_attractions(city: str) -> dict:
    """Top tourist attractions via Wikipedia search API."""
    try:
        specific = _disambiguate(city)
        r = _HTTP.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": f"tourist attractions {specific}",
                "format": "json",
                "srlimit": 8,
            },
        )
        r.raise_for_status()
        results = r.json().get("query", {}).get("search", [])
        # Filter: keep only results whose title contains the city name
        city_lower = city.lower()
        filtered = [
            item for item in results
            if city_lower in item["title"].lower() or specific.lower() in item["title"].lower()
        ] or results  # fall back to all if nothing matches
        attractions = [
            {
                "name": item["title"],
                "snippet": item["snippet"]
                .replace('<span class="searchmatch">', "")
                .replace("</span>", "")
                .replace("&#039;", "'"),
            }
            for item in filtered[:6]
        ]
        return {"city": city, "attractions": attractions}
    except Exception as e:
        return {"error": str(e), "city": city}


def get_exchange_rate(from_currency: str, to_currency: str) -> dict:
    """Live exchange rate via exchangerate-api.com (free tier, no key)."""
    try:
        r = _HTTP.get(f"https://api.exchangerate-api.com/v4/latest/{from_currency.upper()}")
        r.raise_for_status()
        rates = r.json().get("rates", {})
        to_upper = to_currency.upper()
        rate = rates.get(to_upper)
        if rate is None:
            return {"error": f"Currency {to_upper} not found", "from": from_currency, "to": to_currency}
        return {
            "from": from_currency.upper(),
            "to": to_upper,
            "rate": rate,
            "example": f"1 {from_currency.upper()} = {rate} {to_upper}",
        }
    except Exception as e:
        return {"error": str(e), "from": from_currency, "to": to_currency}


def get_city_info(city: str) -> dict:
    """Brief city overview from Wikipedia extract API."""
    try:
        r = _HTTP.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "prop": "extracts",
                "exintro": True,
                "explaintext": True,
                "redirects": True,
                "titles": _disambiguate(city),
                "format": "json",
            },
        )
        r.raise_for_status()
        pages = r.json().get("query", {}).get("pages", {})
        page = next(iter(pages.values()))
        extract = page.get("extract", "")
        return {
            "city": city,
            "summary": extract[:600].strip() if extract else "No info found.",
        }
    except Exception as e:
        return {"error": str(e), "city": city}
