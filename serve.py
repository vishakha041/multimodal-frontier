"""
SF City Intelligence — API server entry point.

Starts the FastAPI application with uvicorn.

Usage:
    # Standard
    python serve.py

    # With hot-reload for development
    python serve.py --reload

    # Override host/port without editing .env
    API_HOST=127.0.0.1 API_PORT=9000 python serve.py

The scraper agents (main.py) and the API server (serve.py) are
independent processes — run them in separate terminals:
    Terminal 1:  python main.py    # scrapes + stores data
    Terminal 2:  python serve.py   # serves the REST API
"""

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)

from config import cfg  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="SF City Intelligence API server")
    parser.add_argument("--reload", action="store_true",
                        help="Enable uvicorn auto-reload (development only)")
    parser.add_argument("--host", default=cfg.api_host,
                        help=f"Bind host (default: {cfg.api_host})")
    parser.add_argument("--port", type=int, default=cfg.api_port,
                        help=f"Bind port (default: {cfg.api_port})")
    args = parser.parse_args()

    try:
        import uvicorn
    except ImportError:
        logging.error("uvicorn is not installed. Run: pip install -e .")
        sys.exit(1)

    logging.info("=" * 60)
    logging.info("SF City Intelligence API")
    logging.info("Listening on http://%s:%d", args.host, args.port)
    logging.info("Gemini:  %s", "enabled" if cfg.has_gemini() else "disabled (template mode)")
    logging.info("Docs:    http://%s:%d/docs", args.host, args.port)
    logging.info("=" * 60)

    uvicorn.run(
        "api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
