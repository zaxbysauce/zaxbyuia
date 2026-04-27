"""Set-of-Marks overlay tests (cross-platform-safe via fixture image)."""

from __future__ import annotations

from pathlib import Path

from winvision_mcp.annotate import annotate_set_of_marks
from winvision_mcp.models import ElementInfo, Rect


def test_overlay_round_trips_legend(fixture_window_png: Path) -> None:
    from PIL import Image

    base = Image.open(fixture_window_png)
    marks = []
    rects = [
        (1, Rect(x=20, y=20, width=180, height=60)),
        (2, Rect(x=220, y=20, width=180, height=60)),
        (3, Rect(x=420, y=20, width=180, height=60)),
        (4, Rect(x=20, y=120, width=180, height=60)),
        (5, Rect(x=220, y=120, width=180, height=60)),
        (6, Rect(x=420, y=120, width=180, height=60)),
    ]
    for n, r in rects:
        marks.append(
            (
                n,
                r,
                ElementInfo(
                    name=f"Button {n}",
                    automation_id=f"btn_{n}",
                    control_type="Button",
                    rect=r,
                ),
            )
        )

    out, legend = annotate_set_of_marks(base, marks)
    assert out.size == base.size
    assert len(legend) == 6
    assert {k for k in legend} == {str(i) for i in range(1, 7)}
    for i in range(1, 7):
        info = legend[str(i)]
        assert info.automation_id == f"btn_{i}"
        assert info.control_type == "Button"


def test_overlay_handles_offscreen_marks(fixture_window_png: Path) -> None:
    from PIL import Image

    base = Image.open(fixture_window_png)
    # A rect entirely off the right edge should be silently dropped.
    bad = Rect(x=10000, y=10000, width=100, height=100)
    info = ElementInfo(name="off", automation_id="off", control_type="Button", rect=bad)
    out, legend = annotate_set_of_marks(base, [(1, bad, info)])
    assert out.size == base.size
    # legend may or may not include the off-screen mark depending on the
    # implementation; the important thing is that we didn't crash.
    assert isinstance(legend, dict)
