"""
BaseAgent — shared infrastructure for all SF City Intelligence scrapers.

Every scraper agent inherits from BaseAgent and implements only `fetch()`.
BaseAgent handles:
  - aperture-nexus Principal identity (one per agent class)
  - Context creation per scrape session
  - Normalization of scraped records to a shared schema
  - Committing to ApertureDB via aperture-nexus Memory
  - Graceful degradation when Memory is unavailable (logs only)

Normalized record schema (all fields except source/timestamp are optional):
    {
        "source":    str,          # e.g. "sf311", "yelp", "airnow"
        "timestamp": str,          # ISO-8601 UTC
        "category":  str,          # domain category, e.g. "air_quality"
        "title":     str | None,
        "content":   str,          # human-readable summary / description
        "location": {
            "lat": float, "lon": float,
            "address": str | None, "city": str, "state": str
        },
        "url":       str | None,
        "raw":       dict | None,  # original API payload
    }
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Optional

import asyncio
import aiohttp

from aperture_nexus.auth import Principal
from aperture_nexus.context import Context
from aperture_nexus.information import Information

logger = logging.getLogger(__name__)

# Geographic center of San Francisco
SF_CENTER = {"lat": 37.7749, "lon": -122.4194, "city": "San Francisco", "state": "CA"}


class BaseAgent(ABC):
    """Abstract base class for all SF City Intelligence scraper agents.

    Subclasses must define the class-level constants and implement `fetch()`.

    Class constants:
        AGENT_ID (str): Unique stable identifier, e.g. "sf311-agent".
        AGENT_NAME (str): Human-readable name for logs/UI.
        IS_LIVE (bool): True → poll every INTERVAL_SECONDS. False → run daily.
        INTERVAL_SECONDS (int): Only used when IS_LIVE is True.

    Example:
        class MyAgent(BaseAgent):
            AGENT_ID = "my-source-agent"
            AGENT_NAME = "My Source Agent"
            IS_LIVE = False
            INTERVAL_SECONDS = 300

            async def fetch(self) -> list[dict]:
                data = await self._get("https://api.example.com/data")
                return [
                    self.normalize(source="my-source", content=str(item),
                                   category="events", raw=item)
                    for item in data
                ]
    """

    AGENT_ID: str
    AGENT_NAME: str
    IS_LIVE: bool
    INTERVAL_SECONDS: int = 300

    _DEPARTMENT = "sf-scrapers"
    _ORGANIZATION = "sf-city-intelligence"

    def __init__(self) -> None:
        # Start with a local Principal; upgraded to an authenticated one lazily
        # on first commit if NEXUS_API_KEY is configured (see _get_principal()).
        self._local_principal = Principal(
            user_id=self.AGENT_ID,
            user_name=self.AGENT_NAME,
            department=self._DEPARTMENT,
            organization=self._ORGANIZATION,
        )
        self.principal: Principal = self._local_principal
        self._memory: Any = None  # lazy-loaded aperture_nexus.Memory
        self._authenticated = False
        logger.debug("Agent initialised: %s", self.AGENT_ID)

    # ------------------------------------------------------------------
    # aperture-nexus integration
    # ------------------------------------------------------------------

    @property
    def memory(self) -> Any:
        """Lazy-load aperture_nexus.Memory and authenticate the agent principal.

        On first access, instantiates Memory() and — if NEXUS_API_KEY is set —
        calls memory.authenticate() to exchange the shared key for a validated
        Principal backed by a NexusUser entity in ApertureDB.

        Falls back to the local (unauthenticated) Principal if the key is
        missing or authentication fails, so agents can still commit without
        running provisioning (useful during development).
        """
        if self._memory is None:
            try:
                from aperture_nexus import Memory  # noqa: PLC0415
                from config import cfg             # noqa: PLC0415
                self._memory = Memory()
                logger.info("%s: connected to aperture-nexus Memory", self.AGENT_ID)
                if cfg.has_nexus() and not self._authenticated:
                    try:
                        self.principal = self._memory.authenticate(
                            user_id=self.AGENT_ID,
                            api_key=cfg.nexus_api_key,
                        )
                        self._authenticated = True
                        logger.info("%s: authenticated principal %r", self.AGENT_ID, self.AGENT_ID)
                    except Exception as auth_err:
                        logger.warning(
                            "%s: authentication failed — using local principal. "
                            "Run provisioning.py first. Error: %s",
                            self.AGENT_ID, auth_err,
                        )
            except (ImportError, Exception) as e:
                logger.warning(
                    "%s: aperture-nexus Memory unavailable — records will be "
                    "logged but not stored. Reason: %s",
                    self.AGENT_ID, e,
                )
        return self._memory

    def _make_context(self) -> Context:
        """Create a Context for this scrape session (one session per agent per day)."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return Context(
            principal=self.principal,
            session_name=f"{self.AGENT_ID}-{date_str}",
            purpose=f"Scraping {self.AGENT_NAME} data for SF city intelligence",
            organization=self._ORGANIZATION,
            department=self._DEPARTMENT,
        )

    def commit_records(self, records: list[dict]) -> None:
        """Normalize and commit scraped records to aperture-nexus.

        Each record is serialized as JSON text and logged to an Information
        buffer, then committed as a single Memory entry. Falls back to
        debug-logging when Memory is not available.

        Args:
            records: List of dicts produced by fetch() and normalize().
        """
        if not records:
            logger.debug("%s: no records to commit", self.AGENT_ID)
            return

        ctx = self._make_context()
        info = Information(context_id=ctx.id)
        for record in records:
            info.log(
                text=_record_text(record),
                metadata=_record_metadata(record),
            )

        mem = self.memory
        if mem is not None:
            try:
                mem.process_and_commit(ctx, info)
                logger.info("%s: committed %d records (with embeddings)", self.AGENT_ID, len(records))
            except Exception as e:
                logger.error("%s: process_and_commit failed: %s", self.AGENT_ID, e)
        else:
            logger.info(
                "%s: [no-storage] would have committed %d records",
                self.AGENT_ID, len(records),
            )
            for record in records:
                logger.debug("  record: %s", record.get("title") or record.get("content", "")[:80])

    # ------------------------------------------------------------------
    # Record normalization
    # ------------------------------------------------------------------

    @staticmethod
    def normalize(
        source: str,
        content: str,
        category: str,
        title: Optional[str] = None,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        address: Optional[str] = None,
        url: Optional[str] = None,
        raw: Optional[dict] = None,
    ) -> dict:
        """Build a normalized record dict with the shared SF-data schema.

        Args:
            source: Data source identifier, e.g. "sf311", "yelp".
            content: Human-readable description or summary.
            category: Domain category, e.g. "incident", "restaurant", "air_quality".
            title: Optional short title or name.
            lat: Latitude. Defaults to SF center.
            lon: Longitude. Defaults to SF center.
            address: Street address or None.
            url: Canonical URL for more information.
            raw: Original API payload dict (stored as-is for traceability).

        Returns:
            Normalized record dict ready for info.log(text=...).
        """
        return {
            "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": category,
            "title": title,
            "content": content,
            "location": {
                "lat": lat if lat is not None else SF_CENTER["lat"],
                "lon": lon if lon is not None else SF_CENTER["lon"],
                "address": address,
                "city": SF_CENTER["city"],
                "state": SF_CENTER["state"],
            },
            "url": url,
            "raw": raw,
        }

    # ------------------------------------------------------------------
    # Lifecycle — implemented by scheduler
    # ------------------------------------------------------------------

    @abstractmethod
    async def fetch(self) -> list[dict]:
        """Fetch data from the source API and return normalized records.

        Returns:
            List of dicts produced via self.normalize(...).

        Raises:
            Any exception — BaseAgent.run_once() catches and logs all errors.
        """
        ...

    async def run_once(self) -> None:
        """Run one full fetch-and-commit cycle. Safe to call from the scheduler."""
        logger.info("%s: starting fetch", self.AGENT_ID)
        try:
            records = await self.fetch()
            await self._async_commit_records(records)
        except Exception as e:
            logger.error("%s: fetch failed: %s", self.AGENT_ID, e, exc_info=True)

    async def _async_commit_records(self, records: list[dict]) -> None:
        """Async wrapper: run the blocking process_and_commit in a thread executor.

        process_and_commit() is CPU-heavy (CLIP embedding) and does blocking
        network I/O (ApertureDB writes). Running it in a thread keeps the
        event loop free so Ctrl-C / task cancellation responds instantly.
        """
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.commit_records, records)


class BaseImageAgent(BaseAgent, ABC):
    """BaseAgent variant for agents that scrape geo-tagged images or videos.

    Extends BaseAgent with image-aware commit logic:
      - Each record returned by fetch() must include an ``image_url`` key.
      - When ``store_image_bytes=True`` (default), bytes are downloaded and
        stored in ApertureDB as an Image object alongside the text metadata.
      - When ``store_image_bytes=False``, the URL is passed directly —
        aperture-nexus stores it as a URL reference resolved at commit time.

    Subclasses implement ``fetch()`` exactly as with BaseAgent, but each
    returned record dict should contain an ``image_url`` field.

    Example record from fetch():
        {
            "source": "flickr",
            "image_url": "https://live.staticflickr.com/...",
            "title": "Golden Gate at sunset",
            ...   # all standard normalize() fields
        }
    """

    @property
    def store_image_bytes(self) -> bool:
        """True if image bytes should be downloaded and stored in ApertureDB."""
        from config import cfg  # local import to avoid circular deps at module load
        return cfg.store_image_bytes

    @property
    def _download_headers(self) -> dict:
        """HTTP headers used when downloading image bytes.

        Subclasses can override to supply a stricter User-Agent required by
        certain CDNs (e.g. Wikimedia Commons requires a policy-compliant string).
        """
        return {"User-Agent": "SF-City-Intelligence/1.0 (educational hackathon)"}

    async def run_once(self) -> None:
        """Fetch records and commit each as text + image to aperture-nexus."""
        logger.info("%s: starting image fetch", self.AGENT_ID)
        try:
            records = await self.fetch()
            if records:
                await self._commit_image_records(records)
        except Exception as e:
            logger.error("%s: fetch failed: %s", self.AGENT_ID, e, exc_info=True)

    async def _commit_image_records(self, records: list[dict]) -> None:
        """Download images (if configured) and commit text+image pairs."""
        ctx = self._make_context()
        info = Information(context_id=ctx.id)

        async with aiohttp.ClientSession(headers=self._download_headers) as session:
            for record in records:
                image_url = record.pop("image_url", None)
                text = _record_text(record)
                meta = _record_metadata(record)

                if image_url:
                    meta["image_url"] = image_url[:500]

                if not image_url:
                    info.log(text=text, metadata=meta)
                    continue

                if self.store_image_bytes:
                    image_data = await self._download_image(session, image_url)
                    if image_data:
                        info.log(text=text, image=image_data, metadata=meta)
                    else:
                        # fallback to URL ref if download failed
                        info.log(text=text, image=image_url, metadata=meta)
                else:
                    # aperture-nexus accepts https:// URLs directly
                    info.log(text=text, image=image_url, metadata=meta)

        mem = self.memory
        if mem is not None:
            try:
                # Run in executor: CLIP embedding + DB write are blocking ops
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, mem.process_and_commit, ctx, info)
                logger.info("%s: committed %d image records (with embeddings)", self.AGENT_ID, len(records))
            except Exception as e:
                logger.error("%s: process_and_commit failed: %s", self.AGENT_ID, e)
        else:
            logger.info(
                "%s: [no-storage] would have committed %d image records",
                self.AGENT_ID, len(records),
            )

    @staticmethod
    async def _download_image(
        session: aiohttp.ClientSession, url: str
    ) -> Optional[bytes]:
        """Download image bytes from a URL. Returns None on any failure."""
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                resp.raise_for_status()
                content_type = resp.headers.get("Content-Type", "")
                if not content_type.startswith("image/"):
                    logger.debug("Skipping non-image content-type %r at %s", content_type, url)
                    return None
                return await resp.read()
        except Exception as e:
            logger.warning("Image download failed (%s): %s", url, e)
            return None


# ---------------------------------------------------------------------------
# Module-level helpers used by both BaseAgent and BaseImageAgent
# ---------------------------------------------------------------------------

def _record_text(record: dict) -> str:
    """Build the text string stored & embedded for a normalized record.

    Combines title and content into a single searchable string.
    The ``raw`` payload is intentionally excluded — it lives in ``metadata``
    as a URL reference or is omitted to keep the text clean for embedding.
    """
    parts = []
    if record.get("title"):
        parts.append(record["title"])
    if record.get("content"):
        parts.append(record["content"])
    return "\n".join(parts) if parts else "(no content)"


def _record_metadata(record: dict) -> dict:
    """Extract flat, ApertureDB-compatible metadata from a normalized record.

    Only str / int / float / bool values are permitted by aperture-nexus.
    Nested dicts (location, raw) are flattened to top-level scalar fields.
    """
    loc = record.get("location") or {}
    return {
        "source":   str(record.get("source") or ""),
        "category": str(record.get("category") or ""),
        "title":    str(record.get("title") or "")[:200],
        "url":      str(record.get("url") or "")[:500],
        "lat":      float(loc.get("lat") or SF_CENTER["lat"]),
        "lon":      float(loc.get("lon") or SF_CENTER["lon"]),
        "address":  str(loc.get("address") or "")[:200],
    }
