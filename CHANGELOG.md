# PROJECT ZORO — Changelog

All notable changes to PROJECT ZORO are documented in this file in reverse chronological order.

---

## [0.4.0] - 2026-11-16 (Milestone 04: High-Speed Local Voice Interaction)

### Added
- **Audio Capture & Speaker Playback Foundation (`zoro.voice.audio`)**:
  - `AudioDeviceManager`: Real-time query and enumeration of host audio endpoints via PortAudio/`sounddevice`, with fallback device synthesizer for headless or restricted CI environments.
  - `CircularAudioBuffer`: Thread-safe ring buffer with bounded capacity and overflow eviction, offering `write`, `get_recent`, `get_all`, and `get_all_bytes`.
  - `AudioCaptureManager`: Non-blocking microphone stream acquisition (16,000 Hz, 16-bit PCM mono), RMS visual gain calculation, listener callbacks, and synthetic frame injection.
  - `AudioPlaybackManager`: Queue-based streaming speaker output with immediate cancellation (<10ms stop), volume scaling, and finished callbacks.
- **Voice Activity Detection (`zoro.voice.vad`)**:
  - `VoiceActivityDetector`: WebRTC VAD engine combined with RMS energy-floor gating (>1100x real-time speed, sub-2ms processing for 2 seconds of audio), tracking speech onset, active presence, and speech termination.
- **Offline Local Wake-Word Detection (`zoro.voice.wake`)**:
  - `WakeWordDetector`: Dual wake-phrase detector supporting **"Zoro"** (primary) and **"Hey Zoro"** (alternative), both enabled by default with independent toggles. Includes acoustic fricative/spectral analysis, fast transcription hint matching, cooldown enforcement, Push-to-Talk activation, and self-voice suppression during assistant playback.
- **Modular Speech-to-Text Subsystem (`zoro.voice.stt`)**:
  - `BaseSTTProvider` interface specifying async loading, model eviction, structured transcription (`STTResult`), and health verification.
  - `FasterWhisperProvider`: Local CPU-based CTranslate2 inference pinned strictly to `compute_type="int8"` (consuming 0 MB GPU VRAM, leaving 100% of 4GB GTX 1050 Ti VRAM for Ollama/llama.cpp).
  - `WhisperCppProvider`: Standalone CLI adapter for `whisper-cli.exe`.
  - `MockSTTProvider`: Deterministic transcription queueing, latency injection, and simulated failure testing.
  - `STTRegistry`: Provider registry with active provider switching, RAM eviction, and automatic cascading fallback.
- **Modular Text-to-Speech Subsystem (`zoro.voice.tts`)**:
  - `BaseTTSProvider` interface for complete and incremental chunk streaming (`TTSAudioChunk`).
  - `WindowsSapiTTSProvider`: 100% offline, zero-dependency native Windows 11 SAPI5 synthesizer using `SAPI.SpVoice` with `SAPI.SpMemoryStream` (~100ms first-chunk in-memory synthesis, zero disk I/O, zero VRAM).
  - `PiperTTSProvider`: ONNX neural voice synthesis wrapper with streaming raw output.
  - `MockTTSProvider`: Synthetic 440 Hz PCM tone generator for test automation.
  - `TTSRegistry`: Dynamic provider coordinator with sentence streaming and failover cascading.
- **Conversational Voice Engine (`zoro.voice.conversation`)**:
  - `VoiceTurnManager`: Conversational context preservation across turns, multi-sentence splitting for streaming TTS, direct routing to Central AI Orchestrator, and verbal approval prompts for sensitive operations.
  - `VoiceSessionManager`: Session lifecycle and privacy-compliant SQLite logging (`voice_sessions`, `voice_utterances`) with zero raw audio persistence and full history purge (`clear_history`).
  - `InterruptionManager`: Barge-in playback cancellation detecting explicit stop keywords ("stop", "cancel", "quiet", "shut up", "hold on") or high-energy speech onset during active playback.
- **Streaming Voice Pipeline (`zoro.voice.pipeline`)**:
  - `VoicePipeline`: Unified asynchronous pipeline orchestrating Capture -> VAD -> Wake Word -> STT -> Orchestrator -> Sentence-chunked TTS -> Playback, with FSM states (`IDLE`, `LISTENING`, `WAKE_DETECTED`, `TRANSCRIBING`, `THINKING`, `SPEAKING`, `INTERRUPTED`, `ERROR`, `DISABLED`).
  - `StreamingTextChunker`: Incremental sentence splitter turning streaming LLM token streams into natural spoken sentences.
- **Monitoring & Device Health (`zoro.voice.monitoring`)**:
  - `VoiceMetricsCollector`: Running average latencies for STT, TTFT, TTS, and total turnaround times stored in `voice_metrics`.
  - `VoiceHealthMonitor`: Real-time audio endpoint and hardware health monitor.
- **Central Facade & Named Pipe RPCs (`zoro.voice.manager` & `zoro.core.engine`)**:
  - `VoiceManager` facade coordinating all voice components, emergency halt checks, and EventBus broadcasting.
  - Registered 17 `voice.*` Named Pipe JSON-RPC methods on `ZoroEngine` and wired real-time notifications to the IPC server.
- **PySide6 Desktop HUD Integration (`zoro.ui`)**:
  - Dedicated Voice Control & Audio Pipeline panel in HUD: Voice state pill, Enable/Disable toggle, Push-to-Talk, Stop Speaking, Wake-word listening toggle, and independent checkboxes for "Zoro" and "Hey Zoro".
- **Database Schema Migration 005 (`005_voice_interaction.sql`)**:
  - Added 4 tables: `voice_sessions`, `voice_utterances`, `voice_metrics`, `voice_settings`.
- **Security & Privacy Invariants**:
  - Emergency hard kill immediately terminates audio capture and playback streams and freezes all voice RPCs.
  - Wake-word detection only activates microphone listening; never bypasses permission tiers or approval tokens.
  - Raw audio bytes are never stored in database, audit logs, or telemetry payloads.
- **Automated Test Suite**:
  - Expanded test suite to **266 automated tests** across **43 modules**, passing with **100% pass rate** in **37.45s** with **86% overall line coverage** across `zoro.*`.

---

## [0.3.0] - 2026-11-16 (Milestone 03: Windows Computer Control, UI Automation & Execution Sandbox)

### Added
- **Windows UI Automation Engine (`zoro.computer.ui`)**:
  - `WindowManager`: Full Win32 window management (`list_windows`, `find_window`, `focus_window`, `minimize_window`, `maximize_window`, `restore_window`, `close_window`, `move_resize_window`, `is_hung` using `IsHungAppWindow`).
  - `UIElementInspector`: UIA accessibility inspection via `pywinauto` backend extracting element hierarchies, control types, automation IDs, and bounding rectangles.
  - `UIElementInteractor`: Native pattern interaction dispatching `invoke`, `set_value`, `toggle`, and `select` patterns safely.
  - `KeyboardController` & `MouseController`: Smooth cursor positioning, click types (single, double, right), drags, wheel scrolling, and simulated keystrokes.
  - `CoordinateFallbackInteractor`: Fallback for non-standard UI controls with bounding box checks and mandatory pre-action screen verification callbacks.
  - `UIVerificationEngine`: Observe-Act-Verify loop verifying window appearances, window terminations, element presence, element vanishing, and element text matching.
- **Screen Capture & Computer Perception (`zoro.computer.vision`)**:
  - `ScreenCaptureManager`: Multi-monitor desktop capture via `mss`, active window cropping via `GetWindowRect`, and headless Session 0 fallback canvas generation. Automated 15-minute retention cleanup (`cleanup_old_screenshots`).
  - `WindowsOCR`: 100% offline, zero-dependency native Windows OCR using WinRT `Windows.Media.Ocr.OcrEngine` invoked via PowerShell .NET runtime (`WindowsRuntimeSystemExtensions.AsTask`). Extracts full text and bounding boxes for every detected word.
  - `VisionModelInterface`: Multi-modal screen interpretation using local Ollama vision models (e.g. `llava`, `minicpm-v`) with graceful offline OCR fallback.
- **Secure Filesystem Agent (`zoro.computer.filesystem`)**:
  - `PathSecurityValidator`: Strictly enforces canonical path resolution (`resolve()`), permitted workspace boundaries, directory traversal rejection (`..`, `...`), reparse-point / junction / symlink escape prevention, and hard blocks on sensitive security files (`audit.key`, `emergency.lock`, `zoro.pid`, `audit.checkpoint`) and Windows system directories (`System32`, `SysWOW64`, `Windows`).
  - `SecureFilesystemAgent`: File listing, reading with 50 MB limits, atomic writing, copying, moving, and safe deletion to the Windows Recycle Bin via Win32 `SHFileOperationW` (`FO_DELETE` with `FOF_ALLOWUNDO`).
- **Controlled Shell Execution (`zoro.computer.shell`)**:
  - `CommandRiskPolicy`: Tiers shell commands into `TIER_1_SAFE`, `TIER_2_MODERATE`, `TIER_3_ELEVATED`, and `TIER_4_BLOCKED`. Maintains executable allowlist and structural token parser (`shlex.split(posix=False)`). Rejects dangerous chaining characters (`&`, `|`, `;`, `>`, `<`, backticks).
  - `CommandRunner`: Executes commands in child processes assigned to the containment Job Object. Restricts working directories to permitted workspace paths, enforces execution timeouts, and truncates output captures to 1 MB.
  - `ProcessMonitor`: Lists running processes with CPU and RAM tracking, hung GUI window detection, and safe process termination protecting supervisor PIDs.
- **Application Discovery & Control (`zoro.computer.apps`)**:
  - `ApplicationRegistry`: Discovers installed software across 32-bit and 64-bit Windows Registry Uninstall keys (`HKLM` and `HKCU`) and Start Menu directories, supplemented by built-in Windows accessories (`notepad`, `calc`, `mspaint`, `cmd`, `powershell`, `explorer`).
  - `ApplicationLauncher`: Spawns processes assigned to Windows Job Object containment and awaits main window presentation (`WaitForInputIdle` and polling).
  - `ApplicationController`: Manages window focus, minimize, maximize, restore, and safe termination.
- **Execution Sandbox & Resource Governance (`zoro.computer.sandbox`)**:
  - `ExecutionPolicyEngine`: 4 execution profiles (Profile A: Read-Only, Profile B: Standard, Profile C: Restricted Modification, Profile D: High-Risk).
  - `ResourceGovernor`: Sliding-window screenshot rate limiting, task concurrency slots, CPU/RAM threshold guarding.
  - `SandboxManager`: Comprehensive session management logging all computer sessions, actions, shell executions, and screenshot metadata to SQLite (`computer_sessions`, `computer_actions`, `shell_executions`, `screenshot_metadata`).
- **Central Tool Registry Integration (`zoro.tools.builtin.computer_tools`)**:
  - Registers 9 builtin computer tools: `WindowListTool`, `WindowFocusTool`, `ScreenCaptureTool`, `ScreenOCRTool`, `ElementInspectTool`, `ElementActionTool`, `ShellExecuteTool`, `AppLaunchTool`, `AppCloseTool`.
- **ZoroEngine IPC JSON-RPC Extensions**:
  - Registered 19 `computer.*` Named Pipe methods covering profiles, resource governance, window controls, UI inspections and actions, mouse/keyboard input, screen captures, offline OCR, secure file operations, shell execution, and app controls.
- **Desktop HUD Integration (`zoro.ui`)**:
  - Added dedicated Computer Control & Sandbox Panel with execution profile selector, screenshot capture, offline OCR trigger, and live window listing.
- **Database Schema Migration 004 (`004_computer_control.sql`)**:
  - Added 5 tables: `computer_sessions`, `computer_actions`, `shell_executions`, `app_registry`, `screenshot_metadata`.
- **Verification & Test Suite**:
  - Expanded test suite to **211 automated tests** across **33 modules** (86 Milestone 01 tests + 39 Milestone 02 tests + 86 Milestone 03 tests), passing with **100% pass rate** in **28.33s** with **86% overall line coverage** across `zoro.*`.

---

## [0.2.0] - 2026-11-16 (Milestone 02: The Intelligence Core)

### Added
- **AI Model Provider Abstraction Layer (`zoro.models`)**:
  - `BaseModelProvider` interface specifying async completion (`chat_completion`), async chunk streaming (`chat_completion_stream`), health checks (`health_check`), capability inspection (`get_capabilities`), and model listing (`list_models`).
  - Standardized Pydantic schemas: `ChatMessage`, `ChatCompletionRequest`, `ChatCompletionResponse`, `ChatCompletionChunk`, `ModelCapabilities`, `ModelInfo`, `ProviderHealth`.
  - Normalized error hierarchy in `zoro.models.exceptions`: `ModelProviderError`, `ProviderUnavailableError`, `ProviderTimeoutError`, `ModelNotFoundError`, `CapabilityNotSupportedError`, `StructuredOutputError`, `ContextLengthExceededError`, `AuthenticationError`, `RateLimitError`.
  - `OllamaProvider`: Native REST adapter for Ollama (`/api/chat`, `/api/tags`, `/api/show`, NDJSON line streaming).
  - `LlamaCppProvider`: OpenAI-compatible HTTP adapter for `llama-server.exe` (`/v1/chat/completions`, Server-Sent Events chunk streaming, `/v1/models`).
  - `MockModelProvider`: Deterministic responses, queueing, latency and error simulation for offline development and test automation.
  - `ProviderRegistry`: Registry coordinating multiple runtimes, active provider/model selection, concurrent health probing with timeouts, and automatic fallback cascading with parameter adjustment.
- **Hardware-Aware Model Benchmark Runner (`zoro.benchmarks`)**:
  - `HardwareAwareBenchmarkRunner` measuring Time-to-First-Token (TTFT), sustained token throughput (tokens/sec), host RAM and GPU VRAM footprint via NVML C-bindings.
  - Multi-dimensional capability evaluation: Structured JSON schema compliance, multi-constraint instruction following, and tool-calling protocol compatibility.
  - Emits Pascal architecture (GTX 1050 Ti 4GB) saturation warnings when VRAM load approaches capacity.
  - Results persisted to SQLite `model_benchmarks` table with full raw metrics JSON.
- **Multi-Step Task Planner (`zoro.planner`)**:
  - `TaskPlan` and `PlanStep` Pydantic models for structured plan decomposition, dependency mapping, and parameter binding.
  - `DependencyGraph`: Directed Acyclic Graph (DAG) dependency validation and topological sort using Kahn's algorithm; cycle detection raises `CircularDependencyError`.
  - `PlanValidator`: Structural and security validator enforcing step count bounds ($\le 20$), tool existence checks, argument schema checks, and automatic permission tier assignment.
  - `PlanExecutor`: Asynchronous execution engine resolving dynamic outputs across steps (`{{step_id.key}}`), managing retries for transient tool failures, pausing on approval requirements, and persisting plan/step states to SQLite (`task_plans`, `task_steps`).
- **Secure Tool Registry & Permission System (`zoro.tools`)**:
  - `ToolRegistry`: Enforces application-level capability gates independent of LLM prompts.
  - 5 capability permission tiers: `READ_ONLY`, `LOW_RISK`, `SENSITIVE`, `DESTRUCTIVE`, `SYSTEM_CRITICAL`.
  - `ApprovalToken`: Single-use cryptographically generated token (`secrets.token_hex`), bound to specific tool and step IDs, unexpired, and transitioned immediately to `CONSUMED` upon first use (replay attack protection).
  - Built-in secure tools in `zoro.tools.builtin.file_tools`: `FileDiscoveryTool`, `FileReadMetadataTool`, `ReportGeneratorTool`, `FileMoveTool`, `FileDeleteTool`.
  - Hard lock protection against reading, overwriting, moving, or deleting security files (`audit.key`, `audit.checkpoint`, `emergency.lock`, `zoro.pid`, Windows system directories).
- **Central AI Orchestrator (`zoro.orchestrator`)**:
  - `ZoroOrchestrator`: Coordinates user interactions, intent understanding, provider selection, planning vs. direct chat routing, and tool dispatch.
  - 9-state FSM: `IDLE`, `UNDERSTANDING`, `PLANNING`, `WAITING_FOR_APPROVAL`, `EXECUTING`, `WAITING_FOR_RESULT`, `COMPLETED`, `FAILED`, `CANCELLED`.
  - Emergency halt verification before executing any request; active halt lock aborts execution immediately.
  - Human approval pause & resume workflow: Sensitive or destructive operations pause execution in `WAITING_FOR_APPROVAL` state, returning an approval token. Resumes execution upon user authorization via `resolve_approval()`.
- **Database Schema Migration 003 (`003_intelligence_core.sql`)**:
  - Added 8 tables: `ai_providers`, `ai_models`, `model_benchmarks`, `conversations`, `messages`, `task_plans`, `task_steps`, `tool_executions`.
- **Desktop HUD Shell Integration (`zoro.ui`)**:
  - Added AI runtime controls to PySide6 HUD: Provider dropdown, model dropdown, real-time AI state badge, directive prompt input with dispatch button, cancel button, and benchmark execution button.
  - Added real-time action authorization dialog with Approve and Reject buttons for paused plan steps.
  - Named Pipe IPC integration with notification handlers for real-time state changes (`ai.state_changed`), approval requests (`ai.approval_requested`), and step updates (`ai.step_update`).
- **Verification & Test Suite**:
  - Test suite expanded to **125 automated tests** across **21 modules** (86 Milestone 01 tests + 39 Milestone 02 tests), passing with **100% pass rate** in **24.65s** with **86% line coverage** across `zoro.*`.
  - Verified end-to-end intelligence pipeline over Named Pipe IPC (`test_e2e_intelligence.py`).

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
