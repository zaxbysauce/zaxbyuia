"""Element finding via composable :class:`ElementQuery`."""

from __future__ import annotations

import re
import sys
import time
from typing import Any

from ..models import ElementInfo, ElementQuery, ElementRef
from .cache import get_cache
from .tree import control_to_info, get_window_control


def _require_win() -> None:
    if sys.platform != "win32":
        raise OSError("UIA functions require Windows")


def _matches(ctrl: Any, q: ElementQuery, info: ElementInfo) -> bool:
    if q.name is not None and info.name != q.name:
        return False
    if q.name_regex is not None and not re.search(q.name_regex, info.name):
        return False
    if q.automation_id is not None and info.automation_id != q.automation_id:
        return False
    if q.control_type is not None and info.control_type != q.control_type:
        return False
    if q.class_name is not None and info.class_name != q.class_name:
        return False
    return True


def _walk(ctrl: Any, depth: int, max_depth: int = 32) -> list[Any]:
    out = [ctrl]
    if depth >= max_depth:
        return out
    try:
        for c in ctrl.GetChildren():
            out.extend(_walk(c, depth + 1, max_depth))
    except Exception:
        pass
    return out


def find_elements(query: ElementQuery, *, limit: int = 50) -> list[tuple[Any, ElementInfo, str]]:
    """Find UIA elements matching ``query``.

    Args:
        query: composable query.
        limit: cap on returned matches (default 50).

    Returns:
        List of ``(control, info, handle)`` tuples — the ``handle`` is the
        opaque cache token that subsequent tools can pass via ``ElementRef``.
    """
    _require_win()

    # Restrict starting scope to a window if requested.
    scope: list[Any]
    if query.window_title is not None:
        win = get_window_control(query.window_title)
        if win is None:
            return []
        scope = [win]
    elif query.window_title_regex is not None:
        import uiautomation as auto  # type: ignore[import-not-found]

        pat = re.compile(query.window_title_regex)
        scope = [w for w in auto.GetRootControl().GetChildren() if pat.search(w.Name or "")]
    else:
        win = get_window_control(None)  # foreground window
        if win is None:
            return []
        scope = [win]

    cache = get_cache()
    results: list[tuple[Any, ElementInfo, str]] = []

    # Optional descendant filter (element must be within ancestor_automation_id).
    if query.ancestor_automation_id:
        new_scope: list[Any] = []
        for s in scope:
            ancestor_q = ElementQuery(automation_id=query.ancestor_automation_id)
            for ctrl, _info, _h in find_elements(
                ancestor_q.model_copy(update={"window_title": query.window_title}), limit=8
            ):
                new_scope.append(ctrl)
        scope = new_scope or scope

    for s in scope:
        for ctrl in _walk(s, 0):
            try:
                info = control_to_info(ctrl)
            except Exception:
                continue
            if not _matches(ctrl, query, info):
                continue
            handle = cache.put(ctrl)
            results.append((ctrl, info, handle))
            if len(results) >= limit:
                return results

    # Optional descendant filter: the matched element must contain
    # an element with descendant_automation_id below it.
    if query.descendant_automation_id:
        filtered = []
        desc_q = ElementQuery(automation_id=query.descendant_automation_id)
        for ctrl, info, h in results:
            for sub in _walk(ctrl, 0):
                sub_info = control_to_info(sub)
                if _matches(sub, desc_q, sub_info):
                    filtered.append((ctrl, info, h))
                    break
        results = filtered

    return results


def resolve_ref(ref: ElementRef) -> tuple[Any, ElementInfo, str] | None:
    """Resolve an :class:`ElementRef` to a live control + info + handle.

    Tries the opaque ``handle`` cache first, then falls back to a query.
    """
    cache = get_cache()
    if ref.handle:
        cached = cache.get(ref.handle)
        if cached is not None:
            try:
                info = control_to_info(cached)
                return cached, info, ref.handle
            except Exception:
                cache.discard(ref.handle)

    matches = find_elements(ref.to_query(), limit=1)
    return matches[0] if matches else None


def wait_for_element(query: ElementQuery, *, timeout_s: float = 10.0, poll_ms: int = 200) -> tuple[Any, ElementInfo, str] | None:
    """Poll for the first match of ``query`` up to ``timeout_s`` seconds."""
    deadline = time.monotonic() + timeout_s
    interval = max(0.01, poll_ms / 1000.0)
    while True:
        matches = find_elements(query, limit=1)
        if matches:
            return matches[0]
        if time.monotonic() >= deadline:
            return None
        time.sleep(interval)


def get_focused() -> ElementInfo | None:
    """Return info for the currently focused UIA element."""
    _require_win()
    import uiautomation as auto  # type: ignore[import-not-found]

    try:
        ctrl = auto.GetFocusedControl()
        if ctrl is None:
            return None
        return control_to_info(ctrl)
    except Exception:
        return None
