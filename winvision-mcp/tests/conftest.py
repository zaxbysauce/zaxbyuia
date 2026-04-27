"""Shared pytest fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point WinVision at a per-test data directory."""
    data_dir = tmp_path / "winvision-data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("WINVISION_DATA_DIR", str(data_dir))
    monkeypatch.setenv("WINVISION_ALLOWLIST_MODE", "off")
    # Reset both the settings singleton and the DB-init flag so the new
    # per-test DB file gets its schema applied.
    from winvision_mcp.config import reset_settings_for_tests
    from winvision_mcp.storage import db as _db

    reset_settings_for_tests()
    _db._initialized = False
    yield data_dir
    reset_settings_for_tests()
    _db._initialized = False


@pytest.fixture
def fixture_window_png(tmp_path: Path) -> Path:
    """Synthetic PNG used for SoM overlay tests on non-Windows hosts."""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (640, 400), (240, 240, 240))
    draw = ImageDraw.Draw(img)
    # Draw 6 fake "buttons"
    for i, (x, y) in enumerate([(20, 20), (220, 20), (420, 20), (20, 120), (220, 120), (420, 120)]):
        draw.rectangle((x, y, x + 180, y + 60), fill=(220, 220, 220), outline=(140, 140, 140))
        draw.text((x + 10, y + 20), f"Button {i+1}", fill=(20, 20, 20))
    out = tmp_path / "window.png"
    img.save(out, format="PNG")
    return out


win_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only test")
