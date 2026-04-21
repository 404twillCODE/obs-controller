"""
Lightweight top-right toast notifications using tkinter.

Runs on a dedicated daemon thread with a single hidden Tk root so pops do not
block the pygame / main loop.
"""

from __future__ import annotations

import logging
import queue
import sys
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
from typing import Literal

logger = logging.getLogger(__name__)

# --- Windows: keep toasts above fullscreen / exclusive apps ----------------------------

HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_SHOWWINDOW = 0x0040
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000


def _win32_pin_topmost(hwnd: int) -> None:
    """Raise window above normal Z-order without stealing keyboard focus."""
    try:
        import ctypes
    except ImportError:
        return
    user32 = ctypes.windll.user32
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW | SWP_NOACTIVATE
    user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)


def _win32_apply_fullscreen_friendly_styles(hwnd: int) -> None:
    """
    Tool / no-activate extended styles so the toast behaves like an overlay and
    is less likely to be blocked by exclusive-fullscreen games (best-effort).
    """
    try:
        import ctypes
    except ImportError:
        return
    user32 = ctypes.windll.user32
    try:
        get_ex = user32.GetWindowLongPtrW
        set_ex = user32.SetWindowLongPtrW
    except AttributeError:
        get_ex = user32.GetWindowLongW
        set_ex = user32.SetWindowLongW
    ex = int(get_ex(hwnd, GWL_EXSTYLE))
    ex |= WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    set_ex(hwnd, GWL_EXSTYLE, ex)
    user32.SetWindowPos(
        hwnd,
        HWND_TOPMOST,
        0,
        0,
        0,
        0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_FRAMECHANGED | SWP_NOACTIVATE | SWP_SHOWWINDOW,
    )


def _win32_toast_hwnd(win: tk.Misc) -> int | None:
    if sys.platform != "win32":
        return None
    try:
        return int(win.winfo_id())
    except (tk.TclError, TypeError, ValueError):
        return None


def _win32_arm_topmost_pinner(win: tk.Toplevel) -> None:
    """Re-apply TOPMOST while visible; games often fight Z-order every frame."""
    if sys.platform != "win32":
        return
    win._toast_pin_active = True  # noqa: SLF001 — private attr on tk widget

    def tick() -> None:
        if not getattr(win, "_toast_pin_active", False):
            return
        try:
            if not win.winfo_exists():
                return
        except tk.TclError:
            return
        hwnd = _win32_toast_hwnd(win)
        if hwnd is not None:
            _win32_pin_topmost(hwnd)
        try:
            win.after(120, tick)
        except tk.TclError:
            pass

    win.after(1, tick)


def _win32_disarm_topmost_pinner(win: tk.Toplevel) -> None:
    try:
        win._toast_pin_active = False  # noqa: SLF001
    except tk.TclError:
        pass

ToastKind = Literal["info", "success", "error"]


@dataclass(frozen=True)
class _ToastJob:
    message: str
    kind: ToastKind
    duration_ms: int


class ToastService:
    """Queue-based toast worker; call ``show`` from any thread."""

    def __init__(self, *, default_duration_ms: int) -> None:
        self._default_duration_ms = default_duration_ms
        self._queue: queue.Queue[_ToastJob | None] = queue.Queue()
        self._thread = threading.Thread(target=self._worker, name="toast-worker", daemon=True)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread.start()

    def stop(self) -> None:
        """Ask the worker thread to exit (best-effort for clean shutdown)."""
        if not self._started:
            return
        self._queue.put(None)

    def show(self, message: str, kind: ToastKind = "info", *, duration_ms: int | None = None) -> None:
        if not self._started:
            logger.warning("ToastService.show called before start(): %s", message)
        job = _ToastJob(
            message=message,
            kind=kind,
            duration_ms=duration_ms if duration_ms is not None else self._default_duration_ms,
        )
        self._queue.put(job)

    def _worker(self) -> None:
        root = tk.Tk()
        root.withdraw()
        root.overrideredirect(True)
        root.configure(bg="#111418")

        def pump() -> None:
            try:
                while True:
                    job = self._queue.get_nowait()
                    if job is None:
                        root.quit()
                        return
                    self._present(root, job)
            except queue.Empty:
                pass
            root.after(120, pump)

        root.after(120, pump)
        try:
            root.mainloop()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Toast worker crashed: %s", exc)
        finally:
            try:
                root.destroy()
            except Exception:
                pass

    def _present(self, root: tk.Tk, job: _ToastJob) -> None:
        win = tk.Toplevel(root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)

        colors = {
            "info": ("#e8eaef", "#1b1f27", "#2a3140"),
            "success": ("#e8ffef", "#15251c", "#1f4d32"),
            "error": ("#ffecec", "#2a1414", "#6b2222"),
        }
        fg, bg, border = colors[job.kind]

        win.configure(bg=border)
        frame = tk.Frame(win, bg=bg, highlightthickness=1, highlightbackground=border)
        frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        title_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        lbl = tk.Label(
            frame,
            text=job.message,
            fg=fg,
            bg=bg,
            wraplength=360,
            justify=tk.LEFT,
            font=title_font,
            padx=18,
            pady=14,
        )
        lbl.pack(fill=tk.BOTH, expand=True)

        win.update_idletasks()
        w = max(win.winfo_reqwidth(), 320)
        h = win.winfo_reqheight()
        sw = win.winfo_screenwidth()
        x = max(12, sw - w - 20)
        y = 20
        win.geometry(f"{w}x{h}+{x}+{y}")

        hwnd = _win32_toast_hwnd(win)
        if hwnd is not None:
            try:
                _win32_apply_fullscreen_friendly_styles(hwnd)
                _win32_pin_topmost(hwnd)
                _win32_arm_topmost_pinner(win)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Win32 toast layering failed (non-fatal): %s", exc)

        try:
            win.attributes("-alpha", 0.0)
        except tk.TclError:
            win.attributes("-alpha", 1.0)

        fade_in_ms = 160
        steps = 10

        def fade_in(step: int = 0) -> None:
            try:
                a = min(1.0, (step + 1) / steps)
                win.attributes("-alpha", a)
            except tk.TclError:
                pass
            if step + 1 < steps:
                win.after(fade_in_ms // steps, lambda: fade_in(step + 1))
            else:

                def fade_out(step_out: int = 10) -> None:
                    if step_out == 10:
                        _win32_disarm_topmost_pinner(win)
                    if step_out <= 0:
                        try:
                            win.destroy()
                        except tk.TclError:
                            pass
                        return
                    try:
                        win.attributes("-alpha", max(0.0, step_out / 10.0))
                    except tk.TclError:
                        pass
                    win.after(40, lambda: fade_out(step_out - 1))

                win.after(max(600, job.duration_ms), lambda: fade_out(10))

        fade_in()

