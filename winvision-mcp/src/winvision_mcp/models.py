"""Shared Pydantic models used across tool boundaries.

Keeping these in one place lets every tool reuse the same types so the LLM sees
consistent schema descriptions in the MCP ``tools/list`` response.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Rect(BaseModel):
    """Axis-aligned rectangle in physical screen pixels."""

    x: int = Field(..., description="Left edge in physical pixels.")
    y: int = Field(..., description="Top edge in physical pixels.")
    width: int = Field(..., ge=0, description="Width in physical pixels.")
    height: int = Field(..., ge=0, description="Height in physical pixels.")

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height

    @property
    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)


class WindowInfo(BaseModel):
    """A top-level Windows window."""

    hwnd: int = Field(..., description="HWND value (Windows window handle).")
    title: str = Field("", description="Window title (caption).")
    class_name: str = Field("", description="Window class name.")
    process_name: str = Field("", description="Owning process executable basename.")
    pid: int = Field(0, description="Owning process ID.")
    rect: Rect | None = Field(None, description="Window bounding box, or None if minimized.")
    is_foreground: bool = Field(False, description="Whether this is the current foreground window.")
    is_visible: bool = Field(True, description="Whether the window is currently visible.")


class ProcessInfo(BaseModel):
    """A running OS process."""

    pid: int
    name: str
    exe: str = ""
    user: str = ""


class ElementInfo(BaseModel):
    """A UI Automation element snapshot.

    All fields are best-effort and may be empty if the underlying provider does
    not expose them.
    """

    name: str = ""
    automation_id: str = ""
    control_type: str = ""
    class_name: str = ""
    rect: Rect | None = None
    is_enabled: bool = True
    is_offscreen: bool = False
    has_keyboard_focus: bool = False
    patterns: list[str] = Field(default_factory=list, description="Supported UIA pattern names.")
    runtime_id: list[int] = Field(default_factory=list)
    process_id: int = 0
    window_handle: int = Field(0, description="HWND of the containing top-level window.")
    children_count: int = 0


class ElementQuery(BaseModel):
    """Composable query for locating UIA elements.

    All non-None fields are AND-combined. Only one of ``automation_id`` /
    ``name`` is usually enough; the more constraints provided, the faster
    the lookup.
    """

    name: str | None = Field(None, description="Exact element Name property.")
    name_regex: str | None = Field(None, description="Regex matched against Name.")
    automation_id: str | None = Field(None, description="Exact AutomationId.")
    control_type: str | None = Field(None, description="UIA control type, e.g. 'Button'.")
    class_name: str | None = Field(None, description="UIA ClassName.")
    window_title: str | None = Field(
        None, description="Restrict search to the window whose title matches this."
    )
    window_title_regex: str | None = None
    process_name: str | None = Field(None, description="Restrict to a specific process.exe.")
    ancestor_automation_id: str | None = Field(
        None, description="Element must be a descendant of an element with this AutomationId."
    )
    descendant_automation_id: str | None = Field(
        None, description="Element must be an ancestor of an element with this AutomationId."
    )


class ElementRef(BaseModel):
    """Reference to a UIA element.

    Either an explicit query (``automation_id`` + optional ``window_title``) or
    an opaque ``handle`` returned by a prior tool.
    """

    automation_id: str | None = None
    name: str | None = None
    control_type: str | None = None
    window_title: str | None = None
    handle: str | None = Field(
        None, description="Opaque handle from a prior tool result (cache key)."
    )

    def to_query(self) -> ElementQuery:
        return ElementQuery(
            name=self.name,
            automation_id=self.automation_id,
            control_type=self.control_type,
            window_title=self.window_title,
        )


class BaselineInfo(BaseModel):
    name: str
    window_title: str
    created_at: str
    png_path: str
    width: int
    height: int
    dpi: float
    notes: str = ""
    hash: str


class ReplayStep(BaseModel):
    tool: str
    args: dict[str, object]
    ts: str = ""


class ReplayReport(BaseModel):
    script_path: str
    steps_total: int
    steps_passed: int
    steps_failed: int
    duration_s: float
    failed_step_index: int | None = None
    failure_reason: str | None = None


# --- Result envelopes ---------------------------------------------------------


class ToolError(BaseModel):
    """Standard error envelope returned by tools instead of raising.

    The server should never crash; tools return this so the client/LLM can
    reason about failure modes structurally.
    """

    error: str = Field(..., description="Stable, machine-readable error code.")
    message: str = Field(..., description="Human-readable description.")
    details: dict[str, object] = Field(default_factory=dict)


class OkResult(BaseModel):
    ok: Literal[True] = True
    message: str = ""


class ImageResult(BaseModel):
    """Returned alongside an MCP image when extra metadata matters."""

    width: int
    height: int
    path: str = Field("", description="Path on disk if persisted.")
    backend: str = Field("", description="Capture backend used (wgc/mss/window).")


class AnnotatedResult(BaseModel):
    width: int
    height: int
    legend: dict[str, ElementInfo] = Field(default_factory=dict)
    image_path: str = ""
