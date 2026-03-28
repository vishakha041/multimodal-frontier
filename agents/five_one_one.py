"""
511 SF Bay scraper agent.

Polls the 511 SF Bay open data API for real-time traffic events and
transit service disruptions in the San Francisco Bay Area.

Requires: FIVE_ONE_ONE_API_KEY environment variable.
Register at: https://511.org/open-data/token (instant, free)
Cadence: live — polls every few minutes (IS_LIVE = True)
"""

import json
import logging
from typing import Optional

import aiohttp

from agents.base import BaseAgent
from config import cfg

logger = logging.getLogger(__name__)

_API_BASE = "https://api.511.org"

# Traffic events endpoint — returns CHP/Caltrans incidents in the region
_EVENTS_URL = f"{_API_BASE}/traffic/events"

# Transit service alerts for SFMTA via 511
_ALERTS_URL = f"{_API_BASE}/transit/servicealerts"

# Operators we care about for the SF demo
_SF_TRANSIT_OPERATORS = ["SF", "BA", "CT", "FS"]  # SFMTA, BART, Caltrain, Ferry


class FiveOneOneAgent(BaseAgent):
    """Polls 511 SF Bay for live traffic events and transit disruptions.

    Fetches both traffic incidents (accidents, construction, road closures)
    and transit service alerts for SF-area operators every few minutes.

    Attributes:
        AGENT_ID: Unique identifier in aperture-nexus.
        IS_LIVE: True — polls on INTERVAL_SECONDS cadence.
    """

    AGENT_ID = "511sfbay-agent"
    AGENT_NAME = "511 SF Bay Live Traffic & Transit Agent"
    IS_LIVE = True
    INTERVAL_SECONDS = 300  # 5 minutes

    async def fetch(self) -> list[dict]:
        """Fetch live traffic events and transit alerts from 511 SF Bay.

        Returns:
            Normalized records for active traffic events and service alerts.
        """
        if not cfg.has_511():
            logger.warning("511 SF Bay: FIVE_ONE_ONE_API_KEY not set — skipping")
            return []

        records: list[dict] = []
        async with aiohttp.ClientSession() as session:
            events = await self._fetch_events(session)
            alerts = await self._fetch_transit_alerts(session)

        records.extend(events)
        records.extend(alerts)
        logger.info("511: fetched %d records (%d events, %d alerts)",
                    len(records), len(events), len(alerts))
        return records

    async def _fetch_events(self, session: aiohttp.ClientSession) -> list[dict]:
        """Fetch active traffic events from the 511 events endpoint."""
        params = {
            "api_key": cfg.five_one_one_api_key,
            "format": "json",
        }
        try:
            async with session.get(
                _EVENTS_URL, params=params, timeout=aiohttp.ClientTimeout(total=20)
            ) as resp:
                resp.raise_for_status()
                # 511 API returns UTF-8 with BOM — read as text with utf-8-sig
                # then parse manually so the BOM doesn't break json decoding
                text = await resp.text(encoding="utf-8-sig")
                data = json.loads(text)
        except Exception as e:
            logger.warning("511 events: request failed: %s", e)
            return []

        events = _extract_list(data)
        records = []
        for event in events:
            record = self._event_to_record(event)
            if record:
                records.append(record)
        return records

    async def _fetch_transit_alerts(self, session: aiohttp.ClientSession) -> list[dict]:
        """Fetch transit service alerts for SF-area operators."""
        records = []
        for operator in _SF_TRANSIT_OPERATORS:
            params = {
                "api_key": cfg.five_one_one_api_key,
                "agency": operator,
                "format": "json",
            }
            try:
                async with session.get(
                    _ALERTS_URL, params=params, timeout=aiohttp.ClientTimeout(total=20)
                ) as resp:
                    resp.raise_for_status()
                    text = await resp.text(encoding="utf-8-sig")
                    data = json.loads(text)
                alerts = _extract_list(data, keys=["Entities", "entity"])
                for alert in alerts:
                    record = self._alert_to_record(alert, operator)
                    if record:
                        records.append(record)
            except Exception as e:
                logger.debug("511 alerts for operator=%s failed: %s", operator, e)
        return records

    def _event_to_record(self, event: dict) -> Optional[dict]:
        """Convert a 511 traffic event to a normalized record."""
        event_type = event.get("event_type") or event.get("EventType") or "incident"
        headline = event.get("headline") or event.get("Description") or ""
        severity = event.get("severity") or event.get("Severity") or "unknown"

        # Location from geography
        geo = event.get("geography") or event.get("Geography") or {}
        coords = _parse_geometry(geo)
        roads = event.get("roads") or event.get("Roads") or []
        road_name = roads[0].get("name", "") if roads else ""

        if not headline:
            return None

        content = (
            f"511 Traffic {event_type.title()}: {headline}. "
            f"Severity: {severity}."
            f"{f' Road: {road_name}.' if road_name else ''}"
        )

        return self.normalize(
            source="511sfbay",
            content=content,
            category=f"traffic_{event_type.lower().replace(' ', '_')}",
            title=headline[:100],
            lat=coords[0] if coords else None,
            lon=coords[1] if coords else None,
            url="https://511.org",
            raw={"event_type": event_type, "severity": severity,
                 "headline": headline, "road": road_name},
        )

    def _alert_to_record(self, alert: dict, operator: str) -> Optional[dict]:
        """Convert a 511 transit service alert to a normalized record."""
        # GTFS-RT alert structure (nested)
        alert_body = alert.get("alert", {})
        header = _get_translated(alert_body.get("header_text", {}))
        description = _get_translated(alert_body.get("description_text", {}))

        if not header:
            return None

        content = f"511 Transit Alert [{operator}]: {header}."
        if description:
            content += f" {description[:300]}"

        return self.normalize(
            source="511sfbay",
            content=content,
            category="transit_alert",
            title=header[:100],
            url="https://511.org/transit",
            raw={"operator": operator, "header": header, "description": description},
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_list(data: object, keys: Optional[list[str]] = None) -> list:
    """Navigate nested 511 API responses to find the list of items."""
    if isinstance(data, list):
        return data
    if not isinstance(data, dict):
        return []
    for key in (keys or ["Events", "events", "Entities", "entity", "data"]):
        val = data.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            return _extract_list(val)
    return []


def _parse_geometry(geo: dict) -> Optional[tuple[float, float]]:
    """Extract (lat, lon) from a 511 geography object."""
    if not geo:
        return None
    coords = geo.get("coordinates")
    if isinstance(coords, list) and len(coords) >= 2:
        # GeoJSON: [lon, lat]
        return (coords[1], coords[0])
    return None


def _get_translated(text_obj: dict) -> str:
    """Extract English text from a GTFS-RT TranslatedString object."""
    if not isinstance(text_obj, dict):
        return ""
    for t in text_obj.get("translation", []):
        if t.get("language", "en") in ("en", ""):
            return t.get("text", "")
    return ""
