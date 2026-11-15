"""Tests for PermissionGate capability evaluation and protected paths."""

from pathlib import Path
import pytest
from zoro.security.permissions import (
    ActionTier,
    PermissionDecision,
    PermissionGate,
)


def test_permission_gate_protected_paths():
    gate = PermissionGate(strict_mode=True)

    # Protected file patterns
    assert gate.is_protected_path("D:/projects/scripts/emergency_kill.py")
    assert gate.is_protected_path(r"C:\Security\halt.lock")
    assert gate.is_protected_path("supervisor.py")
    assert gate.is_protected_path("resume_zoro.bat")

    # Protected directory patterns
    assert gate.is_protected_path(r"C:\Windows\System32\cmd.exe")
    assert gate.is_protected_path(r"D:\Zoro\Security\keys.dat")

    # Normal unprotected paths
    assert not gate.is_protected_path(r"D:\Zoro\Data\test.txt")
    assert not gate.is_protected_path(r"C:\Users\User\Documents\notes.md")


def test_permission_gate_protected_file_write_denied():
    gate = PermissionGate(strict_mode=True)
    decision, msg = gate.evaluate(
        tier=ActionTier.IRREVERSIBLE_CHANGE,
        resource=r"C:\Security\halt.lock",
        is_user_approved=True,
    )
    assert decision == PermissionDecision.DENIED
    assert "hard-locked security component" in msg


def test_permission_gate_read_only_allowed():
    gate = PermissionGate(strict_mode=True)
    decision, msg = gate.evaluate(tier=ActionTier.READ_ONLY, resource=r"C:\Security\halt.lock")
    assert decision == PermissionDecision.ALLOWED


def test_permission_gate_reversible_change_allowed():
    gate = PermissionGate(strict_mode=True)
    decision, msg = gate.evaluate(tier=ActionTier.REVERSIBLE_CHANGE, resource=r"D:\workspace\file.txt")
    assert decision == PermissionDecision.ALLOWED


def test_permission_gate_confirmation_tiers():
    gate = PermissionGate(strict_mode=True)

    for tier in (ActionTier.IRREVERSIBLE_CHANGE, ActionTier.SYSTEM_SETTING, ActionTier.EXTERNAL_COMMUNICATION):
        # Without approval -> REQUIRES_CONFIRMATION
        decision, msg = gate.evaluate(tier=tier, resource=r"D:\workspace\data.bin", is_user_approved=False)
        assert decision == PermissionDecision.REQUIRES_CONFIRMATION
        assert "explicit user approval" in msg

        # With approval -> ALLOWED
        decision, msg = gate.evaluate(tier=tier, resource=r"D:\workspace\data.bin", is_user_approved=True)
        assert decision == PermissionDecision.ALLOWED
