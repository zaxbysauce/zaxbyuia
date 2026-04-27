"""System-level tools (system info, clipboard, process memory)."""

from __future__ import annotations

import getpass
import os
import platform
import sys
from typing import Any

from pydantic import Field

from ..models import OkResult, ToolError
from ..security.allowlist import check_window_title
from ._helpers import to_mcp_image, tool_telemetry


def register(mcp: Any) -> None:
    @mcp.tool
    def get_system_info() -> dict[str, Any]:
        """Return a snapshot of host info: OS, monitors, DPI, user, admin status."""
        with tool_telemetry("get_system_info", {}):
            info: dict[str, Any] = {
                "os": platform.platform(),
                "os_release": platform.release(),
                "python": sys.version.split()[0],
                "user": _safe_user(),
                "is_admin": _is_admin(),
                "primary_language": _primary_language(),
                "monitors": _monitors_with_dpi(),
                "has_uiaccess": _has_uiaccess(),
            }
            return info

    @mcp.tool
    def read_clipboard() -> dict[str, Any]:
        """Read the system clipboard.

        Returns ``{type: "text", text: ...}`` or ``{type: "image", image: <Image>}``
        or ``{type: "empty"}``.
        """
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()

        with tool_telemetry("read_clipboard", {}):
            try:
                import io

                import win32clipboard  # type: ignore[import-not-found]
                import win32con  # type: ignore[import-not-found]
                from PIL import Image

                win32clipboard.OpenClipboard()
                try:
                    if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                        text = str(win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT))
                        return {"type": "text", "text": text}
                    if win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
                        data = win32clipboard.GetClipboardData(win32con.CF_DIB)
                        # CF_DIB lacks the 14-byte BITMAPFILEHEADER; prepend it.
                        bmp = b"BM" + (len(data) + 14).to_bytes(4, "little") + b"\x00\x00\x00\x00" + (54).to_bytes(4, "little") + data
                        img = Image.open(io.BytesIO(bmp))
                        return {"type": "image", "image": to_mcp_image(img)}
                    return {"type": "empty"}
                finally:
                    win32clipboard.CloseClipboard()
            except Exception as exc:
                return ToolError(error="clipboard_failed", message=str(exc)).model_dump()

    @mcp.tool
    def write_clipboard(
        content: str = Field(..., description="Text to copy to the clipboard."),
        dry_run: bool = Field(False),
    ) -> dict[str, Any]:
        """Write text to the system clipboard. Allowlist-gated."""
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        decision = check_window_title("clipboard", action="write_clipboard")
        if not decision.allowed:
            return ToolError(error="forbidden", message=decision.reason).model_dump()
        if dry_run:
            return OkResult(message=f"DRY-RUN: would copy {len(content)} chars").model_dump()
        with tool_telemetry("write_clipboard", {"len": len(content), "dry_run": dry_run}):
            try:
                import win32clipboard  # type: ignore[import-not-found]
                import win32con  # type: ignore[import-not-found]

                win32clipboard.OpenClipboard()
                try:
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, content)
                finally:
                    win32clipboard.CloseClipboard()
                return OkResult(message=f"copied {len(content)} chars").model_dump()
            except Exception as exc:
                return ToolError(error="clipboard_failed", message=str(exc)).model_dump()

    @mcp.tool
    def get_process_memory(pid: int = Field(..., description="Target PID.")) -> dict[str, Any]:
        """Return ``{working_set, private, handles, threads}`` for a process.

        Useful for catching memory leaks in Electron / Chromium-based apps over
        long-running test runs. All values are in bytes (memory) or counts.
        """
        with tool_telemetry("get_process_memory", {"pid": pid}):
            try:
                import psutil  # type: ignore[import-not-found]

                p = psutil.Process(pid)
                mem = p.memory_info()
                return {
                    "pid": pid,
                    "name": p.name(),
                    "working_set": int(getattr(mem, "rss", 0)),
                    "private": int(getattr(mem, "private", getattr(mem, "vms", 0))),
                    "handles": int(getattr(p, "num_handles", lambda: 0)() if sys.platform == "win32" else 0),
                    "threads": int(p.num_threads()),
                }
            except Exception as exc:
                return ToolError(error="psutil_failed", message=str(exc)).model_dump()

    @mcp.tool
    def get_allowlist_policy() -> dict[str, Any]:
        """Return the active allowlist policy snapshot (read-only)."""
        from ..security.allowlist import summarize_policy

        with tool_telemetry("get_allowlist_policy", {}):
            return summarize_policy()

    _ = (get_system_info, read_clipboard, write_clipboard, get_process_memory, get_allowlist_policy)


def _safe_user() -> str:
    try:
        return getpass.getuser()
    except Exception:
        return os.environ.get("USERNAME", os.environ.get("USER", ""))


def _is_admin() -> bool:
    if sys.platform != "win32":
        return os.geteuid() == 0  # type: ignore[attr-defined]
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except Exception:
        return False


def _primary_language() -> str:
    try:
        import locale

        return locale.getdefaultlocale()[0] or ""
    except Exception:
        return ""


def _monitors_with_dpi() -> list[dict[str, Any]]:
    try:
        from .. import capture as cap

        out: list[dict[str, Any]] = []
        for i, m in enumerate(cap.list_monitors()):
            out.append({"index": i, **m, "dpi": 96})
        return out
    except Exception:
        return []


def _has_uiaccess() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        advapi = ctypes.windll.advapi32  # type: ignore[attr-defined]

        TOKEN_QUERY = 0x0008
        TokenUIAccess = 26

        h_proc = kernel32.GetCurrentProcess()
        h_tok = wintypes.HANDLE()
        if not advapi.OpenProcessToken(h_proc, TOKEN_QUERY, ctypes.byref(h_tok)):
            return False
        try:
            ui = wintypes.DWORD(0)
            ret_len = wintypes.DWORD(0)
            if not advapi.GetTokenInformation(
                h_tok, TokenUIAccess, ctypes.byref(ui),
                ctypes.sizeof(ui), ctypes.byref(ret_len),
            ):
                return False
            return bool(ui.value)
        finally:
            kernel32.CloseHandle(h_tok)
    except Exception:
        return False
