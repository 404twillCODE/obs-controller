"""
PS4 / DualShock-style controller polling via pygame.

The SHARE button index varies by driver; override ``share_button_index`` in
``settings.json`` if your controller maps SHARE to a different button number.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Optional

import pygame

logger = logging.getLogger(__name__)


class Ps4InputListener:
    """
    Poll pygame joystick events and invoke ``on_share_pressed`` for SHARE taps.

    This class intentionally hides pygame details so another backend could be
    swapped in later without touching the rest of the app.
    """

    def __init__(
        self,
        *,
        device_index: int,
        share_button_index: int,
        on_share_pressed: Callable[[], None],
        on_controller_status: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._device_index = device_index
        self._share_button_index = share_button_index
        self._on_share_pressed = on_share_pressed
        self._on_controller_status = on_controller_status
        self._joystick: Optional[pygame.joystick.Joystick] = None
        self._initialized = False
        self._had_controller = False

    def init(self) -> bool:
        """Initialize pygame joystick subsystem and attempt to open the device."""
        if not self._initialized:
            pygame.init()
            pygame.joystick.init()
            self._initialized = True
            logger.debug("pygame joystick subsystem initialized")

        return self._try_open_joystick()

    def _try_open_joystick(self) -> bool:
        if self._joystick is not None:
            return True

        count = pygame.joystick.get_count()
        logger.info("Detected %s joystick device(s)", count)
        if count <= self._device_index:
            logger.error(
                "Joystick device index %s not found (only %s devices). "
                "Connect your PS4 controller and adjust joystick_device_index if needed.",
                self._device_index,
                count,
            )
            if self._on_controller_status:
                self._on_controller_status("disconnected")
            return False

        js = pygame.joystick.Joystick(self._device_index)
        js.init()
        self._joystick = js
        self._had_controller = True
        logger.info(
            "Opened joystick %s: %s (buttons=%s)",
            self._device_index,
            js.get_name(),
            js.get_numbuttons(),
        )
        if self._on_controller_status:
            self._on_controller_status("connected")
        return True

    def poll(self) -> None:
        """Drain pygame events; reconnect if the device was unplugged."""
        if not self._initialized:
            return

        for event in pygame.event.get():
            if event.type == pygame.JOYDEVICEADDED:
                logger.info("Joystick plugged in: %s", getattr(event, "device_index", "?"))
                self._try_open_joystick()

            if event.type == pygame.JOYDEVICEREMOVED:
                if self._joystick is not None and getattr(event, "instance_id", None) == self._joystick.get_instance_id():
                    logger.warning("Active joystick was removed")
                    self._joystick = None
                    if self._on_controller_status:
                        self._on_controller_status("disconnected")

            if event.type == pygame.JOYBUTTONDOWN and self._joystick is not None:
                if event.instance_id != self._joystick.get_instance_id():
                    continue
                if event.button == self._share_button_index:
                    logger.debug("SHARE button press (button index %s)", event.button)
                    self._on_share_pressed()

    def shutdown(self) -> None:
        """Release joystick resources (call before process exit)."""
        if self._joystick is not None:
            try:
                self._joystick.quit()
            except Exception as exc:  # noqa: BLE001
                logger.debug("joystick quit raised: %s", exc)
            self._joystick = None
        if self._initialized:
            try:
                pygame.joystick.quit()
                pygame.quit()
            except Exception as exc:  # noqa: BLE001
                logger.debug("pygame quit raised: %s", exc)
            self._initialized = False
