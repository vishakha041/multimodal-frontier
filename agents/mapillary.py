"""
Mapillary scraper agent.

Fetches geo-tagged street-level photos from Mapillary within the
San Francisco bounding box. Every Mapillary image has a precise GPS
coordinate — ideal for exploring SF neighborhoods, streets, and landmarks.

Requires: MAPILLARY_API_KEY environment variable.
Register at: https://www.mapillary.com/developer
  1. Sign up / log in
  2. Go to Dashboard → Applications → Register application
  3. Copy the "Client Token" (this is your access_token)
Free for non-commercial use.

Cadence: daily (static agent)
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from agents.base import BaseImageAgent
from config import cfg

logger = logging.getLogger(__name__)

_ENDPOINT = "https://graph.mapillary.com/images"

# SF bounding box: west, south, east, north
_SF_BBOX = "-122.5270,37.7034,-122.3482,37.8324"

# Fields to request — keep lean to stay within API limits.
# Note: computed_compass_angle is NOT a valid Graph API v4 field → 500 error.
# Use compass_angle (the raw sensor value) instead.
_FIELDS = ",".join([
    "id",
    "geometry",       # GeoJSON Point — gives us precise lat/lon
    "thumb_1024_url", # best quality thumbnail for storage
    "thumb_256_url",  # fallback thumbnail
    "captured_at",    # timestamp in milliseconds
    "is_pano",        # True if this is a 360° panorama
    "compass_angle",  # direction the camera was facing (raw sensor value)
    # Note: "creator" is an object/edge field and cannot be requested in a
    # flat field list — it requires nested syntax (creator{id,username}) which
    # the REST endpoint does not support, causing a 500 error.
])

_LIMIT = 50


class MapillaryAgent(BaseImageAgent):
    """Scrapes geo-tagged street-level photos from Mapillary near SF.

    Uses the Mapillary Graph API to search for images within the SF
    bounding box. Every returned image has a precise GPS point from
    the GeoJSON geometry field.

    Attributes:
        AGENT_ID: Unique identifier in aperture-nexus.
        IS_LIVE: False — runs once daily.
    """

    AGENT_ID = "mapillary-agent"
    AGENT_NAME = "Mapillary SF Street-Level Photos Agent"
    IS_LIVE = False
    INTERVAL_SECONDS = 86400  # daily

    async def fetch(self) -> list[dict]:
        """Search Mapillary for SF street-level photos and return image records.

        Returns:
            List of records with ``image_url`` key for BaseImageAgent.
        """
        if not cfg.has_mapillary():
            logger.warning(
                "Mapillary: MAPILLARY_API_KEY not set — skipping. "
                "Register at https://www.mapillary.com/developer"
            )
            return []

        params = {
            "access_token": cfg.mapillary_api_key,
            "bbox": _SF_BBOX,
            "fields": _FIELDS,
            "limit": _LIMIT,
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    _ENDPOINT,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
            except Exception as e:
                logger.error("Mapillary: request failed: %s", e)
                return []

        images = data.get("data", [])
        records = [r for r in (self._to_record(img) for img in images) if r]
        logger.info("Mapillary: fetched %d street-level photos", len(records))
        return records

    def _to_record(self, img: dict) -> Optional[dict]:
        """Convert a raw Mapillary image dict to a normalized image record."""
        # Prefer 1024px thumb; fall back to 256px
        image_url = img.get("thumb_1024_url") or img.get("thumb_256_url", "")
        if not image_url:
            return None

        # GeoJSON Point: coordinates are [longitude, latitude]
        geometry = img.get("geometry") or {}
        coords = geometry.get("coordinates", [])
        lon = float(coords[0]) if len(coords) >= 2 else cfg.sf_center_lon
        lat = float(coords[1]) if len(coords) >= 2 else cfg.sf_center_lat

        # Metadata
        img_id = img.get("id", "")
        is_pano = img.get("is_pano", False)
        compass = img.get("compass_angle")

        # captured_at is Unix timestamp in milliseconds
        captured_ms = img.get("captured_at")
        captured_str = ""
        if captured_ms:
            try:
                captured_str = datetime.fromtimestamp(
                    captured_ms / 1000, tz=timezone.utc
                ).strftime("%Y-%m-%d")
            except (ValueError, OSError):
                pass

        content = (
            f"Mapillary street-level photo in San Francisco"
            f"{f', captured {captured_str}' if captured_str else ''}. "
            f"{'360° panorama. ' if is_pano else ''}"
            f"{f'Camera facing {compass:.0f}°.' if compass is not None else ''}"
        )

        record = self.normalize(
            source="mapillary",
            content=content,
            category="street_photo",
            title=f"SF Street View — {captured_str or 'unknown date'}",
            lat=lat,
            lon=lon,
            url=f"https://www.mapillary.com/app/?pKey={img_id}",
            raw={
                "id": img_id,
                "captured_at": captured_str,
                "is_pano": is_pano,
                "compass_angle": compass,
                "thumb_1024_url": img.get("thumb_1024_url"),
                "thumb_256_url": img.get("thumb_256_url"),
            },
        )
        record["image_url"] = image_url
        return record
