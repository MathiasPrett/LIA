import datetime as dt
from dataclasses import dataclass

import httpx

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

_WEATHER_CODE_LABELS = {
    0: "☀️ despejado",
    1: "🌤️ mayormente despejado",
    2: "⛅ parcialmente nublado",
    3: "☁️ nublado",
    45: "🌫️ niebla",
    48: "🌫️ niebla con escarcha",
    51: "🌦️ llovizna leve",
    53: "🌦️ llovizna",
    55: "🌦️ llovizna intensa",
    61: "🌧️ lluvia leve",
    63: "🌧️ lluvia",
    65: "🌧️ lluvia intensa",
    71: "🌨️ nieve leve",
    73: "🌨️ nieve",
    75: "🌨️ nieve intensa",
    80: "🌦️ chubascos leves",
    81: "🌦️ chubascos",
    82: "⛈️ chubascos intensos",
    95: "⛈️ tormenta eléctrica",
    96: "⛈️ tormenta con granizo",
    99: "⛈️ tormenta fuerte con granizo",
}


class WeatherError(Exception):
    """Error de red al consultar Open-Meteo."""


@dataclass
class DailyForecast:
    date: dt.date
    temp_max: float
    temp_min: float
    precipitation_probability: int
    condition: str


def _describe(code: int) -> str:
    return _WEATHER_CODE_LABELS.get(code, f"código {code}")


async def fetch_daily_forecast(
    latitude: float, longitude: float, timezone: str, forecast_days: int = 7
) -> list[DailyForecast]:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode",
        "timezone": timezone,
        "forecast_days": forecast_days,
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            response = await client.get(FORECAST_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise WeatherError(f"No se pudo consultar el clima: {exc}") from exc

    daily = response.json()["daily"]
    return [
        DailyForecast(
            date=dt.date.fromisoformat(daily["time"][i]),
            temp_max=daily["temperature_2m_max"][i],
            temp_min=daily["temperature_2m_min"][i],
            precipitation_probability=daily["precipitation_probability_max"][i],
            condition=_describe(daily["weathercode"][i]),
        )
        for i in range(len(daily["time"]))
    ]
