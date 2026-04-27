"""Per-monitor DPI awareness.

Mixed-DPI multi-monitor setups will silently land clicks on the wrong pixel if
the process is not declared per-monitor-DPI-aware before any window is created
or any UIA call is made. We call ``SetProcessDpiAwarenessContext`` with
``PER_MONITOR_AWARE_V2`` (-4) at server startup.

References:
- https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setprocessdpiawarenesscontext
- DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
"""

from __future__ import annotations

import logging
import sys

logger = logging.getLogger(__name__)

DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4

_applied = False


def set_per_monitor_dpi_aware() -> bool:
    """Mark this process as PER_MONITOR_DPI_AWARE_V2.

    Returns:
        ``True`` if awareness was successfully applied or already applied,
        ``False`` if the call failed (caller may proceed but warn the user).

    On non-Windows platforms this is a no-op that returns ``True``.
    """
    global _applied
    if _applied:
        return True
    if sys.platform != "win32":
        _applied = True
        return True
    try:
        import ctypes

        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        # DPI_AWARENESS_CONTEXT is a HANDLE (pointer-sized signed integer). On
        # 64-bit Python ctypes will marshal a bare Python `int` as `c_int`
        # (32-bit), so the upper 32 bits are not sign-extended and -4 turns
        # into 0xFFFFFFFC instead of 0xFFFFFFFFFFFFFFFC. We declare argtypes
        # explicitly so the value is passed as a pointer-sized signed int.
        try:
            user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_ssize_t]
            user32.SetProcessDpiAwarenessContext.restype = ctypes.c_int
        except Exception:
            pass
        # SetProcessDpiAwarenessContext returns BOOL; nonzero == success.
        ok = bool(
            user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        )
        if not ok:
            # Fallback: SetProcessDpiAwareness(2 = PER_MONITOR_AWARE)
            try:
                shcore = ctypes.windll.shcore  # type: ignore[attr-defined]
                shcore.SetProcessDpiAwareness(2)
                ok = True
            except Exception:
                pass
        if not ok:
            # Last fallback: legacy SetProcessDPIAware
            try:
                user32.SetProcessDPIAware()
                ok = True
            except Exception:
                pass
        _applied = ok
        return ok
    except Exception as exc:  # pragma: no cover - shouldn't happen on win32
        logger.warning("Failed to set DPI awareness: %s", exc)
        return False


def get_dpi_for_monitor(hmonitor: int) -> tuple[int, int]:
    """Return (dpi_x, dpi_y) for an HMONITOR. Windows-only.

    Args:
        hmonitor: HMONITOR handle.

    Returns:
        Tuple of effective DPI for x and y axes. Returns (96, 96) on failure.
    """
    if sys.platform != "win32":
        return (96, 96)
    try:
        import ctypes

        shcore = ctypes.windll.shcore  # type: ignore[attr-defined]
        dpi_x = ctypes.c_uint()
        dpi_y = ctypes.c_uint()
        # MDT_EFFECTIVE_DPI = 0
        rc = shcore.GetDpiForMonitor(hmonitor, 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y))
        if rc == 0:
            return (int(dpi_x.value), int(dpi_y.value))
    except Exception:
        pass
    return (96, 96)
