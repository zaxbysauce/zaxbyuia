"""UIA tree serialization.

We use the ``uiautomation`` (yinkaisheng) wrapper because it has more robust
tree-walk semantics than raw comtypes against modern Win11 apps.

Two serializers are provided:

- :func:`serialize_tree` — pruned JSON-ready dict tree.
- :func:`render_text_tree` — ASCII tree (cheap for LLM context).
"""

from __future__ import annotations

import sys
from typing import Any

from ..models import ElementInfo, Rect

# UIA control types we treat as "interactable" for filter_types and
# screenshot_annotated. Other types are still walkable but not numbered.
INTERACTABLE_TYPES: frozenset[str] = frozenset(
    {
        "Button",
        "CheckBox",
        "ComboBox",
        "Edit",
        "Hyperlink",
        "ListItem",
        "MenuItem",
        "RadioButton",
        "SplitButton",
        "Tab",
        "TabItem",
        "Tree",
        "TreeItem",
        "Slider",
        "Spinner",
    }
)


def _require_win() -> None:
    if sys.platform != "win32":
        raise OSError("UIA functions require Windows")


def get_root() -> Any:
    """Return the UIA root (desktop) control."""
    _require_win()
    import uiautomation as auto  # type: ignore[import-not-found]

    return auto.GetRootControl()


def get_window_control(title: str | None, *, exact: bool = False) -> Any | None:
    """Find a top-level window by title (regex unless ``exact``).

    Returns ``None`` if no matching window is found within the search horizon.
    """
    _require_win()
    import re

    import uiautomation as auto  # type: ignore[import-not-found]

    if title is None:
        # The currently-foreground top-level window.
        fg = auto.GetForegroundControl()
        # Walk up to the top-level WindowControl/PaneControl.
        cur = fg
        while cur and cur.GetParentControl():
            parent = cur.GetParentControl()
            if parent.ControlTypeName == "PaneControl" and parent.Name == "Desktop":
                return cur
            cur = parent
        return cur

    pattern = re.compile(title) if not exact else None
    root = auto.GetRootControl()
    for child in root.GetChildren():
        try:
            name = child.Name or ""
        except Exception:
            continue
        if exact:
            if name == title:
                return child
        else:
            if pattern and pattern.search(name):
                return child
    return None


def control_to_info(ctrl: Any) -> ElementInfo:
    """Convert a uiautomation control to a serializable :class:`ElementInfo`."""
    rect: Rect | None = None
    try:
        bb = ctrl.BoundingRectangle
        if bb and getattr(bb, "width", lambda: 0)() > 0:
            rect = Rect(x=int(bb.left), y=int(bb.top), width=int(bb.width()), height=int(bb.height()))
    except Exception:
        pass

    # The uiautomation library exposes patterns via Get<Name>Pattern() accessors.
    # We probe an explicit allowlist instead of dir()-introspection so the
    # returned list reads as ["Invoke", "Value", ...] rather than ["GetInvoke",
    # ...], and so we don't accidentally include unrelated attrs that happen
    # to end in "Pattern".
    _SUPPORTED_PATTERN_GETTERS = (
        "GetInvokePattern", "GetValuePattern", "GetRangeValuePattern",
        "GetTogglePattern", "GetSelectionItemPattern", "GetSelectionPattern",
        "GetExpandCollapsePattern", "GetScrollPattern", "GetScrollItemPattern",
        "GetTextPattern", "GetWindowPattern", "GetTransformPattern",
        "GetGridPattern", "GetGridItemPattern", "GetTablePattern",
        "GetTableItemPattern", "GetDockPattern", "GetMultipleViewPattern",
        "GetVirtualizedItemPattern", "GetItemContainerPattern",
        "GetSynchronizedInputPattern", "GetTextChildPattern",
        "GetLegacyIAccessiblePattern",
    )
    patterns: list[str] = []
    for getter in _SUPPORTED_PATTERN_GETTERS:
        fn = getattr(ctrl, getter, None)
        if not callable(fn):
            continue
        try:
            obj = fn()
        except Exception:
            continue
        if obj is not None:
            patterns.append(getter[3:-len("Pattern")])  # GetInvokePattern -> "Invoke"

    runtime_id: list[int] = []
    try:
        rid = ctrl.GetRuntimeId() or []
        runtime_id = [int(x) for x in rid]
    except Exception:
        pass

    try:
        children_count = len(ctrl.GetChildren())
    except Exception:
        children_count = 0

    return ElementInfo(
        name=str(getattr(ctrl, "Name", "") or ""),
        automation_id=str(getattr(ctrl, "AutomationId", "") or ""),
        control_type=str(getattr(ctrl, "ControlTypeName", "") or "").replace("Control", ""),
        class_name=str(getattr(ctrl, "ClassName", "") or ""),
        rect=rect,
        is_enabled=bool(getattr(ctrl, "IsEnabled", True)),
        is_offscreen=bool(getattr(ctrl, "IsOffscreen", False)),
        has_keyboard_focus=bool(getattr(ctrl, "HasKeyboardFocus", False)),
        patterns=sorted(set(patterns)),
        runtime_id=runtime_id,
        process_id=int(getattr(ctrl, "ProcessId", 0) or 0),
        window_handle=int(_safe_hwnd(ctrl)),
        children_count=children_count,
    )


def _safe_hwnd(ctrl: Any) -> int:
    try:
        return int(ctrl.NativeWindowHandle or 0)
    except Exception:
        return 0


def serialize_tree(
    root_ctrl: Any,
    *,
    depth: int = 8,
    visible_only: bool = True,
    interactable_only: bool = False,
    max_nodes: int = 500,
) -> dict[str, Any]:
    """Serialize a UIA subtree to a JSON-friendly dict.

    Args:
        root_ctrl: starting control (e.g. a window).
        depth: max walk depth (root is depth 0).
        visible_only: skip ``IsOffscreen`` controls.
        interactable_only: only emit controls whose type is in
            :data:`INTERACTABLE_TYPES`.
        max_nodes: hard cap on total nodes; truncated subtrees are marked.

    Returns:
        ``{"root": {...}, "truncated": bool, "total_nodes": int}``.
    """
    counter = {"n": 0, "truncated": False}

    def walk(ctrl: Any, d: int) -> dict[str, Any] | None:
        if counter["n"] >= max_nodes:
            counter["truncated"] = True
            return None
        if visible_only and bool(getattr(ctrl, "IsOffscreen", False)):
            return None
        info = control_to_info(ctrl)
        if interactable_only and info.control_type not in INTERACTABLE_TYPES:
            # We still recurse: hidden interactables may be deeper.
            children: list[dict[str, Any]] = []
            if d < depth:
                try:
                    for c in ctrl.GetChildren():
                        node = walk(c, d + 1)
                        if node is not None:
                            children.append(node)
                except Exception:
                    pass
            if not children:
                return None
            counter["n"] += 1
            return {**info.model_dump(), "children": children}

        counter["n"] += 1
        node: dict[str, Any] = info.model_dump()
        node["children"] = []
        if d < depth:
            try:
                for c in ctrl.GetChildren():
                    sub = walk(c, d + 1)
                    if sub is not None:
                        node["children"].append(sub)
                    if counter["n"] >= max_nodes:
                        counter["truncated"] = True
                        break
            except Exception:
                pass
        return node

    root = walk(root_ctrl, 0)
    return {"root": root, "truncated": counter["truncated"], "total_nodes": counter["n"]}


def render_text_tree(root_ctrl: Any, *, depth: int = 6, max_lines: int = 400) -> str:
    """Render a UIA subtree as an ASCII tree, like ``tree /F``."""
    lines: list[str] = []

    def walk(ctrl: Any, d: int, prefix: str, is_last: bool, is_root: bool) -> None:
        if len(lines) >= max_lines:
            return
        info = control_to_info(ctrl)
        label = info.control_type or "?"
        if info.name:
            label += f" {info.name!r}"[:80]
        if info.automation_id:
            label += f" #{info.automation_id}"
        if is_root:
            lines.append(label)
        else:
            connector = "└── " if is_last else "├── "
            lines.append(prefix + connector + label)
        if d >= depth:
            return
        try:
            children = ctrl.GetChildren()
        except Exception:
            return
        new_prefix = prefix + ("    " if is_last else "│   ") if not is_root else ""
        for i, c in enumerate(children):
            walk(c, d + 1, new_prefix, i == len(children) - 1, False)

    walk(root_ctrl, 0, "", True, True)
    if len(lines) >= max_lines:
        lines.append("... (truncated)")
    return "\n".join(lines)
