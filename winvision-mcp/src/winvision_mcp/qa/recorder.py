"""JSONL session recorder.

When a session is active, every tool invocation is appended as one JSON line:

  {"ts": "...", "tool": "click_at", "args": {...}}

These scripts can be replayed deterministically by :mod:`winvision_mcp.qa.replayer`
without invoking any LLM (zero cost in CI).
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..storage import record_session


class _RecorderState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.name: str | None = None
        self.path: Path | None = None
        self.count: int = 0


_state = _RecorderState()


def is_recording() -> bool:
    return _state.name is not None


def start(session_name: str) -> Path:
    """Start a new recording session.

    Args:
        session_name: Identifier (becomes the JSONL filename stem).

    Returns:
        Path of the JSONL file.

    Raises:
        RuntimeError: if a session is already active.
    """
    settings = get_settings()
    settings.ensure_dirs()
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_name)
    path = settings.recordings_dir / f"{safe}.jsonl"
    with _state.lock:
        if _state.name is not None:
            raise RuntimeError(f"recording already in progress: {_state.name}")
        _state.name = session_name
        _state.path = path
        _state.count = 0
        path.write_text("", encoding="utf-8")
    return path


def stop() -> tuple[str, Path, int]:
    """Stop the active recording.

    Returns:
        ``(name, path, count)`` for the recording just closed.
    """
    with _state.lock:
        if _state.name is None or _state.path is None:
            raise RuntimeError("no recording in progress")
        name = _state.name
        path = _state.path
        count = _state.count
        _state.name = None
        _state.path = None
        _state.count = 0
    record_session(name=name, script_path=str(path), tool_count=count)
    return name, path, count


def record_invocation(tool: str, args: dict[str, Any]) -> None:
    """Append a tool invocation to the active recording (no-op if not recording)."""
    with _state.lock:
        if _state.name is None or _state.path is None:
            return
        line = json.dumps(
            {
                "ts": datetime.now(tz=UTC).isoformat(),
                "tool": tool,
                "args": _scrub(args),
            },
            default=str,
        )
        with _state.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        _state.count += 1


def _scrub(args: dict[str, Any]) -> dict[str, Any]:
    """Strip non-serializable values."""
    out: dict[str, Any] = {}
    for k, v in args.items():
        if k.startswith("_"):
            continue
        try:
            json.dumps(v, default=str)
            out[k] = v
        except Exception:
            out[k] = repr(v)
    return out
