"""Load and validate JSON configuration for the OBS controller app."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _app_base_dir() -> Path:
    """Directory used for settings.json, logs, and frozen EXE layout."""
    if getattr(sys, "frozen", False) and hasattr(sys, "executable"):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


@dataclass(frozen=True)
class AppConfig:
    """Typed application configuration (mirrors settings.json)."""

    obs_host: str
    obs_port: int
    obs_password: str
    obs_recordings_output_folder: str
    obs_clips_output_folder: str
    final_recordings_folder: str
    final_clips_folder: str
    share_double_tap_window_ms: int
    notification_duration_ms: int
    enable_system_tray: bool
    debug_logging: bool
    share_button_index: int
    joystick_device_index: int
    obs_connect_timeout_sec: float
    obs_action_timeout_sec: float
    file_stable_poll_ms: int
    file_stable_required_ms: int
    file_finalize_timeout_sec: float
    obs_reconnect_interval_sec: float
    recording_name_prefix: str
    clip_name_prefix: str
    video_extensions: tuple[str, ...]

    @staticmethod
    def settings_path() -> Path:
        return _app_base_dir() / "settings.json"

    @classmethod
    def load(cls, path: Path | None = None) -> AppConfig:
        cfg_path = path or cls.settings_path()
        if not cfg_path.is_file():
            raise FileNotFoundError(
                f"Missing configuration file: {cfg_path}. "
                "Copy settings.json next to the app or see README.md."
            )
        raw = json.loads(cfg_path.read_text(encoding="utf-8"))
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppConfig:
        def req(key: str) -> Any:
            if key not in data:
                raise KeyError(f"settings.json missing required key: {key!r}")
            return data[key]

        exts = req("video_extensions")
        if not isinstance(exts, list) or not all(isinstance(x, str) for x in exts):
            raise ValueError("video_extensions must be a list of strings")

        return cls(
            obs_host=str(req("obs_host")),
            obs_port=int(req("obs_port")),
            obs_password=str(req("obs_password")),
            obs_recordings_output_folder=str(req("obs_recordings_output_folder")),
            obs_clips_output_folder=str(req("obs_clips_output_folder")),
            final_recordings_folder=str(req("final_recordings_folder")),
            final_clips_folder=str(req("final_clips_folder")),
            share_double_tap_window_ms=int(req("share_double_tap_window_ms")),
            notification_duration_ms=int(req("notification_duration_ms")),
            enable_system_tray=bool(req("enable_system_tray")),
            debug_logging=bool(req("debug_logging")),
            share_button_index=int(req("share_button_index")),
            joystick_device_index=int(req("joystick_device_index")),
            obs_connect_timeout_sec=float(req("obs_connect_timeout_sec")),
            obs_action_timeout_sec=float(req("obs_action_timeout_sec")),
            file_stable_poll_ms=int(req("file_stable_poll_ms")),
            file_stable_required_ms=int(req("file_stable_required_ms")),
            file_finalize_timeout_sec=float(req("file_finalize_timeout_sec")),
            obs_reconnect_interval_sec=float(req("obs_reconnect_interval_sec")),
            recording_name_prefix=str(req("recording_name_prefix")),
            clip_name_prefix=str(req("clip_name_prefix")),
            video_extensions=tuple(str(x).lower() if str(x).startswith(".") else f".{x}".lower() for x in exts),
        )

    def resolved_obs_recordings_folder(self) -> Path:
        return Path(self.obs_recordings_output_folder).expanduser().resolve()

    def resolved_obs_clips_folder(self) -> Path:
        return Path(self.obs_clips_output_folder).expanduser().resolve()

    def resolved_final_recordings_folder(self) -> Path:
        return Path(self.final_recordings_folder).expanduser().resolve()

    def resolved_final_clips_folder(self) -> Path:
        return Path(self.final_clips_folder).expanduser().resolve()

    def logs_dir(self) -> Path:
        return _app_base_dir() / "logs"
