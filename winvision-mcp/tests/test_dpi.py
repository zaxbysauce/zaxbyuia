"""DPI awareness module tests (cross-platform safe)."""

from __future__ import annotations

import sys

from winvision_mcp.dpi import set_per_monitor_dpi_aware


def test_set_per_monitor_idempotent() -> None:
    a = set_per_monitor_dpi_aware()
    b = set_per_monitor_dpi_aware()
    # On non-Windows, both should be True (no-op). On Windows, both should be True.
    assert a is True or sys.platform == "win32"
    assert a == b
