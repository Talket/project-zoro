# PROJECT ZORO — Testing Guide & Verification Suite

This document defines testing standards, test execution procedures, and CI requirements for PROJECT ZORO.

---

## 1. Running the Test Suite

Run the full automated test suite with coverage reporting:

```powershell
# Using the virtual environment
.\.venv\Scripts\pytest tests/ -v --cov=zoro --cov-report=term-missing
```

To run a specific test module:
```powershell
.\.venv\Scripts\pytest tests/test_db.py -v
.\.venv\Scripts\pytest tests/test_ipc.py -v
.\.venv\Scripts\pytest tests/test_job_object.py -v
```

---

## 2. Test Architecture

The test suite covers all core subsystems with isolated unit and integration tests:

1. `test_config.py`: Verifies Pydantic v2 `BaseSettings` validation, default fallback values, environment variable overrides, and OS path resolution.
2. `test_db.py`: Verifies SQLite WAL mode activation, deterministic migration runner, transaction rollbacks, and concurrent stress testing of the Single-Writer Actor pattern.
3. `test_audit.py`: Validates cryptographic HMAC-SHA256 audit chaining, tamper-detection functions, and append-only invariants.
4. `test_event_bus.py`: Validates in-memory pub/sub routing, asynchronous handlers, exception containment, and wildcard subscriptions.
5. `test_health.py`: Verifies CPU, RAM, and direct NVML GPU telemetry sampling and threshold alert broadcasts.
6. `test_job_object.py`: Validates Win32 Job Object creation, process assignment, descendant containment, and atomic termination.
7. `test_emergency.py`: Validates pre-flight halt checks, halt lock creation, process kill triggers, and resume clearance.
8. `test_permissions.py`: Validates capability categorization, approval prompts, and hard-locked path protections.
9. `test_ipc.py`: Validates Windows Named Pipe framed JSON-RPC 2.0 communication, bidirectional request-response, notifications, overlapped full duplex I/O, and client auto-reconnection.
10. `test_lifecycle.py`: Validates state machine transitions (`INITIALIZING` $\to$ `RUNNING` $\to$ `STOPPED`), clean shutdown, signal handlers, and sleep/wake handlers.
11. `test_ui.py`: Validates PySide6 HUD telemetry rendering, signal dispatching, system tray minimization on close, and window visibility toggles.
12. `test_e2e_stress.py`: End-to-end full system lifecycle, live telemetry stream, IPC RPC roundtrips, database reboot persistence, emergency halt lock blocking, and 50+ concurrent write stress testing.
13. `test_models.py`: Validates BaseModelProvider abstraction and deterministic MockModelProvider for Milestone 1.

---

## 3. Acceptance Coverage Criteria

- **Target Coverage**: $\ge 85\%$ across `zoro.core`, `zoro.config`, `zoro.storage`, `zoro.ipc`, and `zoro.security`.
- **Actual Verified Coverage**: **86%** (60/60 passing tests).
- **Zero Lock Contention**: The SQLite write stress test must complete 100 concurrent async writes with zero `database is locked` exceptions.
- **Fail-Safe Invariant**: Emergency shutdown tests must prove that child processes terminate unconditionally.
