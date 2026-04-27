"""Capture backends and the unified capture API.

This package exposes three capture strategies:

- :mod:`wgc_backend` — Windows.Graphics.Capture via winrt; primary on Win10+.
- :mod:`mss_backend` — Cross-backend desktop / region capture, fallback.
- :mod:`window_backend` — PrintWindow + PW_RENDERFULLCONTENT for occluded windows.

Use :func:`capture_desktop`, :func:`capture_window`, :func:`capture_region` from
this module to get a fully-formed PIL Image without caring about the backend.
"""

from __future__ import annotations

from .api import (
    capture_desktop,
    capture_region,
    capture_window,
    downsample_to_max_edge,
    encode_png_bytes,
    list_monitors,
)

__all__ = [
    "capture_desktop",
    "capture_region",
    "capture_window",
    "downsample_to_max_edge",
    "encode_png_bytes",
    "list_monitors",
]
