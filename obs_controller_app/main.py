"""Entry point: ``python -m obs_controller_app.main`` from the repository root."""

from __future__ import annotations

import logging
import sys

from obs_controller_app import __version__
from obs_controller_app.app import ObsControllerApp
from obs_controller_app.config import AppConfig
from obs_controller_app.utils.logger import setup_logging

logger = logging.getLogger(__name__)


def main() -> int:
    try:
        config = AppConfig.load()
    except (OSError, ValueError, KeyError) as exc:
        print(f"Failed to load settings: {exc}", file=sys.stderr)
        return 1

    setup_logging(logs_dir=config.logs_dir(), debug=config.debug_logging)
    logger.info("Starting OBS Controller v%s", __version__)

    try:
        ObsControllerApp(config).run()
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as exc:  # noqa: BLE001 — top-level safety net
        logger.exception("Fatal error: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
