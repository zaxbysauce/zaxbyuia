"""Windows.Graphics.Capture (WGC) — fully wired via the ``windows-capture`` Rust binding.

WGC is the modern, hardware-composited capture path on Windows 10 1903+ /
Windows 11. Unlike PrintWindow it correctly captures Chromium, Electron, and
GPU-rendered WPF surfaces without returning black frames.

Why we use ``windows-capture`` here instead of pure ``winrt-Windows.Graphics.Capture``:
the upstream PyWinRT projection ships the WGC runtime classes but does NOT
expose ``IGraphicsCaptureItemInterop``, which is the COM interface required to
construct a ``GraphicsCaptureItem`` from an HWND or HMONITOR. ``windows-capture``
ships a Rust-backed wheel that handles the interop + DXGI/D3D11 device dance
correctly, so we get the full WGC pipeline without re-implementing it in
``comtypes``.

The WGC API is callback/event-driven; for a one-shot capture we drive it from
a worker thread, wait for the first frame, stop the session, and return a
PIL Image. Two seconds is the timeout per call.
"""

from __future__ import annotations

import sys
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from PIL import Image as PILImage


def is_supported() -> bool:
    """Return True if WGC capture is wired up on this host."""
    if sys.platform != "win32":
        return False
    try:
        import windows_capture
    except ImportError:
        return False
    return True


def capture_window(hwnd: int, *, timeout_s: float = 2.0) -> PILImage.Image:
    """Capture a window via WGC and return a PIL RGB image.

    Args:
        hwnd: A valid HWND. The capture target stays bound to this exact handle
            (so the result is correct even if the window's title changes mid-
            capture or the user has multiple instances of the app open).
        timeout_s: Max seconds to wait for the first frame. WGC normally
            delivers within ~50 ms; the timeout guards against rare cases
            where the compositor hasn't produced a frame yet (e.g. minimized
            windows or windows that just appeared).

    Returns:
        PIL Image (RGB).

    Raises:
        OSError: on non-Windows hosts.
        ImportError: if ``windows-capture`` isn't installed.
        RuntimeError: if no frame arrived within ``timeout_s``.
    """
    if sys.platform != "win32":
        raise OSError("WGC is Windows-only")
    return _capture(window_hwnd=int(hwnd), monitor_index=None, timeout_s=timeout_s)


def capture_monitor(monitor_index: int, *, timeout_s: float = 2.0) -> PILImage.Image:
    """Capture a single monitor via WGC.

    Args:
        monitor_index: 1-based monitor index (matches ``windows-capture``'s
            convention; index 0 is invalid here — use mss for the virtual
            desktop).
        timeout_s: Max seconds to wait for the first frame.

    Returns:
        PIL Image (RGB).
    """
    if sys.platform != "win32":
        raise OSError("WGC is Windows-only")
    if monitor_index < 1:
        raise ValueError("monitor_index must be >= 1 for WGC monitor capture")
    return _capture(window_hwnd=None, monitor_index=int(monitor_index), timeout_s=timeout_s)


def _capture(
    *, window_hwnd: int | None, monitor_index: int | None, timeout_s: float
) -> PILImage.Image:
    """Drive a one-shot ``windows-capture`` session."""
    from PIL import Image
    from windows_capture import Frame, InternalCaptureControl, WindowsCapture

    frame_holder: dict[str, Any] = {}
    error_holder: dict[str, str] = {}
    done = threading.Event()

    capture = WindowsCapture(
        cursor_capture=False,
        draw_border=False,
        monitor_index=monitor_index,
        window_hwnd=window_hwnd,
    )

    @capture.event  # type: ignore[misc]
    def on_frame_arrived(frame: Frame, capture_control: InternalCaptureControl) -> None:
        try:
            # frame.frame_buffer is a numpy uint8 array shaped (H, W, 4) in
            # BGRA order. Convert to RGB and stash a copy (the underlying
            # buffer is reused by the next frame).
            buf = frame.frame_buffer
            rgb = buf[..., [2, 1, 0]].copy()
            frame_holder["image"] = Image.fromarray(rgb, mode="RGB")
        except Exception as exc:  # pragma: no cover - exotic image shapes
            error_holder["err"] = f"frame conversion failed: {exc}"
        finally:
            done.set()
            try:
                capture_control.stop()
            except Exception:
                pass

    @capture.event  # type: ignore[misc]
    def on_closed() -> None:
        done.set()

    # Run the capture on a dedicated worker thread so we can wait on `done`
    # from the caller without blocking the event loop. ``start_free_threaded``
    # is the windows-capture helper that does exactly this.
    try:
        capture.start_free_threaded()
    except Exception as exc:
        raise RuntimeError(f"WGC start_free_threaded failed: {exc}") from exc

    if not done.wait(timeout=timeout_s):
        raise RuntimeError(f"WGC produced no frames within {timeout_s}s")

    if "image" in frame_holder:
        return frame_holder["image"]
    err = error_holder.get("err", "no frame and no error")
    raise RuntimeError(f"WGC capture failed: {err}")
