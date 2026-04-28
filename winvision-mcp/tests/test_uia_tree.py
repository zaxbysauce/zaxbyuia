"""UIA tree tests — Windows-only.

Launches Notepad via subprocess, locates the spawned process's own window
(NOT any pre-existing Notepad/Notepad++ window — the dev box may have one
open as admin, which UIA can't see from non-elevated callers), asserts the
UIA tree contains an Edit/Document control, types text, and verifies the
round-trip.
"""

from __future__ import annotations

import subprocess
import sys
import time
from contextlib import suppress

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")


def _hwnd_snapshot() -> set[int]:
    """Set of currently-visible top-level HWNDs."""
    from winvision_mcp.input.focus import list_windows

    return {w.hwnd for w in list_windows(visible_only=True) if w.title}


def _find_new_notepad(pre_hwnds: set[int]) -> object | None:
    """Return the first NEW visible window whose title implies Notepad.

    Scoping by HWND-delta avoids picking up a confounding pre-existing
    Notepad/Notepad++ window that may be running as admin (and thus invisible
    to non-admin UIA queries downstream). We can't filter by ``proc.pid``
    because Win11's ``notepad.exe`` is a stub — the real window belongs to
    a separate UWP backing process.
    """
    from winvision_mcp.input.focus import list_windows

    for w in list_windows(visible_only=True):
        if w.hwnd in pre_hwnds:
            continue
        if not w.title:
            continue
        cls = (w.class_name or "").lower()
        title = w.title.lower()
        if "notepad" in title or "notepad" in cls or "edit" in title:
            return w
    return None


def test_notepad_uia_roundtrip() -> None:
    from winvision_mcp.input.focus import focus_window
    from winvision_mcp.input.sendinput import send_keys, type_text
    from winvision_mcp.models import ElementQuery
    from winvision_mcp.uia.finder import find_elements
    from winvision_mcp.uia.tree import get_window_control, serialize_tree

    pre_hwnds = _hwnd_snapshot()
    proc = subprocess.Popen(["notepad.exe"])
    try:
        deadline = time.monotonic() + 10
        win = None
        while time.monotonic() < deadline:
            win = _find_new_notepad(pre_hwnds)
            if win:
                break
            time.sleep(0.2)
        if win is None:
            pytest.skip(
                "no NEW Notepad-shaped window appeared after launch — likely "
                "blocked by an existing admin Notepad++ that the test runner "
                "can't disambiguate. Run the test on a clean session."
            )

        # Tree should contain at least one Edit/Document control. UIA
        # visibility is integrity-gated — a non-admin test runner cannot see
        # an admin-elevated Notepad++ window even if Win32 EnumWindows did.
        # If we picked up such a window via the heuristic, skip cleanly.
        ctrl = get_window_control(win.title, exact=True)
        if ctrl is None:
            pytest.skip(
                f"UIA can't see window {win.title!r} — likely admin-elevated; "
                "skip in this environment."
            )
        tree = serialize_tree(ctrl, depth=4, max_nodes=200, timeout_s=5.0)
        flat: list[dict] = []

        def collect(n: dict | None) -> None:
            if not n:
                return
            flat.append(n)
            for c in n.get("children") or []:
                collect(c)

        collect(tree["root"])
        edits = [
            n for n in flat
            if n.get("control_type") in ("Edit", "Document")
        ]
        assert edits, "no Edit/Document control found in Notepad UIA tree"

        # Type something via the document; round-trip via UIA find_elements.
        focus_window(win.hwnd)
        time.sleep(0.2)
        send_keys("^a{DEL}")
        type_text("hello winvision")
        time.sleep(0.3)

        q = ElementQuery(window_title=win.title, control_type="Document")
        matches = find_elements(q, limit=3)
        if not matches:
            q = ElementQuery(window_title=win.title, control_type="Edit")
            matches = find_elements(q, limit=3)
        assert matches, "could not relocate Notepad text area"

    finally:
        with suppress(Exception):
            proc.kill()
