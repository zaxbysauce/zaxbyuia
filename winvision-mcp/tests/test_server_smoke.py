"""Server build smoke test.

We don't actually run the stdio loop here — instead we just verify the FastMCP
instance can be constructed and the tool registry is non-empty. The end-to-end
JSON-RPC smoke is in scripts/smoke_client.py and exercised manually.
"""

from __future__ import annotations

import sys

import pytest


def test_server_builds_and_registers_tools() -> None:
    pytest.importorskip("fastmcp")

    import asyncio

    from winvision_mcp.server import build_mcp

    mcp = build_mcp(transport="stdio")
    # FastMCP 3.x: list_tools is async. Older versions exposed sync get_tools.
    if hasattr(mcp, "list_tools"):
        tools_list = asyncio.run(mcp.list_tools())
    elif hasattr(mcp, "_tool_manager"):
        tools_list = list(getattr(mcp._tool_manager, "_tools", {}).values())
    else:
        tools_list = []
    assert tools_list, "FastMCP did not register any tools"
    names = {t.name for t in tools_list}
    # Spot-check a few we know we registered.
    expected_subset = {
        "screenshot_desktop",
        "screenshot_annotated",
        "find_elements",
        "list_windows",
        "click_at",
        "type_text",
        "assert_visual",
        "baseline_capture",
        "list_baselines",
        "get_system_info",
    }
    missing = expected_subset - names
    assert not missing, f"missing expected tools: {missing}"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
def test_list_windows_returns_a_list() -> None:
    from winvision_mcp.input.focus import list_windows

    out = list_windows(visible_only=True)
    assert isinstance(out, list)
    # Almost guaranteed to have at least one visible top-level window in a
    # normal test environment.
    assert len(out) >= 1
