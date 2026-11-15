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
- **Audit Logging**: Each audit entry includes `HMAC-SHA256(prev_hash || timestamp || action || details, key)`. Any manual database alteration invalidates subsequent hashes.

### 3.4 OS Security & Emergency Controller (`zoro.security`)
- **Process Isolation**: All ZORO processes belong to a kernel-managed Windows Job Object.
- **Hard Kill Switch**: An external script/shortcut executes `TerminateJobObject`, killing the entire process tree unconditionally.
- **Halt State Immutability**: The halt file is placed in `%PROGRAMDATA%\Zoro\Security\halt.lock`. Windows DACLs (`icacls`) explicitly deny write and delete privileges to the interactive user, preventing agent self-modification.

### 3.5 Model Abstraction Layer (`zoro.models`)
- `BaseModelProvider` decouples the system from specific model formats.
- Supports `LlamaServerProvider` (native C++ `llama-server.exe` with exact `-ngl` GPU layer controls and `q8_0` KV cache quantization) and `OllamaProvider`.
- Includes `MockModelProvider` for automated testing without requiring local weights.

### 3.6 Desktop Shell (`zoro.ui`)
- PySide6 (Qt 6) application styled with a clean, functional dark theme.
- Displays real-time hardware telemetry gauges, activity feeds, and system state.
- Minimizable to the Windows System Tray with global context menu.
