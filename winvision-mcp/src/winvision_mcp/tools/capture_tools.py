"""Capture tools (``screenshot_*`` and ``tile_screenshot``)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .. import capture as cap
from ..annotate import annotate_set_of_marks
from ..config import get_settings
from ..models import AnnotatedResult, ImageResult, Rect, ToolError
from ._helpers import to_mcp_image, tool_telemetry


def register(mcp: Any) -> None:
    @mcp.tool
    def screenshot_desktop(
        monitor: int = Field(0, description="0 = full virtual desktop, 1+ = individual monitor."),
    ) -> Any:
        """Capture a monitor (or virtual desktop) and return a PNG.

        Use this when you need to see the whole screen. For a single window
        prefer :func:`screenshot_window` (smaller, faster, occlusion-tolerant).
        Output is downsampled so the longest edge is <= ``capture_max_edge``
        (default 1600 px) to keep vision-LLM token cost manageable.
        """
        with tool_telemetry("screenshot_desktop", {"monitor": monitor}):
            img = cap.capture_desktop(monitor=monitor)
            img = cap.downsample_to_max_edge(img)
            return to_mcp_image(img, persist_name=f"desktop_{monitor}")

    @mcp.tool
    def screenshot_window(
        hwnd: int | None = Field(None, description="Optional explicit HWND."),
        title_regex: str | None = Field(None, description="Regex to match the window title."),
        process_name: str | None = Field(None, description="Owning .exe basename."),
    ) -> Any:
        """Capture a single top-level window by HWND, title regex, or process name.

        Tries Windows.Graphics.Capture first (handles Chromium/WPF correctly),
        then falls back to PrintWindow + PW_RENDERFULLCONTENT for occluded or
        unsupported windows.
        """
        with tool_telemetry(
            "screenshot_window",
            {"hwnd": hwnd, "title_regex": title_regex, "process_name": process_name},
        ):
            if hwnd is None:
                from ..input.focus import find_window

                w = find_window(title_regex=title_regex, process_name=process_name)
                if w is None:
                    return ToolError(error="not_found", message="no matching window")
                hwnd = w.hwnd
            img = cap.capture_window(int(hwnd))
            img = cap.downsample_to_max_edge(img)
            return to_mcp_image(img, persist_name=f"window_{hwnd}")

    @mcp.tool
    def screenshot_region(
        x: int = Field(..., description="Left edge in physical px (virtual-desktop coords)."),
        y: int = Field(..., description="Top edge in physical px."),
        w: int = Field(..., gt=0, description="Width in physical px."),
        h: int = Field(..., gt=0, description="Height in physical px."),
        monitor: int = Field(0, description="If >0, (x,y) is treated as monitor-local."),
    ) -> Any:
        """Capture an arbitrary rectangle of the virtual desktop."""
        with tool_telemetry(
            "screenshot_region", {"x": x, "y": y, "w": w, "h": h, "monitor": monitor}
        ):
            img = cap.capture_region(x, y, w, h, monitor=monitor)
            img = cap.downsample_to_max_edge(img)
            return to_mcp_image(img, persist_name=f"region_{x}_{y}_{w}_{h}")

    @mcp.tool
    def screenshot_element(
        automation_id: str | None = Field(None, description="Element AutomationId."),
        name: str | None = Field(None, description="Element Name."),
        window_title: str | None = Field(None, description="Restrict to a window."),
    ) -> Any:
        """Resolve an element by UIA query and capture only its bounding box."""
        from ..models import ElementQuery
        from ..uia.finder import find_elements

        with tool_telemetry(
            "screenshot_element",
            {"automation_id": automation_id, "name": name, "window_title": window_title},
        ):
            q = ElementQuery(
                automation_id=automation_id, name=name, window_title=window_title
            )
            matches = find_elements(q, limit=1)
            if not matches:
                return ToolError(error="not_found", message="no matching element")
            _ctrl, info, _h = matches[0]
            if info.rect is None:
                return ToolError(error="no_rect", message="element has no bounding rectangle")
            r = info.rect
            img = cap.capture_region(r.x, r.y, r.width, r.height)
            img = cap.downsample_to_max_edge(img)
            return to_mcp_image(img, persist_name=f"element_{automation_id or name}")

    @mcp.tool
    def screenshot_annotated(
        window_title: str | None = Field(
            None, description="If None, uses the foreground window."
        ),
        filter_types: list[str] | None = Field(
            None,
            description="Restrict marks to these UIA control types (default: interactable types).",
        ),
        max_elements: int = Field(60, ge=1, le=200, description="Cap on numbered marks."),
    ) -> dict[str, Any]:
        """Take a window screenshot and overlay numbered marks on interactable UI.

        This is THE tool to call when the LLM needs to "see" the UI. The legend
        maps each mark number to ``{automation_id, name, control_type, rect}``;
        the LLM should pick a mark and then act via :func:`invoke_element` /
        :func:`set_value` using the returned ``automation_id`` (NOT pixel
        coordinates).
        """
        import sys

        if sys.platform != "win32":
            return ToolError(
                error="unsupported_platform",
                message="screenshot_annotated requires Windows",
            ).model_dump()

        from ..uia.tree import INTERACTABLE_TYPES, get_window_control

        with tool_telemetry(
            "screenshot_annotated",
            {"window_title": window_title, "filter_types": filter_types, "max_elements": max_elements},
        ):
            win = get_window_control(window_title)
            if win is None:
                return ToolError(error="not_found", message="no matching window").model_dump()

            from ..uia.tree import control_to_info

            win_info = control_to_info(win)
            if win_info.window_handle == 0 or win_info.rect is None:
                return ToolError(error="no_rect", message="window has no rect/HWND").model_dump()

            img = cap.capture_window(win_info.window_handle)

            allowed = (
                set(filter_types) if filter_types else set(INTERACTABLE_TYPES)
            )

            # Walk the window's UIA subtree to gather candidates.
            candidates: list[tuple[Any, Any]] = []  # (control, info)
            stack = [win]
            while stack and len(candidates) < max_elements * 4:
                ctrl = stack.pop()
                try:
                    info = control_to_info(ctrl)
                except Exception:
                    continue
                if info.control_type in allowed and info.rect and not info.is_offscreen and info.is_enabled:
                    candidates.append((ctrl, info))
                try:
                    stack.extend(ctrl.GetChildren() or [])
                except Exception:
                    continue

            # Sort by rect area ascending so smaller controls are numbered last
            # (improves visibility of overlapping marks).
            candidates.sort(
                key=lambda ci: (ci[1].rect.width * ci[1].rect.height) if ci[1].rect else 0
            )
            candidates = candidates[:max_elements]

            from ..uia.cache import get_cache

            cache = get_cache()
            marks = []
            legend_full: dict[str, Any] = {}
            for i, (ctrl, info) in enumerate(candidates, start=1):
                marks.append((i, info.rect, info))
                handle = cache.put(ctrl)
                d = info.model_dump()
                d["handle"] = handle
                legend_full[str(i)] = d

            crop_offset = (win_info.rect.x, win_info.rect.y)
            annotated, _legend = annotate_set_of_marks(
                img, marks, crop_offset=crop_offset
            )
            annotated = cap.downsample_to_max_edge(annotated)

            mcp_img = to_mcp_image(annotated, persist_name="annotated_latest")
            return {"image": mcp_img, "legend": legend_full,
                    "result": AnnotatedResult(
                        width=annotated.size[0], height=annotated.size[1],
                        legend={k: info for k, info in zip(legend_full.keys(), [c[1] for c in candidates])},
                        image_path=str(get_settings().screenshots_dir / "annotated_latest.png"),
                    ).model_dump()}

    @mcp.tool
    def tile_screenshot(
        window_title: str | None = Field(None, description="Window to tile."),
        tile_size: int = Field(1072, ge=256, le=4096, description="Tile size in px."),
    ) -> dict[str, Any]:
        """Capture a window and split into vision-model-friendly tiles.

        Returns a list of base64 PNG tiles in row-major order plus the original
        size and tile geometry.
        """
        import sys

        if sys.platform != "win32":
            return ToolError(error="unsupported_platform", message="Windows-only").model_dump()

        from ..input.focus import find_window

        with tool_telemetry("tile_screenshot", {"window_title": window_title, "tile_size": tile_size}):
            w = find_window(title_regex=window_title) if window_title else find_window(title_regex=".*")
            if w is None:
                return ToolError(error="not_found", message="no matching window").model_dump()
            img = cap.capture_window(w.hwnd)
            tiles = []
            tw = th = tile_size
            for ty in range(0, img.size[1], th):
                for tx in range(0, img.size[0], tw):
                    crop = img.crop((tx, ty, min(tx + tw, img.size[0]), min(ty + th, img.size[1])))
                    tiles.append(to_mcp_image(crop))
            return {
                "tiles": tiles,
                "tile_size": tile_size,
                "source_size": list(img.size),
                "rows": (img.size[1] + th - 1) // th,
                "cols": (img.size[0] + tw - 1) // tw,
            }

    @mcp.tool
    def list_monitors() -> list[dict[str, int]]:
        """List monitors as ``[{left, top, width, height}, ...]``.

        Index 0 is the synthetic virtual desktop spanning all monitors.
        """
        with tool_telemetry("list_monitors", {}):
            return cap.list_monitors()

    # Suppress "unused" linter warnings on the registered closures.
    _ = (
        screenshot_desktop,
        screenshot_window,
        screenshot_region,
        screenshot_element,
        screenshot_annotated,
        tile_screenshot,
        list_monitors,
        ImageResult,
        Rect,
    )
