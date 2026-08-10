"""
BlockSync — application entry point.

Launches the Developer 2 UI. Core services are wired via ui.app_services
(mocks by default; set BLOCKSYNC_USE_MOCKS=0 plus config env vars for real).
"""

from __future__ import annotations

import logging
import sys


def main() -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    from ui.app import run_app

    run_app()


if __name__ == "__main__":
    main()
