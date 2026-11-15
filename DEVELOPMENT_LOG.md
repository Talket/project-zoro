# PROJECT ZORO — Engineering Development Log

---

## Session 1: Research, Architecture, and Milestone 1 Foundation

### Timestamp: 2026-11-15 17:00 IST
- **Objective**: Execute Milestone 0 (Environment inspection, hardware assessment, architecture specification) and begin Milestone 1 (Foundation codebase).
- **Environment Assessment**:
  - Confirmed Host: Acer Nitro 5, Windows 11 Home (64-bit, Build 26300).
  - CPU: Intel Core i5-8300H (4 Cores / 8 Threads @ 2.30 GHz, AVX2).
  - RAM: 15.85 GB Physical Memory.
  - Dedicated GPU: NVIDIA GeForce GTX 1050 Ti (4096 MiB GDDR5, Compute Capability 6.1, Driver 581.08, CUDA 13.0).
  - Python: 3.12.10 (64-bit).
- **Architectural Findings & Decisions**:
  - *Direct NVML Access*: Verified that `nvml.dll` can be directly loaded via `ctypes` in Python 3.12, enabling $<1$ ms sampling of GPU load, VRAM, and temperature without spawning `nvidia-smi` child processes.
  - *Windows Job Objects*: Verified that `kernel32.CreateJobObjectW` and `AssignProcessToJobObject` function reliably via Python `ctypes` on Windows 11, providing kernel-enforced process containment.
  - *Windows Named Pipes*: Verified that `CreateNamedPipeW` with custom security descriptors provides high-throughput, low-latency IPC between the Core Runtime and PySide6 UI.
  - *SQLite Concurrency*: Replaced connection pooling concept with a Single-Writer Async Actor pattern over SQLite WAL mode to eliminate database lock errors.
  - *OS Security Boundary*: Established `%PROGRAMDATA%\Zoro\Security\halt.lock` with Windows DACLs (`icacls`) to prevent agent self-modification of the emergency halt state.
- **Actions Completed**:
  - Virtual environment `.venv` initialized with Python 3.12.
  - Installed packages: `PySide6-6.12.0`, `pydantic-2.14.3`, `pydantic-settings-2.16.3`, `aiosqlite-0.22.1`, `psutil-7.2.2`, `pytest-9.2.0`, `pytest-asyncio-1.5.0`, `pytest-cov-7.1.0`, `pyyaml-6.0.3`, `colorama-0.4.6`.
  - Authored foundational documentation: `README.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `SECURITY.md`, `CONFIGURATION.md`, `TESTING.md`, `CHANGELOG.md`.
  - Built `zoro.config` (`paths.py`, `settings.py` with Pydantic v2 BaseSettings).
  - Built `zoro.storage` (SQLite WAL mode, async serialized writer queue actor, versioned migrations with SHA-256 tamper verification).
  - Built `zoro.security` (Windows Job Objects via ctypes, emergency halt controller with OS DACL protection, capability permissions gate, HMAC-SHA256 chained audit logs).
  - Built `zoro.core` (Direct NVML C-bindings via ctypes, health monitor, dynamic resource governor, async pub/sub event bus, lifecycle FSM).
  - Built `zoro.ipc` (Windows Named Pipes, 4-byte length-prefixed binary framing, JSON-RPC 2.0 schemas, server and client with auto-reconnection).
  - Built `zoro.models` (Model Abstraction Layer interface `BaseModelProvider` and deterministic mock provider).
  - Built `zoro.ui` (PySide6 Obsidian & Cyan HUD window, live telemetry gauges, system tray integration, emergency button).
  - Built `scripts/` (Supervisor with Job Object containment, emergency kill switch, resume authorization script, normal launcher).
  - Built `benchmarks/` (`benchmark_models.py` empirical hardware and local model testing harness).
  - Created automated test suite in `tests/`: 25 passing unit and integration tests across all core subsystems.
  - Live verified:
    1. Headless Core Engine execution, SQLite migration execution, and NVML telemetry initialization.
    2. Emergency hard kill switch execution via `scripts/emergency_kill.py --kill`: process tree termination and creation of protected `halt.lock`.
    3. Boot rejection while halted: `python -m zoro` aborted immediately with exit code 1.
    4. Resumption authorization via `scripts/emergency_kill.py --resume`: cleared halt lock and restored normal operation.
    5. Baseline hardware benchmark: NVML successfully sampled the NVIDIA GeForce GTX 1050 Ti in < 1 ms.

---

## Session 2: Milestone 1 Independent Audit, Deep Repairs, and Rigorous Verification

### Timestamp: 2026-11-15 19:30 IST
- **Objective**: Independently audit, repair, stress test, and formally verify PROJECT ZORO Milestone 1 without advancing to Milestone 2.
- **Defects Identified & Repaired**:
  1. *Win32 64-Bit Handle Truncation Bug in ctypes*:
     - Default ctypes return type for `CreateNamedPipeW`, `CreateFileW`, and `OpenThread` is 32-bit `c_long`. On 64-bit Windows, pointer truncation occurred, yielding `ERROR_INVALID_HANDLE` (WinError 6) during I/O.
     - Repaired with explicit `_get_kernel32()` helper configuring typed `.restype = wintypes.HANDLE` and typed `.argtypes`.
  2. *Named Pipe Duplex Deadlock*:
     - Synchronous Win32 file handles serialize read and write operations via a single kernel file object lock. A continuous background reader thread calling `ReadFile` deadlocked any calling thread invoking `WriteFile` on the same handle.
     - Repaired by refactoring `NamedPipeServer` and `NamedPipeClient` to use standard asynchronous Win32 Overlapped I/O (`FILE_FLAG_OVERLAPPED`, `OVERLAPPED` structs, `WaitForSingleObject` with timeouts, `GetOverlappedResult`, and `CancelIoEx`).
  3. *Audit Key Hardcoding & Incomplete Tamper Detection*:
     - Hardcoded static HMAC secret replaced with Windows DPAPI-protected key store (`zoro.security.dpapi`), generating and persisting a machine/user-bound 256-bit cryptographic key.
     - Enhanced `verify_integrity()` with strictly sequential ID continuity checking, instantly catching deleted records (including middle and tail records) in addition to hash chaining and HMAC tampering.
  4. *Database Writer Actor Queue Draining & Rollback*:
     - Fixed `DatabaseManager._writer_loop()` to trigger transaction rollback on query errors, and added `_accepting_writes` flag to ensure all in-flight queue operations drain and commit before `close()`.
  5. *UI System Tray Minimization*:
     - Added `QApplication.setQuitOnLastWindowClosed(False)` and overrode `closeEvent()` on `ZoroMainWindow` to hide to tray on window close. Painted a crisp procedural obsidian/cyan icon onto the system tray pixmap.
- **Verification & Stress Results**:
  - Test Suite: **60 passing tests / 0 failures** executed in 4.39 seconds.
  - Test Coverage: **86% line coverage** across `zoro.*` modules (HTML report generated in `htmlcov/index.html`).
  - Empirical Hardware Resource Measurement:
    - Host Physical RAM: 15.85 GB; Active Host RAM Used: 14.55 GB; Host RAM Available: 1.30 GB.
    - ZORO Core Engine RSS: **36.52 MB**.
    - ZORO Full Stack (Core + PySide6 HUD) RSS: **70.91 MB**.
    - NVIDIA GTX 1050 Ti VRAM Free: 2.1 GB; GPU Temperature: 44 °C.
  - Milestone 1 Status: Fully verified and robust. Ready for Milestone 2 approval.
