"""First-run diagnostics — verifies DPI awareness, COM init, admin status, etc."""

from __future__ import annotations

import sys
from typing import Any

from rich.console import Console
from rich.table import Table

from .config import get_settings
from .dpi import set_per_monitor_dpi_aware


def run() -> dict[str, Any]:
    """Run all checks and return a dict of results (also prints a table)."""
    console = Console(stderr=True)
    table = Table(title="WinVision Doctor", show_lines=False)
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail")

    results: dict[str, Any] = {}

    settings = get_settings()
    table.add_row("data_dir", "OK", str(settings.data_dir))
    results["data_dir"] = str(settings.data_dir)

    # DPI awareness
    dpi_ok = set_per_monitor_dpi_aware()
    table.add_row("DPI awareness", "OK" if dpi_ok else "WARN", "PER_MONITOR_AWARE_V2")
    results["dpi_aware"] = dpi_ok

    # Platform
    table.add_row("platform", "OK" if sys.platform == "win32" else "WARN", sys.platform)
    results["platform"] = sys.platform

    # Admin
    is_admin = _is_admin()
    table.add_row("running as admin", "OK" if is_admin else "INFO", str(is_admin))
    results["is_admin"] = is_admin

    # UIA COM init
    uia_ok, uia_detail = _check_uia()
    table.add_row("UIA COM", "OK" if uia_ok else "WARN", uia_detail)
    results["uia_ok"] = uia_ok

    # WGC
    wgc_ok, wgc_detail = _check_wgc()
    table.add_row("Windows.Graphics.Capture", "OK" if wgc_ok else "INFO", wgc_detail)
    results["wgc_ok"] = wgc_ok

    # Allowlist mode
    table.add_row("allowlist mode", "OK", settings.allowlist_mode)
    results["allowlist_mode"] = settings.allowlist_mode

    # FastMCP version
    try:
        import importlib.metadata as md

        fm_v = md.version("fastmcp")
    except Exception:
        fm_v = "unknown"
    table.add_row("fastmcp", "OK", fm_v)
    results["fastmcp_version"] = fm_v

    console.print(table)
    return results


def _is_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


def _check_uia() -> tuple[bool, str]:
    if sys.platform != "win32":
        return False, "non-Windows host"
    try:
        import uiautomation as auto  # type: ignore[import-not-found]

        root = auto.GetRootControl()
        return True, f"root='{root.Name}'"
    except Exception as exc:
        return False, str(exc)


def _check_wgc() -> tuple[bool, str]:
    from .capture import wgc_backend

    if not wgc_backend.is_supported():
        return False, "windows-capture not installed (pip install windows-capture)"
    try:
        import importlib.metadata as md

        return True, f"windows-capture {md.version('windows-capture')}"
    except Exception:
        return True, "available"


def main() -> None:  # pragma: no cover
    run()


if __name__ == "__main__":  # pragma: no cover
    main()
