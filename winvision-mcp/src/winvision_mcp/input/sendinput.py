"""SendInput-based mouse and keyboard.

We bypass the higher-level pywinauto helpers for the synthesized cursor moves
because we need:
  - normalized 0–65535 absolute coordinates with MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    (correctly accounts for multi-monitor layouts including monitors at negative offsets)
  - KEYEVENTF_UNICODE for full Unicode text typing without IME pop-ups
  - the ability to interleave a small inter-key delay without the GIL hiccups
    pywinauto's wait loop introduces

Based on the SendInput Win32 API documented in winuser.h.
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from typing import Literal

# --- struct definitions ------------------------------------------------------

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800

ULONG_PTR = ctypes.c_size_t


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


def _virtual_desktop_size() -> tuple[int, int, int, int]:
    """Return ``(left, top, width, height)`` of the virtual desktop in physical px."""
    if sys.platform != "win32":
        return (0, 0, 1920, 1080)
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN = 76, 77
    SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 78, 79
    return (
        int(user32.GetSystemMetrics(SM_XVIRTUALSCREEN)),
        int(user32.GetSystemMetrics(SM_YVIRTUALSCREEN)),
        int(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)),
        int(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)),
    )


def _to_absolute_normalized(x: int, y: int) -> tuple[int, int]:
    """Map physical-pixel virtual-desktop coords to 0..65535."""
    left, top, w, h = _virtual_desktop_size()
    if w <= 0:
        w = 1
    if h <= 0:
        h = 1
    nx = int(round((x - left) * 65535.0 / w))
    ny = int(round((y - top) * 65535.0 / h))
    return nx, ny


def _send(inputs: list[_INPUT]) -> int:
    if sys.platform != "win32":
        raise OSError("SendInput is Windows-only")
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    n = len(inputs)
    arr = (_INPUT * n)(*inputs)
    return int(user32.SendInput(n, arr, ctypes.sizeof(_INPUT)))


# --- Mouse -------------------------------------------------------------------

_BUTTON_FLAGS = {
    "left": (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP),
    "right": (MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP),
    "middle": (MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
}


def click_at(
    x: int, y: int, *, button: str = "left", count: int = 1, hold_ms: int = 20
) -> None:
    """Click at virtual-desktop coordinate ``(x, y)``.

    Args:
        x, y: physical-pixel coords (matches what UIA BoundingRectangle returns).
        button: "left" | "right" | "middle".
        count: 1 for single, 2 for double-click.
        hold_ms: how long to hold each press (default 20 ms).

    Example:
        >>> click_at(640, 360, button="left", count=2)  # doctest: +SKIP
    """
    if button not in _BUTTON_FLAGS:
        raise ValueError(f"Unknown button: {button}")
    nx, ny = _to_absolute_normalized(x, y)

    move = _INPUT(type=INPUT_MOUSE, u=_INPUT_UNION(mi=_MOUSEINPUT(
        dx=nx, dy=ny, mouseData=0,
        dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
        time=0, dwExtraInfo=ULONG_PTR(0),
    )))
    _send([move])
    time.sleep(0.005)

    down_flag, up_flag = _BUTTON_FLAGS[button]
    for _ in range(max(1, count)):
        down = _INPUT(type=INPUT_MOUSE, u=_INPUT_UNION(mi=_MOUSEINPUT(
            dx=nx, dy=ny, mouseData=0,
            dwFlags=down_flag | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
            time=0, dwExtraInfo=ULONG_PTR(0),
        )))
        up = _INPUT(type=INPUT_MOUSE, u=_INPUT_UNION(mi=_MOUSEINPUT(
            dx=nx, dy=ny, mouseData=0,
            dwFlags=up_flag | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
            time=0, dwExtraInfo=ULONG_PTR(0),
        )))
        _send([down])
        time.sleep(max(0.0, hold_ms / 1000.0))
        _send([up])
        time.sleep(0.02)


def drag(from_x: int, from_y: int, to_x: int, to_y: int, *, duration_ms: int = 300) -> None:
    """Mouse-drag from ``(from_x, from_y)`` to ``(to_x, to_y)`` over ``duration_ms``."""
    nx, ny = _to_absolute_normalized(from_x, from_y)
    move = _INPUT(type=INPUT_MOUSE, u=_INPUT_UNION(mi=_MOUSEINPUT(
        dx=nx, dy=ny, mouseData=0,
        dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
        time=0, dwExtraInfo=ULONG_PTR(0),
    )))
    _send([move])
    time.sleep(0.01)

    down = _INPUT(type=INPUT_MOUSE, u=_INPUT_UNION(mi=_MOUSEINPUT(
        dx=nx, dy=ny, mouseData=0,
        dwFlags=MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
        time=0, dwExtraInfo=ULONG_PTR(0),
    )))
    _send([down])

    steps = max(8, int(duration_ms / 16))
    for i in range(1, steps + 1):
        ix = int(from_x + (to_x - from_x) * (i / steps))
        iy = int(from_y + (to_y - from_y) * (i / steps))
        nix, niy = _to_absolute_normalized(ix, iy)
        mv = _INPUT(type=INPUT_MOUSE, u=_INPUT_UNION(mi=_MOUSEINPUT(
            dx=nix, dy=niy, mouseData=0,
            dwFlags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
            time=0, dwExtraInfo=ULONG_PTR(0),
        )))
        _send([mv])
        time.sleep(duration_ms / 1000.0 / steps)

    up = _INPUT(type=INPUT_MOUSE, u=_INPUT_UNION(mi=_MOUSEINPUT(
        dx=0, dy=0, mouseData=0,
        dwFlags=MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK,
        time=0, dwExtraInfo=ULONG_PTR(0),
    )))
    _send([up])


# --- Keyboard ----------------------------------------------------------------


def type_text(text: str, *, interval_ms: int = 5) -> None:
    """Type a Unicode string via KEYEVENTF_UNICODE.

    Bypasses keyboard layouts entirely — every character is delivered as the
    Unicode code point. For control sequences (Ctrl+A, Enter, F-keys), use
    :func:`send_keys` instead.
    """
    sleep_s = max(0.0, interval_ms / 1000.0)
    for ch in text:
        for code in _utf16_units(ch):
            down = _INPUT(type=INPUT_KEYBOARD, u=_INPUT_UNION(ki=_KEYBDINPUT(
                wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=ULONG_PTR(0),
            )))
            up = _INPUT(type=INPUT_KEYBOARD, u=_INPUT_UNION(ki=_KEYBDINPUT(
                wVk=0, wScan=code, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                time=0, dwExtraInfo=ULONG_PTR(0),
            )))
            _send([down, up])
        if sleep_s:
            time.sleep(sleep_s)


def _utf16_units(ch: str) -> list[int]:
    enc = ch.encode("utf-16-le")
    return [int.from_bytes(enc[i : i + 2], "little") for i in range(0, len(enc), 2)]


def send_keys(keys: str) -> None:
    """Send pywinauto-style key sequences (e.g. ``"^a{DEL}Hello{ENTER}"``).

    Delegates to :mod:`pywinauto.keyboard.send_keys`, which understands the
    same syntax used widely in Windows automation scripts.
    """
    if sys.platform != "win32":
        raise OSError("send_keys is Windows-only")
    from pywinauto.keyboard import send_keys as _pwk  # type: ignore[import-not-found]

    _pwk(keys, with_spaces=True, pause=0.01)


# --- Wheel -------------------------------------------------------------------


def wheel(direction: Literal["up", "down"], notches: int = 1) -> None:
    """Synthesize a wheel scroll at the current cursor position."""
    delta = 120 * notches * (1 if direction == "up" else -1)
    inp = _INPUT(type=INPUT_MOUSE, u=_INPUT_UNION(mi=_MOUSEINPUT(
        dx=0, dy=0, mouseData=delta,
        dwFlags=MOUSEEVENTF_WHEEL, time=0, dwExtraInfo=ULONG_PTR(0),
    )))
    _send([inp])
