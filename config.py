"""
Configuration loader for the SF City Intelligence agent scrapers.

All values are read from environment variables (populated from .env).
No credentials are ever hardcoded here.

Usage:
    from config import cfg
    print(cfg.yelp_api_key)
    print(cfg.sf_center_lat)
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Resolve .env relative to this file so the process can be started from any CWD
_ENV_FILE = Path(__file__).parent / ".env"


def _load_env() -> None:
    """Load .env file if present. Silently skips if absent."""
    if _ENV_FILE.is_file():
        load_dotenv(_ENV_FILE)
        logger.debug("Loaded env from %s", _ENV_FILE)
    else:
        logger.debug(".env not found at %s — relying on shell environment", _ENV_FILE)


@dataclass(frozen=True)
class AgentConfig:
    """Typed, immutable configuration for all scraper agents.

    Loaded once at import time from environment variables. All API keys
    are Optional — agents that require a missing key will log a warning
    and skip gracefully rather than crash the whole process.

    Attributes:
        yelp_api_key: Yelp Fusion API key.
        five_one_one_api_key: 511 SF Bay API key.
        airnow_api_key: AirNow API key.
        reddit_client_id: Reddit OAuth2 client ID.
        reddit_client_secret: Reddit OAuth2 client secret.
        reddit_user_agent: User-agent string for Reddit API requests.
        sf_center_lat: Latitude of the SF geographic center.
        sf_center_lon: Longitude of the SF geographic center.
        sf_radius_meters: Search radius around the center (meters).
        live_interval_seconds: Polling interval for live agents.
        static_interval_seconds: Polling interval for static agents.
        log_level: Logging level for the scraper process.
        nexus_department: aperture-nexus department for all agents.
        nexus_organization: aperture-nexus organization for all agents.
    """

    # --- aperture-nexus auth ---
    nexus_api_key: Optional[str]   # shared key used by all agents to authenticate

    # --- Gemini (optional — enables richer chat responses + image recognition) ---
    gemini_api_key: Optional[str]
    gemini_model: str              # default: gemini-2.0-flash

    # --- REST API server ---
    api_host: str
    api_port: int

    # --- API keys (all optional so missing keys don't crash on import) ---
    yelp_api_key: Optional[str]
    five_one_one_api_key: Optional[str]
    airnow_api_key: Optional[str]
    mapillary_api_key: Optional[str]
    # Reddit public JSON API needs only a User-Agent — no credentials required
    reddit_user_agent: str

    # --- Image storage behaviour ---
    store_image_bytes: bool  # True → download & store bytes; False → store URL ref

    # --- Geographic anchor ---
    sf_center_lat: float
    sf_center_lon: float
    sf_radius_meters: int

    # --- Scheduler ---
    live_interval_seconds: int
    static_interval_seconds: int

    # --- Logging ---
    log_level: str

    # --- aperture-nexus identity ---
    nexus_department: str
    nexus_organization: str

    def has_yelp(self) -> bool:
        return bool(self.yelp_api_key)

    def has_511(self) -> bool:
        return bool(self.five_one_one_api_key)

    def has_airnow(self) -> bool:
        return bool(self.airnow_api_key)

    def has_nexus(self) -> bool:
        return bool(self.nexus_api_key)

    def has_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    def has_mapillary(self) -> bool:
        return bool(self.mapillary_api_key)


def _load() -> AgentConfig:
    _load_env()

    def _int(key: str, default: int) -> int:
        raw = os.environ.get(key, "")
        try:
            return int(raw) if raw.strip() else default
        except ValueError:
            logger.warning("Invalid value for %s=%r — using default %d", key, raw, default)
            return default

    def _float(key: str, default: float) -> float:
        raw = os.environ.get(key, "")
        try:
            return float(raw) if raw.strip() else default
        except ValueError:
            logger.warning("Invalid value for %s=%r — using default %f", key, raw, default)
            return default

    def _opt(key: str) -> Optional[str]:
        val = os.environ.get(key, "").strip()
        return val if val else None

    def _bool(key: str, default: bool) -> bool:
        raw = os.environ.get(key, "").strip().lower()
        if raw in ("true", "1", "yes"):
            return True
        if raw in ("false", "0", "no"):
            return False
        return default

    return AgentConfig(
        yelp_api_key=_opt("YELP_API_KEY"),
        five_one_one_api_key=_opt("FIVE_ONE_ONE_API_KEY"),
        airnow_api_key=_opt("AIRNOW_API_KEY"),
        nexus_api_key=_opt("NEXUS_API_KEY"),
        gemini_api_key=_opt("GEMINI_API_KEY"),
        gemini_model=os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
        api_host=os.environ.get("API_HOST", "0.0.0.0"),
        api_port=_int("API_PORT", 8000),
        mapillary_api_key=_opt("MAPILLARY_API_KEY"),
        reddit_user_agent=os.environ.get(
            "REDDIT_USER_AGENT", "sf-city-intelligence-bot/1.0"
        ),
        store_image_bytes=_bool("STORE_IMAGE_BYTES", True),
        sf_center_lat=_float("SF_CENTER_LAT", 37.7749),
        sf_center_lon=_float("SF_CENTER_LON", -122.4194),
        sf_radius_meters=_int("SF_RADIUS_METERS", 40000),  # ~25 miles covers all of SF
        live_interval_seconds=_int("LIVE_INTERVAL_SECONDS", 300),   # 5 min
        static_interval_seconds=_int("STATIC_INTERVAL_SECONDS", 86400),  # 24 h
        log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        nexus_department="sf-scrapers",
        nexus_organization="sf-city-intelligence",
    )


# Singleton — loaded once when this module is first imported.
cfg: AgentConfig = _load()
