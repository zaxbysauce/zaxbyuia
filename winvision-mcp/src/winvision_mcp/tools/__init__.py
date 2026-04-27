"""MCP tool wrappers.

Each submodule exposes a ``register(mcp)`` function that registers its tools
on the shared FastMCP instance. The :func:`register_all` helper here is the
single entry point used by :mod:`winvision_mcp.server`.
"""

from __future__ import annotations

from typing import Any

from . import (
    app_tools,
    capture_tools,
    input_tools,
    qa_tools,
    system_tools,
    uia_tools,
)


def register_all(mcp: Any) -> None:
    """Register every tool group on the MCP server."""
    capture_tools.register(mcp)
    uia_tools.register(mcp)
    input_tools.register(mcp)
    app_tools.register(mcp)
    qa_tools.register(mcp)
    system_tools.register(mcp)
