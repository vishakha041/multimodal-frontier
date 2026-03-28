"""
SF MTA scraper agent.

Provides Muni route information for the SF city intelligence demo.

Note on data sources: data.sfmta.com does not exist as a hostname.
Real-time service alerts for SFMTA are already covered by the 511 SF Bay
agent (FiveOneOneAgent). This agent focuses on static route catalogue data
which is stable enough to hardcode for the hackathon demo.

For future production use, SFMTA GTFS static feeds are available at:
  https://www.sfmta.com/reports/gtfs-transit-data (ZIP download)

Cadence: daily (static agent)
"""

import logging

from agents.base import BaseAgent

logger = logging.getLogger(__name__)

# Comprehensive Muni route catalogue used when no live feed is available.
# Covers all major lines a visitor or local would use for activities in SF.
_MUNI_ROUTES = [
    ("F",          "Market & Wharves Historic Streetcar",        "streetcar",
     "Historic F-Market streetcar running from Castro to Fisherman's Wharf along Market St."),
    ("N",          "Judah Metro",                                 "metro",
     "Runs from Caltrain/4th & King through downtown tunnel to Ocean Beach."),
    ("J",          "Church Metro",                                "metro",
     "Connects Balboa Park to Embarcadero via Noe Valley and the Mission."),
    ("K/T",        "Ingleside / Third Street Metro",              "metro",
     "Links Balboa Park, Chinatown-Rose Pak, and Sunnydale via downtown."),
    ("L",          "Taraval Metro",                               "metro",
     "Runs from West Portal through the Sunset to SF Zoo and Ocean Beach."),
    ("M",          "Ocean View Metro",                            "metro",
     "Connects Embarcadero to Balboa Park via West Portal and Oceanview."),
    ("38",         "Geary Rapid Bus",                             "bus",
     "Major east-west corridor from Transbay Terminal to Ocean Beach via Geary Blvd."),
    ("49",         "Van Ness / Mission Rapid Bus",                "bus",
     "North-south spine from Fisherman's Wharf to Bayshore via Van Ness and Mission."),
    ("1",          "California Bus",                              "bus",
     "Runs along California St from the Ferry Building to Ocean Beach."),
    ("8",          "Bayshore Bus",                                "bus",
     "Connects the Ferry Building, SoMa, Caltrain, and Bayshore."),
    ("Powell-Hyde",    "Cable Car — Powell-Hyde",                 "cable_car",
     "Iconic cable car from Powell & Market to Aquatic Park near Ghirardelli Square."),
    ("Powell-Mason",   "Cable Car — Powell-Mason",                "cable_car",
     "Cable car from Powell & Market to Bay Street at Fisherman's Wharf."),
    ("California St",  "Cable Car — California Street",           "cable_car",
     "Cable car along California St between the Financial District and Van Ness."),
    ("BART",       "Bay Area Rapid Transit",                      "rail",
     "BART serves SF at Embarcadero, Montgomery, Civic Center, 16th St, 24th St, Balboa Park, and Glen Park."),
]


class SFMTAAgent(BaseAgent):
    """Returns SFMTA Muni route catalogue for the SF city intelligence demo.

    Uses a curated static route list rather than a live API endpoint.
    Real-time SFMTA service alerts are covered by FiveOneOneAgent.

    Attributes:
        AGENT_ID: Unique identifier in aperture-nexus.
        IS_LIVE: False — runs once daily.
    """

    AGENT_ID = "sfmta-agent"
    AGENT_NAME = "SF MTA Transit Agent"
    IS_LIVE = False
    INTERVAL_SECONDS = 86400  # daily

    async def fetch(self) -> list[dict]:
        """Return normalized records for all major Muni lines."""
        records = [self._to_record(*row) for row in _MUNI_ROUTES]
        logger.info("SFMTA: returning %d static route records", len(records))
        return records

    def _to_record(
        self,
        route_id: str,
        name: str,
        route_type: str,
        description: str,
    ) -> dict:
        content = (
            f"SFMTA {route_type.replace('_', ' ').title()} — "
            f"{route_id}: {name}. {description}"
        )
        return self.normalize(
            source="sfmta",
            content=content,
            category="transit_route",
            title=f"Muni {route_id} — {name}",
            url=f"https://www.sfmta.com",
            raw={"route_id": route_id, "route_name": name, "route_type": route_type},
        )
