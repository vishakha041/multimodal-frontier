"""
SearchResult → Buckets mapping for the SF City Intelligence API.

Converts flat aperture-nexus SearchResult objects into the structured
Buckets response expected by the Lovable frontend.
"""

import math
import logging
import re
from typing import Optional

from api.models import BucketItem, Buckets

logger = logging.getLogger(__name__)

SF_LAT = 37.7749
SF_LON = -122.4194

# ---------------------------------------------------------------------------
# Category → bucket mapping
# ---------------------------------------------------------------------------

_CATEGORY_BUCKET: dict[str, Optional[str]] = {
    # food
    "restaurants": "food", "food": "food", "arts": "food",
    "tours": "food", "festivals": "food", "amusementparks": "food",
    "aquariums": "food", "zoos": "food", "movietheaters": "food",
    "sportsteams": "food",
    # coffee
    "coffee": "coffee", "cafes": "coffee",
    # drinks
    "nightlife": "drinks", "bars": "drinks", "drinks": "drinks",
    # parks / outdoors
    "active": "parks", "parks": "parks", "beaches": "parks",
    "botanicalgardens": "parks", "nature_observation": "parks",
    "geo_photo": "parks", "street_photo": "parks",
    # conditions — live road/air/transit/city data
    "air_quality": "conditions",
    "transit_alert": "conditions",
    "transit_route": "conditions",
    "traffic_incident": "conditions",
    "traffic_construction": "conditions",
    "traffic_closure": "conditions",
    "city_service": "conditions",        # SF 311 requests (potholes, blockages)
    # Reddit — keyword-classified into conditions OR activities
    "community_recommendation": None,
}

_KEYWORD_BUCKET: dict[str, list[str]] = {
    "coffee": ["coffee", "café", "cafe", "espresso", "latte", "cappuccino"],
    "drinks": ["bar", "cocktail", "beer", "wine", "brewery", "nightlife", "pub"],
    "parks":  ["park", "hike", "trail", "beach", "garden", "outdoor", "nature",
               "presidio", "golden gate", "land's end"],
    "food":   ["restaurant", "food", "eat", "brunch", "lunch", "dinner",
               "taco", "pizza", "sushi", "ramen", "burger"],
    # Reddit posts about road/outdoor conditions go here
    "conditions": ["pothole", "closure", "blocked", "closed", "accident",
                   "construction", "detour", "muni", "bus", "delay", "alert",
                   "aqi", "air quality", "smoke", "bike lane", "road work",
                   "traffic", "flood", "homeless", "safe", "unsafe"],
}

# Max items per bucket in the response
_MAX_PER_BUCKET = 5
_MAX_CONDITIONS = 8  # more conditions = richer LLM context


def _classify_by_keywords(text: str) -> Optional[str]:
    """Classify a result into a bucket using keyword matching on text."""
    lower = text.lower()
    for bucket, keywords in _KEYWORD_BUCKET.items():
        if any(kw in lower for kw in keywords):
            return bucket
    return None


def _haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles between two lat/lon points."""
    R = 3958.8  # Earth radius in miles
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def _parse_rating(text: str) -> Optional[float]:
    """Extract a numeric rating from stored text content (e.g. 'Rating: 4.5/5')."""
    m = re.search(r"[Rr]ating[:\s]+([0-9.]+)", text or "")
    if m:
        try:
            return round(float(m.group(1)), 1)
        except ValueError:
            pass
    return None


def _to_bucket_item(result) -> BucketItem:
    """Convert a SearchResult to a BucketItem."""
    meta = result.metadata or {}
    text = result.text or ""

    lat = float(meta.get("lat") or SF_LAT)
    lon = float(meta.get("lon") or SF_LON)

    # Distance — only show if not the default SF center coords
    distance_str: Optional[str] = None
    if abs(lat - SF_LAT) > 0.001 or abs(lon - SF_LON) > 0.001:
        miles = _haversine_miles(SF_LAT, SF_LON, lat, lon)
        distance_str = f"{miles:.1f} mi"

    return BucketItem(
        name=meta.get("title") or "SF Location",
        description=text[:300] if text else "A great spot in San Francisco.",
        address=meta.get("address") or None,
        rating=_parse_rating(text),
        distance=distance_str,
        image_url=meta.get("image_url") or None,
        url=meta.get("url") or None,
        source=meta.get("source") or None,
        category=meta.get("category") or None,
        lat=lat if abs(lat - SF_LAT) > 0.001 else None,
        lon=lon if abs(lon - SF_LON) > 0.001 else None,
    )


def build_buckets(results: list, query: str = "") -> Buckets:
    """Map a flat list of SearchResults into categorised Buckets.

    Activity buckets (food/coffee/drinks/parks) are filled from Yelp,
    iNaturalist, Mapillary, Wikimedia, and activity-related Reddit posts.

    The conditions bucket is filled from:
      - AirNow (air_quality) — AQI readings
      - SF 311 (city_service) — potholes, blockages, city issues
      - 511 SF Bay (transit_alert, transit_route, traffic_*) — alerts and closures
      - Reddit (community_recommendation) — posts about road/transit conditions

    Reddit posts are classified by keyword: infrastructure/transit keywords
    → conditions; food/drink/park keywords → activity buckets.

    Args:
        results: SearchResult objects from memory.search().
        query: Original user query — used to classify ambiguous results.

    Returns:
        Populated Buckets object (path is empty; caller fills it in).
    """
    buckets: dict[str, list[BucketItem]] = {
        "food": [], "coffee": [], "drinks": [], "parks": [], "conditions": []
    }
    seen_names: set[str] = set()

    for result in results:
        meta = result.metadata or {}
        category = str(meta.get("category") or "").lower()
        text = result.text or ""

        # Determine bucket from category map first
        bucket = _CATEGORY_BUCKET.get(category)

        # community_recommendation (Reddit) and unknown categories: keyword classify
        if bucket is None:
            bucket = _classify_by_keywords(f"{text} {query}")

        if bucket is None or bucket not in buckets:
            continue

        cap = _MAX_CONDITIONS if bucket == "conditions" else _MAX_PER_BUCKET
        if len(buckets[bucket]) >= cap:
            continue

        # Deduplicate by name (skip empty names — conditions often have no title)
        name = str(meta.get("title") or "")
        if name and name in seen_names:
            continue
        if name:
            seen_names.add(name)

        buckets[bucket].append(_to_bucket_item(result))

    return Buckets(
        food=buckets["food"],
        coffee=buckets["coffee"],
        drinks=buckets["drinks"],
        parks=buckets["parks"],
        conditions=buckets["conditions"],
    )


def first_coordinate(buckets: Buckets) -> Optional[tuple[float, float]]:
    """Return (lat, lon) of the first result with real coordinates, for routing."""
    for group in (buckets.food, buckets.coffee, buckets.parks, buckets.drinks,
                  buckets.conditions):
        for item in group:
            if item.lat is not None and item.lon is not None:
                return item.lat, item.lon
    return None
