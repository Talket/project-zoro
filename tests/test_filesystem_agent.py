"""Tests for Secure Filesystem Agent and Security Validator in PROJECT ZORO."""

from __future__ import annotations

from pathlib import Path
import pytest

from zoro.computer.filesystem.filesystem_agent import SecureFilesystemAgent
from zoro.computer.filesystem.models import FileInfo, FileOperationResult, FileRiskTier
from zoro.computer.filesystem.path_validator import PathSecurityValidator


class TestPathSecurityValidator:
    def test_canonicalize_and_allowed_roots(self, tmp_path: Path):
        root = tmp_path / "workspace"
        root.mkdir()
        validator = PathSecurityValidator(allowed_roots=[root])

        inside = root / "file.txt"
        inside.write_text("hello")
        is_val, msg, canon = validator.validate_path(inside)
        assert is_val is True
        assert canon == inside.resolve()

        outside = tmp_path / "outside.txt"
        outside.write_text("evil")
        is_val, msg, _ = validator.validate_path(outside)
        assert is_val is False
        assert "outside permitted workspace roots" in msg

    def test_directory_traversal_detection(self, tmp_path: Path):
        root = tmp_path / "workspace"
        root.mkdir()
        validator = PathSecurityValidator(allowed_roots=[root])

        traversal = root / "subdir" / ".." / ".." / "evil.txt"
        is_val, msg, _ = validator.validate_path(traversal)
        assert is_val is False

    def test_protected_security_files_blocked(self, tmp_path: Path):
        root = tmp_path / "workspace"
        root.mkdir()
        validator = PathSecurityValidator(allowed_roots=[root])

        for sec_name in ["audit.key", "emergency.lock", "zoro.pid", "audit.checkpoint"]:
            sec_file = root / sec_name
            # Blocked for write
            is_val, msg, _ = validator.validate_path(sec_file, for_write=True)
            assert is_val is False
            assert "forbidden" in msg.lower() or "tampering" in msg.lower()

    def test_protected_system_paths_blocked(self):
        validator = PathSecurityValidator(allowed_roots=[])
        for sys_path in [r"C:\Windows\System32\cmd.exe", r"C:\Program Files\App"]:
            is_val, msg, _ = validator.validate_path(sys_path, for_write=True)
            assert is_val is False
            assert "system-critical" in msg.lower()


class TestSecureFilesystemAgent:
    def test_list_dir_and_metadata(self, tmp_path: Path):
        agent = SecureFilesystemAgent(PathSecurityValidator(allowed_roots=[tmp_path]))
        f1 = tmp_path / "test1.txt"
        f1.write_text("hello world")
        sub = tmp_path / "subdir"
        sub.mkdir()

        entries = agent.list_dir(tmp_path)
        assert len(entries) == 2
        names = {e.name for e in entries}
        assert "test1.txt" in names
        assert "subdir" in names

        file_entry = [e for e in entries if e.name == "test1.txt"][0]
        assert file_entry.size_bytes == 11
        assert file_entry.is_dir is False

    def test_read_file_and_size_limit(self, tmp_path: Path):
        agent = SecureFilesystemAgent(
            validator=PathSecurityValidator(allowed_roots=[tmp_path]),
            max_read_bytes=100,
        )
        small = tmp_path / "small.txt"
        small.write_text("small content")
        assert agent.read_file(small) == "small content"

        large = tmp_path / "large.txt"
        large.write_bytes(b"A" * 200)
        with pytest.raises(ValueError, match="exceeds maximum permitted read limit"):
            agent.read_file(large)

    def test_write_copy_move_delete(self, tmp_path: Path):
        agent = SecureFilesystemAgent(PathSecurityValidator(allowed_roots=[tmp_path]))
        src = tmp_path / "src.txt"
        res_write = agent.write_file(src, "test content")
        assert res_write.success is True
        assert src.exists()

        # Copy
        dest = tmp_path / "dest.txt"
        res_copy = agent.copy_file(src, dest)
        assert res_copy.success is True
        assert dest.exists()
        assert dest.read_text() == "test content"

        # Move
        dest_moved = tmp_path / "moved.txt"
        res_move = agent.move_file(dest, dest_moved)
        assert res_move.success is True
        assert not dest.exists()
        assert dest_moved.exists()

        # Delete
        res_del = agent.delete_file(dest_moved, to_recycle_bin=False)
        assert res_del.success is True
        assert not dest_moved.exists()

    def test_preview_operation(self, tmp_path: Path):
        agent = SecureFilesystemAgent(PathSecurityValidator(allowed_roots=[tmp_path]))
        target = tmp_path / "delete_me.txt"
        target.write_text("content to delete")

        prev = agent.preview_operation("delete", target)
        assert prev.operation == "delete"
        assert prev.risk_tier == FileRiskTier.DESTRUCTIVE
        assert prev.requires_approval is True
        assert prev.total_bytes > 0
