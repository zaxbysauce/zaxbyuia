"""Pydantic-based configuration.

Settings are loaded (in order) from:
  1. Environment variables prefixed with ``WINVISION_``.
  2. ``%LOCALAPPDATA%/WinVision/config.toml`` (Windows) or ``~/.winvision/config.toml``.
  3. Defaults defined in this module.

The ``WINVISION_DATA_DIR`` env var overrides the storage root used for the SQLite
database, baselines, recordings, and screenshots.
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AllowlistMode = Literal["strict", "permissive_with_confirm", "off"]


def _default_data_dir() -> Path:
    """Resolve the default storage root.

    On Windows we use ``%LOCALAPPDATA%/WinVision`` (created on first use). On
    non-Windows hosts we fall back to ``~/.winvision`` so test/import on Linux
    CI works without surprise.
    """
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            return Path(local) / "WinVision"
    return Path.home() / ".winvision"


def _config_file_paths() -> list[Path]:
    """Search paths for a ``config.toml`` (highest priority first)."""
    out: list[Path] = []
    if sys.platform == "win32" and (la := os.environ.get("LOCALAPPDATA")):
        out.append(Path(la) / "WinVision" / "config.toml")
    out.append(Path.home() / ".winvision" / "config.toml")
    return out


def _load_toml_overrides() -> dict[str, object]:
    for p in _config_file_paths():
        if p.is_file():
            try:
                with p.open("rb") as fh:
                    data = tomllib.load(fh)
                # Flatten one level: ``[allowlist] processes = [...]`` -> ``allowlist_processes``
                flat: dict[str, object] = {}
                for k, v in data.items():
                    if isinstance(v, dict):
                        for sk, sv in v.items():
                            flat[f"{k}_{sk}".lower()] = sv
                    else:
                        flat[k.lower()] = v
                return flat
            except Exception:
                continue
    return {}


class Settings(BaseSettings):
    """Top-level configuration."""

    model_config = SettingsConfigDict(
        env_prefix="WINVISION_",
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    # --- storage -------------------------------------------------------------
    data_dir: Path = Field(default_factory=_default_data_dir, description="Root storage directory.")

    # --- capture -------------------------------------------------------------
    capture_max_edge: int = Field(1600, description="Downsample longest edge to this many px.")
    capture_default_backend: Literal["wgc", "mss", "window"] = Field("wgc")

    # --- input ---------------------------------------------------------------
    input_settle_ms: int = Field(50, description="Sleep after focusing before sending input.")
    default_action_timeout_s: float = Field(10.0)

    # --- UIA walk safety -----------------------------------------------------
    # Hard wall-clock cap on any single UIA tree walk. Targets like VS Code or
    # Office expose 5k-10k accessible elements; without this guard a walk can
    # easily exceed the MCP client's 30s default timeout and the client will
    # sever the stdio connection (every subsequent tool call returns "Not
    # connected" until the user restarts opencode/Claude Desktop). 8s is well
    # under any reasonable client timeout and forces noisy targets to truncate
    # gracefully rather than hang.
    uia_walk_timeout_s: float = Field(
        8.0,
        gt=0.0,
        le=60.0,
        description="Max seconds any single UIA tree walk may consume.",
    )

    # Process names of MCP-host IDEs/terminals. screenshot_annotated refuses
    # to default to the foreground window when the foreground process matches
    # one of these — otherwise we'd walk the host IDE's giant accessibility
    # tree and time out the client.
    ide_host_processes: list[str] = Field(
        default_factory=lambda: [
            "code.exe",
            "Code.exe",
            "Cursor.exe",
            "WindowsTerminal.exe",
            "windowsterminal.exe",
            "wt.exe",
            "powershell.exe",
            "pwsh.exe",
            "cmd.exe",
            "OpenConsole.exe",
            "opencode.exe",
            "claude.exe",
            "Claude.exe",
        ]
    )

    # --- security ------------------------------------------------------------
    allowlist_mode: AllowlistMode = Field("permissive_with_confirm")
    allowlist_processes: list[str] = Field(default_factory=list)
    allowlist_window_titles: list[str] = Field(default_factory=list)
    block_processes: list[str] = Field(
        default_factory=lambda: [
            "explorer.exe",
            "winlogon.exe",
            "csrss.exe",
            "smss.exe",
            "lsass.exe",
            "services.exe",
            "system",
            "wininit.exe",
        ]
    )

    # --- logging -------------------------------------------------------------
    log_level: str = Field("INFO")

    # --- transport -----------------------------------------------------------
    http_host: str = Field("127.0.0.1")
    http_port: int = Field(8787)

    # --- derived paths -------------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.data_dir / "winvision.sqlite"

    @property
    def baselines_dir(self) -> Path:
        return self.data_dir / "baselines"

    @property
    def recordings_dir(self) -> Path:
        return self.data_dir / "recordings"

    @property
    def screenshots_dir(self) -> Path:
        return self.data_dir / "screenshots"

    def ensure_dirs(self) -> None:
        for p in (self.data_dir, self.baselines_dir, self.recordings_dir, self.screenshots_dir):
            p.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the singleton ``Settings`` instance, layering TOML over env."""
    global _settings
    if _settings is None:
        toml_overrides = _load_toml_overrides()
        # Env vars are loaded by BaseSettings; TOML fills gaps without overriding env.
        kwargs: dict[str, object] = {
            k: v for k, v in toml_overrides.items() if k not in os.environ
        }
        _settings = Settings(**kwargs)  # type: ignore[arg-type]
        _settings.ensure_dirs()
    return _settings


def reset_settings_for_tests() -> None:
    """Reset the cached settings singleton (test-only)."""
    global _settings
    _settings = None
