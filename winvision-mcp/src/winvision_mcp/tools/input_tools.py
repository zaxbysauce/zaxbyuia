"""Interaction tools.

All UI-changing tools focus the target window and apply a small settle delay
before sending input. UIA patterns are tried first; SendInput is the fallback.
"""

from __future__ import annotations

import sys
import time
from typing import Any, Literal

from pydantic import Field

from ..models import ElementQuery, ElementRef, OkResult, ToolError
from ._helpers import tool_telemetry


def _focus_for(info: Any) -> bool:
    """Best-effort focus the window owning the element."""
    if not info or not getattr(info, "window_handle", 0):
        return False
    from ..input.focus import focus_window

    return focus_window(int(info.window_handle))


def register(mcp: Any) -> None:
    @mcp.tool
    def invoke_element(ref: ElementRef) -> dict[str, Any]:
        """Click/invoke a UIA element.

        Tries InvokePattern, then SelectionItemPattern, then TogglePattern.
        If none are supported, falls back to a SendInput click at the element's
        bounding-box center.
        """
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..input import sendinput
        from ..uia import patterns
        from ..uia.finder import resolve_ref

        with tool_telemetry("invoke_element", {"ref": ref.model_dump()}):
            res = resolve_ref(ref)
            if res is None:
                return ToolError(error="not_found", message="no matching element").model_dump()
            ctrl, info, _h = res
            # focus_window already sleeps `input_settle_ms` after focusing,
            # so callers don't add their own sleep.
            _focus_for(info)
            ok, fb, err = patterns.invoke(ctrl)
            if not ok:
                if info.rect:
                    cx, cy = info.rect.center
                    sendinput.click_at(cx, cy)
                    return OkResult(message="invoked via fallback click_at").model_dump()
                return ToolError(error="not_invokable", message=err or "no invocation path").model_dump()
            return OkResult(message=f"invoked{' (fallback)' if fb else ''}").model_dump()

    @mcp.tool
    def set_value(
        ref: ElementRef,
        value: str = Field(..., description="The new text/value."),
    ) -> dict[str, Any]:
        """Set the value of an Edit/ComboBox-like element.

        Tries ValuePattern.SetValue first; falls back to focus + Ctrl+A + type.
        """
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..input import sendinput
        from ..uia import patterns
        from ..uia.finder import resolve_ref

        with tool_telemetry("set_value", {"ref": ref.model_dump(), "value_len": len(value)}):
            res = resolve_ref(ref)
            if res is None:
                return ToolError(error="not_found", message="no matching element").model_dump()
            ctrl, info, _h = res
            _focus_for(info)
            ok, _fb, err = patterns.set_value(ctrl, value)
            if ok:
                return OkResult(message="value set via pattern").model_dump()
            # Fallback: click the element, select-all, type.
            if info.rect:
                cx, cy = info.rect.center
                sendinput.click_at(cx, cy)
                time.sleep(0.05)
                sendinput.send_keys("^a{DEL}")
                sendinput.type_text(value)
                return OkResult(message="value set via type fallback").model_dump()
            return ToolError(error="set_value_failed", message=err).model_dump()

    @mcp.tool
    def toggle_element(ref: ElementRef) -> dict[str, Any]:
        """Toggle a CheckBox / ToggleButton via TogglePattern."""
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..uia import patterns
        from ..uia.finder import resolve_ref

        with tool_telemetry("toggle_element", {"ref": ref.model_dump()}):
            res = resolve_ref(ref)
            if res is None:
                return ToolError(error="not_found", message="no matching element").model_dump()
            ctrl, info, _h = res
            _focus_for(info)
            ok, _fb, err = patterns.toggle(ctrl)
            return OkResult(message="toggled").model_dump() if ok else ToolError(
                error="toggle_failed", message=err
            ).model_dump()

    @mcp.tool
    def select_item(ref: ElementRef) -> dict[str, Any]:
        """Select a ListItem/TabItem/ComboBoxItem via SelectionItemPattern."""
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..uia import patterns
        from ..uia.finder import resolve_ref

        with tool_telemetry("select_item", {"ref": ref.model_dump()}):
            res = resolve_ref(ref)
            if res is None:
                return ToolError(error="not_found", message="no matching element").model_dump()
            ctrl, info, _h = res
            _focus_for(info)
            ok, _fb, err = patterns.select_item(ctrl)
            return OkResult(message="selected").model_dump() if ok else ToolError(
                error="select_failed", message=err
            ).model_dump()

    @mcp.tool
    def expand_collapse(
        ref: ElementRef,
        action: Literal["expand", "collapse", "toggle"] = Field("toggle"),
    ) -> dict[str, Any]:
        """Expand/collapse a TreeItem / MenuItem / ComboBox dropdown."""
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..uia import patterns
        from ..uia.finder import resolve_ref

        with tool_telemetry("expand_collapse", {"ref": ref.model_dump(), "action": action}):
            res = resolve_ref(ref)
            if res is None:
                return ToolError(error="not_found", message="no matching element").model_dump()
            ctrl, info, _h = res
            _focus_for(info)
            ok, _fb, err = patterns.expand_collapse(ctrl, action)
            return OkResult(message=f"{action} applied").model_dump() if ok else ToolError(
                error="expand_collapse_failed", message=err
            ).model_dump()

    @mcp.tool
    def scroll_element(
        ref: ElementRef,
        direction: Literal["up", "down", "left", "right"] = Field("down"),
        amount: float = Field(1.0, gt=0.0),
    ) -> dict[str, Any]:
        """Scroll a scrollable container."""
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..uia import patterns
        from ..uia.finder import resolve_ref

        with tool_telemetry(
            "scroll_element", {"ref": ref.model_dump(), "direction": direction, "amount": amount}
        ):
            res = resolve_ref(ref)
            if res is None:
                return ToolError(error="not_found", message="no matching element").model_dump()
            ctrl, info, _h = res
            _focus_for(info)
            ok, _fb, err = patterns.scroll(ctrl, direction, amount)
            return OkResult(message="scrolled").model_dump() if ok else ToolError(
                error="scroll_failed", message=err
            ).model_dump()

    @mcp.tool
    def click_at(
        x: int = Field(..., description="X in physical px (virtual-desktop coords)."),
        y: int = Field(..., description="Y in physical px."),
        button: Literal["left", "right", "middle"] = Field("left"),
        count: int = Field(1, ge=1, le=3),
    ) -> dict[str, Any]:
        """Synthesize a mouse click at a virtual-desktop coordinate.

        Prefer :func:`invoke_element` whenever you have an ``automation_id``;
        pixel clicks are fragile under DPI changes and animations.
        """
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..input import sendinput

        with tool_telemetry("click_at", {"x": x, "y": y, "button": button, "count": count}):
            sendinput.click_at(x, y, button=button, count=count)
            return OkResult(message=f"{button} click at ({x},{y})x{count}").model_dump()

    @mcp.tool
    def drag(
        from_x: int, from_y: int, to_x: int, to_y: int,
        duration_ms: int = Field(300, ge=10, le=10000),
    ) -> dict[str, Any]:
        """Mouse-drag from (from_x, from_y) to (to_x, to_y) over ``duration_ms`` ms."""
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..input import sendinput

        with tool_telemetry(
            "drag",
            {"from_x": from_x, "from_y": from_y, "to_x": to_x, "to_y": to_y, "duration_ms": duration_ms},
        ):
            sendinput.drag(from_x, from_y, to_x, to_y, duration_ms=duration_ms)
            return OkResult(message="drag complete").model_dump()

    @mcp.tool
    def type_text(
        text: str = Field(..., description="Unicode text to type."),
        interval_ms: int = Field(5, ge=0, le=1000),
    ) -> dict[str, Any]:
        """Type Unicode text via KEYEVENTF_UNICODE (full Unicode, layout-independent)."""
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..input import sendinput

        with tool_telemetry("type_text", {"text_len": len(text), "interval_ms": interval_ms}):
            sendinput.type_text(text, interval_ms=interval_ms)
            return OkResult(message=f"typed {len(text)} chars").model_dump()

    @mcp.tool
    def send_keys(
        keys: str = Field(..., description='pywinauto sequence, e.g. "^a{DEL}Hello{ENTER}"'),
    ) -> dict[str, Any]:
        """Send a pywinauto-style key sequence (modifiers + special keys)."""
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..input import sendinput

        with tool_telemetry("send_keys", {"keys": keys[:200]}):
            sendinput.send_keys(keys)
            return OkResult(message="keys sent").model_dump()

    @mcp.tool
    def focus_window(
        title_regex: str | None = Field(None),
        hwnd: int | None = Field(None),
    ) -> dict[str, Any]:
        """Bring a window to the foreground using the AttachThreadInput trick."""
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..input.focus import find_window
        from ..input.focus import focus_window as _focus

        with tool_telemetry("focus_window", {"title_regex": title_regex, "hwnd": hwnd}):
            if hwnd is None:
                w = find_window(title_regex=title_regex)
                if w is None:
                    return ToolError(error="not_found", message="no matching window").model_dump()
                hwnd = w.hwnd
            ok = _focus(int(hwnd))
            return OkResult(message=f"focused hwnd={hwnd}").model_dump() if ok else ToolError(
                error="focus_failed",
                message="SetForegroundWindow refused; try running with UIAccess (see docs).",
            ).model_dump()

    @mcp.tool
    def wait_for_element(
        query: ElementQuery,
        timeout_s: float = Field(10.0, gt=0.0, le=120.0),
        poll_ms: int = Field(200, ge=10, le=2000),
    ) -> dict[str, Any]:
        """Poll for an element matching ``query`` up to ``timeout_s`` seconds."""
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..uia.finder import wait_for_element as _wait

        with tool_telemetry(
            "wait_for_element",
            {"query": query.model_dump(), "timeout_s": timeout_s, "poll_ms": poll_ms},
        ):
            res = _wait(query, timeout_s=timeout_s, poll_ms=poll_ms)
            if res is None:
                return ToolError(error="timeout", message="element did not appear").model_dump()
            _ctrl, info, h = res
            return {"info": info.model_dump(), "handle": h}

    @mcp.tool
    def wait_for_idle(
        window_title: str = Field(..., description="Target window."),
        timeout_s: float = Field(5.0, gt=0.0, le=60.0),
    ) -> dict[str, Any]:
        """Wait for a window's process to be input-idle and CPU-quiescent."""
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..input.focus import find_window
        from ..input.focus import wait_for_idle as _wait_idle

        with tool_telemetry("wait_for_idle", {"window_title": window_title, "timeout_s": timeout_s}):
            w = find_window(title_regex=window_title)
            if w is None:
                return ToolError(error="not_found", message="no matching window").model_dump()
            ok = _wait_idle(w.hwnd, timeout_s=timeout_s)
            return OkResult(message="idle" if ok else "timeout reached").model_dump()

    _ = (
        invoke_element, set_value, toggle_element, select_item, expand_collapse,
        scroll_element, click_at, drag, type_text, send_keys, focus_window,
        wait_for_element, wait_for_idle,
    )
