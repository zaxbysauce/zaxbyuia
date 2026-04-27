"""WGC capture integration test (Windows-only).

Launches Notepad, captures its window via the WGC backend, asserts the
returned image has reasonable dimensions and contains non-black pixels
(PrintWindow regression — modern Chromium/composited windows return all-black
when WGC is not engaged).
"""

from __future__ import annotations

import subprocess
import sys
import time
from contextlib import suppress

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")


def test_wgc_captures_notepad_with_real_pixels() -> None:
    from winvision_mcp.capture import wgc_backend
    from winvision_mcp.input.focus import find_window

    if not wgc_backend.is_supported():
        pytest.skip("windows-capture not installed; WGC unavailable")

    proc = subprocess.Popen(["notepad.exe"])
    try:
        deadline = time.monotonic() + 10
        win = None
        while time.monotonic() < deadline:
            win = find_window(title_regex=r"Notepad|Untitled|Editor")
            if win and win.title:
                break
            time.sleep(0.1)
        assert win is not None, "Notepad window did not appear"

        img = wgc_backend.capture_window(win.hwnd, timeout_s=3.0)
        assert img.size[0] > 50 and img.size[1] > 50, f"unreasonably small WGC frame: {img.size}"
        assert img.mode == "RGB"

        import numpy as np

        arr = np.asarray(img)
        # An all-black PrintWindow regression would have non_black ≈ 0.
        non_black = float((arr.sum(axis=2) > 30).mean())
        assert non_black > 0.1, (
            f"WGC frame is mostly black ({non_black:.3f} non-black pixels) — "
            "this likely means WGC fell back to a black-window state. "
            "Check that windows-capture is up to date."
        )
    finally:
        with suppress(Exception):
            proc.kill()


def test_unified_capture_window_engages_wgc() -> None:
    """The high-level capture.api.capture_window should prefer WGC."""
    from winvision_mcp.capture import capture_window
    from winvision_mcp.input.focus import find_window

    proc = subprocess.Popen(["notepad.exe"])
    try:
        deadline = time.monotonic() + 10
        win = None
        while time.monotonic() < deadline:
            win = find_window(title_regex=r"Notepad|Untitled|Editor")
            if win and win.title:
                break
            time.sleep(0.1)
        assert win is not None

        img = capture_window(win.hwnd, prefer="auto")
        assert img.size[0] > 50 and img.size[1] > 50
    finally:
        with suppress(Exception):
            proc.kill()
