"""Allowlist enforcement and dry-run gating for destructive tools."""

from __future__ import annotations

from .allowlist import (
    AllowlistDecision,
    check_process,
    check_window_title,
    is_blocked_process,
    summarize_policy,
)
from .dry_run import destructive

__all__ = [
    "AllowlistDecision",
    "check_process",
    "check_window_title",
    "destructive",
    "is_blocked_process",
    "summarize_policy",
]
