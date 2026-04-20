"""Application logging setup."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(*, logs_dir: Path, debug: bool) -> None:
    """
    Configure root logging to console + rotating file under ``logs_dir``.

    Safe to call once at process startup.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "obs_controller_app.log"

    level = logging.DEBUG if debug else logging.INFO
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(logging.Formatter(fmt, datefmt))

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=2_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(fmt, datefmt))

    root.addHandler(console)
    root.addHandler(file_handler)

    logging.getLogger("websocket").setLevel(logging.WARNING)
