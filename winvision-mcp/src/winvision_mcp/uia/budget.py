"""Wall-clock budget for UIA tree walks.

UIA walks against accessibility-rich apps (VS Code, Office, Chrome with the
inspector enabled) routinely visit thousands of elements. Without a wall-clock
cap, a walk that exceeds the MCP client's default 30s ``timeout`` causes the
client to sever stdio — every subsequent tool call returns ``Not connected``
until the user restarts the client. This is much worse than truncating a
single result.

A :class:`WalkBudget` is a tiny helper passed through every recursive walker;
``budget.expired()`` is checked at each iteration so the walk cooperatively
yields when its time runs out, returning whatever it has so far.
"""

from __future__ import annotations

import time

from ..config import get_settings


class WalkBudget:
    """A monotonic-clock budget for UIA tree walks.

    Args:
        timeout_s: Max seconds the walk may run. Defaults to
            ``settings.uia_walk_timeout_s``.

    Example:
        >>> b = WalkBudget()
        >>> while not b.expired():
        ...     ...  # walk one more node
    """

    __slots__ = ("_deadline",)

    def __init__(self, timeout_s: float | None = None) -> None:
        if timeout_s is None:
            timeout_s = get_settings().uia_walk_timeout_s
        self._deadline = time.monotonic() + max(0.0, float(timeout_s))

    def expired(self) -> bool:
        """Return True once the budget has been exhausted."""
        return time.monotonic() >= self._deadline

    def remaining(self) -> float:
        """Return seconds left in the budget (0.0 if already expired)."""
        return max(0.0, self._deadline - time.monotonic())
