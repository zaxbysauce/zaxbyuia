"""Allowlist policy tests (cross-platform safe — uses string PIDs)."""

from __future__ import annotations

import pytest

from winvision_mcp.config import reset_settings_for_tests
from winvision_mcp.security.allowlist import check_process, is_blocked_process


def test_block_list_is_unconditional(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WINVISION_ALLOWLIST_MODE", "off")
    reset_settings_for_tests()
    # explorer is on the default block list; even off-mode shouldn't allow killing it.
    decision = check_process("explorer.exe", action="kill")
    # In off-mode, the function may return allowed=True for non-blocked names,
    # but explorer.exe should be blocked.
    assert is_blocked_process("explorer.exe") is True
    assert decision.allowed is False
    assert "block list" in decision.reason


def test_strict_mode_rejects_unlisted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WINVISION_ALLOWLIST_MODE", "strict")
    monkeypatch.setenv("WINVISION_ALLOWLIST_PROCESSES", '["notepad.exe"]')
    reset_settings_for_tests()

    decision = check_process("totally-not-on-list.exe", action="kill")
    assert decision.allowed is False
    assert "not on the allowlist" in decision.reason

    listed = check_process("notepad.exe", action="kill")
    assert listed.allowed is True


def test_permissive_mode_allows_with_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WINVISION_ALLOWLIST_MODE", "permissive_with_confirm")
    reset_settings_for_tests()
    decision = check_process("foo.exe", action="kill")
    assert decision.allowed is True
    assert "permissive" in decision.reason
