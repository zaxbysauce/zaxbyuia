"""Window capture via PrintWindow.

Used as a fallback for off-screen, occluded, or minimized windows that WGC
cannot capture. Uses ``PW_RENDERFULLCONTENT`` (flag=2) which forces DWM to
render the full window contents into the device context — without it, many
modern apps (Chromium, WPF) come back with black or partial content.

Limitations:
- Some hardware-accelerated content (GPU compositing, video) may still produce
  black regions; in those cases prefer the WGC backend.
- The window must have a valid HWND.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as PILImage

PW_RENDERFULLCONTENT = 0x00000002


def capture_hwnd(hwnd: int) -> PILImage.Image:
    """Capture the contents of an HWND via PrintWindow + PW_RENDERFULLCONTENT.

    Args:
        hwnd: A Windows window handle.

    Returns:
        PIL RGB image of the window contents.

    Raises:
        RuntimeError: if the OS reported the call failed (e.g. invalid HWND).
        OSError: on non-Windows platforms.
    """
    if sys.platform != "win32":
        raise OSError("PrintWindow is Windows-only")

    import ctypes
    from ctypes import wintypes

    import win32con  # type: ignore[import-not-found]
    import win32gui  # type: ignore[import-not-found]
    import win32ui  # type: ignore[import-not-found]
    from PIL import Image

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]

    if not hwnd or not user32.IsWindow(hwnd):
        raise RuntimeError(f"Invalid HWND: {hwnd}")

    rect = wintypes.RECT()
    # GetWindowRect gives screen coords including non-client; we use client-area
    # dimensions for the bitmap to match what PrintWindow renders.
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise RuntimeError(f"GetWindowRect failed for HWND {hwnd}")

    width = max(1, rect.right - rect.left)
    height = max(1, rect.bottom - rect.top)

    # Track each acquisition so we can unwind partially-acquired state if any
    # of the GDI calls below raise.
    hwnd_dc: int | None = None
    mfc_dc = None
    save_dc = None
    bmp = None
    try:
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bmp)

        result = ctypes.windll.user32.PrintWindow(  # type: ignore[attr-defined]
            hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT
        )
        if result != 1:
            # Fallback to BitBlt (works for non-DWM windows)
            save_dc.BitBlt((0, 0), (width, height), mfc_dc, (0, 0), win32con.SRCCOPY)

        bmpinfo = bmp.GetInfo()
        bmpstr = bmp.GetBitmapBits(True)
        image = Image.frombuffer(
            "RGB",
            (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
            bmpstr,
            "raw",
            "BGRX",
            0,
            1,
        )
    finally:
        if bmp is not None:
            try:
                win32gui.DeleteObject(bmp.GetHandle())
            except Exception:
                pass
        if save_dc is not None:
            try:
                save_dc.DeleteDC()
            except Exception:
                pass
        if mfc_dc is not None:
            try:
                mfc_dc.DeleteDC()
            except Exception:
                pass
        if hwnd_dc is not None:
            try:
                win32gui.ReleaseDC(hwnd, hwnd_dc)
            except Exception:
                pass

    return image
