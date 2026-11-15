# PROJECT ZORO — Changelog

All notable changes to PROJECT ZORO are documented in this file in reverse chronological order.

---

## [0.1.1] - 2026-11-15 (Milestone 1 Verification & Hardening)

### Fixed
- **Win32 64-bit Handle Truncation**: Fixed default 32-bit `c_long` return types in `ctypes` for `CreateNamedPipeW`, `CreateFileW`, and `OpenThread`, ensuring 64-bit pointers are not corrupted.
- **Named Pipe Duplex Deadlock**: Replaced synchronous pipe I/O with Win32 Overlapped I/O (`FILE_FLAG_OVERLAPPED`), eliminating duplex lock deadlock between reader threads and writer callers.
- **Database Writer Rollback & Queue Drain**: Added automatic transaction rollback on failed statements and `_accepting_writes` flag for clean queue draining during shutdown.
- **Audit Tamper Detection**: Added sequential ID continuity checking in `verify_integrity()` to detect record deletions (middle and tail records).
- **Windows DPAPI Key Management**: Added `AuditKeyManager` utilizing `CryptProtectData` to safeguard the audit HMAC key.
- **Desktop UI Tray Minimization**: Configured `quitOnLastWindowClosed(False)` and overrode `closeEvent` to ensure window closes minimize to the system tray rather than exiting.

### Added
- Comprehensive test suite expansion to **60 automated tests** achieving **86% line coverage** across `zoro.*`.
- End-to-end full system lifecycle and concurrency stress verification suite (`tests/test_e2e_stress.py`).
- Desktop UI and window unit test suite (`tests/test_ui.py`).
- Asynchronous event bus unit test suite (`tests/test_event_bus.py`).
- Permission gate capability evaluation test suite (`tests/test_permissions.py`).

---

## [0.1.0] - 2026-11-15

### Added
- Comprehensive project documentation suite (`README.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `SECURITY.md`, `CONFIGURATION.md`, `TESTING.md`, `DEVELOPMENT_LOG.md`).
- Virtual environment `.venv` with Python 3.12, PySide6, Pydantic v2, aiosqlite, and psutil.
- Windows Job Object process containment architecture (`ZoroJobObject`).
- OS-level DACL emergency halt controller and resumption batch scripts.
- Direct `nvml.dll` C-bindings for hardware telemetry.
- Serialized Single-Writer SQLite storage engine with WAL mode and cryptographic HMAC audit chaining.
- Windows Named Pipe framed JSON-RPC 2.0 inter-process communication subsystem.
- PySide6 dark obsidian HUD desktop shell with system tray integration.
- Automated pytest test suite covering core components.
