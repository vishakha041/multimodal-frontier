"""
AirNow API scraper agent.

Polls the AirNow API for current air quality observations at the
geographic center of San Francisco. Useful for the demo to show whether
outdoor activities are advisable.

Requires: AIRNOW_API_KEY environment variable.
Register at: https://docs.airnowapi.org/ (instant, free)
Cadence: live — polls every few minutes (IS_LIVE = True)
"""

import logging

import aiohttp

from agents.base import BaseAgent
from config import cfg

logger = logging.getLogger(__name__)

_ENDPOINT = "https://www.airnowapi.org/aq/observation/latLong/current/"

# AQI category labels and their activity advice
_AQI_CATEGORIES = {
    "Good": "Air quality is good. Great day for outdoor activities!",
    "Moderate": "Air quality is acceptable. Unusually sensitive people should consider limiting prolonged outdoor exertion.",
    "Unhealthy for Sensitive Groups": "Sensitive groups may experience health effects. The general public is less likely to be affected.",
    "Unhealthy": "Everyone may begin to experience health effects. Limit prolonged outdoor exertion.",
    "Very Unhealthy": "Health alert — everyone may experience more serious health effects. Avoid outdoor activities.",
    "Hazardous": "Health warning of emergency conditions. Entire population is likely to be affected. Stay indoors.",
}

# Radius around SF center to search for monitoring stations (miles)
_SEARCH_RADIUS_MILES = 25


class AirNowAgent(BaseAgent):
    """Polls AirNow for current air quality at the SF geographic center.

    Returns one record per pollutant per observation (typically PM2.5,
    PM10, Ozone). Each record includes the AQI value, category, and
    practical activity advice.

    Attributes:
        AGENT_ID: Unique identifier in aperture-nexus.
        IS_LIVE: True — polls on INTERVAL_SECONDS cadence.
    """

    AGENT_ID = "airnow-agent"
    AGENT_NAME = "AirNow SF Air Quality Agent"
    IS_LIVE = True
    INTERVAL_SECONDS = 300  # 5 minutes (AirNow updates hourly, but polling is fine)

    async def fetch(self) -> list[dict]:
        """Fetch current AQI observations for San Francisco.

        Returns:
            Normalized records — one per pollutant observed near SF center.
        """
        if not cfg.has_airnow():
            logger.warning("AirNow: AIRNOW_API_KEY not set — skipping")
            return []

        params = {
            "latitude": cfg.sf_center_lat,
            "longitude": cfg.sf_center_lon,
            "distance": _SEARCH_RADIUS_MILES,
            "API_KEY": cfg.airnow_api_key,
            "format": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    _ENDPOINT, params=params, timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    resp.raise_for_status()
                    observations = await resp.json(content_type=None)
            except Exception as e:
                logger.error("AirNow: request failed: %s", e)
                return []

        if not isinstance(observations, list):
            logger.warning("AirNow: unexpected response format")
            return []

        records = [self._to_record(obs) for obs in observations if obs.get("AQI") is not None]
        logger.info("AirNow: fetched %d observations", len(records))
        return records

    def _to_record(self, obs: dict) -> dict:
        """Convert a raw AirNow observation to a normalized record."""
        pollutant = obs.get("ParameterName", "Unknown")
        aqi = obs.get("AQI", -1)
        category = obs.get("Category", {}).get("Name", "Unknown")
        station_name = obs.get("ReportingArea", "San Francisco")
        state = obs.get("StateCode", "CA")
        hour_utc = obs.get("HourUTC", "")

        advice = _AQI_CATEGORIES.get(category, "Check AirNow for details.")
        outdoor_ok = category in ("Good", "Moderate")

        content = (
            f"San Francisco air quality — {pollutant}: AQI {aqi} ({category}). "
            f"{advice} "
            f"Outdoor activities: {'✓ advisable' if outdoor_ok else '⚠ check conditions'}. "
            f"Station: {station_name}, {state}. Observed at {hour_utc} UTC."
        )

        return self.normalize(
            source="airnow",
            content=content,
            category="air_quality",
            title=f"SF Air Quality — {pollutant}: AQI {aqi} ({category})",
            url=(
                f"https://www.airnow.gov/?city=San+Francisco"
                f"&state=CA&country=USA"
            ),
            raw={
                "pollutant": pollutant,
                "aqi": aqi,
                "category": category,
                "station": station_name,
                "state_code": state,
                "hour_utc": hour_utc,
                "outdoor_advisable": outdoor_ok,
            },
        )
