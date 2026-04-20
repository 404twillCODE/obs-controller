"""
Application orchestration: OBS WebSocket, SHARE tap timing, filesystem moves, tray.

The pygame event loop runs on the main thread; blocking OBS and file work is
offloaded to a small executor so controller polling stays responsive.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

import pystray
from PIL import Image, ImageDraw
from pystray import MenuItem as tray_item

from obs_controller_app.config import AppConfig
from obs_controller_app.controller.ps4_input import Ps4InputListener
from obs_controller_app.files.organizer import FileOrganizer
from obs_controller_app.notifications.toast import ToastService
from obs_controller_app.obs.obs_client import ObsWsClient
from obs_controller_app.state.app_state import AppState

logger = logging.getLogger(__name__)


class ObsControllerApp:
    """Background controller for OBS driven by the PS4 SHARE button."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._state = AppState()
        self._obs = ObsWsClient(
            host=config.obs_host,
            port=config.obs_port,
            password=config.obs_password,
            connect_timeout_sec=config.obs_connect_timeout_sec,
            action_timeout_sec=config.obs_action_timeout_sec,
        )
        self._organizer = FileOrganizer(
            final_recordings_folder=config.resolved_final_recordings_folder(),
            final_clips_folder=config.resolved_final_clips_folder(),
            recording_prefix=config.recording_name_prefix,
            clip_prefix=config.clip_name_prefix,
            video_extensions=config.video_extensions,
        )
        self._toast = ToastService(default_duration_ms=config.notification_duration_ms)
        self._listener = Ps4InputListener(
            device_index=config.joystick_device_index,
            share_button_indices=config.share_button_indices,
            on_share_pressed=self._on_share_pressed,
            on_controller_status=self._on_controller_status,
            log_all_buttons=config.controller_log_all_buttons,
        )

        self._running = True
        self._share_timer: Optional[threading.Timer] = None
        self._share_timer_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="obs-actions")
        self._last_obs_connect_try = 0.0
        self._last_obs_sync = 0.0
        self._last_controller_status: Optional[str] = None

        self._tray_icon: Optional[pystray.Icon] = None
        self._tray_thread: Optional[threading.Thread] = None
        self._main_commands: list[str] = []

        self._main_command_lock = threading.Lock()

    # --- lifecycle -----------------------------------------------------------------

    def run(self) -> None:
        """Main loop: pygame polling, OBS reconnect cadence, tray commands."""
        self._toast.start()

        if not self._listener.init():
            self._toast.show(
                "Controller not found. Connect a PS4 pad and check joystick_device_index.",
                "error",
            )
        else:
            self._last_controller_status = "connected"

        self._try_connect_obs(show_toast_on_failure=True)

        if self._config.enable_system_tray:
            self._start_tray()

        try:
            while self._running:
                self._drain_main_commands()
                self._auto_reconnect_obs()
                self._maybe_sync_obs_recording_flag()

                self._listener.poll()
                time.sleep(0.01)
        finally:
            self._shutdown()

    def request_exit(self) -> None:
        self._running = False

    def _shutdown(self) -> None:
        logger.info("Shutting down")
        self._running = False
        with self._share_timer_lock:
            if self._share_timer is not None:
                self._share_timer.cancel()
                self._share_timer = None
        self._stop_tray()
        self._executor.shutdown(wait=False, cancel_futures=True)
        self._listener.shutdown()
        self._obs.disconnect()
        self._toast.stop()

    # --- tray / cross-thread commands ----------------------------------------------

    def _enqueue_main(self, command: str) -> None:
        with self._main_command_lock:
            self._main_commands.append(command)

    def _drain_main_commands(self) -> None:
        pending: list[str] = []
        with self._main_command_lock:
            if self._main_commands:
                pending = self._main_commands
                self._main_commands = []
        for cmd in pending:
            if cmd == "exit":
                self.request_exit()
            elif cmd == "open_logs":
                self._open_logs_folder()
            elif cmd == "reconnect_obs":
                self._manual_reconnect_obs()

    def _open_logs_folder(self) -> None:
        logs = self._config.logs_dir()
        logs.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(logs))  # noqa: S606 — Windows-only UX
        except OSError as exc:
            logger.error("Could not open logs folder: %s", exc)
            self._toast.show("Could not open logs folder", "error")

    def _manual_reconnect_obs(self) -> None:
        self._toast.show("Reconnecting to OBS…", "info")
        self._obs.disconnect()
        self._state.set_obs_connected(False)
        if self._obs.connect():
            self._state.set_obs_connected(True)
            self._sync_recording_state_from_obs()
            self._toast.show("OBS connected", "success")
        else:
            self._toast.show("OBS connection failed", "error")

    def _start_tray(self) -> None:
        image = self._build_tray_image()

        menu = pystray.Menu(
            tray_item("Open logs folder", lambda icon, item: self._enqueue_main("open_logs")),
            tray_item("Reconnect OBS", lambda icon, item: self._enqueue_main("reconnect_obs")),
            pystray.Menu.SEPARATOR,
            tray_item("Exit", lambda icon, item: self._enqueue_main("exit")),
        )
        self._tray_icon = pystray.Icon(
            "obs_controller_app",
            image,
            "OBS Controller",
            menu,
        )

        def tray_runner() -> None:
            assert self._tray_icon is not None
            self._tray_icon.run()

        self._tray_thread = threading.Thread(target=tray_runner, name="tray", daemon=True)
        self._tray_thread.start()

    def _stop_tray(self) -> None:
        if self._tray_icon is not None:
            try:
                self._tray_icon.stop()
            except Exception as exc:  # noqa: BLE001
                logger.debug("tray stop: %s", exc)
            self._tray_icon = None

    @staticmethod
    def _build_tray_image() -> Image.Image:
        img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle((4, 4, 60, 60), radius=10, fill=(32, 96, 210, 255))
        draw.text((22, 18), "●", fill=(240, 245, 255, 255))
        return img

    # --- OBS connectivity -----------------------------------------------------------

    def _try_connect_obs(self, *, show_toast_on_failure: bool) -> None:
        if self._obs.is_connected:
            return
        if self._obs.connect():
            self._state.set_obs_connected(True)
            self._sync_recording_state_from_obs()
            logger.info("OBS ready")
        else:
            self._state.set_obs_connected(False)
            if show_toast_on_failure:
                self._toast.show(
                    "Could not connect to OBS. Open OBS and enable WebSocket.",
                    "error",
                )

    def _auto_reconnect_obs(self) -> None:
        if self._obs.is_connected:
            return
        now = time.monotonic()
        if now - self._last_obs_connect_try < self._config.obs_reconnect_interval_sec:
            return
        self._last_obs_connect_try = now
        logger.info("Background OBS reconnect attempt")
        self._try_connect_obs(show_toast_on_failure=False)

    def _maybe_sync_obs_recording_flag(self) -> None:
        if not self._obs.is_connected:
            return
        now = time.monotonic()
        if now - self._last_obs_sync < 2.0:
            return
        self._last_obs_sync = now
        try:
            self._sync_recording_state_from_obs()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Periodic OBS sync failed: %s", exc)

    def _sync_recording_state_from_obs(self) -> None:
        active = self._obs.is_recording()
        self._state.set_obs_is_recording(active)

    # --- controller callbacks -------------------------------------------------------

    def _on_controller_status(self, status: str) -> None:
        prev = self._last_controller_status
        if prev == status:
            return
        self._last_controller_status = status
        # Avoid a noisy toast on cold start when the pad is already connected.
        if status == "disconnected" and prev is not None:
            self._toast.show("Controller disconnected", "error")
        elif status == "connected" and prev == "disconnected":
            self._toast.show("Controller connected", "success")

    def _on_share_pressed(self) -> None:
        """Edge-triggered SHARE handler: double-tap window implemented with a timer."""
        with self._share_timer_lock:
            if self._share_timer is not None:
                self._share_timer.cancel()
                self._share_timer = None
                self._submit_action(self._handle_double_tap)
                return

            delay = max(0.05, self._config.share_double_tap_window_ms / 1000.0)

            def _single_fire() -> None:
                with self._share_timer_lock:
                    self._share_timer = None
                self._submit_action(self._handle_single_tap)

            timer = threading.Timer(delay, _single_fire)
            timer.daemon = True
            self._share_timer = timer
            timer.start()

    def _submit_action(self, fn) -> None:
        def _wrapped() -> None:
            try:
                fn()
            except Exception:  # noqa: BLE001
                logger.exception("Action failed")
                self._toast.show("Unexpected error — see logs", "error")

        self._executor.submit(_wrapped)

    # --- SHARE actions --------------------------------------------------------------

    def _handle_double_tap(self) -> None:
        if not self._obs.is_connected:
            self._toast.show("OBS is not connected", "error")
            return

        try:
            recording = self._obs.is_recording()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read OBS recording state: %s", exc)
            self._toast.show("OBS request failed — check connection", "error")
            return

        if not recording:
            try:
                self._obs.start_recording()
            except Exception as exc:  # noqa: BLE001
                logger.error("StartRecord failed: %s", exc)
                self._toast.show("Could not start recording", "error")
                return
            confirmed = False
            confirm_deadline = time.monotonic() + 8.0
            while time.monotonic() < confirm_deadline:
                try:
                    if self._obs.is_recording():
                        confirmed = True
                        break
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Recording confirm poll failed: %s", exc)
                    break
                time.sleep(0.08)
            if not confirmed:
                self._toast.show("Recording start sent but OBS did not confirm", "error")
                return
            self._state.set_obs_is_recording(True)
            self._state.set_recording_started_wall(time.time())
            self._toast.show("Recording started", "success")
            return

        # --- stop path: wait for flush, then move / rename ----------------------------
        try:
            self._obs.stop_recording()
        except Exception as exc:  # noqa: BLE001
            logger.error("StopRecord failed: %s", exc)
            self._toast.show("Could not stop recording", "error")
            return

        if not self._obs.wait_until_not_recording(
            poll_sec=0.25,
            timeout_sec=self._config.obs_action_timeout_sec,
        ):
            self._toast.show("Recording did not finish cleanly", "error")
            return

        try:
            scan_dir = self._obs.get_record_directory()
        except Exception as exc:  # noqa: BLE001
            logger.warning("GetRecordDirectory failed (%s); using config fallback", exc)
            scan_dir = self._config.resolved_obs_recordings_folder()

        anchor = self._state.get_recording_started_wall()
        finished = self._obs.pick_finished_recording_file(
            scan_dir=scan_dir,
            anchor_wall_time=anchor,
            video_extensions=self._config.video_extensions,
            stability_poll_ms=self._config.file_stable_poll_ms,
            stability_required_ms=self._config.file_stable_required_ms,
            finalize_timeout_sec=self._config.file_finalize_timeout_sec,
        )
        if finished is None:
            self._toast.show("Recording stopped but file could not be located", "error")
            self._state.set_obs_is_recording(False)
            self._state.set_recording_started_wall(None)
            return

        try:
            dest = self._organizer.move_and_rename_recording(finished)
        except OSError as exc:
            logger.error("Failed to move recording: %s", exc)
            self._toast.show("Recording stopped but file move failed", "error")
            self._state.set_obs_is_recording(False)
            self._state.set_recording_started_wall(None)
            return

        self._state.set_obs_is_recording(False)
        self._state.set_recording_started_wall(None)
        self._state.set_last_finished_recording(dest)
        self._toast.show("Recording stopped", "success")

    def _handle_single_tap(self) -> None:
        path = self._state.get_last_finished_recording()
        if path is None or not path.is_file():
            self._toast.show("No recording to delete", "info")
            return
        try:
            self._organizer.delete_file(path)
        except OSError as exc:
            logger.error("Delete failed: %s", exc)
            self._toast.show("Could not delete last recording", "error")
            return
        self._state.set_last_finished_recording(None)
        self._toast.show("Last recording deleted", "success")


# --- future extension ---------------------------------------------------------------
# Replay buffer / clip workflow hook (not wired yet):
# subscribe to OBS events such as ReplayBufferSaved (EventClient) or trigger SaveReplayBuffer,
# then call FileOrganizer.move_and_rename_clip with the path OBS returns.
