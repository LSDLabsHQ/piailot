import json
import logging
import os
import time
import httpx

log = logging.getLogger("piailot")

# WMO weather code descriptions
_WMO_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Rime fog", 51: "Light drizzle", 53: "Moderate drizzle",
    55: "Dense drizzle", 61: "Slight rain", 63: "Moderate rain", 65: "Heavy rain",
    71: "Slight snow", 73: "Moderate snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Slight rain showers", 81: "Moderate rain showers", 82: "Violent rain showers",
    85: "Slight snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with slight hail", 99: "Thunderstorm with heavy hail",
}


async def _tool_weather(location: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            lat, lon, location_name = None, None, location
            if "," in location:
                parts = location.split(",")
                try:
                    lat, lon = float(parts[0].strip()), float(parts[1].strip())
                    location_name = f"{lat}, {lon}"
                except ValueError:
                    pass

            if lat is None:
                geo_resp = await client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params={"name": location, "count": 1, "language": "en"},
                )
                geo_data = geo_resp.json()
                results = geo_data.get("results", [])
                if not results:
                    return json.dumps({"__piailot_widget__": "weather", "data": {"error": f"Location '{location}' not found"}})
                lat = results[0]["latitude"]
                lon = results[0]["longitude"]
                location_name = results[0].get("name", location)
                country = results[0].get("country", "")
                if country:
                    location_name = f"{location_name}, {country}"

            wx_resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                    "daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max",
                    "temperature_unit": "celsius",
                    "wind_speed_unit": "kmh",
                    "forecast_days": 5,
                },
            )
            wx = wx_resp.json()

            current = wx.get("current", {})
            daily = wx.get("daily", {})

            weather_code = current.get("weather_code", 0)
            conditions = _WMO_CODES.get(weather_code, "Unknown")

            temp_c = current.get("temperature_2m", 0)
            temp_f = round(temp_c * 9 / 5 + 32, 1)

            forecast = []
            dates = daily.get("time", [])
            highs = daily.get("temperature_2m_max", [])
            lows = daily.get("temperature_2m_min", [])
            codes = daily.get("weather_code", [])
            precip = daily.get("precipitation_probability_max", [])

            for i in range(min(5, len(dates))):
                high_c = highs[i] if i < len(highs) else 0
                forecast.append({
                    "date": dates[i],
                    "high_c": high_c,
                    "high_f": round(high_c * 9 / 5 + 32, 1),
                    "low_c": lows[i] if i < len(lows) else 0,
                    "conditions": _WMO_CODES.get(codes[i] if i < len(codes) else 0, "Unknown"),
                    "precipitation_chance": precip[i] if i < len(precip) else 0,
                })

            widget = {
                "__piailot_widget__": "weather",
                "data": {
                    "location_name": location_name,
                    "current": {
                        "temp_c": temp_c,
                        "temp_f": temp_f,
                        "conditions": conditions,
                        "humidity": current.get("relative_humidity_2m", 0),
                        "wind_speed": current.get("wind_speed_10m", 0),
                    },
                    "forecast": forecast,
                },
            }
            return json.dumps(widget)
    except Exception as e:
        return json.dumps({"__piailot_widget__": "weather", "data": {"error": str(e)}})


_last_nominatim_call = 0.0


async def _tool_places_search(query: str, latitude: float = None, longitude: float = None, max_results: int = 5) -> str:
    global _last_nominatim_call
    max_results = max(1, min(max_results, 10))

    places_key = os.getenv("PLACES_API_KEY")

    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            if places_key:
                return await _places_google(client, query, latitude, longitude, max_results, places_key)
            else:
                return await _places_nominatim(client, query, latitude, longitude, max_results)
    except Exception as e:
        return json.dumps({"__piailot_widget__": "places", "data": {"query": query, "places": [], "error": str(e)}})


async def _places_nominatim(client, query, latitude, longitude, max_results):
    global _last_nominatim_call
    # Rate limit: 1 req/sec
    now = time.monotonic()
    wait = 1.0 - (now - _last_nominatim_call)
    if wait > 0:
        import asyncio
        await asyncio.sleep(wait)
    _last_nominatim_call = time.monotonic()

    params = {
        "q": query,
        "format": "json",
        "limit": max_results,
        "addressdetails": 1,
    }
    if latitude is not None and longitude is not None:
        params["viewbox"] = f"{longitude-0.1},{latitude+0.1},{longitude+0.1},{latitude-0.1}"
        params["bounded"] = 0

    resp = await client.get(
        "https://nominatim.openstreetmap.org/search",
        params=params,
        headers={"User-Agent": "PiAiLot/1.0 (self-hosted AI gateway)"},
    )
    data = resp.json()

    places = []
    for item in data[:max_results]:
        addr = item.get("address", {})
        address_parts = []
        for key in ["road", "house_number", "city", "town", "village", "state", "country"]:
            if key in addr:
                address_parts.append(addr[key])

        places.append({
            "name": item.get("display_name", "").split(",")[0],
            "address": ", ".join(address_parts) if address_parts else item.get("display_name", ""),
            "latitude": float(item.get("lat", 0)),
            "longitude": float(item.get("lon", 0)),
            "type": item.get("type", ""),
        })

    return json.dumps({"__piailot_widget__": "places", "data": {"query": query, "places": places}})


async def _places_google(client, query, latitude, longitude, max_results, api_key):
    params = {
        "query": query,
        "key": api_key,
    }
    if latitude is not None and longitude is not None:
        params["location"] = f"{latitude},{longitude}"
        params["radius"] = 5000

    resp = await client.get(
        "https://maps.googleapis.com/maps/api/place/textsearch/json",
        params=params,
    )
    data = resp.json()

    places = []
    for item in data.get("results", [])[:max_results]:
        loc = item.get("geometry", {}).get("location", {})
        places.append({
            "name": item.get("name", ""),
            "address": item.get("formatted_address", ""),
            "latitude": loc.get("lat", 0),
            "longitude": loc.get("lng", 0),
            "type": ", ".join(item.get("types", [])[:2]),
            "rating": item.get("rating"),
        })

    return json.dumps({"__piailot_widget__": "places", "data": {"query": query, "places": places}})
