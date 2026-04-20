"""Centralized runtime state for the OBS controller application."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Optional


@dataclass
class AppState:
    """
    Thread-safe-ish runtime flags used by the main loop and SHARE handlers.

    ``last_finished_recording`` always refers to a fully finalized file that was
    moved into ``final_recordings_folder`` — never a file OBS is still writing.
    """

    obs_is_recording: bool = False
    obs_connected: bool = False
    last_finished_recording: Optional[Path] = None
    # Wall-clock time when we last successfully started OBS recording (file picking).
    recording_started_wall: Optional[float] = None
    _lock: Lock = field(default_factory=Lock, repr=False)

    def set_obs_connected(self, value: bool) -> None:
        with self._lock:
            self.obs_connected = value

    def set_obs_is_recording(self, value: bool) -> None:
        with self._lock:
            self.obs_is_recording = value

    def set_recording_started_wall(self, ts: Optional[float]) -> None:
        with self._lock:
            self.recording_started_wall = ts

    def set_last_finished_recording(self, path: Optional[Path]) -> None:
        with self._lock:
            self.last_finished_recording = path

    def get_last_finished_recording(self) -> Optional[Path]:
        with self._lock:
            return self.last_finished_recording

    def get_recording_started_wall(self) -> Optional[float]:
        with self._lock:
            return self.recording_started_wall

    def snapshot(self) -> tuple[bool, bool, Optional[Path]]:
        """Return a consistent tuple copy for quick reads without many locks."""
        with self._lock:
            return self.obs_connected, self.obs_is_recording, self.last_finished_recording
