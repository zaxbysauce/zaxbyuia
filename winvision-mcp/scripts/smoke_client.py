"""One-shot MCP client used to smoke-test the server over stdio.

Spawns ``winvision-mcp stdio`` (or ``python -m winvision_mcp stdio``), sends an
``initialize`` then a ``tools/list`` request, asserts the response is well-
formed, and prints a short summary.

Usage:
    python scripts/smoke_client.py
    python scripts/smoke_client.py --command "winvision-mcp"

Exit codes:
    0  success
    1  failed to initialize
    2  tools/list returned no tools
    3  unexpected error
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


async def _smoke(cmd: list[str]) -> int:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert proc.stdin is not None and proc.stdout is not None

    async def send(payload: dict) -> None:
        line = (json.dumps(payload) + "\n").encode("utf-8")
        proc.stdin.write(line)
        await proc.stdin.drain()

    async def recv() -> dict | None:
        line = await proc.stdout.readline()
        if not line:
            return None
        try:
            return json.loads(line.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    try:
        await send(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"sampling": {}},
                    "clientInfo": {"name": "winvision-smoke", "version": "1.0.0"},
                },
            }
        )
        init_resp = await asyncio.wait_for(recv(), timeout=10.0)
        if not init_resp or "result" not in init_resp:
            print("FAIL: initialize did not return a result", file=sys.stderr)
            print("got:", init_resp, file=sys.stderr)
            return 1
        await send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

        await send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        list_resp = await asyncio.wait_for(recv(), timeout=10.0)
        if not list_resp or "result" not in list_resp:
            print("FAIL: tools/list returned no result", file=sys.stderr)
            return 2
        tools = list_resp["result"].get("tools") or []
        if not tools:
            print("FAIL: tools/list returned an empty array", file=sys.stderr)
            return 2

        names = sorted(t.get("name", "") for t in tools)
        print(f"OK: {len(names)} tools registered")
        for n in names:
            print(f"  - {n}")
        return 0
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except Exception:
            proc.kill()


def main() -> int:
    args = sys.argv[1:]
    cmd: list[str]
    if args and args[0] == "--command" and len(args) >= 2:
        cmd = args[1].split()
    else:
        # Default: invoke via this Python interpreter.
        repo_root = Path(__file__).resolve().parent.parent
        cmd = [sys.executable, "-m", "winvision_mcp", "stdio"]
        # ensure the package is importable
        env_src = repo_root / "src"
        if str(env_src) not in sys.path and env_src.exists():
            sys.path.insert(0, str(env_src))
    try:
        return asyncio.run(_smoke(cmd))
    except Exception as exc:
        print(f"UNEXPECTED: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main())
