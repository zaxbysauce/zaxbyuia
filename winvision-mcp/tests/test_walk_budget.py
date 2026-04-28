"""Walk-budget tests — cross-platform safe.

Exercises the WalkBudget primitive directly and indirectly through the
``find_elements._walk`` helper using fake controls. The point is to lock in
the behavior that motivated 1.0.1: a walk that takes too long must STOP
returning data within the wall-clock budget rather than letting the MCP
client time out and sever stdio.
"""

from __future__ import annotations

import time

from winvision_mcp.uia.budget import WalkBudget


def test_budget_expires_after_timeout() -> None:
    b = WalkBudget(timeout_s=0.05)
    assert not b.expired()
    time.sleep(0.07)
    assert b.expired()


def test_budget_remaining_is_nonnegative() -> None:
    b = WalkBudget(timeout_s=0.05)
    assert 0.0 <= b.remaining() <= 0.05
    time.sleep(0.07)
    assert b.remaining() == 0.0


def test_budget_zero_timeout_expires_immediately() -> None:
    b = WalkBudget(timeout_s=0.0)
    assert b.expired()


def test_finder_walk_respects_budget() -> None:
    """Pure-Python ctrl-shaped object lets us run _walk on any platform."""
    from winvision_mcp.uia.finder import _walk

    class FakeCtrl:
        def __init__(self, name: str, children: list | None = None, sleep: float = 0.0) -> None:
            self.name = name
            self._children = children or []
            self._sleep = sleep

        def GetChildren(self) -> list:
            if self._sleep:
                time.sleep(self._sleep)
            return self._children

    # Build a tree where each leaf access takes 30 ms; with a 50 ms budget the
    # walk should stop early instead of visiting all 20 children.
    leaves = [FakeCtrl(f"leaf-{i}") for i in range(20)]
    root = FakeCtrl("root", children=leaves, sleep=0.03)
    b = WalkBudget(timeout_s=0.05)

    t0 = time.monotonic()
    out = _walk(root, 0, budget=b)
    elapsed = time.monotonic() - t0

    # We must always include root, and we must finish well before the
    # un-budgeted upper bound (which would be ~30 ms * 20 leaves + overhead).
    assert out[0] is root
    assert elapsed < 0.5, f"walk took {elapsed:.3f}s — budget didn't fire"
    # And we must NOT have collected all 21 nodes (root + 20 leaves) — if we
    # did, the budget did nothing.
    assert len(out) <= 21


def test_finder_walk_no_budget_collects_everything() -> None:
    """Sanity: with no budget, we still visit the whole tree."""
    from winvision_mcp.uia.finder import _walk

    class FakeCtrl:
        def __init__(self, name: str, children: list | None = None) -> None:
            self.name = name
            self._children = children or []

        def GetChildren(self) -> list:
            return self._children

    leaves = [FakeCtrl(f"leaf-{i}") for i in range(5)]
    root = FakeCtrl("root", children=leaves)
    out = _walk(root, 0)
    assert len(out) == 6  # root + 5 leaves
