"""OBS Studio WebSocket (v5) client built on obsws-python ``ReqClient``."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from threading import Lock
from typing import Any, Optional

import obsws_python as obs
from obsws_python.error import OBSSDKError

from obs_controller_app.utils.helpers import is_probably_video_file, wait_until_file_stable

logger = logging.getLogger(__name__)


def _output_active_from_get_record_status(data: Any) -> bool:
    """obsws-python may return a dict or a generated dataclass type/instance (snake_case fields)."""
    if isinstance(data, dict):
        return bool(data.get("outputActive"))
    for key in ("output_active", "outputActive"):
        if hasattr(data, key):
            return bool(getattr(data, key))
    raise RuntimeError(f"Unexpected GetRecordStatus payload: {data!r}")


def _record_directory_from_response(data: Any) -> Path:
    if isinstance(data, dict) and "recordDirectory" in data:
        return Path(str(data["recordDirectory"])).expanduser().resolve()
    for key in ("record_directory", "recordDirectory"):
        if hasattr(data, key):
            return Path(str(getattr(data, key))).expanduser().resolve()
    raise RuntimeError(f"Unexpected GetRecordDirectory payload: {data!r}")


class ObsWsClient:
    """
    Thin, logging-friendly wrapper around ``ReqClient`` with basic resilience.

    All remote calls are serialized with a lock so a tray “reconnect” cannot race
    the main loop’s recording commands.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        password: str,
        connect_timeout_sec: float,
        action_timeout_sec: float,
        connect_attempts: int = 4,
        connect_attempt_delay_sec: float = 1.0,
    ) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._connect_timeout = connect_timeout_sec
        self._action_timeout = action_timeout_sec
        self._connect_attempts = max(1, connect_attempts)
        self._connect_attempt_delay = connect_attempt_delay_sec
        self._client: Optional[obs.ReqClient] = None
        self._lock = Lock()

    @property
    def is_connected(self) -> bool:
        return self._client is not None

    def disconnect(self) -> None:
        with self._lock:
            if self._client is not None:
                try:
                    self._client.disconnect()
                except Exception as exc:  # noqa: BLE001 — shutdown should be best-effort
                    logger.debug("disconnect raised (ignored): %s", exc)
                self._client = None

    def connect(self) -> bool:
        """
        Connect to OBS, retrying a few times if the socket is not available yet.

        Returns ``True`` on success. Logs and returns ``False`` if OBS never answers.
        """
        self.disconnect()
        last_error: Optional[BaseException] = None
        for attempt in range(1, self._connect_attempts + 1):
            try:
                logger.info(
                    "Connecting to OBS WebSocket %s:%s (attempt %s/%s)",
                    self._host,
                    self._port,
                    attempt,
                    self._connect_attempts,
                )
                client = obs.ReqClient(
                    host=self._host,
                    port=self._port,
                    password=self._password,
                    timeout=self._connect_timeout,
                )
                with self._lock:
                    self._client = client
                logger.info("Connected to OBS WebSocket")
                return True
            except Exception as exc:  # noqa: BLE001 — many socket / auth errors possible
                last_error = exc
                logger.warning("OBS connect failed (%s/%s): %s", attempt, self._connect_attempts, exc)
                time.sleep(self._connect_attempt_delay)
        logger.error("Giving up connecting to OBS: %s", last_error)
        return False

    def _require_client(self) -> obs.ReqClient:
        if self._client is None:
            raise RuntimeError("OBS WebSocket is not connected")
        return self._client

    def _send(self, fn_name: str, call):
        with self._lock:
            client = self._require_client()
            try:
                return call(client)
            except OBSSDKError as exc:
                logger.error("OBS request failed (%s): %s", fn_name, exc)
                raise
            except Exception as exc:  # noqa: BLE001
                logger.exception("Unexpected OBS error (%s): %s", fn_name, exc)
                raise

    def get_record_directory(self) -> Path:
        """Ask OBS for the active recording directory (preferred over static config)."""
        def call(cl: obs.ReqClient) -> Path:
            data: Any = cl.get_record_directory()
            return _record_directory_from_response(data)

        path = self._send("get_record_directory", call)
        logger.debug("OBS record directory: %s", path)
        return path

    def is_recording(self) -> bool:
        """Return whether OBS currently reports an active recording output."""

        def call(cl: obs.ReqClient) -> bool:
            data: Any = cl.get_record_status()
            return _output_active_from_get_record_status(data)

        active = self._send("get_record_status", call)
        logger.debug("OBS recording active=%s", active)
        return active

    def start_recording(self) -> None:
        logger.info("OBS StartRecord")
        self._send("start_record", lambda cl: cl.start_record())

    def stop_recording(self) -> None:
        logger.info("OBS StopRecord")
        self._send("stop_record", lambda cl: cl.stop_record())

    def wait_until_not_recording(
        self,
        *,
        poll_sec: float = 0.25,
        timeout_sec: float,
    ) -> bool:
        """Poll until ``outputActive`` is false or timeout."""
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            try:
                if not self.is_recording():
                    return True
            except Exception as exc:  # noqa: BLE001
                logger.warning("wait_until_not_recording poll failed: %s", exc)
                return False
            time.sleep(poll_sec)
        logger.error("Timed out waiting for OBS to leave recording state")
        return False

    def pick_finished_recording_file(
        self,
        *,
        scan_dir: Path,
        anchor_wall_time: Optional[float],
        video_extensions: tuple[str, ...],
        stability_poll_ms: int,
        stability_required_ms: int,
        finalize_timeout_sec: float,
    ) -> Optional[Path]:
        """
        After recording stops, pick the newest plausible video file under ``scan_dir``.

        Uses ``anchor_wall_time`` (set when recording started) so older unrelated
        videos in the same folder are ignored. Waits until the chosen file is stable
        on disk before returning.
        """
        deadline = time.monotonic() + finalize_timeout_sec
        since = (anchor_wall_time or (time.time() - 3600.0)) - 3.0

        while time.monotonic() < deadline:
            try:
                if not scan_dir.is_dir():
                    logger.error("Recording scan directory does not exist: %s", scan_dir)
                    return None

                candidates: list[Path] = []
                for p in scan_dir.iterdir():
                    if not p.is_file():
                        continue
                    if not is_probably_video_file(p, video_extensions):
                        continue
                    try:
                        if p.stat().st_mtime >= since:
                            candidates.append(p)
                    except OSError:
                        continue

                if not candidates:
                    logger.debug("No recording candidates yet in %s", scan_dir)
                    time.sleep(0.25)
                    continue

                candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                top = candidates[0]
                if wait_until_file_stable(
                    top,
                    stability_ms=stability_required_ms,
                    poll_ms=stability_poll_ms,
                    timeout_sec=min(30.0, finalize_timeout_sec),
                ):
                    logger.info("Selected finished recording file: %s", top)
                    return top
            except Exception as exc:  # noqa: BLE001
                logger.warning("Error while scanning for finished recording: %s", exc)
            time.sleep(0.25)

        logger.error("Could not determine finished recording file under %s", scan_dir)
        return None
