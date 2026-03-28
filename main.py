"""
SF City Intelligence — Agent Scraper Entry Point

Wires together config, all six scraper agents, and the async scheduler.
Run from the multimodal-frontier directory:

    python main.py

Or with overridden intervals for quick testing:

    LIVE_INTERVAL_SECONDS=30 STATIC_INTERVAL_SECONDS=60 python main.py

Press Ctrl+C to stop all agents gracefully.
"""

import asyncio
import logging
import sys

from config import cfg
from agents.sf311 import SF311Agent
from agents.yelp import YelpAgent
from agents.reddit import RedditAgent
from agents.sf_mta import SFMTAAgent
from agents.five_one_one import FiveOneOneAgent
from agents.airnow import AirNowAgent
from agents.mapillary import MapillaryAgent
from agents.wikimedia import WikimediaAgent
from agents.inat import iNaturalistAgent
from scheduler import Scheduler


def _configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, cfg.log_level, logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # Quiet noisy third-party libraries
    for lib in ("aiohttp", "urllib3", "praw"):
        logging.getLogger(lib).setLevel(logging.WARNING)


def _build_agents() -> list:
    """Instantiate all agents and log which ones have API keys configured."""
    log = logging.getLogger(__name__)
    agents = []

    # --- Public agents (no key needed) ---
    agents.append(SF311Agent())
    agents.append(SFMTAAgent())

    # --- Reddit (no credentials required — public JSON API) ---
    agents.append(RedditAgent())

    # --- Yelp (free key required) ---
    agents.append(YelpAgent())
    if not cfg.has_yelp():
        logging.getLogger(__name__).warning(
            "Yelp: YELP_API_KEY not set in .env — "
            "Yelp agent will skip. Register at https://docs.developer.yelp.com/"
        )

    # --- 511 SF Bay (free key required) ---
    agents.append(FiveOneOneAgent())
    if not cfg.has_511():
        logging.getLogger(__name__).warning(
            "511 SF Bay: FIVE_ONE_ONE_API_KEY not set in .env — "
            "511 agent will skip. Register at https://511.org/open-data/token"
        )

    # --- AirNow (free key required) ---
    agents.append(AirNowAgent())
    if not cfg.has_airnow():
        logging.getLogger(__name__).warning(
            "AirNow: AIRNOW_API_KEY not set in .env — "
            "AirNow agent will skip. Register at https://docs.airnowapi.org/"
        )

    # --- Image agents ---
    log.info(
        "Image storage mode: %s",
        "bytes (full multimodal)" if cfg.store_image_bytes else "URL reference only",
    )
    log.info("Note: Yelp photos always stored as URL refs (ToS restriction)")

    # Mapillary — street-level geo-tagged photos (free key required)
    agents.append(MapillaryAgent())
    if not cfg.has_mapillary():
        log.warning(
            "Mapillary: MAPILLARY_API_KEY not set in .env — "
            "Mapillary agent will skip. "
            "Register at https://www.mapillary.com/developer"
        )

    # Wikimedia Commons — landmark photos (no key needed)
    agents.append(WikimediaAgent())

    # iNaturalist — nature/park observation photos (no key needed)
    agents.append(iNaturalistAgent())

    return agents


async def main() -> None:
    _configure_logging()
    log = logging.getLogger(__name__)

    log.info("=" * 60)
    log.info("SF City Intelligence — Agent Scraper")
    log.info("SF center: lat=%.4f, lon=%.4f", cfg.sf_center_lat, cfg.sf_center_lon)
    log.info("Live interval:   %ds", cfg.live_interval_seconds)
    log.info("Static interval: %ds", cfg.static_interval_seconds)
    log.info("=" * 60)

    agents = _build_agents()
    log.info("Agents loaded: %d total", len(agents))
    for agent in agents:
        cadence = f"every {agent.INTERVAL_SECONDS}s" if agent.IS_LIVE else "daily"
        log.info("  %-35s  [%s]", agent.AGENT_NAME, cadence)

    scheduler = Scheduler(
        agents,
        live_interval=cfg.live_interval_seconds,
        static_interval=cfg.static_interval_seconds,
    )

    log.info("Starting scheduler — press Ctrl+C to stop")
    await scheduler.run()
    log.info("Scheduler stopped. Goodbye.")


if __name__ == "__main__":
    asyncio.run(main())
