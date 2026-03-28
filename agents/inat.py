"""
iNaturalist scraper agent.

Fetches publicly available, geo-tagged nature observation photos from
iNaturalist within San Francisco. Great for outdoor & park activities
(Golden Gate Park, Presidio, Land's End, etc.).

No API key required for read-only observation access.
Cadence: daily (static agent)

iNaturalist place IDs used:
  - 853  → San Francisco (city)
"""

import logging
from typing import Optional

import aiohttp

from agents.base import BaseImageAgent
from config import cfg

logger = logging.getLogger(__name__)

_ENDPOINT = "https://api.inaturalist.org/v1/observations"

# iNaturalist place_id for San Francisco
_SF_PLACE_ID = 853

_PER_PAGE = 50

# Only include research-grade observations (community-verified)
# and those that have at least one photo
_DEFAULT_PARAMS = {
    "place_id": _SF_PLACE_ID,
    "photos": "true",
    "quality_grade": "research",
    "order_by": "created_at",
    "order": "desc",
    "per_page": _PER_PAGE,
    "geoprivacy": "open",           # only publicly geo-tagged
}


class iNaturalistAgent(BaseImageAgent):
    """Scrapes geo-tagged nature observation photos from iNaturalist in SF.

    Research-grade observations are community-verified and include precise
    GPS coordinates, species names, and photo URLs. Ideal for representing
    outdoor SF activities in parks and natural areas.

    Attributes:
        AGENT_ID: Unique identifier in aperture-nexus.
        IS_LIVE: False — runs once daily.
    """

    AGENT_ID = "inat-agent"
    AGENT_NAME = "iNaturalist SF Nature Observations Agent"
    IS_LIVE = False
    INTERVAL_SECONDS = 86400  # daily

    async def fetch(self) -> list[dict]:
        """Fetch recent research-grade observations with photos near SF.

        Returns:
            List of records with ``image_url`` keys for BaseImageAgent.
        """
        async with aiohttp.ClientSession(
            headers={"User-Agent": "SF-City-Intelligence/1.0 (hackathon)"}
        ) as session:
            try:
                async with session.get(
                    _ENDPOINT,
                    params=_DEFAULT_PARAMS,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
            except Exception as e:
                logger.error("iNaturalist: request failed: %s", e)
                return []

        observations = data.get("results", [])
        records = []
        for obs in observations:
            record = self._to_record(obs)
            if record:
                records.append(record)

        logger.info("iNaturalist: fetched %d observations with photos", len(records))
        return records

    def _to_record(self, obs: dict) -> Optional[dict]:
        """Convert a raw iNaturalist observation to a normalized image record."""
        # Photos: pick the first medium-sized photo
        photos = obs.get("photos", [])
        if not photos:
            return None

        photo = photos[0]
        image_url = (photo.get("url") or "").replace("/square.", "/medium.")
        if not image_url.startswith("http"):
            return None

        # Location
        geo = obs.get("geojson") or {}
        coords = geo.get("coordinates", [])  # GeoJSON: [lon, lat]
        lat = float(coords[1]) if len(coords) >= 2 else cfg.sf_center_lat
        lon = float(coords[0]) if len(coords) >= 2 else cfg.sf_center_lon

        # Taxon (species) info
        taxon = obs.get("taxon") or {}
        common_name = taxon.get("preferred_common_name") or taxon.get("name") or "Unknown species"
        sci_name = taxon.get("name") or ""
        iconic = taxon.get("iconic_taxon_name") or "Nature"

        # Place info
        place_str = obs.get("place_guess") or "San Francisco"
        obs_date = obs.get("observed_on") or obs.get("created_at", "")[:10]
        observer = (obs.get("user") or {}).get("login", "unknown")
        quality = obs.get("quality_grade", "")
        obs_id = obs.get("id", "")

        content = (
            f"iNaturalist observation in {place_str}: {common_name}"
            f"{f' ({sci_name})' if sci_name and sci_name != common_name else ''}. "
            f"Type: {iconic}. Observed {obs_date} by {observer}. "
            f"Quality: {quality}. "
            f"Great for outdoor activities in SF's parks and natural areas."
        )

        record = self.normalize(
            source="inat",
            content=content,
            category="nature_observation",
            title=f"{common_name} in {place_str}",
            lat=lat,
            lon=lon,
            url=f"https://www.inaturalist.org/observations/{obs_id}",
            raw={
                "id": obs_id,
                "taxon_common": common_name,
                "taxon_scientific": sci_name,
                "iconic_taxon": iconic,
                "place": place_str,
                "observed_on": obs_date,
                "observer": observer,
                "quality_grade": quality,
                "num_photos": len(photos),
                "image_url": image_url,
            },
        )
        record["image_url"] = image_url
        return record
