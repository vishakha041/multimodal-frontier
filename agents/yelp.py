"""
Yelp Fusion API scraper agent.

Fetches businesses and venues in San Francisco related to activities,
entertainment, food, and nightlife — explicitly excluding trade services
(plumbers, electricians, etc.).

Also stores the Yelp cover photo for each business as a URL reference
(not bytes — Yelp's Terms of Service prohibit caching their images).
The URL is logged alongside the text metadata so ApertureDB can
reference the image without hosting it.

Requires: YELP_API_KEY environment variable.
Get your key at: https://docs.developer.yelp.com/
Cadence: daily (static agent)
"""

import logging

import aiohttp

from agents.base import BaseImageAgent
from config import cfg

logger = logging.getLogger(__name__)

_ENDPOINT = "https://api.yelp.com/v3/businesses/search"

# Yelp category aliases that represent "things to do" in SF.
# See full list: https://docs.developer.yelp.com/docs/resources-categories
_ACTIVITY_CATEGORIES = [
    "arts",           # Arts & Entertainment (museums, galleries, theatres)
    "active",         # Active Life (hiking, climbing, yoga, etc.)
    "nightlife",      # Nightlife (bars, clubs, comedy)
    "restaurants",    # Restaurants (food experiences)
    "food",           # Food (markets, coffee, desserts)
    "tours",          # Tours & Experiences
    "festivals",      # Festivals & Events
    "beaches",        # Beaches & Parks
    "amusementparks", # Amusement Parks
    "aquariums",      # Aquariums
    "zoos",           # Zoos
    "botanicalgardens", # Gardens
    "sportsteams",    # Spectator Sports
    "movietheaters",  # Movie Theaters
]

# Yelp limits: 50 results per request, max offset 1000
_LIMIT = 50
_MAX_RESULTS = 200  # 4 pages — enough for a demo


class YelpAgent(BaseImageAgent):
    """Scrapes Yelp for SF activity businesses using the Fusion API.

    Iterates over activity categories and fetches the top-rated venues
    near SF center. Deduplicates by Yelp business ID across categories.

    Each record includes the Yelp cover photo as a URL reference.
    Image bytes are never downloaded — Yelp's ToS prohibits caching
    their images, so ``store_image_bytes`` is always False here regardless
    of the global ``STORE_IMAGE_BYTES`` setting.

    Attributes:
        AGENT_ID: Unique identifier in aperture-nexus.
        IS_LIVE: False — runs once daily.
    """

    @property
    def store_image_bytes(self) -> bool:
        """Always False — Yelp ToS prohibits downloading and caching their images."""
        return False

    AGENT_ID = "yelp-agent"
    AGENT_NAME = "Yelp SF Activities Agent"
    IS_LIVE = False
    INTERVAL_SECONDS = 86400  # daily

    async def fetch(self) -> list[dict]:
        """Fetch top SF activity businesses from Yelp Fusion API.

        Returns:
            Deduplicated list of normalized business records.

        Raises:
            RuntimeError: If YELP_API_KEY is not configured.
        """
        if not cfg.has_yelp():
            logger.warning("Yelp: YELP_API_KEY not set — skipping")
            return []

        headers = {
            "Authorization": f"Bearer {cfg.yelp_api_key}",
            "Accept": "application/json",
        }
        seen_ids: set[str] = set()
        records: list[dict] = []

        async with aiohttp.ClientSession(headers=headers) as session:
            for category in _ACTIVITY_CATEGORIES:
                batch = await self._fetch_category(session, category, seen_ids)
                records.extend(batch)
                if len(records) >= _MAX_RESULTS:
                    break

        logger.info("Yelp: fetched %d unique businesses", len(records))
        return records

    async def _fetch_category(
        self,
        session: aiohttp.ClientSession,
        category: str,
        seen_ids: set[str],
    ) -> list[dict]:
        """Fetch one page of businesses for a given Yelp category."""
        params = {
            "latitude": cfg.sf_center_lat,
            "longitude": cfg.sf_center_lon,
            "radius": min(cfg.sf_radius_meters, 40000),  # Yelp max is 40000m
            "categories": category,
            "limit": _LIMIT,
            "sort_by": "rating",
            "locale": "en_US",
        }
        try:
            async with session.get(
                _ENDPOINT, params=params, timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
        except Exception as e:
            logger.warning("Yelp: failed to fetch category=%s: %s", category, e)
            return []

        results = []
        for biz in data.get("businesses", []):
            biz_id = biz.get("id", "")
            if biz_id in seen_ids:
                continue
            seen_ids.add(biz_id)
            results.append(self._to_record(biz, category))
        return results

    def _to_record(self, biz: dict, category: str) -> dict:
        """Convert a raw Yelp business dict to a normalized record."""
        coords = biz.get("coordinates", {})
        location = biz.get("location", {})
        address_parts = [
            location.get("address1", ""),
            location.get("city", ""),
            location.get("state", ""),
        ]
        address = ", ".join(p for p in address_parts if p)

        rating = biz.get("rating", "N/A")
        review_count = biz.get("review_count", 0)
        price = biz.get("price", "")
        cats = ", ".join(c.get("title", "") for c in biz.get("categories", []))

        content = (
            f"{biz.get('name', 'Venue')} — {cats}. "
            f"Rating: {rating}/5 ({review_count} reviews). "
            f"{f'Price: {price}. ' if price else ''}"
            f"Address: {address}."
        )

        yelp_image_url = biz.get("image_url") or ""

        record = self.normalize(
            source="yelp",
            content=content,
            category=category,
            title=biz.get("name"),
            lat=coords.get("latitude"),
            lon=coords.get("longitude"),
            address=address or None,
            url=biz.get("url"),
            raw={
                "id": biz.get("id"),
                "name": biz.get("name"),
                "rating": rating,
                "review_count": review_count,
                "price": price,
                "categories": biz.get("categories"),
                "phone": biz.get("display_phone"),
                "image_url": yelp_image_url,
                "is_closed": biz.get("is_closed"),
            },
        )
        # BaseImageAgent will log this as info.log(text=metadata, image=url)
        # store_image_bytes=False ensures we pass the URL ref, never download bytes
        if yelp_image_url:
            record["image_url"] = yelp_image_url
        return record
