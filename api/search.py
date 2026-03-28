"""
Memory search helpers for the SF City Intelligence API.

All modalities (text and image) share the same CLIP embedding space
(ViT-B/16). This means a plain text query like "I want to ride my bike"
can be used to search BOTH the text DescriptorSet (AirNow AQI entries,
511 alerts, Reddit posts, 311 reports) AND the image DescriptorSet
(Mapillary street photos, Wikimedia landmarks, iNaturalist observations)
with a single CLIP vector — no separate model call needed.

search_all_modalities() is the primary entry point for /chat queries.
search_image_bytes() is used by /image to find visually similar content.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Singleton Memory
# ---------------------------------------------------------------------------

_memory: Any = None  # aperture_nexus.Memory


def get_memory() -> Any:
    """Return the shared Memory instance, initialising it on first call."""
    global _memory
    if _memory is None:
        try:
            from aperture_nexus import Memory  # noqa: PLC0415
            _memory = Memory()
            logger.info("API: connected to aperture-nexus Memory")
        except Exception as e:
            logger.error("API: could not connect to Memory: %s", e)
            raise
    return _memory


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------

def search_text(query: str, k: int = 30) -> list:
    """Semantic text search against the nexus_text DescriptorSet.

    Args:
        query: Natural-language query string.
        k: Maximum number of results.

    Returns:
        List of SearchResult ordered by descending similarity score.
    """
    try:
        results = get_memory().search(query=query, k=k)
        logger.info("search_text(%r): %d results", query[:60], len(results))
        return results
    except Exception as e:
        logger.error("search_text failed: %s", e)
        return []


def search_all_modalities(query: str, k_per_modality: int = 30) -> list:
    """Cross-modal semantic search using a single CLIP text embedding.

    Because CLIP shares one embedding space for text and images, the same
    vector produced from a text query can search both modalities:

      "I want to ride my bike today"
          → nexus_text__ViT-B/16   : AirNow AQI, 511 alerts, 311 potholes, Reddit
          → nexus_image__ViT-B/16  : Mapillary bike paths, Wikimedia parks

    Results from both DescriptorSets are merged and deduplicated by
    context_id. Text results come first so activity/condition buckets
    are populated before image results.

    Args:
        query: Natural-language query string.
        k_per_modality: Max results to fetch from each DescriptorSet.

    Returns:
        Merged list of SearchResult, text results first.
    """
    mem = get_memory()

    text_results = []
    image_results = []

    try:
        text_results = mem.search(query=query, modality="text", k=k_per_modality)
        logger.info("search text(%r): %d results", query[:60], len(text_results))
    except Exception as e:
        logger.error("search_all_modalities text search failed: %s", e)

    try:
        # Same text query → image DescriptorSet (cross-modal — no extra model call)
        image_results = mem.search(query=query, modality="image", k=k_per_modality)
        logger.info("search image(%r): %d results", query[:60], len(image_results))
    except Exception as e:
        logger.warning("search_all_modalities image search failed (index may be empty): %s", e)

    # Deduplicate by context_id — prefer text result if both modalities return it
    seen_ctx: set[str] = set()
    merged = []
    for r in text_results + image_results:
        ctx_id = getattr(r, "context_id", None) or id(r)
        if ctx_id not in seen_ctx:
            seen_ctx.add(ctx_id)
            merged.append(r)

    return merged


def search_image_bytes(image_bytes: bytes, k: int = 20) -> list:
    """CLIP image embedding search against the nexus_image DescriptorSet.

    Embeds the uploaded image with CLIP and returns the most visually
    similar indexed images. Requires images to have been committed via
    Memory.process_and_commit() with a CLIP embedding model configured.

    Args:
        image_bytes: Raw bytes of the uploaded image.
        k: Maximum number of results.

    Returns:
        List of SearchResult ordered by descending similarity score.
        Empty list if no image index exists or CLIP is not configured.
    """
    try:
        results = get_memory().search(query=image_bytes, modality="image", k=k)
        logger.info("search_image_bytes: %d results", len(results))
        return results
    except Exception as e:
        logger.warning("search_image_bytes failed (index may not exist): %s", e)
        return []
