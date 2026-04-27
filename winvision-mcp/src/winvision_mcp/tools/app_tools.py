"""Process / app lifecycle tools."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from pydantic import Field

from ..models import OkResult, ProcessInfo, ToolError
from ..security.allowlist import check_process, is_blocked_process
from ..storage import log_invocation
from ._helpers import tool_telemetry


def register(mcp: Any) -> None:
    @mcp.tool
    def launch_app(
        path: str = Field(..., description="Executable path or AUMID (e.g. for UWP apps)."),
        args: list[str] = Field(default_factory=list),
        cwd: str | None = Field(None, description="Working directory."),
        wait_for_window_s: float = Field(
            5.0, ge=0.0, le=60.0, description="Wait this many seconds for a top-level window."
        ),
    ) -> dict[str, Any]:
        """Launch an app and return ``{pid, hwnd}`` once a window appears.

        Supports both regular ``.exe`` paths and AUMIDs via the
        ``shell:AppsFolder\\<AUMID>`` trick. If no window appears within
        ``wait_for_window_s``, ``hwnd`` will be ``0``.
        """
        with tool_telemetry("launch_app", {"path": path, "args": args, "cwd": cwd}):
            if sys.platform != "win32":
                return ToolError(error="unsupported_platform", message="Windows-only").model_dump()

            is_aumid = "!" in path and not Path(path).exists()
            if is_aumid:
                # AUMID launch via Windows shell. NOTE: Popen.pid here is
                # explorer.exe's PID, not the launched UWP/MSIX app's PID.
                # We snapshot the process list before the launch and after
                # the window appears, then attribute the new PID to the
                # most-recently-spawned process whose window matches.
                from ..input.focus import list_windows

                cmdline = ["explorer", f"shell:AppsFolder\\{path}"]
                pre_pids = _snapshot_pids()
                proc = subprocess.Popen(cmdline, cwd=cwd)
                shell_pid = proc.pid  # explorer's PID — we'll override below
            else:
                cmdline = [path, *args]
                proc = subprocess.Popen(cmdline, cwd=cwd)
                shell_pid = proc.pid
                pre_pids = None  # not needed for direct .exe launches

            hwnd = 0
            real_pid = shell_pid
            if wait_for_window_s > 0:
                from ..input.focus import list_windows

                deadline = time.monotonic() + wait_for_window_s
                while time.monotonic() < deadline:
                    if is_aumid and pre_pids is not None:
                        # Look at NEW windows owned by NEW processes.
                        for w in list_windows(visible_only=True):
                            if w.pid not in pre_pids and w.title and w.process_name.lower() != "explorer.exe":
                                hwnd = w.hwnd
                                real_pid = w.pid
                                break
                    else:
                        for w in list_windows(visible_only=True):
                            if w.pid == shell_pid and w.title:
                                hwnd = w.hwnd
                                break
                    if hwnd:
                        break
                    time.sleep(0.1)
            return {"pid": int(real_pid), "hwnd": int(hwnd), "aumid": bool(is_aumid)}

    @mcp.tool
    def kill_process(
        pid: int | None = Field(None, description="PID to kill. Mutually exclusive with process_name."),
        process_name: str | None = Field(None, description="Exe basename (e.g. 'notepad.exe')."),
        force: bool = Field(False, description="Use SIGKILL/TerminateProcess."),
        dry_run: bool = Field(
            False,
            description="Log the intent but do NOT actually kill — useful for testing allowlist rules.",
        ),
    ) -> dict[str, Any]:
        """Terminate a process by PID or name.

        Subject to the allowlist policy: in ``strict`` mode the target must be
        on the configured allowlist; the global block list (lsass, winlogon, ...)
        is enforced unconditionally.
        """
        target: int | str
        if pid is not None:
            target = int(pid)
        elif process_name:
            target = process_name
        else:
            return ToolError(error="bad_args", message="pid or process_name required").model_dump()

        decision = check_process(target, action="kill")
        log_invocation(
            tool="kill_process",
            args={"target": target, "force": force, "dry_run": dry_run, "decision": decision.reason},
            outcome="dry_run" if dry_run else ("blocked" if not decision.allowed else "ok"),
            duration_ms=0,
        )
        if not decision.allowed:
            return ToolError(error="forbidden", message=decision.reason).model_dump()
        if dry_run:
            return OkResult(message=f"DRY-RUN: would kill {target} (force={force})").model_dump()

        if isinstance(target, int):
            ok = _kill_by_pid(target, force=force)
        else:
            ok = _kill_by_name(target, force=force)
        return OkResult(message=f"killed {target}").model_dump() if ok else ToolError(
            error="kill_failed", message=f"could not terminate {target}"
        ).model_dump()

    @mcp.tool
    def list_processes() -> list[dict[str, Any]]:
        """List running processes ``[{pid, name, exe, user}, ...]``."""
        with tool_telemetry("list_processes", {}):
            return [p.model_dump() for p in _list_processes()]

    @mcp.tool
    def is_running(process_name: str = Field(..., description="Exe basename.")) -> dict[str, Any]:
        """Return ``{running: bool, pids: [...]}`` for a process name."""
        with tool_telemetry("is_running", {"process_name": process_name}):
            try:
                import psutil  # type: ignore[import-not-found]

                pids = [p.pid for p in psutil.process_iter(["name"]) if (p.info.get("name") or "").lower() == process_name.lower()]
                return {"running": bool(pids), "pids": pids}
            except Exception as exc:
                return ToolError(error="psutil_failed", message=str(exc)).model_dump()

    _ = (launch_app, kill_process, list_processes, is_running, ProcessInfo)


def _snapshot_pids() -> set[int]:
    try:
        import psutil  # type: ignore[import-not-found]

        return {p.pid for p in psutil.process_iter(["pid"])}
    except Exception:
        return set()


def _kill_by_pid(pid: int, *, force: bool) -> bool:
    if is_blocked_process(pid):
        return False
    try:
        import psutil  # type: ignore[import-not-found]

        proc = psutil.Process(pid)
        if force:
            proc.kill()
        else:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except Exception:
                proc.kill()
        return True
    except Exception:
        try:
            os.kill(pid, 9)  # SIGKILL on POSIX; on Windows this maps to TerminateProcess.
            return True
        except Exception:
            return False


def _kill_by_name(name: str, *, force: bool) -> bool:
    try:
        import psutil  # type: ignore[import-not-found]

        any_killed = False
        for p in psutil.process_iter(["name", "pid"]):
            if (p.info.get("name") or "").lower() == name.lower():
                if is_blocked_process(p.pid):
                    continue
                try:
                    if force:
                        p.kill()
                    else:
                        p.terminate()
                    any_killed = True
                except Exception:
                    continue
        return any_killed
    except Exception:
        return False


def _list_processes() -> list[ProcessInfo]:
    try:
        import psutil  # type: ignore[import-not-found]

        out: list[ProcessInfo] = []
        for p in psutil.process_iter(["pid", "name", "exe", "username"]):
            try:
                out.append(
                    ProcessInfo(
                        pid=int(p.info.get("pid") or 0),
                        name=str(p.info.get("name") or ""),
                        exe=str(p.info.get("exe") or ""),
                        user=str(p.info.get("username") or ""),
                    )
                )
            except Exception:
                continue
        return out
    except Exception:
        return []
