"""``@destructive`` decorator for tools that mutate user state.

Wraps a tool callable so that:

- The call is logged to SQLite via :func:`winvision_mcp.storage.log_invocation`.
- If the caller passes ``dry_run=True`` (a kwarg every destructive tool accepts),
  the function is NOT executed; we return a structured "dry-run" envelope
  describing what *would* have happened.
- A blocked allowlist decision short-circuits the call and returns an error
  envelope.

This decorator intentionally does NOT swallow exceptions raised by the tool —
the outer per-tool wrapper in :mod:`winvision_mcp.tools` handles that to ensure
a single, uniform error shape.
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from typing import Any, TypeVar

from ..logging_setup import get_logger
from ..models import OkResult, ToolError
from ..storage import log_invocation

logger = get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


def destructive(tool_name: str | None = None) -> Callable[[F], F]:
    """Mark a tool as destructive.

    Args:
        tool_name: Optional override for the logged tool name (defaults to the
            wrapped function's ``__name__``).

    Example:
        >>> @destructive("kill_process")
        ... def kill_process(pid: int, *, dry_run: bool = False, _allow: bool = True,
        ...                  _allow_reason: str = "") -> OkResult:
        ...     ...

    Wrapped tools must accept four kwargs:

    - ``dry_run`` (bool, default False): when True, the wrapper short-circuits
      and returns ``OkResult(message="DRY-RUN: ...")``.
    - ``_allow`` (bool, default True): pre-computed allowlist verdict.
    - ``_allow_reason`` (str): human-readable reason from allowlist.
    """

    def deco(fn: F) -> F:
        name = tool_name or fn.__name__

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            t0 = time.monotonic()
            dry = bool(kwargs.pop("dry_run", False))
            allow = bool(kwargs.pop("_allow", True))
            reason = str(kwargs.pop("_allow_reason", ""))

            if not allow:
                outcome = "blocked"
                err = f"blocked by allowlist: {reason}"
                log_invocation(
                    tool=name, args=_safe_args(args, kwargs), outcome=outcome,
                    duration_ms=int((time.monotonic() - t0) * 1000), error=err,
                )
                logger.warning("tool_blocked", tool=name, reason=reason)
                return ToolError(error="forbidden", message=err)

            if dry:
                outcome = "dry_run"
                msg = f"DRY-RUN: would call {name}({_short_args(args, kwargs)})"
                log_invocation(
                    tool=name, args=_safe_args(args, kwargs), outcome=outcome,
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
                return OkResult(message=msg)

            try:
                result = fn(*args, **kwargs)
                log_invocation(
                    tool=name, args=_safe_args(args, kwargs), outcome="ok",
                    duration_ms=int((time.monotonic() - t0) * 1000),
                )
                return result
            except Exception as exc:
                log_invocation(
                    tool=name, args=_safe_args(args, kwargs), outcome="error",
                    duration_ms=int((time.monotonic() - t0) * 1000), error=str(exc),
                )
                logger.exception("tool_failed", tool=name)
                raise

        return wrapper  # type: ignore[return-value]

    return deco


def _safe_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> dict[str, Any]:
    return {"args": [repr(a)[:200] for a in args], "kwargs": {k: repr(v)[:200] for k, v in kwargs.items()}}


def _short_args(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    parts = [repr(a)[:80] for a in args] + [f"{k}={repr(v)[:80]}" for k, v in kwargs.items()]
    return ", ".join(parts)
