"""UIA tools (``get_ui_tree``, ``find_elements``, ``list_windows``, ...)."""

from __future__ import annotations

import sys
from typing import Any

from pydantic import Field

from ..models import ElementQuery, ElementRef, ToolError, WindowInfo
from ._helpers import tool_telemetry


def register(mcp: Any) -> None:
    @mcp.tool
    def get_ui_tree(
        window_title: str | None = Field(None, description="Window title; None = foreground."),
        depth: int = Field(8, ge=1, le=32, description="Max walk depth."),
        visible_only: bool = Field(True, description="Skip IsOffscreen=true controls."),
        interactable_only: bool = Field(False, description="Only emit interactable types."),
        max_nodes: int = Field(500, ge=10, le=5000, description="Hard cap on total nodes."),
    ) -> dict[str, Any]:
        """Return a JSON tree of the target window's UI Automation hierarchy.

        Use this to understand a window's structure and find ``automation_id``s.
        For dense UIs prefer ``interactable_only=True`` to keep the response small.
        """
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()

        from ..uia.tree import get_window_control, serialize_tree

        with tool_telemetry(
            "get_ui_tree",
            {
                "window_title": window_title,
                "depth": depth,
                "visible_only": visible_only,
                "interactable_only": interactable_only,
                "max_nodes": max_nodes,
            },
        ):
            win = get_window_control(window_title)
            if win is None:
                return ToolError(error="not_found", message="no matching window").model_dump()
            return serialize_tree(
                win,
                depth=depth,
                visible_only=visible_only,
                interactable_only=interactable_only,
                max_nodes=max_nodes,
            )

    @mcp.tool
    def get_ui_tree_text(
        window_title: str | None = Field(None, description="Window to render."),
        depth: int = Field(6, ge=1, le=12),
        max_lines: int = Field(400, ge=20, le=4000),
    ) -> dict[str, Any]:
        """Return the UI tree as ASCII text (cheap for LLM context).

        Like ``tree /F`` but for UI elements. Each line shows
        ``<ControlType> 'Name' #automation_id``.
        """
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()

        from ..uia.tree import get_window_control, render_text_tree

        with tool_telemetry(
            "get_ui_tree_text",
            {"window_title": window_title, "depth": depth, "max_lines": max_lines},
        ):
            win = get_window_control(window_title)
            if win is None:
                return ToolError(error="not_found", message="no matching window").model_dump()
            return {"tree": render_text_tree(win, depth=depth, max_lines=max_lines)}

    @mcp.tool
    def find_elements(
        query: ElementQuery,
        limit: int = Field(50, ge=1, le=500),
    ) -> dict[str, Any]:
        """Find UIA elements matching a composable query.

        Each result has ``info`` (ElementInfo) and ``handle`` — pass the handle
        in :class:`ElementRef` to subsequent tools to avoid re-walking the tree.

        When ``query.window_title`` and ``query.window_title_regex`` are both
        ``None``, search is restricted to the **foreground window** (the
        commonly-intended scope when an LLM is driving a single app). To
        search across all visible windows, pass ``window_title_regex=".*"``.
        """
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()

        from ..uia.finder import find_elements as _find

        with tool_telemetry("find_elements", {"query": query.model_dump(), "limit": limit}):
            results = _find(query, limit=limit)
            return {
                "matches": [{"info": info.model_dump(), "handle": h} for _ctrl, info, h in results],
                "count": len(results),
            }

    @mcp.tool
    def get_element(ref: ElementRef) -> dict[str, Any]:
        """Resolve an :class:`ElementRef` and return ElementInfo + handle."""
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..uia.finder import resolve_ref

        with tool_telemetry("get_element", {"ref": ref.model_dump()}):
            res = resolve_ref(ref)
            if res is None:
                return ToolError(error="not_found", message="no matching element").model_dump()
            _ctrl, info, handle = res
            return {"info": info.model_dump(), "handle": handle}

    @mcp.tool
    def get_focused_element() -> dict[str, Any]:
        """Return ElementInfo for the currently focused UIA element."""
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..uia.finder import get_focused

        with tool_telemetry("get_focused_element", {}):
            info = get_focused()
            if info is None:
                return ToolError(error="not_found", message="no focused element").model_dump()
            return info.model_dump()

    @mcp.tool
    def list_windows(visible_only: bool = Field(True)) -> dict[str, Any]:
        """Enumerate top-level windows on the desktop."""
        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()
        from ..input.focus import list_windows as _lw

        with tool_telemetry("list_windows", {"visible_only": visible_only}):
            wins = _lw(visible_only=visible_only)
            return {"windows": [w.model_dump() for w in wins], "count": len(wins)}

    _ = (
        get_ui_tree,
        get_ui_tree_text,
        find_elements,
        get_element,
        get_focused_element,
        list_windows,
        WindowInfo,
    )
