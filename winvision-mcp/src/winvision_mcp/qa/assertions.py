"""Visual + structural assertions.

The flagship is :func:`assert_visual`, which uses MCP **sampling** so the
client's LLM grades a freshly-captured screenshot. The server itself never
holds an API key — we just ask the connected client to perform one judgment
call. This is supported by FastMCP via ``ctx.sample(...)``.

Structural assertions (:func:`assert_element_visible`, :func:`assert_text_present`)
do NOT call the LLM and run instantly.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from ..logging_setup import get_logger
from ..models import ElementQuery
from ..storage import log_assertion

if TYPE_CHECKING:
    from PIL import Image as PILImage

logger = get_logger(__name__)


_PROMPT = """\
You are a strict QA judge. The image is a screenshot of a Windows desktop application.
Decide if the following expectation holds:

EXPECTATION: {description}

Respond ONLY with a single JSON object on one line, with these fields:
  passed:     boolean — true if the expectation holds, false otherwise
  confidence: number  — your confidence in [0.0, 1.0]
  reasoning:  string  — one short sentence (max 200 chars) justifying the verdict

Do not add any prose outside the JSON. Do not wrap the JSON in code fences.
"""


async def visual_assert_via_sampling(
    *,
    ctx: Any,
    description: str,
    image: PILImage.Image,
    model_hint: str | None = None,
    persist_path: str = "",
) -> dict[str, Any]:
    """Run a visual assertion by asking the connected MCP client's LLM.

    Args:
        ctx: FastMCP request context (provides ``.sample()`` for sampling).
        description: natural-language expectation.
        image: PIL Image to grade.
        model_hint: optional model preference string forwarded to the client.
        persist_path: optional path where the screenshot was saved (logged).

    Returns:
        Dict ``{"passed": bool, "confidence": float, "reasoning": str}``.
        On any failure the dict has ``passed=False`` and a ``reasoning`` field
        explaining what went wrong (e.g. sampling unsupported by the client).
    """
    import io

    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=False)
    png_bytes = buf.getvalue()

    prompt_text = _PROMPT.format(description=description.strip())

    try:
        # FastMCP exposes ctx.sample(messages=..., system_prompt=..., model_preferences=...)
        # which abstracts MCP sampling. The exact signature varies by version;
        # we handle both shapes (positional content vs kwargs).
        messages = _build_sampling_messages(prompt_text, png_bytes)
        result = await _call_sample(ctx, messages, model_hint=model_hint)
        text = _extract_text(result)
        verdict = _parse_verdict(text, description=description)
    except Exception as exc:
        logger.warning("assert_visual_sampling_failed", err=str(exc))
        verdict = {
            "passed": False,
            "confidence": 0.0,
            "reasoning": f"sampling unavailable: {exc}",
        }

    log_assertion(
        description=description,
        passed=bool(verdict.get("passed", False)),
        confidence=float(verdict.get("confidence", 0.0)),
        reasoning=str(verdict.get("reasoning", "")),
        screenshot_path=persist_path,
    )
    return verdict


def _build_sampling_messages(prompt: str, png_bytes: bytes) -> list[Any]:
    """Build a list of ``SamplingMessage`` objects for ``ctx.sample``.

    FastMCP 3.x's ``Context.sample`` accepts ``str | Sequence[str | SamplingMessage]``;
    a raw dict shape is rejected by the underlying serializer. We construct
    real Pydantic ``SamplingMessage`` instances with mixed text+image content.
    """
    import base64

    from mcp.types import ImageContent, SamplingMessage, TextContent

    msg = SamplingMessage(
        role="user",
        content=[
            TextContent(type="text", text=prompt),
            ImageContent(
                type="image",
                data=base64.b64encode(png_bytes).decode("ascii"),
                mimeType="image/png",
            ),
        ],
    )
    return [msg]


async def _call_sample(ctx: Any, messages: list[Any], *, model_hint: str | None) -> Any:
    """Call ``ctx.sample`` across FastMCP versions.

    FastMCP 3.x exposes ``ctx.sample(messages, *, model_preferences=...)``.
    The ``model_preferences`` parameter accepts ``ModelPreferences | str | list[str]``
    — we pass a single-element list so the client's model picker uses it as
    a hint without breaking validation.
    """
    kwargs: dict[str, Any] = {"messages": messages}
    if model_hint:
        kwargs["model_preferences"] = [model_hint]
    if hasattr(ctx, "sample"):
        return await ctx.sample(**kwargs)
    if hasattr(ctx, "session") and hasattr(ctx.session, "create_message"):
        return await ctx.session.create_message(**kwargs)
    raise RuntimeError("MCP sampling unsupported by this context")


def _extract_text(result: Any) -> str:
    # FastMCP returns either an object with .content or a list of content parts.
    if hasattr(result, "content"):
        result = result.content
    if isinstance(result, list):
        for part in result:
            if isinstance(part, dict) and part.get("type") == "text":
                return str(part.get("text", ""))
            if hasattr(part, "text"):
                return str(part.text)
    if isinstance(result, str):
        return result
    return str(result)


def _parse_verdict(text: str, *, description: str) -> dict[str, Any]:
    text = text.strip()
    # Strip code fences if present.
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        # Try to find the first {...} block.
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return {"passed": False, "confidence": 0.0, "reasoning": f"invalid LLM output: {text[:120]}"}
        try:
            obj = json.loads(m.group(0))
        except Exception:
            return {"passed": False, "confidence": 0.0, "reasoning": f"unparseable LLM JSON: {text[:120]}"}
    return {
        "passed": bool(obj.get("passed", False)),
        "confidence": float(obj.get("confidence", 0.0)),
        "reasoning": str(obj.get("reasoning", ""))[:400] or f"no reasoning provided for: {description}",
    }


# --- Structural --------------------------------------------------------------


def assert_element_visible(query: ElementQuery) -> dict[str, Any]:
    """Return ``{"passed": bool, "match": ElementInfo | None}`` (deterministic, no LLM)."""
    from ..uia.finder import find_elements

    matches = find_elements(query, limit=1)
    if not matches:
        return {"passed": False, "match": None, "reason": "no element matched query"}
    _ctrl, info, _h = matches[0]
    visible = (not info.is_offscreen) and info.is_enabled
    return {"passed": bool(visible), "match": info.model_dump()}


def assert_text_present(text: str, *, window_title: str | None = None, use_ocr: bool = False) -> dict[str, Any]:
    """Return ``{"passed": bool, "where": "uia"|"ocr"|"none"}``.

    Walks the UIA tree of the target window looking for any element whose Name
    or Value contains ``text``. If ``use_ocr`` is True and UIA didn't find it,
    runs Tesseract via opencv as a fallback (Tesseract must be installed
    separately; failure to import is treated as "not found").
    """
    import sys

    if sys.platform != "win32":
        return {"passed": False, "where": "none", "reason": "Windows-only"}

    from ..uia.tree import get_window_control

    win = get_window_control(window_title) if window_title is not None else get_window_control(None)
    if win is None:
        return {"passed": False, "where": "none", "reason": "no matching window"}

    needle = text.lower()
    stack = [win]
    while stack:
        ctrl = stack.pop()
        try:
            name = (getattr(ctrl, "Name", "") or "").lower()
            val = ""
            try:
                vp = ctrl.GetValuePattern()
                if vp:
                    val = (vp.Value or "").lower()
            except Exception:
                pass
            if needle in name or needle in val:
                return {"passed": True, "where": "uia"}
            stack.extend(ctrl.GetChildren() or [])
        except Exception:
            continue

    if use_ocr:
        try:
            return _ocr_search(win, needle)
        except Exception as exc:
            return {"passed": False, "where": "none", "reason": f"OCR failed: {exc}"}

    return {"passed": False, "where": "none"}


def _ocr_search(win_ctrl: Any, needle: str) -> dict[str, Any]:
    """Best-effort OCR via pytesseract if available."""
    try:
        import pytesseract  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("pytesseract not installed") from exc

    from ..capture import capture_window
    from ..uia.tree import control_to_info

    info = control_to_info(win_ctrl)
    if info.window_handle:
        img = capture_window(info.window_handle)
        text = pytesseract.image_to_string(img).lower()
        if needle in text:
            return {"passed": True, "where": "ocr"}
    return {"passed": False, "where": "none"}
