"""QA tools: assertions, baselines, recorder/replayer."""

from __future__ import annotations

import sys
from typing import Any

from pydantic import Field

from ..models import ElementQuery, OkResult, Rect, ToolError
from ._helpers import tool_telemetry


def register(mcp: Any) -> None:
    @mcp.tool
    async def assert_visual(
        ctx: Any,
        description: str = Field(..., description="Natural-language expectation."),
        window_title: str | None = Field(None, description="Window to capture; None = foreground."),
        model_hint: str | None = Field(None, description="Optional model name hint for sampling."),
    ) -> dict[str, Any]:
        """Vision-LLM assertion: capture a screenshot and ask the client's LLM to grade it.

        Uses MCP **sampling** so no API key lives in the server. Returns
        ``{passed, confidence, reasoning}``. For structural checks (a button is
        visible, a string is present in the UIA tree) prefer
        :func:`assert_element_visible` / :func:`assert_text_present` —
        they're free and deterministic.
        """
        from .. import capture as cap
        from ..config import get_settings
        from ..qa.assertions import visual_assert_via_sampling

        with tool_telemetry(
            "assert_visual",
            {"description": description, "window_title": window_title, "model_hint": model_hint},
        ):
            if window_title:
                from ..input.focus import find_window

                w = find_window(title_regex=window_title)
                if w is None:
                    return ToolError(error="not_found", message="no matching window").model_dump()
                img = cap.capture_window(w.hwnd)
            else:
                img = cap.capture_desktop()
            img = cap.downsample_to_max_edge(img)

            persist = ""
            try:
                settings = get_settings()
                persist_path = settings.screenshots_dir / "assert_visual_latest.png"
                img.save(persist_path, format="PNG")
                persist = str(persist_path)
            except Exception:
                pass

            verdict = await visual_assert_via_sampling(
                ctx=ctx, description=description, image=img,
                model_hint=model_hint, persist_path=persist,
            )
            return verdict

    @mcp.tool
    def assert_element_visible(query: ElementQuery) -> dict[str, Any]:
        """Deterministic assertion: an element matching ``query`` is visible.

        No LLM call. Returns ``{passed: bool, match: ElementInfo | None}``.
        """
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..qa.assertions import assert_element_visible as _assert

        with tool_telemetry("assert_element_visible", {"query": query.model_dump()}):
            return _assert(query)

    @mcp.tool
    def assert_text_present(
        text: str = Field(..., description="Substring to search for."),
        window_title: str | None = Field(None),
        use_ocr: bool = Field(False, description="Try OCR fallback if UIA misses."),
    ) -> dict[str, Any]:
        """Check whether some text is present in the UIA tree (or via OCR)."""
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..qa.assertions import assert_text_present as _assert

        with tool_telemetry(
            "assert_text_present",
            {"text": text[:200], "window_title": window_title, "use_ocr": use_ocr},
        ):
            return _assert(text, window_title=window_title, use_ocr=use_ocr)

    @mcp.tool
    def baseline_capture(
        name: str = Field(..., description="Baseline identifier (also the filename stem)."),
        window_title: str = Field(..., description="Window to capture."),
        notes: str = Field("", description="Free-form notes."),
    ) -> dict[str, Any]:
        """Save the current state of a window as a named visual baseline."""
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from .. import capture as cap
        from ..input.focus import find_window
        from ..qa.baselines import save_baseline

        with tool_telemetry(
            "baseline_capture",
            {"name": name, "window_title": window_title, "notes": notes[:200]},
        ):
            w = find_window(title_regex=window_title)
            if w is None:
                return ToolError(error="not_found", message="no matching window").model_dump()
            img = cap.capture_window(w.hwnd)
            info = save_baseline(name, img, window_title=window_title, notes=notes)
            return info.model_dump()

    @mcp.tool
    def baseline_compare(
        name: str = Field(..., description="Baseline name to compare against."),
        window_title: str = Field(..., description="Window to capture for comparison."),
        threshold_ssim: float = Field(0.98, ge=0.0, le=1.0),
        mask_regions: list[Rect] = Field(default_factory=list),
    ) -> dict[str, Any]:
        """Compare a fresh capture against a named baseline using SSIM + region diff."""
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from .. import capture as cap
        from ..input.focus import find_window
        from ..qa.baselines import compare_to_baseline

        with tool_telemetry(
            "baseline_compare",
            {
                "name": name,
                "window_title": window_title,
                "threshold_ssim": threshold_ssim,
                "mask_count": len(mask_regions),
            },
        ):
            w = find_window(title_regex=window_title)
            if w is None:
                return ToolError(error="not_found", message="no matching window").model_dump()
            img = cap.capture_window(w.hwnd)
            return compare_to_baseline(
                name, img, threshold_ssim=threshold_ssim, mask_regions=mask_regions
            )

    @mcp.tool
    def list_baselines() -> list[dict[str, Any]]:
        """List all stored baselines."""
        from ..storage import list_baselines as _ls

        with tool_telemetry("list_baselines", {}):
            return [b.model_dump() for b in _ls()]

    @mcp.tool
    def start_recording(
        session_name: str = Field(..., description="Identifier for the recording."),
    ) -> dict[str, Any]:
        """Start recording subsequent tool invocations to a JSONL script."""
        from ..qa import recorder

        with tool_telemetry("start_recording", {"session_name": session_name}):
            try:
                path = recorder.start(session_name)
                return OkResult(message=f"recording -> {path}").model_dump() | {"path": str(path)}
            except RuntimeError as exc:
                return ToolError(error="already_recording", message=str(exc)).model_dump()

    @mcp.tool
    def stop_recording() -> dict[str, Any]:
        """Stop the active recording and return the script path + step count."""
        from ..qa import recorder

        with tool_telemetry("stop_recording", {}):
            try:
                name, path, count = recorder.stop()
                return {"name": name, "path": str(path), "tool_count": count}
            except RuntimeError as exc:
                return ToolError(error="no_recording", message=str(exc)).model_dump()

    @mcp.tool
    def replay_script(
        path: str = Field(..., description="Path to a JSONL script."),
        speed: float = Field(1.0, gt=0.0, le=20.0),
        strict: bool = Field(True, description="Abort on first failed step."),
    ) -> dict[str, Any]:
        """Replay a recorded script. Deterministic — no LLM calls."""
        from ..qa.replayer import replay
        from ..server import get_tool_dispatch

        with tool_telemetry("replay_script", {"path": path, "speed": speed, "strict": strict}):
            dispatch = get_tool_dispatch()
            report = replay(path, tool_dispatch=dispatch, speed=speed, strict=strict)
            return report.model_dump()

    _ = (
        assert_visual, assert_element_visible, assert_text_present,
        baseline_capture, baseline_compare, list_baselines,
        start_recording, stop_recording, replay_script,
    )
