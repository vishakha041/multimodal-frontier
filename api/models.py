"""Pydantic request/response models for the SF City Intelligence API."""

from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared bucket item
# ---------------------------------------------------------------------------

class BucketItem(BaseModel):
    """One result item inside a response bucket."""
    name: str
    description: str
    address: Optional[str] = None
    rating: Optional[float] = None
    distance: Optional[str] = None   # e.g. "0.3 mi"
    image_url: Optional[str] = None
    url: Optional[str] = None        # source page URL
    source: Optional[str] = None     # "yelp" | "reddit" | "inat" | …
    category: Optional[str] = None   # raw category from scraper
    lat: Optional[float] = None
    lon: Optional[float] = None


# ---------------------------------------------------------------------------
# Path (walking directions via OSRM)
# ---------------------------------------------------------------------------

class PathInfo(BaseModel):
    """Walking route from SF center to the closest relevant result."""
    mode: str = "walking"
    duration: Optional[str] = None   # e.g. "12 min"
    distance: Optional[str] = None   # e.g. "0.6 mi"
    steps: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Buckets
# ---------------------------------------------------------------------------

class Buckets(BaseModel):
    """Categorised result buckets returned by both endpoints."""
    food: list[BucketItem] = Field(default_factory=list)
    coffee: list[BucketItem] = Field(default_factory=list)
    drinks: list[BucketItem] = Field(default_factory=list)
    parks: list[BucketItem] = Field(default_factory=list)
    # Live conditions: AQI readings, 311 blockages, 511 alerts, Reddit reports
    conditions: list[BucketItem] = Field(default_factory=list)
    path: PathInfo = Field(default_factory=PathInfo)


# ---------------------------------------------------------------------------
# /chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str = Field(..., examples=["Where can I find the best coffee near me?"])
    email: str = Field(..., examples=["user@example.com"])


class ChatResponse(BaseModel):
    message: str
    buckets: Buckets


# ---------------------------------------------------------------------------
# /image
# ---------------------------------------------------------------------------

class ImageResponse(BaseModel):
    description: str          # 2-3 sentence description of what's in the image
    identified: str           # short label e.g. "Golden Gate Bridge"
    buckets: Buckets
