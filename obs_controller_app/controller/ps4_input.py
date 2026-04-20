"""
PS4 / DualShock-style controller input via pygame.

SHARE is detected with **polling** (``get_button``) each frame, not only
``JOYBUTTONDOWN`` events, because some Windows + SDL setups drop button events
unless a display is initialized and/or background joystick events are allowed.

Set ``share_button_indices`` in ``settings.json`` if SHARE maps to a different
button number for your driver. Use ``controller_log_all_buttons`` to discover
indices from the log while pressing each face control.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from typing import Optional

# Must run before pygame/SDL init so SDL picks up the hint.
os.environ.setdefault("SDL_JOYSTICK_ALLOW_BACKGROUND_EVENTS", "1")

import pygame  # noqa: E402 — after SDL env hints

logger = logging.getLogger(__name__)


class Ps4InputListener:
    """
    Poll pygame joystick state and invoke ``on_share_pressed`` for SHARE edges.

    Isolated from the rest of the app so another input backend can replace this
    module later.
    """

    def __init__(
        self,
        *,
        device_index: int,
        share_button_indices: Sequence[int],
        on_share_pressed: Callable[[], None],
        on_controller_status: Optional[Callable[[str], None]] = None,
        log_all_buttons: bool = False,
    ) -> None:
        self._device_index = int(device_index)
        self._share_button_indices = tuple(int(i) for i in share_button_indices)
        if not self._share_button_indices:
            raise ValueError("share_button_indices must contain at least one button index")
        self._on_share_pressed = on_share_pressed
        self._on_controller_status = on_controller_status
        self._log_all_buttons = bool(log_all_buttons)

        self._joystick: Optional[pygame.joystick.Joystick] = None
        self._initialized = False
        self._display_initialized = False
        # Edge detection for polling-based SHARE (and optional debug logging).
        self._share_prev: dict[int, bool] = {}
        self._debug_btn_prev: dict[int, bool] = {}

    def init(self) -> bool:
        """Initialize pygame (display + joystick) and open the chosen device."""
        if not self._initialized:
            pygame.init()
            pygame.joystick.init()
            self._ensure_hidden_window()
            self._initialized = True
            logger.debug("pygame initialized (joystick + hidden display)")

        return self._try_open_joystick()

    def _ensure_hidden_window(self) -> None:
        """
        SDL on Windows often requires a display surface before joystick state
        and events update reliably. A 1x1 hidden window keeps the app tray-only.
        """
        if self._display_initialized:
            return
        try:
            pygame.display.init()
            pygame.display.set_mode((1, 1), pygame.HIDDEN)
            self._display_initialized = True
            logger.debug("Created hidden pygame display for joystick input")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not create hidden display window: %s", exc)

    def _reset_button_edge_state(self) -> None:
        self._share_prev = {i: False for i in self._share_button_indices}
        self._debug_btn_prev = {}

    def _try_open_joystick(self) -> bool:
        if self._joystick is not None:
            return True

        count = pygame.joystick.get_count()
        logger.info("Detected %s joystick device(s)", count)
        if count <= self._device_index:
            logger.error(
                "Joystick device index %s not found (only %s devices). "
                "Connect your PS4 controller or set joystick_device_index (0 = first).",
                self._device_index,
                count,
            )
            if self._on_controller_status:
                self._on_controller_status("disconnected")
            return False

        js = pygame.joystick.Joystick(self._device_index)
        js.init()
        self._joystick = js
        self._reset_button_edge_state()
        logger.info(
            "Opened joystick %s: %r (buttons=%s, axes=%s, hats=%s). SHARE indices=%s",
            self._device_index,
            js.get_name(),
            js.get_numbuttons(),
            js.get_numaxes(),
            js.get_numhats(),
            self._share_button_indices,
        )
        if self._on_controller_status:
            self._on_controller_status("connected")
        return True

    def poll(self) -> None:
        """Pump SDL events (hotplug) and poll SHARE / debug buttons."""
        if not self._initialized:
            return

        for event in pygame.event.get():
            if event.type == pygame.JOYDEVICEADDED:
                dev_i = getattr(event, "device_index", None)
                logger.info("Joystick plugged in (device_index=%s)", dev_i)
                self._try_open_joystick()

            if event.type == pygame.JOYDEVICEREMOVED:
                if self._joystick is None:
                    continue
                removed = getattr(event, "instance_id", None)
                if removed is not None and removed == self._joystick.get_instance_id():
                    logger.warning("Active joystick was removed")
                    self._joystick = None
                    self._share_prev.clear()
                    self._debug_btn_prev.clear()
                    if self._on_controller_status:
                        self._on_controller_status("disconnected")

        if self._joystick is None:
            return

        # Primary path: poll hardware state (works when JOYBUTTONDOWN is not delivered).
        self._poll_share_edges()
        if self._log_all_buttons:
            self._poll_debug_all_buttons()

    def _poll_share_edges(self) -> None:
        assert self._joystick is not None
        for idx in self._share_button_indices:
            try:
                cur = bool(self._joystick.get_button(idx))
            except pygame.error as exc:
                logger.debug("get_button(%s) failed: %s", idx, exc)
                continue
            prev = self._share_prev.get(idx, False)
            if cur and not prev:
                logger.debug("SHARE edge (button index %s)", idx)
                self._on_share_pressed()
            self._share_prev[idx] = cur

    def _poll_debug_all_buttons(self) -> None:
        assert self._joystick is not None
        n = self._joystick.get_numbuttons()
        for b in range(n):
            try:
                cur = bool(self._joystick.get_button(b))
            except pygame.error:
                continue
            prev = self._debug_btn_prev.get(b, False)
            if cur and not prev:
                logger.info(
                    'Joystick "%s" button DOWN — index=%s (put this in share_button_indices if it is SHARE)',
                    self._joystick.get_name(),
                    b,
                )
            self._debug_btn_prev[b] = cur

    def shutdown(self) -> None:
        """Release joystick and pygame (call before process exit)."""
        if self._joystick is not None:
            try:
                self._joystick.quit()
            except Exception as exc:  # noqa: BLE001
                logger.debug("joystick quit raised: %s", exc)
            self._joystick = None
        self._share_prev.clear()
        self._debug_btn_prev.clear()
        if self._initialized:
            try:
                pygame.joystick.quit()
                if self._display_initialized:
                    pygame.display.quit()
                    self._display_initialized = False
                pygame.quit()
            except Exception as exc:  # noqa: BLE001
                logger.debug("pygame quit raised: %s", exc)
            self._initialized = False
