"""SQLite database access (sync; the volume here is tiny — no async needed).

We keep this synchronous because:
- Per-invocation logging happens once per tool call (~10/s peak).
- FastMCP runs tools in threads, so a sync sqlite call is fine.
- ``aiosqlite`` is listed for users who want it from external code.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..models import BaselineInfo

_lock = threading.Lock()
_initialized = False
_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _connect() -> sqlite3.Connection:
    settings = get_settings()
    settings.ensure_dirs()
    conn = sqlite3.connect(settings.db_path, isolation_level=None, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def init_db() -> None:
    """Create tables if they don't exist (idempotent)."""
    global _initialized
    with _lock:
        if _initialized:
            return
        schema = _SCHEMA_PATH.read_text(encoding="utf-8")
        conn = _connect()
        try:
            conn.executescript(schema)
        finally:
            conn.close()
        _initialized = True


def hash_args(args: dict[str, Any]) -> str:
    """Stable SHA256 of a JSON-serialized arg dict."""
    try:
        blob = json.dumps(args, sort_keys=True, default=str).encode("utf-8")
    except Exception:
        blob = repr(args).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def log_invocation(
    *, tool: str, args: dict[str, Any], outcome: str, duration_ms: int, error: str | None = None
) -> None:
    """Log a single tool invocation."""
    init_db()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO invocations (ts, tool, args_hash, outcome, duration_ms, error) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_now_iso(), tool, hash_args(args), outcome, duration_ms, error),
        )
    finally:
        conn.close()


def log_assertion(
    *,
    description: str,
    passed: bool,
    confidence: float,
    reasoning: str,
    screenshot_path: str = "",
) -> None:
    init_db()
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO assertions (ts, description, passed, confidence, reasoning, screenshot_path) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (_now_iso(), description, 1 if passed else 0, float(confidence), reasoning, screenshot_path),
        )
    finally:
        conn.close()


def record_baseline(info: BaselineInfo) -> None:
    """Insert-or-replace a baseline row."""
    init_db()
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO baselines "
            "(name, window_title, created_at, png_path, width, height, dpi, notes, hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                info.name,
                info.window_title,
                info.created_at,
                info.png_path,
                info.width,
                info.height,
                info.dpi,
                info.notes,
                info.hash,
            ),
        )
    finally:
        conn.close()


def get_baseline(name: str) -> BaselineInfo | None:
    init_db()
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM baselines WHERE name = ?", (name,)).fetchone()
        if row is None:
            return None
        return BaselineInfo(
            name=row["name"],
            window_title=row["window_title"] or "",
            created_at=row["created_at"],
            png_path=row["png_path"],
            width=row["width"],
            height=row["height"],
            dpi=row["dpi"],
            notes=row["notes"] or "",
            hash=row["hash"],
        )
    finally:
        conn.close()


def list_baselines() -> list[BaselineInfo]:
    init_db()
    conn = _connect()
    try:
        rows = conn.execute("SELECT * FROM baselines ORDER BY created_at DESC").fetchall()
        return [
            BaselineInfo(
                name=r["name"],
                window_title=r["window_title"] or "",
                created_at=r["created_at"],
                png_path=r["png_path"],
                width=r["width"],
                height=r["height"],
                dpi=r["dpi"],
                notes=r["notes"] or "",
                hash=r["hash"],
            )
            for r in rows
        ]
    finally:
        conn.close()


def record_session(*, name: str, script_path: str, tool_count: int) -> None:
    init_db()
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO sessions (name, created_at, script_path, tool_count) "
            "VALUES (?, ?, ?, ?)",
            (name, _now_iso(), script_path, tool_count),
        )
    finally:
        conn.close()
