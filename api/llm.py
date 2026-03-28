"""
Gemini integration for the SF City Intelligence API.

Uses Google Gemini via its OpenAI-compatible endpoint — no extra SDK
needed, the existing openai package is reused with a different base_url.

Provides two capabilities when GEMINI_API_KEY is configured:
  1. generate_chat_message() — Gemini summarises search results into a
     friendly natural-language response to the user's question.
  2. identify_image()        — Gemini Vision identifies what is in an
     uploaded image and returns a label + description.

Both functions degrade gracefully when no API key is available:
  - generate_chat_message() returns a template string.
  - identify_image() returns ("SF Location", top search result text).

Get a free key (no credit card) at: https://aistudio.google.com
"""

import base64
import logging
from typing import Optional

from api.models import Buckets

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Chat message generation
# ---------------------------------------------------------------------------

def _template_message(buckets: Buckets) -> str:
    """Build a simple template message when OpenAI is not configured."""
    parts = []
    if buckets.conditions:
        parts.append(f"{len(buckets.conditions)} live condition update(s)")
    if buckets.food:
        parts.append(f"{len(buckets.food)} food spot(s)")
    if buckets.coffee:
        parts.append(f"{len(buckets.coffee)} coffee spot(s)")
    if buckets.drinks:
        parts.append(f"{len(buckets.drinks)} drink venue(s)")
    if buckets.parks:
        parts.append(f"{len(buckets.parks)} park/outdoor location(s)")
    if parts:
        return f"Here's what I found in San Francisco: {', '.join(parts)}!"
    return "I searched our SF database but couldn't find a close match. Try a broader question!"


def _build_conditions_context(buckets: Buckets) -> str:
    """Render conditions bucket into a compact text block for the LLM prompt.

    Separates AQI readings, road/transit issues, and Reddit community
    reports so Gemini can cite them specifically in its response.
    """
    if not buckets.conditions:
        return ""

    aqi_lines, road_lines, reddit_lines, other_lines = [], [], [], []
    for item in buckets.conditions:
        src = (item.source or "").lower()
        cat = (item.category or "").lower()
        line = f"  • {item.name}: {item.description[:140]}"
        if cat == "air_quality":
            aqi_lines.append(line)
        elif src == "reddit":
            reddit_lines.append(line)
        elif cat in ("city_service", "traffic_incident", "traffic_construction",
                     "traffic_closure", "transit_alert", "transit_route"):
            road_lines.append(line)
        else:
            other_lines.append(line)

    sections = []
    if aqi_lines:
        sections.append("AIR QUALITY (AirNow):\n" + "\n".join(aqi_lines))
    if road_lines:
        sections.append("ROAD & TRANSIT CONDITIONS (511 SF Bay / SF 311):\n" + "\n".join(road_lines))
    if reddit_lines:
        sections.append("COMMUNITY REPORTS (Reddit r/sanfrancisco):\n" + "\n".join(reddit_lines))
    if other_lines:
        sections.append("OTHER CONDITIONS:\n" + "\n".join(other_lines))
    return "\n\n".join(sections)


def _gemini_client():
    """Return an AsyncOpenAI client pointed at Gemini's OpenAI-compatible endpoint."""
    from openai import AsyncOpenAI  # noqa: PLC0415
    from config import cfg
    return AsyncOpenAI(
        api_key=cfg.gemini_api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )


async def generate_chat_message(user_message: str, buckets: Buckets) -> str:
    """Generate a contextual assistant reply using Gemini.

    The prompt includes:
    - Live conditions (AQI, 311 road issues, 511 transit alerts, Reddit)
    - Activity suggestions (food/coffee/drinks/parks)
    - Walking route duration if available

    Falls back to a template message if GEMINI_API_KEY is not set.
    """
    from config import cfg  # local import — cfg loaded at call time
    if not cfg.has_gemini():
        return _template_message(buckets)

    try:
        client = _gemini_client()

        # --- Conditions context ---
        conditions_text = _build_conditions_context(buckets)

        # --- Activity context ---
        activity_lines = []
        for bucket_name, items in [
            ("food", buckets.food), ("coffee", buckets.coffee),
            ("drinks", buckets.drinks), ("parks / outdoors", buckets.parks),
        ]:
            for item in items[:2]:
                dist = f" ({item.distance})" if item.distance else ""
                activity_lines.append(
                    f"  • [{bucket_name}]{dist} {item.name}: {item.description[:120]}"
                )
        activities_text = "\n".join(activity_lines) or "  No specific activities found."

        # --- Route context ---
        route_text = ""
        if buckets.path.duration:
            route_text = (
                f"SUGGESTED ROUTE: {buckets.path.duration} walk / bike"
                f" ({buckets.path.distance or '?'})"
            )
            if buckets.path.steps:
                route_text += f" — starts: {buckets.path.steps[0]}"

        prompt = (
            f"You are a knowledgeable San Francisco city guide with access to "
            f"live city data. The user asked: \"{user_message}\"\n\n"
        )
        if conditions_text:
            prompt += f"LIVE CONDITIONS:\n{conditions_text}\n\n"
        prompt += f"NEARBY ACTIVITIES:\n{activities_text}\n\n"
        if route_text:
            prompt += f"{route_text}\n\n"
        prompt += (
            f"Write a helpful, conversational 2-3 sentence response. "
            f"If conditions data is present, lead with any safety or comfort "
            f"considerations (AQI, road closures, transit delays) before "
            f"suggesting activities. Be specific — name places and cite the "
            f"live data. Reference Reddit community reports if relevant."
        )

        response = await client.chat.completions.create(
            model=cfg.gemini_model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning("Gemini chat generation failed: %s — using template", e)
        return _template_message(buckets)


# ---------------------------------------------------------------------------
# Image identification
# ---------------------------------------------------------------------------

async def identify_image(
    image_bytes: bytes,
    fallback_results: list,
) -> tuple[str, str]:
    """Identify what is in an uploaded image using Gemini Vision.

    Args:
        image_bytes: Raw bytes of the uploaded image (JPEG/PNG/WEBP).
        fallback_results: SearchResult list — used when Gemini unavailable.

    Returns:
        (identified, description) — short label and 2-3 sentence description.
    """
    from config import cfg  # local import
    if cfg.has_gemini():
        try:
            return await _gemini_identify(image_bytes, cfg)
        except Exception as e:
            logger.warning("Gemini image identification failed: %s — using fallback", e)

    # Fallback: use top search result
    if fallback_results:
        top = fallback_results[0]
        meta = top.metadata or {}
        label = meta.get("title") or "SF Location"
        description = (top.text or "A location in San Francisco.")[:300]
        return label, description

    return "San Francisco", "An image from San Francisco."


async def _gemini_identify(image_bytes: bytes, cfg) -> tuple[str, str]:
    """Call Gemini Vision to identify the image content."""
    import json  # noqa: PLC0415
    client = _gemini_client()

    b64 = base64.b64encode(image_bytes).decode()
    # Detect MIME type from magic bytes
    mime = "image/jpeg"
    if image_bytes[:4] == b"\x89PNG":
        mime = "image/png"
    elif image_bytes[:4] in (b"RIFF", b"WEBP"):
        mime = "image/webp"

    prompt = (
        "Analyze this image and identify the San Francisco landmark, neighborhood, "
        "venue, or type of place shown. Respond ONLY with JSON in this exact format:\n"
        '{"identified": "short label", "description": "2-3 sentence description"}'
    )
    response = await client.chat.completions.create(
        model=cfg.gemini_model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ],
        }],
        max_tokens=200,
        temperature=0.3,
    )
    raw = response.choices[0].message.content.strip()
    # Strip markdown code fences if Gemini wraps the JSON
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    data = json.loads(raw.strip())
    return data["identified"], data["description"]
