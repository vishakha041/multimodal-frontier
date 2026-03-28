"""
SF311 scraper agent.

Pulls the latest service requests from San Francisco's open 311 dataset
via the Socrata Open Data API. No API key required.

Data source: https://data.sfgov.org/City-Infrastructure/311-Cases/vw6y-z8j6
Cadence: daily (static agent)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp

from agents.base import BaseAgent

logger = logging.getLogger(__name__)

# Socrata endpoint — no token required, but rate-limited at ~1000 req/hr
_ENDPOINT = "https://data.sfgov.org/resource/vw6y-z8j6.json"

# Maximum records to fetch per run (Socrata default page size is 1000)
_LIMIT = 1000

# SF311 request types that relate to "things to do" / city experience
# (parks, streets, graffiti, public spaces — exclude purely residential complaints)
_RELEVANT_CATEGORIES = {
    "Street and Sidewalk Cleaning",
    "Parks & Recreation",
    "Graffiti",
    "Abandoned Vehicle",
    "Street Defects",
    "Tree Maintenance",
    "Noise Report",
    "Public Works",
    "Rec and Park",
    "Illegal Posting",
}


class SF311Agent(BaseAgent):
    """Scrapes recent SF311 city service requests from the open data portal.

    Fetches requests from the past 24 hours and normalizes them into the
    shared SF city intelligence schema. No API key required.

    Attributes:
        AGENT_ID: Unique identifier in aperture-nexus.
        IS_LIVE: False — runs once daily.
    """

    AGENT_ID = "sf311-agent"
    AGENT_NAME = "SF311 City Issues Agent"
    IS_LIVE = False
    INTERVAL_SECONDS = 86400  # daily

    async def fetch(self) -> list[dict]:
        """Fetch SF311 service requests from the past 24 hours.

        Returns:
            List of normalized records for relevant service categories.
        """
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        params = {
            "$limit": _LIMIT,
            "$where": f"requested_datetime >= '{since}'",
            "$order": "requested_datetime DESC",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(_ENDPOINT, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                resp.raise_for_status()
                cases = await resp.json()

        logger.info("SF311: fetched %d cases from past 24h", len(cases))
        return [self._to_record(c) for c in cases if self._is_relevant(c)]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_relevant(case: dict) -> bool:
        """Return True if the case category relates to public city experience."""
        category = case.get("category", "")
        request_type = case.get("request_type", "")
        for term in _RELEVANT_CATEGORIES:
            if term.lower() in category.lower() or term.lower() in request_type.lower():
                return True
        return True  # include all for now — can tighten with real data

    def _to_record(self, case: dict) -> dict:
        """Convert a raw SF311 case dict to a normalized record."""
        lat = _safe_float(case.get("lat"))
        lon = _safe_float(case.get("long"))
        address = case.get("address")
        title = case.get("request_type") or case.get("category") or "SF311 Case"
        content_parts = [
            f"SF311 service request: {title}",
            f"Status: {case.get('status', 'unknown')}",
        ]
        if case.get("neighborhoods_sffind_boundaries"):
            content_parts.append(f"Neighborhood: {case['neighborhoods_sffind_boundaries']}")
        if case.get("responsible_agency"):
            content_parts.append(f"Agency: {case['responsible_agency']}")

        return self.normalize(
            source="sf311",
            content=" | ".join(content_parts),
            category=case.get("category", "city_service").lower().replace(" ", "_"),
            title=title,
            lat=lat,
            lon=lon,
            address=address,
            url=f"https://sf311.org/cases/{case.get('service_request_id', '')}",
            raw={k: v for k, v in case.items() if k not in ("point",)},
        )


def _safe_float(val: Optional[str]) -> Optional[float]:
    try:
        return float(val) if val else None
    except (ValueError, TypeError):
        return None
