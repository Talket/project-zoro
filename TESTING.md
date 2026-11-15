# PROJECT ZORO — Testing Guide & Verification Suite

This document defines testing standards, test execution procedures, and the comprehensive test inventory for PROJECT ZORO.

---

## 1. Running the Test Suite

Run the full automated test suite with coverage reporting:

```powershell
# Using the virtual environment on Windows 11
.\.venv\Scripts\pytest tests/ -v --cov=zoro --cov-report=term-missing
```

To run a specific test module:
```powershell
.\.venv\Scripts\pytest tests/test_db.py -v
.\.venv\Scripts\pytest tests/test_ipc.py -v
.\.venv\Scripts\pytest tests/test_job_object.py -v
.\.venv\Scripts\pytest tests/test_emergency_scenarios.py -v
```

---

## 2. Test Architecture & Reconciled Module Inventory

The test suite contains **125 automated tests** structured across **21 dedicated test modules** in `tests/`:

| # | Test Module | Tests | Execution Time | Subsystem Under Test & Verification Scope |
| :--- | :--- | :---: | :---: | :--- |
| 1 | `tests/test_audit.py` | 13 | 0.85s | Cryptographic HMAC-SHA256 audit chaining, DPAPI key protection/unprotection, corrupted key fail-closed behavior, intermediate record tampering detection, middle deletion detection, external audit checkpoint atomic writes (`audit.checkpoint`), single and multiple tail-deletion detection, checkpoint tampering detection, persistence across restarts, crash consistency when database is ahead, stray temp file handling, missing checkpoint fail-closed, and manual recovery. |
| 2 | `tests/test_benchmarks.py` | 4 | 1.99s | Hardware-Aware Local AI Model Benchmarking: host RAM and GPU VRAM load, runtime availability detection, latency/TTFT, throughput (tokens/sec), streaming fallback, JSON compliance scoring, instruction following scoring, and database persistence into `model_benchmarks`. |
| 3 | `tests/test_config.py` | 3 | 0.12s | Pydantic v2 `BaseSettings` validation, default configuration parameters, environment variable overrides (`ZORO_*`), and dynamic path resolution. |
| 4 | `tests/test_db.py` | 8 | 1.15s | SQLite WAL mode activation, deterministic migration runner, checksum tamper detection, transaction rollbacks on failure, 50-task serialized writer queue concurrency, shutdown with pending writes, and idempotent initialization. |
| 5 | `tests/test_e2e_intelligence.py` | 2 | 4.08s | Milestone 02 End-to-End Intelligence Pipeline: full integration over Windows Named Pipe IPC, AI provider discovery, active model selection, benchmark execution, direct conversational chat, multi-step planning, sensitive tool execution pausing for human approval, single-use token resolution, database persistence, and emergency halt interception. |
| 6 | `tests/test_e2e_stress.py` | 2 | 2.10s | End-to-end full system lifecycle, live telemetry stream, Named Pipe IPC RPC roundtrips, database reboot persistence, emergency halt lock blocking, and high-concurrency stress testing. |
| 7 | `tests/test_emergency.py` | 11 | 0.85s | Unit-level `EmergencyManager` logic: pre-flight halt checks, halt lock creation/resumption, runtime PID and 64-bit `creation_filetime` persistence, handle-bound process termination (`OpenProcess` $\to$ `GetProcessTimes` $\to$ `TerminateProcess` $\to$ `WaitForSingleObject`), anti-PID-reuse verification, stale/malformed record handling, handle cleanup on all failure paths, proof of same-handle execution without `taskkill`, repeated shutdown cycles, and kernel file sharing lock behavior (`WinError 32`). |
| 8 | `tests/test_emergency_scenarios.py` | 7 | 3.37s | 7 live Windows NT failure and emergency shutdown scenarios: (1) normal emergency kill with halt persistence, (2) supervisor crash terminating child via `KILL_ON_JOB_CLOSE`, (3) core crash detected by supervisor, (4) child/grandchild containment and atomic termination, (5) handle non-inheritance rejection (`HANDLE_FLAG_INHERIT=0`, `ERROR_INVALID_HANDLE=6`), (6) halt lock persistence and restart refusal, (7) 10x repeated cycle of boot $\to$ emergency kill $\to$ resume $\to$ boot. |
| 9 | `tests/test_engine.py` | 2 | 0.45s | Central `ZoroEngine` orchestrator initialization, pre-flight halt gate blocking, subsystem coordination, RPC dispatcher, and background telemetry loop. |
| 10 | `tests/test_event_bus.py` | 3 | 0.10s | In-memory asynchronous publish/subscribe routing, handler exception containment/isolation, and wildcard (`*`) pattern subscriptions. |
| 11 | `tests/test_health.py` | 6 | 0.35s | Hardware telemetry sampling structure, NVML GPU fallback when GPU absent, resource threshold alert generation, Resource Governor workload acquisition/release, VRAM ceiling admission refusal, and idle model eviction triggers. |
| 12 | `tests/test_intelligence_db.py` | 1 | 0.25s | Schema migration 003 validation: verifies 8 new tables (`ai_providers`, `ai_models`, `model_benchmarks`, `conversations`, `messages`, `task_plans`, `task_steps`, `tool_executions`), foreign keys, and CRUD operations. |
| 13 | `tests/test_ipc.py` | 5 | 1.25s | Win32 Overlapped Named Pipe IPC, 4-byte length-prefixed framing protocol, partial buffer reassembly, oversized frame rejection, bidirectional RPC roundtrip, client auto-reconnection, and unsolicited notification broadcasting. |
| 14 | `tests/test_job_object.py` | 8 | 1.10s | Windows Job Object Win32 API, process assignment, named termination, kernel limit flags (`KILL_ON_JOB_CLOSE = 0x2000`, zero breakaway), handle non-inheritance (`HANDLE_FLAG_INHERIT == 0`), process accounting, unnamed Job Object default and non-openable verification, empirical proof of named job same-user access, unconditional termination on close, and empirical verification of same-user explicit handle duplication (`PROCESS_DUP_HANDLE`) boundary. |
| 15 | `tests/test_lifecycle.py` | 4 | 0.20s | State machine transitions (`INITIALIZING` $\to$ `RUNNING` $\to$ `STOPPED`), clean shutdown hooks, signal handlers, pre-flight halt blocking, and resume blocking while halted. |
| 16 | `tests/test_main.py` | 4 | 0.15s | CLI entry point parsing, preflight halt exit (`sys.exit(1)`), `--headless` execution dispatch, `--ui` execution dispatch, and async engine runner helper. |
| 17 | `tests/test_model_providers.py` | 8 | 0.39s | AI Provider Abstraction: Mock, Ollama, and llama.cpp adapters; health checks, model catalog discovery, streaming chunk generation (NDJSON and SSE), error normalization, and ProviderRegistry fallback cascading. |
| 18 | `tests/test_models.py` | 2 | 0.08s | `BaseModelProvider` interface, health check, capabilities contract, and deterministic `MockModelProvider` chat completions. |
| 19 | `tests/test_orchestrator.py` | 6 | 0.94s | Central AI Orchestrator: direct chat vs task planning classification, FSM state machine transitions, human approval pause & resume, approval rejection handling, emergency halt refusal, and cancellation. |
| 20 | `tests/test_permissions.py` | 5 | 0.10s | Capability categorization (5 tiers), read-only auto-allow, reversible change logging, irreversible change confirmation prompts, and hard-locked protected path enforcement. |
| 21 | `tests/test_task_planner.py` | 9 | 1.02s | Multi-step task planner: DAG dependency resolution (Kahn's topological sort), cycle detection (`CircularDependencyError`), plan validator step limits, approval pause/resume, step retries, and dynamic input parameter interpolation. |
| 22 | `tests/test_tool_registry.py` | 8 | 1.23s | Secure Tool Registry: argument/output validation, 5 capability tiers, single-use approval tokens, replay attack rejection, execution timeouts, built-in file tools, hard-locked security paths, and audit logging. |
| 23 | `tests/test_ui.py` | 4 | 0.70s | PySide6 Desktop HUD: hardware telemetry rendering, window close-to-tray minimization, tray toggle, AI state badge, directive input prompt, approval prompt dialog, and benchmark runner controls. |
| **Total** | **21 Modules** | **125 Tests** | **~24.65s** | **Milestone 01 Core Foundation + Milestone 02 Intelligence Core** |

---

## 3. Verified Coverage & Quality Metrics

- **Total Statements**: 3,750
- **Missed Statements**: 523
- **Overall Line Coverage**: **86%** (exceeds the $\ge 85\%$ milestone requirement).
- **Test Pass Rate**: **100%** (125 passed, 0 failed, 0 skipped, 0 errors).
- **Execution Speed**: 125 tests execute in **24.65 seconds** on the host Windows machine.
- **Milestone 01 Regressions**: **0 regressions** (all 86 foundation tests pass).
- **Milestone 02 Additions**: **39 new tests** verifying all intelligence core components.
- **SQLite Concurrency Invariant**: Zero database lock errors under serialized writer load.
- **Kernel Process Containment Invariant**: Descendant processes cannot escape the Job Object, cannot inherit job handles, and are terminated unconditionally upon job termination or supervisor crash.
- **Explicit Duplication Boundary**: Empirically verified that same-user processes can duplicate unnamed job handles via Win32 `OpenProcess(PROCESS_DUP_HANDLE)` + `DuplicateHandle()`; documented that same-user isolation is not an OS security boundary under the standard Windows interactive desktop token model.
- **Handle-Bound Termination Invariant**: Empirically verified that emergency termination operates exclusively on the opened, validated process handle (`TerminateProcess`), preventing Time-of-Check/Time-of-Use (TOCTOU) races and never invoking `taskkill`.
- **PID Reuse Invariant**: Verified that emergency termination refuses execution if the process creation timestamp on the opened handle does not match the recorded supervisor timestamp, strictly preventing accidental termination of reused PIDs.
- **Handle Cleanup Invariant**: Verified that Win32 process handles are reliably closed via `CloseHandle` on all failure and success paths.
