"""
SF City Guide — static web UI server.

Serves the webapp/ directory over HTTP on port 8080.
No dependencies beyond the Python standard library.

Usage:
    python webapp.py
    WEBAPP_PORT=3000 python webapp.py
"""

import http.server
import logging
import os
import sys

PORT = int(os.environ.get("WEBAPP_PORT", 8080))
WEBAPP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webapp")


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEBAPP_DIR, **kwargs)

    def log_message(self, fmt, *args):
        # Forward to Python logging instead of stderr noise
        logging.getLogger("webapp").debug(fmt, *args)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    log = logging.getLogger("webapp")
    log.info("Web UI running at http://localhost:%d", PORT)

    with http.server.HTTPServer(("", PORT), _Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
