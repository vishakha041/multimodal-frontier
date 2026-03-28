"""
SF City Guide — one-command launcher.

Starts all three processes in the correct order:
  1. python main.py    — scraper agents (indexes SF data into ApertureDB)
  2. python serve.py   — FastAPI REST API on port 8000
  3. python webapp.py  — static web UI on port 8080

Press Ctrl-C once to stop everything cleanly.

Usage:
    python launch.py

    # Fast scraping intervals for quick testing:
    LIVE_INTERVAL_SECONDS=30 STATIC_INTERVAL_SECONDS=60 python launch.py

    # Skip the scraper (API + UI only, e.g. when ApertureDB already has data):
    NO_SCRAPER=1 python launch.py
"""

import os
import signal
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable
_PROCS: list[tuple[str, subprocess.Popen]] = []


def _launch(script: str, label: str, extra_env: dict | None = None) -> subprocess.Popen:
    env = {**os.environ, **(extra_env or {})}
    p = subprocess.Popen(
        [PYTHON, os.path.join(BASE, script)],
        cwd=BASE,
        env=env,
    )
    _PROCS.append((label, p))
    print(f"  ✓  {label:<28} pid={p.pid}")
    return p


def _shutdown(sig=None, frame=None) -> None:
    print("\n\nShutting down…")
    # Terminate all in reverse order (UI → API → scraper)
    for label, p in reversed(_PROCS):
        try:
            p.terminate()
            print(f"  ↓  {label} (pid {p.pid})")
        except ProcessLookupError:
            pass

    # Wait up to 6 seconds, then force-kill anything still running
    deadline = time.time() + 6
    for label, p in _PROCS:
        remaining = max(0.0, deadline - time.time())
        try:
            p.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            print(f"  ✗  {label} did not exit — killing")
            p.kill()

    print("All stopped. Goodbye.")
    sys.exit(0)


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


def main() -> None:
    print("🌉  SF City Guide\n")

    skip_scraper = os.environ.get("NO_SCRAPER", "").strip() not in ("", "0")

    if not skip_scraper:
        _launch("main.py", "Scraper agents")
        # Give the scraper a moment to start before the API warms up
        time.sleep(1)
    else:
        print("  –  Scraper agents         skipped (NO_SCRAPER=1)")

    _launch("serve.py", "API server        :8000")
    _launch("webapp.py", "Web UI            :8080")

    print()
    print("  🌐  Web UI   →  http://localhost:8080")
    print("  🔌  API      →  http://localhost:8000")
    print("  📖  API docs →  http://localhost:8000/docs")
    print()
    print("Press Ctrl-C to stop all.\n")

    # Monitor loop — report unexpected exits
    while True:
        time.sleep(2)
        for label, p in list(_PROCS):
            code = p.poll()
            if code is not None:
                print(f"  ⚠  {label} (pid {p.pid}) exited with code {code}")
                _PROCS.remove((label, p))
        if not _PROCS:
            print("All processes have exited.")
            break


if __name__ == "__main__":
    main()
