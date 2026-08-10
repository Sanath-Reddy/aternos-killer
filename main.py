"""
BlockSync — main entry point.

For development/testing: python main.py
The full UI is owned by Developer 2 and will replace this stub.
"""

import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger("blocksync")


def main() -> None:
    logger.info("BlockSync core started (dev stub)")
    logger.info(
        "To use BlockSync, import and call the service layer:\n"
        "  from core.session_service import SessionService\n"
        "  from core.world_service    import WorldService\n"
        "  from core.minecraft_service import MinecraftService\n"
    )


if __name__ == "__main__":
    main()
