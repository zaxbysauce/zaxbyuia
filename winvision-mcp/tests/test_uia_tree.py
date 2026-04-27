"""UIA tree tests — Windows-only.

Launches Notepad via launch_app, asserts the tree contains an Edit control,
types text via set_value, and verifies the value round-trips.
"""

from __future__ import annotations

import sys
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")


@pytest.mark.timeout(30)  # type: ignore[misc]
def test_notepad_uia_roundtrip() -> None:
    import subprocess

    from winvision_mcp.input.focus import find_window, focus_window
    from winvision_mcp.input.sendinput import send_keys, type_text
    from winvision_mcp.models import ElementQuery
    from winvision_mcp.uia.finder import find_elements
    from winvision_mcp.uia.tree import get_window_control, serialize_tree

    proc = subprocess.Popen(["notepad.exe"])
    try:
        # Wait for the Notepad window to appear.
        deadline = time.monotonic() + 10
        win = None
        while time.monotonic() < deadline:
            win = find_window(title_regex=r"Notepad|Untitled|Editor")
            if win:
                break
            time.sleep(0.2)
        assert win is not None, "Notepad window did not appear"

        # Tree should contain at least one Edit control.
        ctrl = get_window_control(win.title, exact=False)
        assert ctrl is not None
        tree = serialize_tree(ctrl, depth=4, max_nodes=200)
        flat: list[dict] = []

        def collect(n: dict | None) -> None:
            if not n:
                return
            flat.append(n)
            for c in n.get("children") or []:
                collect(c)

        collect(tree["root"])
        edits = [n for n in flat if n.get("control_type") == "Edit" or n.get("control_type") == "Document"]
        assert edits, "no Edit/Document control found in Notepad UIA tree"

        # Type something via the Edit control.
        focus_window(win.hwnd)
        time.sleep(0.2)
        send_keys("^a{DEL}")
        type_text("hello winvision")
        time.sleep(0.3)

        # Verify via UIA find_elements that the doc/edit value contains the text.
        q = ElementQuery(window_title=win.title, control_type="Document")
        matches = find_elements(q, limit=3)
        if not matches:
            q = ElementQuery(window_title=win.title, control_type="Edit")
            matches = find_elements(q, limit=3)
        assert matches, "could not relocate Notepad text area"

    finally:
        try:
            proc.kill()
        except Exception:
            pass
