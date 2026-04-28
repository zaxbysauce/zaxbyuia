"""FastMCP server bootstrap.

Creates the global ``mcp`` singleton and a ``get_tool_dispatch`` helper that
the replayer uses to invoke tools by name without importing every wrapper.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .config import get_settings
from .dpi import set_per_monitor_dpi_aware
from .logging_setup import configure_logging, get_logger
from .storage import init_db
from .tools import register_all

logger = get_logger(__name__)

INSTRUCTIONS = """
WinVision: Windows 11 desktop automation and vision-LLM QA.

Always prefer UIA tools (find_elements, invoke_element, set_value) over
pixel-based click_at. Use screenshot_annotated to see the UI with numbered
marks, then reference elements by their automation_id (NOT by coordinates).

For assertions, prefer assert_element_visible / assert_text_present
(deterministic, free) over assert_visual (LLM-judged) when the check is
structural. Use assert_visual only for "looks-right" judgments that have no
clean structural form.

Recording sessions (start_recording → ... → stop_recording → replay_script)
let you turn an LLM-driven flow into a deterministic CI test that costs $0.
""".strip()


def build_mcp(*, transport: str = "stdio") -> Any:
    """Build and configure the FastMCP app singleton."""
    set_per_monitor_dpi_aware()
    settings = get_settings()
    configure_logging(level=settings.log_level, transport=transport)
    init_db()
    _prewarm_heavy_imports()

    if settings.allowlist_mode == "off":
        logger.warning(
            "ALLOWLIST_MODE_OFF",
            note="Destructive tools are NOT gated. Re-enable for production!",
        )

    from fastmcp import FastMCP  # type: ignore[import-not-found]

    mcp = FastMCP(name="winvision-mcp", instructions=INSTRUCTIONS)
    register_all(mcp)

    # Stash the dispatch helper on the instance so replayer can find it.
    mcp._winvision_dispatch = _build_dispatch(mcp)  # type: ignore[attr-defined]
    _set_singleton(mcp)
    logger.info("mcp_ready", transport=transport, data_dir=str(settings.data_dir))
    return mcp


def _prewarm_heavy_imports() -> None:
    """Eagerly import the slow modules so the FIRST tool call doesn't pay
    for them under the MCP client's request timeout.

    Without this, the first ``screenshot_*`` or ``find_elements`` call has to
    import ``windows_capture`` (which transitively imports ``cv2`` and
    ``numpy`` — collectively ~500 MB and 1-3 s on cold disk), bring up the
    UIA COM, and load the Pillow font cache. On a cold-start client with a
    30 s timeout, that can blow the budget on the very first call.

    We swallow all import errors here — non-Windows hosts and slimmed-down
    environments should still build the MCP and serve every cross-platform
    tool we expose.
    """
    import sys
    import time

    t0 = time.monotonic()
    try:
        import numpy
        from PIL import Image
    except Exception as exc:  # pragma: no cover
        logger.debug("prewarm_pillow_numpy_failed", err=str(exc))

    if sys.platform == "win32":
        try:
            import uiautomation
        except Exception as exc:  # pragma: no cover
            logger.debug("prewarm_uiautomation_failed", err=str(exc))
        try:
            import windows_capture
        except Exception as exc:
            logger.debug("prewarm_windows_capture_failed", err=str(exc))
    logger.debug("prewarm_done", duration_ms=int((time.monotonic() - t0) * 1000))


_singleton: Any = None


def _set_singleton(mcp: Any) -> None:
    global _singleton
    _singleton = mcp


def get_mcp() -> Any:
    """Return the configured MCP instance, building one with stdio defaults if missing."""
    if _singleton is None:
        return build_mcp(transport="stdio")
    return _singleton


def get_tool_dispatch() -> Callable[[str, dict[str, Any]], Any]:
    """Return a synchronous callable mapping ``(tool_name, args) -> result``.

    The replayer uses this to drive tool invocations without re-importing every
    tool module. Only synchronous tools and async-via-loop dispatch are
    supported; ``assert_visual`` (which needs a live MCP request context) is
    intentionally not replay-safe and will raise.
    """
    mcp = get_mcp()
    return getattr(mcp, "_winvision_dispatch", _build_dispatch(mcp))


def _build_dispatch(mcp: Any) -> Callable[[str, dict[str, Any]], Any]:
    import asyncio
    import inspect

    def _resolve_tool(name: str) -> Any:
        get_tool = getattr(mcp, "get_tool", None)
        if not callable(get_tool):
            tm = getattr(mcp, "_tool_manager", None)
            return getattr(tm, "_tools", {}).get(name) if tm else None
        if inspect.iscoroutinefunction(get_tool):
            return asyncio.run(get_tool(name))
        return get_tool(name)

    def dispatch(tool: str, args: dict[str, Any]) -> Any:
        tool_obj = _resolve_tool(tool)
        if tool_obj is None:
            raise KeyError(f"unknown tool: {tool}")
        fn = getattr(tool_obj, "fn", tool_obj)
        if inspect.iscoroutinefunction(fn):
            # Skip ctx-dependent tools during replay.
            if "ctx" in inspect.signature(fn).parameters:
                raise RuntimeError(f"tool '{tool}' requires MCP context; not replayable")
            return asyncio.run(fn(**args))
        return fn(**args)

    return dispatch
