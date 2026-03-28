"""
Walking route generation via OSRM (Open Source Routing Machine).

Uses the public OSRM demo server — free, no API key required.
Routes from the SF geographic center to the nearest result coordinate.
"""

import logging
from typing import Optional

import httpx

from api.models import PathInfo

logger = logging.getLogger(__name__)

_OSRM_BASE = "https://router.project-osrm.org/route/v1/walking"
SF_LAT = 37.7749
SF_LON = -122.4194

# Maneuver type → human-readable verb
_MANEUVER_VERBS: dict[str, str] = {
    "turn": "Turn", "new name": "Continue onto", "depart": "Head",
    "arrive": "Arrive at", "merge": "Merge onto", "ramp": "Take the ramp onto",
    "on ramp": "Take the on-ramp onto", "off ramp": "Take the off-ramp onto",
    "fork": "Keep", "end of road": "Turn", "continue": "Continue on",
    "roundabout": "Enter the roundabout", "rotary": "Enter the rotary",
    "roundabout turn": "Turn at the roundabout", "notification": "Note:",
    "exit roundabout": "Exit the roundabout onto",
}

_MODIFIER_WORDS: dict[str, str] = {
    "uturn": "a U-turn", "sharp right": "sharp right", "right": "right",
    "slight right": "slight right", "straight": "straight",
    "slight left": "slight left", "left": "left", "sharp left": "sharp left",
}


def _step_instruction(step: dict) -> Optional[str]:
    """Build a human-readable instruction from an OSRM step dict."""
    maneuver = step.get("maneuver", {})
    mtype = maneuver.get("type", "")
    modifier = maneuver.get("modifier", "")
    name = step.get("name", "")

    verb = _MANEUVER_VERBS.get(mtype, "Continue")
    mod_word = _MODIFIER_WORDS.get(modifier, modifier)

    if mtype == "depart":
        direction = f" {mod_word}" if mod_word else ""
        return f"Head{direction}{f' on {name}' if name else ''}"
    if mtype == "arrive":
        return "Arrive at your destination"
    if mod_word and name:
        return f"{verb} {mod_word} onto {name}"
    if name:
        return f"{verb} onto {name}"
    if mod_word:
        return f"{verb} {mod_word}"
    return None


async def get_walking_path(
    dest_lat: float, dest_lon: float, timeout: float = 8.0
) -> PathInfo:
    """Get a walking route from SF center to (dest_lat, dest_lon).

    Args:
        dest_lat: Destination latitude.
        dest_lon: Destination longitude.
        timeout: Request timeout in seconds.

    Returns:
        PathInfo with duration, distance, and step-by-step instructions.
        Returns an empty PathInfo on any network or parsing error.
    """
    url = f"{_OSRM_BASE}/{SF_LON},{SF_LAT};{dest_lon},{dest_lat}"
    params = {"steps": "true", "overview": "false"}

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning("OSRM routing failed: %s", e)
        return PathInfo(mode="walking")

    try:
        route = data["routes"][0]
        leg = route["legs"][0]

        duration_sec = leg.get("duration", 0)
        duration_min = max(1, round(duration_sec / 60))

        distance_m = leg.get("distance", 0)
        distance_mi = distance_m * 0.000621371

        steps: list[str] = []
        for step in leg.get("steps", []):
            instruction = _step_instruction(step)
            if instruction:
                steps.append(instruction)

        return PathInfo(
            mode="walking",
            duration=f"{duration_min} min",
            distance=f"{distance_mi:.1f} mi",
            steps=steps[:8],  # cap at 8 steps for readability
        )
    except (KeyError, IndexError, TypeError) as e:
        logger.warning("OSRM response parse error: %s", e)
        return PathInfo(mode="walking")
