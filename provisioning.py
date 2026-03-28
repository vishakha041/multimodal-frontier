"""
SF City Intelligence — Agent Provisioning Script

Registers all scraper agents as NexusUser principals in ApertureDB using
NexusAdmin. Run this ONCE before starting the agents for the first time,
or after wiping the database.

Usage:
    python provisioning.py

What it does:
  1. Connects to ApertureDB using the configured credentials
  2. Creates one NexusUser entity per agent (idempotent — skips existing ones)
  3. All agents share a single API key (printed at the end)
  4. Instructs you to add NEXUS_API_KEY=<key> to your .env file

After running:
    echo "NEXUS_API_KEY=<printed_key>" >> .env
    python main.py
"""

import logging
import sys

# Configure minimal logging before imports so config warnings are visible
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

from config import cfg  # noqa: E402 — must come after logging setup


# All agent (user_id, user_name, department) tuples to register.
# Add entries here if you create new agents.
_AGENTS = [
    ("sf311-agent",      "SF311 City Issues Agent",                "sf-scrapers"),
    ("sfmta-agent",      "SF MTA Transit Agent",                   "sf-scrapers"),
    ("reddit-agent",     "Reddit SF Community Agent",              "sf-scrapers"),
    ("yelp-agent",       "Yelp SF Activities Agent",               "sf-scrapers"),
    ("511sfbay-agent",   "511 SF Bay Live Traffic & Transit Agent", "sf-scrapers"),
    ("airnow-agent",     "AirNow SF Air Quality Agent",            "sf-scrapers"),
    ("mapillary-agent",  "Mapillary SF Street-Level Photos Agent", "sf-scrapers"),
    ("wikimedia-agent",  "Wikimedia Commons SF Images Agent",      "sf-scrapers"),
    ("inat-agent",       "iNaturalist SF Nature Observations Agent","sf-scrapers"),
]

_ORGANIZATION = "sf-city-intelligence"


def provision() -> None:
    """Register all agents and print the shared API key."""
    try:
        from aperture_nexus import NexusAdmin
        from aperture_nexus.exceptions import NexusValidationError
    except ImportError as e:
        log.error("aperture-nexus is not installed: %s", e)
        log.error("Run: pip install -e ../aperture-nexus")
        sys.exit(1)

    try:
        admin = NexusAdmin()
    except Exception as e:
        log.error("Failed to connect to ApertureDB: %s", e)
        log.error(
            "Make sure APERTUREDB_KEY (or host/port/user/password) is set in .env "
            "and ApertureDB is running."
        )
        sys.exit(1)

    import secrets
    # Generate ONE shared key for all agents (simplifies .env for the hackathon).
    # Each agent has its own user_id for attribution but shares the same secret.
    shared_key = secrets.token_urlsafe(32)

    log.info("=" * 60)
    log.info("SF City Intelligence — Agent Provisioning")
    log.info("Registering %d agent principals...", len(_AGENTS))
    log.info("=" * 60)

    created = []
    skipped = []

    for user_id, user_name, department in _AGENTS:
        try:
            # NexusAdmin.create_principal() generates its OWN random key internally.
            # We need to register with a known key — use rotate_key() after creation,
            # OR delete + re-create with the shared key via a patched flow.
            # For simplicity: create the principal (gets a random key), then
            # immediately rotate to our shared_key hash.
            admin.create_principal(
                user_id=user_id,
                user_name=user_name,
                department=department,
                organization=_ORGANIZATION,
            )
            # Rotate to the shared key so all agents authenticate with the same value
            admin.rotate_key(user_id=user_id)
            # Note: rotate_key() generates ANOTHER random key and returns it.
            # We work around this below by patching the hash directly.
            created.append(user_id)
            log.info("  ✓ Created  %s", user_id)
        except NexusValidationError as e:
            if "already exists" in str(e):
                skipped.append(user_id)
                log.info("  ~ Skipped  %s (already registered)", user_id)
            else:
                log.error("  ✗ Failed   %s: %s", user_id, e)

    # Patch all principals to use our shared key hash directly via UpdateEntity
    _patch_shared_key(admin, shared_key)

    log.info("=" * 60)
    log.info("Done. Created: %d  Skipped: %d", len(created), len(skipped))
    log.info("")
    log.info("Add the following line to your .env file:")
    log.info("")
    log.info("    NEXUS_API_KEY=%s", shared_key)
    log.info("")
    log.info("Then start the agents:  python main.py")
    log.info("=" * 60)


def _patch_shared_key(admin, shared_key: str) -> None:
    """Set all agent NexusUser entities to use the shared key hash."""
    import hashlib
    key_hash = hashlib.sha256(shared_key.encode()).hexdigest()
    for user_id, _, _ in _AGENTS:
        try:
            cmd = [{
                "UpdateEntity": {
                    "with_class": "NexusUser",
                    "constraints": {"user_id": ["==", user_id]},
                    "properties": {"api_key_hash": key_hash},
                }
            }]
            admin._db.query(cmd)
        except Exception as e:
            log.warning("Could not patch key for %s: %s", user_id, e)


if __name__ == "__main__":
    provision()
