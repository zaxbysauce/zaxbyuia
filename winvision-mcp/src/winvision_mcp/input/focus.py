"""Foreground/focus helpers using the AttachThreadInput trick.

``SetForegroundWindow`` is rate-limited and silently fails for windows owned
by other processes unless the calling thread satisfies certain conditions
(see Raymond Chen, "When can SetForegroundWindow succeed?"). Attaching the
input queue of our thread to the queue of the foreground window's thread
sidesteps the restriction in the common case.
"""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING

from ..config import get_settings
from ..models import Rect, WindowInfo

if TYPE_CHECKING:
    pass


def _require_win() -> None:
    if sys.platform != "win32":
        raise OSError("Windows-only")


def list_windows(*, visible_only: bool = True) -> list[WindowInfo]:
    """Enumerate top-level windows."""
    _require_win()

    import win32gui  # type: ignore[import-not-found]
    import win32process  # type: ignore[import-not-found]

    foreground_hwnd = win32gui.GetForegroundWindow()
    out: list[WindowInfo] = []

    def enum_handler(hwnd: int, _ctx: object) -> None:
        try:
            if visible_only and not win32gui.IsWindowVisible(hwnd):
                return
            title = win32gui.GetWindowText(hwnd) or ""
            cls = win32gui.GetClassName(hwnd) or ""
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                pid = 0
            try:
                rect = win32gui.GetWindowRect(hwnd)
                r = Rect(x=rect[0], y=rect[1], width=rect[2] - rect[0], height=rect[3] - rect[1])
            except Exception:
                r = None
            out.append(
                WindowInfo(
                    hwnd=int(hwnd),
                    title=title,
                    class_name=cls,
                    pid=int(pid),
                    process_name=_proc_name(pid),
                    rect=r,
                    is_foreground=hwnd == foreground_hwnd,
                    is_visible=bool(win32gui.IsWindowVisible(hwnd)),
                )
            )
        except Exception:
            return

    win32gui.EnumWindows(enum_handler, None)
    return out


def _proc_name(pid: int) -> str:
    if not pid:
        return ""
    try:
        import psutil  # type: ignore[import-not-found]

        return psutil.Process(pid).name()
    except Exception:
        return ""


def find_window(
    title_regex: str | None = None,
    *,
    process_name: str | None = None,
    hwnd: int | None = None,
) -> WindowInfo | None:
    """Find the first matching window by HWND, regex on title, or process name."""
    if hwnd:
        for w in list_windows(visible_only=False):
            if w.hwnd == hwnd:
                return w
        return None

    import re

    pat = re.compile(title_regex) if title_regex else None
    pn = process_name.lower() if process_name else None

    for w in list_windows(visible_only=True):
        if pat and not pat.search(w.title):
            continue
        if pn and w.process_name.lower() != pn:
            continue
        return w
    return None


def focus_window(hwnd: int, *, settle_ms: int | None = None) -> bool:
    """Bring ``hwnd`` to the foreground using the AttachThreadInput trick.

    Args:
        hwnd: target window handle.
        settle_ms: ms to sleep after focusing. Defaults to ``settings.input_settle_ms``.

    Returns:
        True if the window is now the foreground window.
    """
    _require_win()

    import ctypes

    import win32con  # type: ignore[import-not-found]
    import win32gui  # type: ignore[import-not-found]
    import win32process  # type: ignore[import-not-found]

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    if not user32.IsWindow(hwnd):
        return False

    # If minimized, restore.
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        time.sleep(0.05)

    fg_hwnd = user32.GetForegroundWindow()
    if fg_hwnd == hwnd:
        return True

    fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, 0) if fg_hwnd else 0
    cur_thread = kernel32.GetCurrentThreadId()
    target_thread, _ = win32process.GetWindowThreadProcessId(hwnd)

    attached_a = False
    attached_b = False
    try:
        if fg_thread and fg_thread != cur_thread:
            attached_a = bool(user32.AttachThreadInput(cur_thread, fg_thread, True))
        if target_thread and target_thread != cur_thread:
            attached_b = bool(user32.AttachThreadInput(cur_thread, target_thread, True))
        # ALT-press trick: pretend the user pressed ALT to satisfy
        # SetForegroundWindow's "input came from us" check.
        try:
            from .sendinput import (
                _INPUT,
                _INPUT_UNION,
                _KEYBDINPUT,
                INPUT_KEYBOARD,
                KEYEVENTF_KEYUP,
                ULONG_PTR,
                _send,
            )

            VK_MENU = 0x12
            down = _INPUT(type=INPUT_KEYBOARD, u=_INPUT_UNION(
                ki=_KEYBDINPUT(wVk=VK_MENU, wScan=0, dwFlags=0, time=0, dwExtraInfo=ULONG_PTR(0))
            ))
            up = _INPUT(type=INPUT_KEYBOARD, u=_INPUT_UNION(
                ki=_KEYBDINPUT(wVk=VK_MENU, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=ULONG_PTR(0))
            ))
            _send([down, up])
        except Exception:
            pass

        win32gui.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached_a:
            user32.AttachThreadInput(cur_thread, fg_thread, False)
        if attached_b:
            user32.AttachThreadInput(cur_thread, target_thread, False)

    settle = settle_ms if settle_ms is not None else get_settings().input_settle_ms
    time.sleep(max(0.0, settle / 1000.0))
    return user32.GetForegroundWindow() == hwnd


def wait_for_idle(hwnd: int, *, timeout_s: float = 5.0) -> bool:
    """Wait for a window's process to be idle (best-effort).

    Uses ``WaitForInputIdle`` plus a CPU-sample-based quiescence check via
    ``psutil``. Returns True on success, False on timeout.
    """
    _require_win()

    import ctypes

    import win32con  # type: ignore[import-not-found]
    import win32process  # type: ignore[import-not-found]

    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
    except Exception:
        return False

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

    h = kernel32.OpenProcess(win32con.SYNCHRONIZE | win32con.PROCESS_QUERY_INFORMATION, False, pid)
    if h:
        try:
            user32.WaitForInputIdle(h, int(timeout_s * 1000))
        finally:
            kernel32.CloseHandle(h)

    # CPU-sample quiescence: two consecutive low-CPU samples 100ms apart.
    try:
        import psutil  # type: ignore[import-not-found]

        proc = psutil.Process(pid)
        start = time.monotonic()
        low_count = 0
        while time.monotonic() - start < timeout_s:
            cpu = proc.cpu_percent(interval=0.1)
            if cpu < 5.0:
                low_count += 1
                if low_count >= 2:
                    return True
            else:
                low_count = 0
        return False
    except Exception:
        return True
