"""Shared helpers for tool wrappers (image conversion, PIL→FastMCP)."""

from __future__ import annotations

import io
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..logging_setup import get_logger
from ..qa.recorder import record_invocation
from ..storage import log_invocation

logger = get_logger(__name__)


def to_mcp_image(pil_img: Any, *, persist_name: str | None = None) -> Any:
    """Convert a PIL image into the FastMCP Image return type.

    Also persists a copy under ``settings.screenshots_dir`` (best-effort) so
    the user can inspect captures after the fact.
    """
    buf = io.BytesIO()
    pil_img.save(buf, format="PNG", optimize=False)  # type: ignore[attr-defined]
    data = buf.getvalue()

    if persist_name:
        try:
            settings = get_settings()
            settings.ensure_dirs()
            path = settings.screenshots_dir / f"{persist_name}.png"
            path.write_bytes(data)
        except Exception as exc:  # pragma: no cover
            logger.debug("screenshot_persist_failed", err=str(exc))

    # Try the modern FastMCP 2.x Image helper. Fall back to a structured dict
    # if that helper is not importable in the user's installed version.
    try:
        from fastmcp.utilities.types import Image  # type: ignore[import-not-found]

        return Image(data=data, format="png")
    except Exception:
        try:
            from fastmcp import Image as _Image  # type: ignore[attr-defined,unused-ignore]

            return _Image(data=data, format="png")  # type: ignore[operator,unused-ignore]
        except Exception:
            import base64

            return {
                "type": "image",
                "format": "png",
                "data_base64": base64.b64encode(data).decode("ascii"),
                "size_bytes": len(data),
            }


@contextmanager
def tool_telemetry(tool_name: str, args: dict[str, Any]):
    """Context manager that times a tool call and logs it to SQLite.

    Usage:
        with tool_telemetry("screenshot_desktop", {"monitor": 0}):
            ...
    """
    t0 = time.monotonic()
    outcome = "ok"
    err: str | None = None
    try:
        record_invocation(tool_name, args)
        yield
    except Exception as exc:
        outcome = "error"
        err = str(exc)
        raise
    finally:
        log_invocation(
            tool=tool_name,
            args=args,
            outcome=outcome,
            duration_ms=int((time.monotonic() - t0) * 1000),
            error=err,
        )


def safe_path(stem: str) -> Path:
    """Sanitize a user-supplied filename stem and resolve under data_dir."""
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)
    return get_settings().screenshots_dir / safe
