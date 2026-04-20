"""Small filesystem and timing helpers used across the app."""

from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def wait_until_file_stable(
    path: Path,
    *,
    stability_ms: int,
    poll_ms: int,
    timeout_sec: float,
) -> bool:
    """
    Wait until ``path`` exists and its size stays unchanged for ``stability_ms``.

    Used to avoid moving or deleting files while OBS (or the encoder) is still
    flushing data to disk.
    """
    deadline = time.monotonic() + timeout_sec
    poll_sec = max(poll_ms, 50) / 1000.0
    stable_needed = max(stability_ms, 100) / 1000.0

    last_size: int | None = None
    stable_since: float | None = None

    while time.monotonic() < deadline:
        try:
            if not path.is_file():
                last_size = None
                stable_since = None
                time.sleep(poll_sec)
                continue
            size = path.stat().st_size
        except OSError as exc:
            logger.debug("stat failed while waiting for stable file %s: %s", path, exc)
            time.sleep(poll_sec)
            continue

        now = time.monotonic()
        if last_size is None or size != last_size:
            last_size = size
            stable_since = now
        elif stable_since is not None and (now - stable_since) >= stable_needed:
            logger.debug("File stable: %s size=%s", path, size)
            return True

        time.sleep(poll_sec)

    logger.warning("Timed out waiting for file to stabilize: %s", path)
    return False


def is_probably_video_file(path: Path, extensions: tuple[str, ...]) -> bool:
    return path.suffix.lower() in extensions
