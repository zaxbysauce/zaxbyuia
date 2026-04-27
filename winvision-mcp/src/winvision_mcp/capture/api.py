"""Unified high-level capture API.

Picks the right backend automatically and applies post-processing (max-edge
downsampling, PNG encoding) so callers don't have to repeat the same code.
"""

from __future__ import annotations

import io
import sys
from typing import TYPE_CHECKING

from ..config import get_settings
from ..logging_setup import get_logger

if TYPE_CHECKING:
    from PIL import Image as PILImage

logger = get_logger(__name__)


def list_monitors() -> list[dict[str, int]]:
    """Return monitors as ``{left, top, width, height}`` dicts (mss order)."""
    from . import mss_backend

    return mss_backend.list_monitors()


def capture_desktop(monitor: int = 0, *, prefer: str = "auto") -> PILImage.Image:
    """Capture the desktop or a specific monitor.

    Args:
        monitor: 0 for the virtual desktop spanning all monitors, 1..N for an
            individual monitor.
        prefer: ``"wgc"``, ``"mss"``, or ``"auto"``.

            - ``monitor == 0`` always uses ``mss`` regardless of ``prefer``;
              the virtual desktop is not a single WGC capture target.
            - ``monitor >= 1`` defaults to WGC (correct for Chromium/WPF/
              GPU-composited content) and falls back to ``mss`` if WGC fails
              to deliver a frame within the timeout.

    Returns:
        PIL RGB image (full resolution; downsampling is the caller's choice).
    """
    from . import mss_backend

    if monitor <= 0:
        return mss_backend.capture_full(monitor=0)

    if sys.platform == "win32" and prefer in ("auto", "wgc"):
        from . import wgc_backend

        if wgc_backend.is_supported():
            try:
                return wgc_backend.capture_monitor(monitor)
            except Exception as exc:
                logger.info("wgc_monitor_capture_failed_fallback_mss", err=str(exc))

    return mss_backend.capture_full(monitor=monitor)


def capture_window(hwnd: int, *, prefer: str = "auto") -> PILImage.Image:
    """Capture a top-level window by HWND.

    Args:
        hwnd: window handle.
        prefer: ``"wgc"``, ``"window"`` (PrintWindow), or ``"auto"``.

    Returns:
        PIL RGB image of the window contents.
    """
    if sys.platform != "win32":
        raise OSError("capture_window requires Windows")

    if prefer in ("auto", "wgc"):
        from . import wgc_backend

        if wgc_backend.is_supported():
            try:
                return wgc_backend.capture_window(hwnd)
            except Exception as exc:
                logger.info("wgc_capture_failed_fallback_printwindow", err=str(exc))

    from . import window_backend

    return window_backend.capture_hwnd(hwnd)


def capture_region(x: int, y: int, w: int, h: int, *, monitor: int = 0) -> PILImage.Image:
    """Capture a region of the virtual desktop.

    For non-zero monitor indices, the (x, y) is interpreted as monitor-local
    coordinates and translated to virtual-desktop coordinates first.
    """
    from . import mss_backend

    if monitor > 0:
        mons = mss_backend.list_monitors()
        if monitor < len(mons):
            base = mons[monitor]
            x = int(base["left"]) + x
            y = int(base["top"]) + y
    return mss_backend.capture_region(x, y, w, h)


def downsample_to_max_edge(img: PILImage.Image, max_edge: int | None = None) -> PILImage.Image:
    """Downsample so the longest edge is <= ``max_edge`` px (no upscaling).

    Args:
        img: source PIL image.
        max_edge: longest-edge target. Defaults to ``settings.capture_max_edge``.

    Returns:
        A possibly-resized PIL image (returns ``img`` unchanged if already
        within bounds).
    """
    from PIL import Image

    if max_edge is None:
        max_edge = get_settings().capture_max_edge
    longest = max(img.size)
    if longest <= max_edge:
        return img
    scale = max_edge / float(longest)
    new_size = (max(1, int(img.size[0] * scale)), max(1, int(img.size[1] * scale)))
    return img.resize(new_size, Image.LANCZOS)


def encode_png_bytes(img: PILImage.Image) -> bytes:
    """Encode a PIL image as PNG bytes (used by FastMCP image tools)."""
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _resolve_desktop_backend(prefer: str, monitor: int) -> str:
    if prefer != "auto":
        return prefer
    settings = get_settings()
    return settings.capture_default_backend if monitor > 0 else "mss"
