"""
Wikimedia Commons scraper agent.

Fetches publicly available, geo-tagged images from Wikimedia Commons
within a radius of the San Francisco geographic center using the
MediaWiki GeoData API. All images are freely reusable (CC / public domain).

No API key required.
Cadence: daily (static agent)
"""

import logging
from typing import Optional

import aiohttp

from agents.base import BaseImageAgent
from config import cfg

logger = logging.getLogger(__name__)

_API = "https://commons.wikimedia.org/w/api.php"

# Search radius in metres (max 10 000 for Wikimedia GeoData)
_RADIUS_M = 10_000
_LIMIT = 50


class WikimediaAgent(BaseImageAgent):
    """Scrapes geo-tagged images from Wikimedia Commons near SF center.

    Step 1 — GeoData search: finds File: pages within radius of SF.
    Step 2 — ImageInfo fetch: retrieves direct image URLs and metadata
              for each discovered file in a single batched API call.

    Attributes:
        AGENT_ID: Unique identifier in aperture-nexus.
        IS_LIVE: False — runs once daily.
    """

    AGENT_ID = "wikimedia-agent"
    AGENT_NAME = "Wikimedia Commons SF Geo-tagged Images Agent"
    IS_LIVE = False
    INTERVAL_SECONDS = 86400  # daily

    async def fetch(self) -> list[dict]:
        """Discover and return geo-tagged Wikimedia images near SF.

        Returns:
            List of records with ``image_url`` keys for BaseImageAgent.
        """
        # Wikimedia requires a descriptive User-Agent — generic agents get 403
        headers = {
            "User-Agent": (
                "SF-City-Intelligence/1.0 "
                "(educational hackathon; https://github.com/sf-city-intelligence)"
            )
        }
        async with aiohttp.ClientSession(headers=headers) as session:
            page_titles = await self._geosearch(session)
            if not page_titles:
                return []
            image_infos = await self._fetch_image_info(session, page_titles)

        records = []
        for title, info in image_infos.items():
            record = self._to_record(title, info)
            if record:
                records.append(record)

        logger.info("Wikimedia: fetched %d geo-tagged images", len(records))
        return records

    async def _geosearch(self, session: aiohttp.ClientSession) -> list[str]:
        """Return File: page titles within radius of SF center."""
        params = {
            "action": "query",
            "list": "geosearch",
            "gscoord": f"{cfg.sf_center_lat}|{cfg.sf_center_lon}",
            "gsradius": _RADIUS_M,
            "gslimit": _LIMIT,
            "gsnamespace": 6,      # namespace 6 = File:
            "format": "json",
        }
        try:
            async with session.get(
                _API, params=params, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except Exception as e:
            logger.error("Wikimedia geosearch failed: %s", e)
            return []

        hits = data.get("query", {}).get("geosearch", [])
        return [h["title"] for h in hits if "title" in h]

    async def _fetch_image_info(
        self, session: aiohttp.ClientSession, titles: list[str]
    ) -> dict[str, dict]:
        """Batch-fetch image URLs and metadata for a list of File: page titles."""
        params = {
            "action": "query",
            "prop": "imageinfo|coordinates",
            "iiprop": "url|extmetadata|dimensions|mediatype",
            "titles": "|".join(titles),
            "format": "json",
        }
        try:
            async with session.get(
                _API, params=params, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except Exception as e:
            logger.error("Wikimedia imageinfo fetch failed: %s", e)
            return {}

        pages = data.get("query", {}).get("pages", {})
        return {p.get("title", ""): p for p in pages.values()}

    def _to_record(self, title: str, page: dict) -> Optional[dict]:
        """Convert a Wikimedia page dict to a normalized image record."""
        image_infos = page.get("imageinfo", [])
        if not image_infos:
            return None
        info = image_infos[0]

        media_type = info.get("mediatype", "")
        if media_type not in ("BITMAP", "DRAWING", ""):
            return None  # skip audio, video, office docs

        image_url = info.get("url", "")
        if not image_url or not image_url.startswith("http"):
            return None

        # Extract geo coords from the page if present
        coords = page.get("coordinates", [{}])[0]
        lat = coords.get("lat") or cfg.sf_center_lat
        lon = coords.get("lon") or cfg.sf_center_lon

        # Metadata from extmetadata
        meta = info.get("extmetadata", {})
        description = _meta_value(meta, "ImageDescription") or title
        license_name = _meta_value(meta, "LicenseShortName") or "unknown"
        artist = _meta_value(meta, "Artist") or "unknown"
        date_created = _meta_value(meta, "DateTimeOriginal") or ""
        categories = _meta_value(meta, "Categories") or ""

        clean_title = title.replace("File:", "").strip()
        content = (
            f"Wikimedia Commons: '{clean_title}'. "
            f"{description[:200]} "
            f"License: {license_name}. Author: {artist}."
        )

        record = self.normalize(
            source="wikimedia",
            content=content,
            category="geo_photo",
            title=clean_title,
            lat=float(lat),
            lon=float(lon),
            url=page.get("canonicalurl") or f"https://commons.wikimedia.org/wiki/{title}",
            raw={
                "title": title,
                "license": license_name,
                "artist": artist,
                "date_created": date_created,
                "categories": categories,
                "width": info.get("width"),
                "height": info.get("height"),
                "image_url": image_url,
            },
        )
        record["image_url"] = image_url
        return record


def _meta_value(meta: dict, key: str) -> str:
    """Extract the plain-text value from a Wikimedia extmetadata entry."""
    entry = meta.get(key, {})
    if isinstance(entry, dict):
        return entry.get("value", "") or ""
    return str(entry) if entry else ""
