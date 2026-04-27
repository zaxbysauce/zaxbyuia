"""Wrappers for the standard UIA patterns we expose as tools.

Each helper returns ``(ok: bool, fallback_used: bool, error: str)``. If the
control supports the pattern, we use it; otherwise the caller can fall through
to a SendInput-based interaction.
"""

from __future__ import annotations

import sys
from typing import Any, Literal


def _require_win() -> None:
    if sys.platform != "win32":
        raise OSError("UIA functions require Windows")


def invoke(ctrl: Any) -> tuple[bool, bool, str]:
    """Use InvokePattern; falls back to ``SelectionItem`` then ``Toggle``.

    Returns:
        (ok, fallback_used, error_message)
    """
    _require_win()
    err = ""
    try:
        p = ctrl.GetInvokePattern()
        if p is not None:
            p.Invoke()
            return True, False, ""
    except Exception as exc:
        err = f"InvokePattern failed: {exc}"

    try:
        p = ctrl.GetSelectionItemPattern()
        if p is not None:
            p.Select()
            return True, True, ""
    except Exception as exc:
        err = f"{err}; SelectionItemPattern failed: {exc}"

    try:
        p = ctrl.GetTogglePattern()
        if p is not None:
            p.Toggle()
            return True, True, ""
    except Exception as exc:
        err = f"{err}; TogglePattern failed: {exc}"

    return False, False, err or "no compatible pattern"


def set_value(ctrl: Any, value: str) -> tuple[bool, bool, str]:
    """Use ValuePattern.SetValue; caller falls back to ``focus + Ctrl+A + type``."""
    _require_win()
    try:
        p = ctrl.GetValuePattern()
        if p is not None:
            p.SetValue(value)
            return True, False, ""
    except Exception as exc:
        return False, False, f"ValuePattern.SetValue failed: {exc}"
    return False, False, "ValuePattern not supported"


def toggle(ctrl: Any) -> tuple[bool, bool, str]:
    _require_win()
    try:
        p = ctrl.GetTogglePattern()
        if p is not None:
            p.Toggle()
            return True, False, ""
    except Exception as exc:
        return False, False, str(exc)
    return False, False, "TogglePattern not supported"


def select_item(ctrl: Any) -> tuple[bool, bool, str]:
    _require_win()
    try:
        p = ctrl.GetSelectionItemPattern()
        if p is not None:
            p.Select()
            return True, False, ""
    except Exception as exc:
        return False, False, str(exc)
    return False, False, "SelectionItemPattern not supported"


def expand_collapse(
    ctrl: Any, action: Literal["expand", "collapse", "toggle"]
) -> tuple[bool, bool, str]:
    _require_win()
    try:
        p = ctrl.GetExpandCollapsePattern()
        if p is None:
            return False, False, "ExpandCollapsePattern not supported"
        # ExpandCollapseState: 0=Collapsed, 1=Expanded, 2=PartiallyExpanded, 3=LeafNode
        state = int(getattr(p, "ExpandCollapseState", 0))
        if action == "expand" or (action == "toggle" and state == 0):
            p.Expand()
        elif action == "collapse" or (action == "toggle" and state == 1):
            p.Collapse()
        return True, False, ""
    except Exception as exc:
        return False, False, str(exc)


def scroll(
    ctrl: Any, direction: Literal["up", "down", "left", "right"], amount: float = 1.0
) -> tuple[bool, bool, str]:
    """Use ScrollPattern; ``amount`` is in "large/small increment" units (~1)."""
    _require_win()
    try:
        p = ctrl.GetScrollPattern()
        if p is None:
            return False, False, "ScrollPattern not supported"
        # ScrollAmount: 0=LargeDecrement, 1=SmallDecrement, 2=NoAmount,
        # 3=LargeIncrement, 4=SmallIncrement
        if direction in ("up", "left"):
            v_amt = 1  # SmallDecrement
        else:
            v_amt = 4  # SmallIncrement
        h_amt = 2
        if direction in ("left", "right"):
            h_amt = v_amt
            v_amt = 2
        for _ in range(max(1, int(round(amount)))):
            p.Scroll(h_amt, v_amt if direction in ("up", "down") else 2)
        return True, False, ""
    except Exception as exc:
        return False, False, str(exc)
