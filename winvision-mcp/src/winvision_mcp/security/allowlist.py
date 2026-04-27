"""Allowlist policy.

Three modes:

- ``strict``: only entities present on the allowlist are allowed.
- ``permissive_with_confirm``: read-style operations are allowed; destructive
  ones are **logged** (one row per invocation in ``invocations`` SQLite table)
  but proceed automatically. We do NOT prompt the user — genuine
  human-in-the-loop confirmation is the MCP client's job (clients with
  elicitation can ask the user; clients without it should pair this mode with
  ``dry_run=True`` for review-then-execute workflows).
- ``off``: nothing is checked. The server logs a loud warning at startup.

The configured ``block_processes`` list (e.g. system processes like
``lsass.exe``) is enforced in ALL modes — there is never a way to send a kill
signal to ``lsass.exe`` through this server.

Future work (v1.x): wire ``permissive_with_confirm`` to MCP **elicitation**
when the connected client advertises support, so destructive calls actually
ask the user via a "Confirm? [Y/n]" round-trip.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..config import get_settings
from ..logging_setup import get_logger

logger = get_logger(__name__)


@dataclass
class AllowlistDecision:
    allowed: bool
    reason: str
    require_dry_run: bool = False


def is_blocked_process(name_or_pid: str | int) -> bool:
    """Return True if a process is unconditionally blocked.

    The block list is a hard floor that cannot be overridden by mode or
    allowlist entries.
    """
    settings = get_settings()
    if isinstance(name_or_pid, int):
        # Resolve PID -> exe name; if we can't, fail closed.
        name = _pid_to_name(name_or_pid)
    else:
        name = str(name_or_pid).lower()
    blocked = {p.lower() for p in settings.block_processes}
    return name.lower() in blocked


def _pid_to_name(pid: int) -> str:
    try:
        import psutil  # type: ignore[import-not-found]

        return psutil.Process(pid).name()
    except Exception:
        return ""


def check_process(name_or_pid: str | int, *, action: str = "kill") -> AllowlistDecision:
    """Decide whether a process-targeting destructive action is permitted."""
    settings = get_settings()
    if is_blocked_process(name_or_pid):
        return AllowlistDecision(False, f"{name_or_pid} is on the block list (cannot {action})")

    if settings.allowlist_mode == "off":
        return AllowlistDecision(True, "allowlist mode=off (insecure)")

    if settings.allowlist_mode == "permissive_with_confirm":
        return AllowlistDecision(True, f"permissive: {action} on {name_or_pid} will be logged",
                                 require_dry_run=False)

    # strict
    if isinstance(name_or_pid, int):
        name = _pid_to_name(name_or_pid)
    else:
        name = str(name_or_pid)
    allowed = {p.lower() for p in settings.allowlist_processes}
    if name.lower() in allowed:
        return AllowlistDecision(True, f"strict: {name} is on the allowlist")
    return AllowlistDecision(False, f"strict mode: {name} not on the allowlist")


def check_window_title(title: str, *, action: str = "interact") -> AllowlistDecision:
    """Decide whether a window-targeting action is permitted."""
    settings = get_settings()
    if settings.allowlist_mode == "off":
        return AllowlistDecision(True, "allowlist mode=off")
    if settings.allowlist_mode == "permissive_with_confirm":
        return AllowlistDecision(True, "permissive: action will be logged")
    # strict: title must match an allowlist entry (substring)
    needle = title.lower()
    for entry in settings.allowlist_window_titles:
        if entry.lower() in needle:
            return AllowlistDecision(True, f"strict: matched '{entry}'")
    return AllowlistDecision(False, "strict mode: window title not on the allowlist")


def summarize_policy() -> dict[str, object]:
    """Return a dict describing the active allowlist policy (for /status tools)."""
    s = get_settings()
    return {
        "mode": s.allowlist_mode,
        "processes": list(s.allowlist_processes),
        "window_titles": list(s.allowlist_window_titles),
        "block_processes": list(s.block_processes),
    }
