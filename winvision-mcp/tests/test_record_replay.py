"""Record/replay round-trip tests (cross-platform safe)."""

from __future__ import annotations

import json
from pathlib import Path

from winvision_mcp.qa import recorder
from winvision_mcp.qa.replayer import replay


def test_recorder_writes_one_jsonl_line_per_invocation(tmp_path: Path) -> None:
    path = recorder.start("unit-test")
    try:
        recorder.record_invocation("foo", {"x": 1})
        recorder.record_invocation("bar", {"y": "hello"})
    finally:
        name, p, count = recorder.stop()

    assert count == 2
    assert Path(p).is_file()
    lines = Path(p).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    e0 = json.loads(lines[0])
    e1 = json.loads(lines[1])
    assert e0["tool"] == "foo"
    assert e1["args"]["y"] == "hello"


def test_replayer_invokes_each_step_in_order(tmp_path: Path) -> None:
    path = recorder.start("replay-test")
    recorder.record_invocation("alpha", {"v": 1})
    recorder.record_invocation("beta", {"v": 2})
    recorder.record_invocation("gamma", {"v": 3})
    _, script_path, _ = recorder.stop()

    seen: list[tuple[str, dict]] = []

    def dispatch(tool: str, args: dict) -> None:
        seen.append((tool, args))

    report = replay(script_path, tool_dispatch=dispatch, speed=100.0, strict=True)
    assert report.steps_total == 3
    assert report.steps_passed == 3
    assert report.steps_failed == 0
    assert [t for t, _ in seen] == ["alpha", "beta", "gamma"]


def test_replayer_strict_mode_aborts_on_first_failure(tmp_path: Path) -> None:
    path = recorder.start("fail-test")
    recorder.record_invocation("ok", {})
    recorder.record_invocation("explode", {})
    recorder.record_invocation("never_called", {})
    _, script_path, _ = recorder.stop()

    def dispatch(tool: str, args: dict) -> None:
        if tool == "explode":
            raise RuntimeError("boom")

    report = replay(script_path, tool_dispatch=dispatch, speed=100.0, strict=True)
    assert report.steps_total == 3
    assert report.steps_passed == 1
    assert report.failed_step_index == 1
    assert "boom" in (report.failure_reason or "")
