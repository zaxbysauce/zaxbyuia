"""Console entry point for the winvision-mcp server.

Usage:

    winvision-mcp                          # stdio transport (default; for opencode/Claude Desktop)
    winvision-mcp stdio
    winvision-mcp http --host 0.0.0.0 --port 8787   # Streamable HTTP for WSL2/remote
    winvision-mcp version
    winvision-mcp doctor                   # First-run sanity check (DPI, COM, admin, ...)
"""

from __future__ import annotations

import sys

import typer

app = typer.Typer(no_args_is_help=False, add_completion=False, help="WinVision MCP server.")


@app.command("stdio")
def run_stdio() -> None:
    """Run over the MCP stdio transport (default for opencode / Claude Desktop)."""
    from .server import build_mcp

    mcp = build_mcp(transport="stdio")
    mcp.run(transport="stdio")


@app.command("http")
def run_http(
    host: str = typer.Option("127.0.0.1", help="Bind host (use 0.0.0.0 for WSL2)."),
    port: int = typer.Option(8787, help="Bind port."),
) -> None:
    """Run over Streamable HTTP transport (for WSL2 / remote MCP clients)."""
    from .server import build_mcp

    mcp = build_mcp(transport="streamable-http")
    # FastMCP 2.x: `mcp.run(transport="streamable-http", host=..., port=...)`
    mcp.run(transport="streamable-http", host=host, port=port)


@app.command("version")
def show_version() -> None:
    """Print the package version."""
    from . import __version__

    typer.echo(__version__)


@app.command("doctor")
def doctor() -> None:
    """Run first-run sanity checks (DPI, COM init, admin, UIAccess, monitors)."""
    from .diagnostics import run as _run

    _run()


def main() -> None:
    """Console-script entry point.

    With no subcommand, default to stdio (the most common use case for opencode).
    """
    if len(sys.argv) == 1:
        run_stdio()
        return
    app()


if __name__ == "__main__":
    main()
