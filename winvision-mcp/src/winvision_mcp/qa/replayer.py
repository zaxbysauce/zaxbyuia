"""Deterministic replayer for recorded JSONL scripts.

Replays a previously-recorded session by invoking the same tool functions in
order. We deliberately avoid any LLM calls — replays should be free, fast, and
reproducible in CI.

Tools that are inherently non-deterministic (``screenshot_*``, ``assert_visual``,
``baseline_compare``) are still executable but their results are reported as
"observation" rather than "control flow." The replayer never branches on tool
output: it runs the recorded sequence exactly.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..models import ReplayReport


def replay(
    path: str | Path,
    *,
    tool_dispatch: Callable[[str, dict[str, Any]], Any],
    speed: float = 1.0,
    strict: bool = True,
) -> ReplayReport:
    """Replay a recorded JSONL script.

    Args:
        path: path to a JSONL file produced by :mod:`recorder`.
        tool_dispatch: callable ``(tool_name, args) -> result`` provided by the
            server (so we don't import the tool registry at module-load time).
        speed: 1.0 = realtime. 2.0 = twice as fast. Inter-step sleeps based on
            recorded timestamps are scaled by ``1.0 / speed``.
        strict: if True, the first failing step aborts the replay; if False,
            failed steps are noted and replay continues.

    Returns:
        :class:`ReplayReport`.
    """
    p = Path(path)
    if not p.is_file():
        return ReplayReport(
            script_path=str(p),
            steps_total=0,
            steps_passed=0,
            steps_failed=0,
            duration_s=0.0,
            failure_reason=f"script not found: {p}",
        )

    lines = [ln for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]
    total = len(lines)
    passed = 0
    failed = 0
    failed_idx: int | None = None
    failure: str | None = None

    t_start = time.monotonic()
    prev_ts: float | None = None
    for i, raw in enumerate(lines):
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError as exc:
            failed += 1
            if strict:
                failed_idx = i
                failure = f"invalid JSON on step {i}: {exc}"
                break
            continue

        tool = str(entry.get("tool", ""))
        args = dict(entry.get("args", {}))
        ts = _parse_iso(entry.get("ts"))

        if prev_ts is not None and ts is not None and speed > 0:
            delta = max(0.0, ts - prev_ts) / float(speed)
            # Cap interstep sleep at 5s to keep replays fast.
            time.sleep(min(5.0, delta))
        prev_ts = ts

        try:
            tool_dispatch(tool, args)
            passed += 1
        except Exception as exc:
            failed += 1
            if strict:
                failed_idx = i
                failure = f"step {i} ({tool}) failed: {exc}"
                break

    duration = time.monotonic() - t_start
    return ReplayReport(
        script_path=str(p),
        steps_total=total,
        steps_passed=passed,
        steps_failed=failed,
        duration_s=duration,
        failed_step_index=failed_idx,
        failure_reason=failure,
    )


def _parse_iso(s: Any) -> float | None:
    if not isinstance(s, str):
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None
