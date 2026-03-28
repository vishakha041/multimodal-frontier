"""
SF City Intelligence REST API — FastAPI application.

Endpoints:
  POST /chat   — natural-language query → bucketed SF activity results
  POST /image  — uploaded image → identification + bucketed results
  GET  /health — liveness probe
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from api.models import Buckets, ChatRequest, ChatResponse, ImageResponse, PathInfo
from api.search import get_memory, search_all_modalities, search_image_bytes, search_text
from api.buckets import build_buckets, first_coordinate
from api.routing import get_walking_path
from api.llm import generate_chat_message, identify_image

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan — warm up the Memory connection on startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("API startup: warming up aperture-nexus Memory connection…")
    try:
        get_memory()
        logger.info("API startup: Memory ready")
    except Exception as e:
        logger.error("API startup: Memory unavailable — searches will fail: %s", e)
    yield
    logger.info("API shutdown")


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="SF City Intelligence API",
    description="Natural-language and image queries over live SF city data.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],       # open for Lovable / any frontend during hackathon
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# POST /chat
# ---------------------------------------------------------------------------

@app.post("/chat", response_model=ChatResponse, tags=["query"])
async def chat(req: ChatRequest) -> ChatResponse:
    """Answer a natural-language question about things to do in San Francisco.

    Searches the ApertureDB index for semantically similar content, groups
    results into activity buckets, fetches a walking route to the top result,
    and generates a friendly response message.
    """
    logger.info("/chat from=%s query=%r", req.email, req.message[:80])

    # Cross-modal search: same CLIP vector queries text DescriptorSet
    # (AQI, 311, 511, Reddit, Yelp) AND image DescriptorSet (Mapillary,
    # Wikimedia, iNat) in one pass — no extra model call.
    results = search_all_modalities(req.message, k_per_modality=30)
    buckets = build_buckets(results, req.message)

    # Attach walking path to the closest result with real coordinates
    coord = first_coordinate(buckets)
    if coord:
        buckets.path = await get_walking_path(coord[0], coord[1])

    message = await generate_chat_message(req.message, buckets)

    return ChatResponse(message=message, buckets=buckets)


# ---------------------------------------------------------------------------
# POST /image
# ---------------------------------------------------------------------------

@app.post("/image", response_model=ImageResponse, tags=["query"])
async def analyze_image(
    image: UploadFile = File(..., description="Image file to analyze (JPEG/PNG/WEBP)"),
    email: str = Form(..., description="Authenticated user's email"),
) -> ImageResponse:
    """Identify what is in an uploaded image and return nearby SF activity results.

    Uses Gemini Vision (if configured) to identify the image, then searches
    the ApertureDB index using the image embedding and/or identified label.
    """
    logger.info("/image from=%s filename=%s", email, image.filename)

    # Validate content type
    content_type = image.content_type or ""
    if content_type and not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Uploaded file must be an image.")

    image_bytes = await image.read()
    if len(image_bytes) > 20 * 1024 * 1024:  # 20 MB guard
        raise HTTPException(status_code=413, detail="Image file too large (max 20 MB).")

    # 1. Identify the image (Gemini Vision or CLIP fallback)
    clip_results = search_image_bytes(image_bytes, k=20)
    identified, description = await identify_image(image_bytes, clip_results)

    # 2. Text search using the identified label for richer bucket results
    text_results = search_text(f"{identified} San Francisco things to do", k=30)

    # Merge: CLIP image results + text results (CLIP first for visual relevance)
    combined = clip_results + [r for r in text_results if r not in clip_results]

    buckets = build_buckets(combined, identified)

    # Attach walking path
    coord = first_coordinate(buckets)
    if coord:
        buckets.path = await get_walking_path(coord[0], coord[1])

    return ImageResponse(
        description=description,
        identified=identified,
        buckets=buckets,
    )
