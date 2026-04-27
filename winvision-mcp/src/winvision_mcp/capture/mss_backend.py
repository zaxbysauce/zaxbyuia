"""Cross-platform desktop and region capture via mss.

mss is fast, dependency-light, and a reliable fallback when WGC isn't available
or for full-desktop captures. It cannot capture occluded or off-screen windows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image as PILImage


def list_monitors() -> list[dict[str, int]]:
    """Return a list of monitors as ``{left, top, width, height}`` dicts.

    Index 0 is the synthetic "all monitors" virtual desktop. Index 1+ are
    individual physical monitors in the order mss reports them.
    """
    import mss

    with mss.mss() as sct:
        return [dict(m) for m in sct.monitors]  # type: ignore[arg-type]


def capture_full(monitor: int = 0) -> PILImage.Image:
    """Capture an entire monitor (or the virtual desktop if ``monitor=0``).

    Args:
        monitor: 0 for the virtual desktop, 1..N for individual monitors.

    Returns:
        PIL Image (RGB).
    """
    import mss
    from PIL import Image

    with mss.mss() as sct:
        mons = sct.monitors
        if monitor < 0 or monitor >= len(mons):
            monitor = 0
        raw = sct.grab(mons[monitor])
        img = Image.frombytes("RGB", raw.size, raw.rgb)
    return img


def capture_region(x: int, y: int, w: int, h: int) -> PILImage.Image:
    """Capture an arbitrary region of the virtual desktop.

    Coordinates are in physical pixels relative to the virtual desktop origin
    (which on multi-monitor layouts can be negative for monitors to the left of
    the primary).
    """
    import mss
    from PIL import Image

    if w <= 0 or h <= 0:
        raise ValueError(f"Invalid region size {w}x{h}")
    region = {"left": int(x), "top": int(y), "width": int(w), "height": int(h)}
    with mss.mss() as sct:
        raw = sct.grab(region)
        img = Image.frombytes("RGB", raw.size, raw.rgb)
    return img
