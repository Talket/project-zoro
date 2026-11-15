# PROJECT ZORO — System Architecture Specification

## 1. Architectural Philosophy

PROJECT ZORO is engineered as an autonomous personal intelligence designed to run continuously on Windows 11. The architecture prioritizes:
1. **Decoupled Isolation**: The UI, Core Runtime, and Subagents execute across distinct boundaries. A UI freeze or agent error cannot corrupt the core engine.
2. **OS-Enforced Security**: System boundaries are enforced at the Windows kernel level (Job Objects, DACLs, Mandatory Integrity Levels) rather than relying on application-level trust.
3. **Hardware Determinism**: Active telemetry via direct C-bindings to NVIDIA NVML ensures dynamic VRAM budgeting and mutual exclusion between heavy GPU workloads.
4. **Predictable Local Concurrency**: SQLite with Write-Ahead Logging (WAL) and an async Single-Writer Actor pattern prevents database lock contention while supporting concurrent readers.

---

## 2. High-Level Subsystem Architecture

```
+---------------------------------------------------------------------------------------+
|                                    WINDOWS 11 (SESSION 1)                             |
|                                                                                       |
|   +------------------------------------+      +-----------------------------------+   |
|   |         Desktop Shell (UI)         |      |        Core Runtime Engine        |   |
|   |  - PySide6 HUD & System Tray       |      |  - Central Lifecycle FSM          |   |
|   |  - Real-time Hardware Gauges       |      |  - In-Memory Async Event Bus      |   |
|   |  - IPC Client (Background Thread)  |      |  - Hardware Governor & Watchdog   |   |
|   +-----------------+------------------+      +-----------------+-----------------+   |
|                     ^                                           ^                     |
|                     |            Windows Named Pipe             |                     |
|                     +===========================================+                     |
|                                \\.\pipe\zoro-ipc-main                                 |
|                                                                                       |
|   +-------------------------------------------------------------------------------+   |
|   |                          Persistent Storage Layer                             |   |
|   |  - SQLite (WAL Mode, synchronous=NORMAL, cache=8MB)                           |   |
|   |  - Serialized Async Write Actor (asyncio.Queue)                               |   |
|   |  - Concurrent Read Connection Pool (PRAGMA query_only=ON)                     |   |
|   |  - Deterministic Versioned Migration Runner                                   |   |
|   |  - Cryptographically Chained HMAC-SHA256 Audit Log                            |   |
|   +-------------------------------------------------------------------------------+   |
|                                                                                       |
|   +-------------------------------------------------------------------------------+   |
|   |                             OS Security Boundary                              |   |
|   |  - Windows Job Object: ZoroJobObject (KILL_ON_JOB_CLOSE, NO_BREAKAWAY)        |   |
|   |  - Protected Halt Lock: %PROGRAMDATA%\Zoro\Security\halt.lock (icacls DENY)   |   |
|   |  - Independent Emergency Controller: scripts/emergency_kill.py                |   |
|   +-------------------------------------------------------------------------------+   |
+---------------------------------------------------------------------------------------+
```

---

## 3. Subsystem Breakdown

### 3.1 Core Runtime & Orchestrator (`zoro.core`)
- **Lifecycle FSM**: Governs states: `UNINITIALIZED`, `INITIALIZING`, `RUNNING`, `PAUSED`, `SUSPENDED` (Sleep), `SHUTTING_DOWN`, `STOPPED`, and `EMERGENCY_HALTED`.
- **Async Event Bus**: In-memory publish/subscribe event dispatcher within the engine for loose coupling across internal modules.
- **Hardware Telemetry (`nvml_telemetry.py` & `health.py`)**:
  - Directly loads `nvml.dll` via `ctypes` to sample GPU core temperature, total/used/free VRAM, and GPU utilization in $<1$ ms.
  - Samples CPU load, core count, per-process memory, and disk headroom via `psutil`.
- **Dynamic Resource Governor (`governor.py`)**:
  - Enforces the **Single Heavy GPU Workload** rule: Voice STT is pinned to CPU AVX2, preserving 100% of GPU VRAM for the LLM.
  - Dynamically unloads LLM weights from VRAM after 10 minutes of inactivity.
  - Halts new inference requests if free VRAM drops below 400 MiB.

### 3.2 Inter-Process Communication (`zoro.ipc`)
- **Transport**: Windows Named Pipe (`\\.\pipe\zoro-ipc-main`) with `PIPE_ACCESS_DUPLEX`, `PIPE_TYPE_MESSAGE`, and `PIPE_READMODE_MESSAGE`.
- **Security Descriptor**: Custom SDDL restricts pipe access strictly to the owner's Windows SID and Administrators; network access is disabled (`PIPE_REJECT_REMOTE_CLIENTS`).
- **Framing Protocol**: 4-byte big-endian length prefix followed by UTF-8 encoded JSON-RPC 2.0 payloads.
- **Resilience**: GUI thread maintains an exponential backoff auto-reconnect loop (1s, 2s, 4s, up to 10s max). The engine resets pipe listeners upon detecting client disconnects.

### 3.3 Storage Subsystem (`zoro.storage`)
- **Concurrency Solution**: SQLite cannot process concurrent write transactions without locking errors. All write operations are routed through a dedicated single-worker async queue.
- **Transactions**: Atomic execution within `BEGIN IMMEDIATE ... COMMIT` blocks.
- **Read Scalability**: Independent read-only connections allow queries to execute in parallel without blocking writes.
- **Cryptographic Audit Logging (`zoro.security.audit`)**:
  - Each audit entry calculates `HMAC-SHA256(prev_hash || timestamp || actor || action || resource || details_json, key)`.
  - Sequential hash chaining links every record back to the genesis block (`00000000`).
- **Trusted External Audit Checkpoint**:
  - Eliminates the vulnerability where deleting the trailing records of an SQLite audit log could go undetected.
  - An independent checkpoint file (`data/security/audit.checkpoint`) stores `last_sequence_id`, `last_record_hash`, and a DPAPI-HMAC seal.
  - Updates are committed atomically via temporary file writes, `os.fsync`, and atomic `os.replace`.
  - `verify_integrity()` validates both internal DB continuity and external checkpoint consistency; truncation or checkpoint tampering fails closed.

### 3.4 OS Security & Emergency Controller (`zoro.security`)
- **Process Isolation via Win32 Job Object**:
  - All ZORO processes (supervisor, engine, UI, worker subprocesses) are assigned to `WindowsJobObject`.
  - **Unnamed in Production**: Created without a name (`name=None`), completely closing the named-object attack surface where external same-user processes could call `OpenJobObjectW` to clear `LimitFlags` or retain extra handles.
  - Created with NULL security attributes; kernel query confirms `HANDLE_FLAG_INHERIT == 0` (non-inheritable).
  - Configured with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000` and zero breakaway flags (`JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0`, `JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0`).
  - Child processes cannot breakaway, inherit job handles, or remove themselves from the job.
  - When the supervisor process exits, crashes, or is terminated by the emergency controller, the Windows NT kernel closes the sole handle in existence and terminates all descendant processes immediately.
  - *Scope Note*: Direct subprocesses are strictly contained; processes spawned via out-of-band external brokers (COM, WMI, Task Scheduler) execute outside the process tree.
- **Hard Kill Switch**:
  - Standalone controller `scripts/emergency_kill.py` terminates the supervisor process tree via `taskkill /F /T /PID`.
  - Terminating the supervisor closes the unnamed Job Object handle, triggering kernel-level `KILL_ON_JOB_CLOSE`.
- **Halt State Immutability & Resumption**:
  - The halt file is placed in `%PROGRAMDATA%\Zoro\Security\halt.lock` (or repository data directory).
  - Preflight checks in `ZoroEngine` and `zoro.__main__` abort initialization if `halt.lock` exists.
  - Resumption requires running `scripts/emergency_kill.py --resume` or `scripts/resume_zoro.bat`.
- **DPAPI Credential Storage**:
  - HMAC keys are protected at rest via Windows Data Protection API (`CryptProtectData`).
  - Decryption failure raises `RuntimeError` and refuses key overwrite, preserving historical audit records.
  - *Threat Boundary*: Protects against at-rest theft; does not isolate secrets from code executing under the same Windows interactive user identity.

### 3.5 Model Abstraction Layer (`zoro.models`)
- `BaseModelProvider` decouples the system from specific model formats and inference runtimes.
- Normalized error hierarchy: `ModelProviderError`, `ProviderUnavailableError`, `ProviderTimeoutError`, `ModelNotFoundError`, `CapabilityNotSupportedError`, `StructuredOutputError`, `ContextLengthExceededError`, `AuthenticationError`, `RateLimitError`.
- Adapters implemented:
  - `OllamaProvider`: Native REST adapter for Ollama (`/api/chat`, `/api/tags`, `/api/show`, NDJSON line streaming).
  - `LlamaCppProvider`: OpenAI-compatible HTTP adapter for `llama-server.exe` (`/v1/chat/completions`, Server-Sent Events chunk streaming, `/v1/models`).
  - `MockModelProvider`: Deterministic responses, queueing, latency and error simulation for offline testing and test suites.
- `ProviderRegistry`: Coordinates multiple providers, active model selection, capability discovery, and automatic fallback cascading with model parameter substitution.

### 3.6 Central AI Orchestrator (`zoro.orchestrator`)
- `ZoroOrchestrator`: Coordinates intent understanding, model generation, task decomposition, and tool execution.
- FSM State Machine: `IDLE`, `UNDERSTANDING`, `PLANNING`, `WAITING_FOR_APPROVAL`, `EXECUTING`, `WAITING_FOR_RESULT`, `COMPLETED`, `FAILED`, `CANCELLED`.
- Direct Conversational vs. Task Planning branching: Conversational prompts route directly to active LLM; task/action directives trigger DAG plan synthesis.
- Safety Boundary: Checked against `EmergencyManager` before processing any request; active halt lock aborts execution immediately.
- Human Approval Pause & Resume: Sensitive or destructive operations pause execution in `WAITING_FOR_APPROVAL` state, returning a single-use approval token. Execution resumes upon user authorization via `resolve_approval()`.

### 3.7 Multi-Step Task Planner (`zoro.planner`)
- `TaskPlan` and `PlanStep`: Pydantic models for structured plan representations, retry counts, parameter bindings, and dependencies.
- `DependencyGraph`: Directed Acyclic Graph (DAG) validator and topological execution order computation using Kahn's algorithm; cycle detection raises `CircularDependencyError`.
- `PlanValidator`: Structural and security validation enforcing maximum step bounds ($\le 20$ steps), tool existence checks, argument schema checks, and automatic permission tier assignment.
- `PlanExecutor`: Asynchronous execution engine resolving dynamic outputs across steps (`{{step_id.key}}`), managing retries for transient tool failures, pausing on approval requirements, and persisting plan/step states to SQLite (`task_plans`, `task_steps`).

### 3.8 Secure Tool Registry & Permission System (`zoro.tools`)
- `ToolRegistry`: Enforces application-level capability gates independent of LLM prompts.
- Permission Tiers:
  - `READ_ONLY`: File metadata inspection, search (Auto-allowed).
  - `LOW_RISK`: Report generation, logging (Auto-allowed with audit trail).
  - `SENSITIVE`: Moving/renaming user files (Requires explicit user approval).
  - `DESTRUCTIVE`: Permanent deletion (Requires explicit user approval).
  - `SYSTEM_CRITICAL`: Registry, OS changes (Requires elevated privileges).
- Replay Protection: `ApprovalToken` is cryptographically generated (`secrets.token_hex`), bound to specific tool and step IDs, unexpired, and transitioned immediately to `CONSUMED` upon first use to prevent replay attacks.
- Built-in Secure Tools: `FileDiscoveryTool`, `FileReadMetadataTool`, `ReportGeneratorTool`, `FileMoveTool`, `FileDeleteTool`.
- Security Boundaries: Hard locks on security paths (`audit.key`, `audit.checkpoint`, `emergency.lock`, `zoro.pid`, Windows system directories).

### 3.9 Local AI Model Benchmarking Subsystem (`zoro.benchmarks`)
- `HardwareAwareBenchmarkRunner`: Automated benchmarking suite testing model runtimes under real hardware conditions.
- Performance Metrics: Time-to-First-Token (TTFT) via asynchronous streaming, sustained token throughput (tokens/sec), host RAM and GPU VRAM load via NVML C-bindings.
- Capability Scoring: Structured JSON generation compliance, multi-constraint instruction following, and tool-calling protocol compatibility.
- Telemetry & Warnings: Emits Pascal architecture VRAM warnings when memory load approaches the 4 GB GTX 1050 Ti threshold. Persists historical results to `model_benchmarks`.

### 3.10 Desktop Shell (`zoro.ui`)
- PySide6 (Qt 6) application styled with a cybernetic dark HUD theme.
- Hardware gauges for CPU, Host RAM, GPU VRAM, and GPU Core Temperature.
- Milestone 02 Intelligence Controls: Provider dropdown, model selector, real-time AI state badge (`IDLE`, `PLANNING`, `WAITING_FOR_APPROVAL`, `EXECUTING`), directive input prompt with dispatch button, cancel button, and one-click benchmark execution button.
- Real-Time Approval Dialog: Prompts user to Approve or Reject sensitive operations when paused by the orchestrator.
- Minimizable to Windows System Tray with global context menu.
