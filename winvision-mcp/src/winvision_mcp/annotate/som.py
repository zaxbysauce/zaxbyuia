"""Set-of-Marks visual overlay.

Given an image and a list of (id, rect, label) triples, draw:

- A semi-transparent yellow filled rectangle on each region.
- A black-on-white numbered tag in the top-left corner of the box.

The result is a flat PIL Image suitable for sending to a vision LLM. Returns
both the image and the legend so callers can map a chosen mark back to its
underlying UI element.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..models import ElementInfo, Rect

if TYPE_CHECKING:
    from PIL import Image as PILImage


def annotate_set_of_marks(
    base: PILImage.Image,
    marks: list[tuple[int, Rect, ElementInfo]],
    *,
    crop_offset: tuple[int, int] = (0, 0),
    box_color: tuple[int, int, int, int] = (255, 230, 0, 80),
    border_color: tuple[int, int, int, int] = (255, 140, 0, 255),
    label_text_color: tuple[int, int, int, int] = (0, 0, 0, 255),
    label_bg_color: tuple[int, int, int, int] = (255, 255, 255, 235),
) -> tuple[PILImage.Image, dict[str, ElementInfo]]:
    """Render numbered marks over interactable UI regions.

    Args:
        base: Source PIL image (will not be mutated).
        marks: list of ``(mark_number, rect_in_screen_coords, element_info)``.
        crop_offset: ``(dx, dy)`` to subtract from rect coords; useful when
            ``base`` is a window-only screenshot rather than full desktop.
        box_color: RGBA fill for highlight boxes.
        border_color: RGBA stroke for highlight box outlines.

    Returns:
        ``(annotated_image_rgb, legend)`` where ``legend`` maps the printed
        mark string (e.g. ``"7"``) to the corresponding :class:`ElementInfo`.
    """
    from PIL import Image, ImageDraw

    legend: dict[str, ElementInfo] = {}
    img = base.convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")

    font = _load_font(_pick_font_size(base.size))
    label_font = _load_font(max(11, _pick_font_size(base.size) - 2))

    dx, dy = crop_offset
    for n, rect, info in marks:
        x0 = rect.x - dx
        y0 = rect.y - dy
        x1 = rect.right - dx
        y1 = rect.bottom - dy
        if x1 <= x0 or y1 <= y0:
            continue
        # Filled translucent box
        draw.rectangle((x0, y0, x1, y1), fill=box_color, outline=border_color, width=2)

        label = str(n)
        # Compute label box size
        try:
            tb = label_font.getbbox(label)
            tw = tb[2] - tb[0]
            th = tb[3] - tb[1]
        except Exception:
            tw, th = 12, 14
        pad = 3
        lx0 = x0
        ly0 = max(0, y0 - th - pad * 2)
        lx1 = lx0 + tw + pad * 2
        ly1 = ly0 + th + pad * 2
        if ly0 < 0:
            ly0 = y0
            ly1 = y0 + th + pad * 2
        draw.rectangle((lx0, ly0, lx1, ly1), fill=label_bg_color, outline=border_color, width=1)
        draw.text((lx0 + pad, ly0 + pad - 1), label, font=label_font, fill=label_text_color)

        legend[label] = info

    out = Image.alpha_composite(img, overlay).convert("RGB")
    _ = font  # reserved for future caption text
    return out, legend


def _pick_font_size(image_size: tuple[int, int]) -> int:
    """Scale font size with image dimensions so labels stay readable."""
    longest = max(image_size)
    if longest <= 800:
        return 12
    if longest <= 1280:
        return 14
    if longest <= 1920:
        return 16
    return 18


def _load_font(size: int):  # type: ignore[no-untyped-def]
    from PIL import ImageFont

    for name in ("seguiemj.ttf", "segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default()
