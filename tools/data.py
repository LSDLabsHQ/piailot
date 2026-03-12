import json
import logging
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
