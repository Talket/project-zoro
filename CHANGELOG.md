# PROJECT ZORO — Changelog

All notable changes to PROJECT ZORO are documented in this file in reverse chronological order.

---

## [0.1.5] - 2026-11-15 (Handle-Bound Emergency Termination & TOCTOU Race Elimination)

### Security Hardening & Race Elimination
- **Handle-Bound Process Termination**: Replaced the previous `psutil` validation followed by `taskkill /F /T /PID` sequence with atomic, handle-bound Win32 termination in `zoro/security/emergency.py`. The emergency controller now opens the target supervisor PID via `OpenProcess` (`PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE`), queries the creation timestamp directly on that handle via `GetProcessTimes`, validates it against the recorded 64-bit `creation_filetime`, and calls `TerminateProcess` using the exact same validated handle.
- **TOCTOU Race Condition Eliminated**: Eliminated Time-of-Check/Time-of-Use race windows where a process could terminate and have its PID reassigned between validation and `taskkill` invocation. Process handles hold a direct kernel reference to the validated process object, making it impossible to terminate an unrelated reused process.
- **Raw 64-bit FILETIME Persistence**: Upgraded `zoro.pid` schema to record raw 64-bit `creation_filetime` (100-nanosecond intervals since Jan 1, 1601 UTC) alongside legacy Unix timestamps for exact integer precision, eliminating floating-point rounding ambiguities.
- **Windows 11 SDK Access Mask Clarification**: Documented exact SDK version (`10.0.26100.0`) and header path (`C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\um\winnt.h`), showing macro expansion `STANDARD_RIGHTS_REQUIRED | SYNCHRONIZE | 0x3F = 0x1F003F` and decoding the difference with legacy pre-Windows 7 documentation (`0x1F001F`).
- **Test Suite Expansion**: Suite expanded to **86 automated tests** across **16 modules**, passing with **100% pass rate** in **9.95s** with **86% line coverage** across `zoro.*`.

---

## [0.1.4] - 2026-11-15 (Handle Duplication Boundary Verification & PID Reuse Validation)

### Security Verification & Hardening
- **Empirical Handle Duplication Boundary Verification**: Conducted live Win32 API testing of explicit Job Object handle duplication from external processes under the same Windows user token. Empirically demonstrated that `OpenProcess(PROCESS_DUP_HANDLE)` (handle value, err `0`) and `DuplicateHandle` (ret `1`, err `0`) succeed against same-user processes under the Windows NT interactive desktop model. Proved that retaining a duplicated handle holds the Job Object open after supervisor termination, preventing `KILL_ON_JOB_CLOSE` until that external handle closes. Documented the true OS boundary honestly in `SECURITY.md`: same-user processes sharing a logon token cannot be cryptographically isolated without separate Windows security principals or service isolation.
- **Win32 Job Object Access Mask Discrepancy Correction**: Decoded the difference between legacy Windows SDK access mask `0x1F001F` and modern Windows 11 SDK access mask `0x1F003F`. Identified bit `0x0020` as `JOB_OBJECT_IMPERSONATE` (introduced in Windows 7 / Server 2008 R2). Defined explicit symbolic constants in `zoro/security/job_object.py` and documented the bitmask decomposition in `SECURITY.md`.
- **Emergency Controller PID Reuse Protection**: Hardened `EmergencyManager` against Windows PID reuse. `record_pid()` now serializes a JSON payload containing `pid`, `create_time` (`psutil.Process(pid).create_time()`), and `recorded_at`. `validate_target_process()` and `trigger_emergency_kill()` strictly verify process creation time (`abs(actual - expected) <= 0.5s`) before executing termination; if the process does not exist or creation time differs (PID was reused by another process), termination is strictly refused to protect unrelated host applications.
- **Test Suite Expansion**: Suite expanded to **80 automated tests** across **16 modules**, passing with **100% pass rate** in **10.24s** with **86% line coverage** across `zoro.*`.

---

## [0.1.3] - 2026-11-15 (Job Object Re-Architecture & Audit Crash Consistency)

### Fixed
- **Named Job Object Security Vulnerability**: Resolved the vulnerability where named Job Objects (`Local\ZoroJobObject`) had a default DACL granting `JOB_OBJECT_ALL_ACCESS` to same-user processes, allowing external processes to retain handles and prevent `KILL_ON_JOB_CLOSE` from firing, or clear `LimitFlags` via `JOB_OBJECT_SET_ATTRIBUTES`. Re-architected `WindowsJobObject` to be **UNNAMED** by default (`name=None`). Unnamed Job Objects cannot be opened by name (`OpenJobObjectW` returns error 87), ensuring the supervisor's handle is the sole handle in existence.
- **Supervisor Job Ownership**: Configured `scripts/supervisor.py` to record the supervisor's PID so that `emergency_kill.py` terminates the supervisor process, guaranteeing that the unnamed Job Object handle closes and kernel `KILL_ON_JOB_CLOSE` fires unconditionally.
- **Threat Model Corrections**: Corrected `SECURITY.md` and `ARCHITECTURE.md` to remove overstated claims regarding DPAPI and cold boot attacks, explicitly distinguishing direct process containment from out-of-band external brokers (COM, WMI, Task Scheduler) and clarifying same-user process boundaries.

### Added
- **Audit Checkpoint Crash Consistency Verification**: Added tests and verification covering crashes before checkpoint replacement (database ahead of checkpoint), stray `.tmp` file resilience, missing checkpoint fail-closed behavior, and explicit manual recovery policy.
- **Job Object Handle Security Tests**: Added unit tests verifying unnamed Job Object non-openable status, empirical proof of named job same-user access, and unconditional termination on close.
- **Test Suite Expansion**: Suite expanded to **76 automated tests** across **16 modules**, passing with **100% pass rate** in **9.54s** with **86% line coverage** across `zoro.*`.

---

## [0.1.2] - 2026-11-15 (Milestone 1 Final Security Hardening & Acceptance)

### Fixed
- **Audit Log Tail-Deletion Vulnerability**: Solved the tail-truncation vulnerability where deleting trailing SQLite audit records went undetected. Added trusted, external HMAC-signed checkpoint (`data/security/audit.checkpoint`) committed atomically with `os.fsync` + `os.replace`. `verify_integrity()` now fails closed on tail deletion, middle deletion, record alteration, or checkpoint tampering.
- **DPAPI Key Overwrite Vulnerability**: Refactored `AuditKeyManager.get_or_create_key()` to raise `RuntimeError` and log a critical security event if `audit.key` exists but fails decryption, strictly refusing to overwrite the key or silently invalidate historical audit logs.
- **Settings Plaintext Key Deprecation**: Removed hardcoded HMAC keys from default settings; configured `audit_hmac_key: Optional[str] = None` with deprecation note, ensuring DPAPI is the sole key source.
- **Test Module Deduplication**: Removed redundant scratch module `tests/test_engine_and_ipc.py` and consolidated tests into dedicated single-responsibility modules.

### Added
- **Job Object Kernel Inspection Methods**: Added `query_limit_flags()`, `is_handle_inheritable()`, and `query_active_process_count()` to `WindowsJobObject` using Win32 `QueryInformationJobObject` and `GetHandleInformation`.
- **7 Live Windows NT Failure Scenarios**: Automated and verified all 7 emergency scenarios in `tests/test_emergency_scenarios.py`:
  1. Normal emergency shutdown with child process termination and halt persistence.
  2. Supervisor crash (parent killed $\to$ Job Object terminates core via `KILL_ON_JOB_CLOSE`).
  3. Core crash (core crashes or exits $\to$ supervisor detects and handles).
  4. Child process containment (child spawns grandchild $\to$ all contained and killed).
  5. Handle inheritance rejection (`HANDLE_FLAG_INHERIT == 0`, raw handle access returns `ERROR_INVALID_HANDLE`).
  6. Halt lock persistence (startup blocked while halted, resume clears lock).
  7. Repeated cycle (boot $\to$ emergency kill $\to$ resume $\to$ boot 10x consecutively).
- **Test Suite Expansion**: Suite expanded to **70 automated tests** across **16 modules**, passing in **8.16s** with **85% line coverage** across `zoro.*`.
- **Threat Model Update**: Documented the 3 explicit threat levels and DPAPI same-user boundaries in `SECURITY.md`.

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
