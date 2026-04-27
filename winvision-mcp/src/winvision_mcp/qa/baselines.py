"""Visual regression baselines.

A baseline is a (PNG + metadata) pair stored under ``settings.baselines_dir``.
We content-hash each PNG so callers can detect file-system tampering. Diffs
use SSIM (Structural Similarity) from OpenCV plus a connected-component
bounding-box pass to highlight the regions that actually changed.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import get_settings
from ..models import BaselineInfo, Rect
from ..storage import get_baseline as _get_baseline_row
from ..storage import record_baseline as _record_baseline_row

if TYPE_CHECKING:
    from PIL import Image as PILImage


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def _hash_png(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def save_baseline(name: str, image: PILImage.Image, *, window_title: str = "", notes: str = "") -> BaselineInfo:
    """Persist ``image`` as a named baseline.

    Args:
        name: short identifier (used as filename stem and DB key).
        image: PIL Image (will be saved as PNG).
        window_title: optional source window title for human reference.
        notes: optional free-form notes shown in ``list_baselines``.
    """
    settings = get_settings()
    settings.ensure_dirs()
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    out_path = settings.baselines_dir / f"{safe}.png"
    image.save(out_path, format="PNG", optimize=True)
    info = BaselineInfo(
        name=name,
        window_title=window_title,
        created_at=_now_iso(),
        png_path=str(out_path),
        width=image.size[0],
        height=image.size[1],
        dpi=96.0,
        notes=notes,
        hash=_hash_png(out_path),
    )
    _record_baseline_row(info)
    return info


def get_baseline(name: str) -> BaselineInfo | None:
    return _get_baseline_row(name)


def compare_to_baseline(
    name: str,
    candidate: PILImage.Image,
    *,
    threshold_ssim: float = 0.98,
    mask_regions: list[Rect] | None = None,
) -> dict[str, Any]:
    """Compare ``candidate`` against the named baseline.

    Args:
        name: baseline name.
        candidate: live image to test.
        threshold_ssim: pass if ``ssim >= threshold_ssim``.
        mask_regions: optional rectangles painted black before comparison
            (use this to hide volatile regions like clocks, animations, etc.).

    Returns:
        Dict with keys: ``passed``, ``ssim``, ``changed_regions`` (list of Rect
        dicts), ``diff_image_path`` (PNG of red-overlay diff), ``baseline_path``,
        ``candidate_size``.
    """
    base = get_baseline(name)
    if base is None:
        return {"passed": False, "error": f"baseline '{name}' not found"}

    import cv2
    import numpy as np
    from PIL import Image

    base_img = Image.open(base.png_path).convert("RGB")
    cand = candidate.convert("RGB")
    if cand.size != base_img.size:
        cand = cand.resize(base_img.size)

    a = np.asarray(base_img)
    b = np.asarray(cand)

    if mask_regions:
        for r in mask_regions:
            x0, y0 = max(0, r.x), max(0, r.y)
            x1, y1 = min(a.shape[1], r.right), min(a.shape[0], r.bottom)
            a[y0:y1, x0:x1] = 0
            b[y0:y1, x0:x1] = 0

    a_gray = cv2.cvtColor(a, cv2.COLOR_RGB2GRAY)
    b_gray = cv2.cvtColor(b, cv2.COLOR_RGB2GRAY)
    score, diff = _ssim(a_gray, b_gray)
    # Tie the per-pixel "changed" cutoff to the same SSIM threshold the user
    # configured globally. With threshold_ssim=0.98, the cutoff is
    # (1 - 0.98) * 255 ≈ 5 — any pixel whose local SSIM dropped by more than
    # ~2% is highlighted. Without this coupling, a borderline-failing image
    # could fail the global check while reporting an empty changed_regions
    # list, which is misleading.
    pixel_cutoff = max(2.0, (1.0 - float(threshold_ssim)) * 255.0)
    changed_regions = _changed_regions(diff, pixel_cutoff=pixel_cutoff)

    # Render diff image (red-tinted overlay where it differs).
    diff_norm = (255 - (diff * 255).astype("uint8"))
    overlay = b.copy()
    mask = diff_norm > 30
    overlay[mask] = (overlay[mask] * 0.5 + np.array([255, 0, 0]) * 0.5).astype("uint8")
    diff_path = Path(base.png_path).with_suffix(".diff.png")
    Image.fromarray(overlay).save(diff_path, format="PNG")

    passed = bool(score >= threshold_ssim)
    return {
        "passed": passed,
        "ssim": float(score),
        "threshold": threshold_ssim,
        "changed_regions": [r.model_dump() for r in changed_regions],
        "diff_image_path": str(diff_path),
        "baseline_path": base.png_path,
        "candidate_size": list(cand.size),
    }


def _ssim(a: Any, b: Any) -> tuple[float, Any]:
    """Compute SSIM between two grayscale uint8 images of identical shape."""
    import cv2
    import numpy as np

    if a.shape != b.shape:
        raise ValueError(f"shape mismatch {a.shape} vs {b.shape}")

    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    kernel = (11, 11)
    sigma = 1.5

    mu1 = cv2.GaussianBlur(a, kernel, sigma)
    mu2 = cv2.GaussianBlur(b, kernel, sigma)
    mu1_sq = mu1 * mu1
    mu2_sq = mu2 * mu2
    mu1_mu2 = mu1 * mu2
    sigma1_sq = cv2.GaussianBlur(a * a, kernel, sigma) - mu1_sq
    sigma2_sq = cv2.GaussianBlur(b * b, kernel, sigma) - mu2_sq
    sigma12 = cv2.GaussianBlur(a * b, kernel, sigma) - mu1_mu2

    ssim_map = ((2 * mu1_mu2 + C1) * (2 * sigma12 + C2)) / (
        (mu1_sq + mu2_sq + C1) * (sigma1_sq + sigma2_sq + C2)
    )
    return float(ssim_map.mean()), ssim_map


def _changed_regions(ssim_map: Any, *, pixel_cutoff: float = 60.0) -> list[Rect]:
    """Find connected regions where local SSIM dropped significantly.

    Args:
        ssim_map: per-pixel SSIM map in [0, 1].
        pixel_cutoff: a pixel is "changed" when ``(1 - ssim) * 255 > cutoff``.
            By default this is tied to ``threshold_ssim`` by the caller.
    """
    import cv2
    import numpy as np

    inv = (1.0 - np.clip(ssim_map, 0, 1)) * 255
    bw = (inv > pixel_cutoff).astype("uint8") * 255
    if bw.size == 0:
        return []
    contours, _ = cv2.findContours(bw, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rects: list[Rect] = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w * h < 64:
            continue
        rects.append(Rect(x=int(x), y=int(y), width=int(w), height=int(h)))
    rects.sort(key=lambda r: r.width * r.height, reverse=True)
    return rects[:32]
