# PROJECT ZORO — Development Roadmap

This document outlines the phased engineering milestones for PROJECT ZORO. Progress is updated as milestones are verified.

---

## Milestone 0: Research, Hardware Benchmarks & Systems Architecture
- [x] Host hardware inspection (i5-8300H, 16GB RAM, GTX 1050 Ti 4GB, Windows 11).
- [x] VRAM accounting & Pascal Compute Capability 6.1 constraints evaluation.
- [x] OS security threat modeling (Windows Job Objects, DACLs, Mandatory Integrity Levels).
- [x] Named Pipe IPC protocol specification (Framed JSON-RPC 2.0).
- [x] SQLite concurrency architecture (Single-Writer Actor + WAL mode).
- [x] Empirical local AI model benchmark harness design.
- **Status**: **COMPLETED**

---

## Milestone 1: Core Foundation & Desktop Shell
- [x] Virtual environment initialization with verified dependencies.
- [x] Complete documentation suite (`README.md`, `ARCHITECTURE.md`, `SECURITY.md`, `CONFIGURATION.md`, `TESTING.md`, `DEVELOPMENT_LOG.md`).
- [x] Pydantic v2 configuration management (`zoro.config.settings`).
- [x] SQLite WAL storage with serialized write actor and migrations (`zoro.storage`).
- [x] Cryptographically chained HMAC-SHA256 audit logging (`zoro.security.audit`).
- [x] External HMAC-signed audit checkpoint (`audit.checkpoint`) with tail-deletion and truncation detection.
- [x] Windows DPAPI fail-closed key management with documented same-user threat boundaries.
- [x] Windows Job Object process tree isolation (`zoro.security.job_object`) with kernel `KILL_ON_JOB_CLOSE` and zero breakaway.
- [x] Handle non-inheritance verification (`HANDLE_FLAG_INHERIT == 0`).
- [x] 7 live Windows NT failure and emergency shutdown scenarios automated and verified.
- [x] OS-enforced Emergency Halt controller and DACL protection (`zoro.security.emergency`).
- [x] Direct NVML GPU/VRAM telemetry sampler (`zoro.core.nvml_telemetry`).
- [x] Dynamic hardware resource governor (`zoro.core.governor`).
- [x] Windows Named Pipe IPC server and client with Overlapped I/O (`zoro.ipc`).
- [x] Central Engine lifecycle FSM & event bus (`zoro.core`).
- [x] PySide6 Desktop HUD & System Tray Shell (`zoro.ui`).
- [x] Automated pytest suite: **86/86 tests passing** across **16 modules** with **86% line coverage**.
- [x] Unnamed Job Object architecture eliminating namespace discovery.
- [x] Explicit Job Object handle duplication (`PROCESS_DUP_HANDLE`) boundary empirically verified and documented.
- [x] Emergency controller handle-bound termination with raw 64-bit `FILETIME` validation eliminating TOCTOU races and `taskkill`.
- [x] Audit checkpoint crash consistency verified with fail-closed non-regeneration.
- [x] Empirical memory benchmarking: Core Engine RSS 36.5 MB, Full Stack RSS 70.9 MB.
- **Status**: **FINAL ACCEPTANCE COMPLETED**

---

## Milestone 2: Local AI Model Engine & Central Orchestration
- [x] Hardware-aware local model benchmark runner (`zoro.benchmarks`) measuring TTFT, tokens/sec, host RAM, GPU VRAM, structured JSON compliance, instruction following, and tool-calling compatibility.
- [x] Model Abstraction Layer (`zoro.models`) with normalized errors (`ModelProviderError`, `ProviderUnavailableError`, `ProviderTimeoutError`, `ModelNotFoundError`, etc.).
- [x] Adapters for Ollama (REST / streaming), `llama.cpp` (OpenAI-compatible / SSE), and Mock (deterministic testing).
- [x] Provider Registry (`zoro.models.registry`) managing dynamic provider switching and automatic fallback cascading.
- [x] Central AI Orchestrator (`zoro.orchestrator`) with 9-state FSM (`IDLE` to `COMPLETED`), direct chat vs. task planning classification, and emergency halt enforcement.
- [x] Multi-Step Task Planner (`zoro.planner`) with DAG dependency resolution (Kahn's topological sort), cycle detection (`CircularDependencyError`), structural plan validator, step retries, and output interpolation (`{{step_id.key}}`).
- [x] Secure Tool Registry (`zoro.tools`) with Pydantic argument/output validation, 5 capability tiers (`READ_ONLY`, `LOW_RISK`, `SENSITIVE`, `DESTRUCTIVE`, `SYSTEM_CRITICAL`), single-use approval tokens with replay protection, and audit logging.
- [x] Built-in secure tools (`FileDiscoveryTool`, `FileReadMetadataTool`, `ReportGeneratorTool`, `FileMoveTool`, `FileDeleteTool`) with hard locks on security paths.
- [x] SQLite schema migration `003_intelligence_core.sql` adding 8 tables (`ai_providers`, `ai_models`, `model_benchmarks`, `conversations`, `messages`, `task_plans`, `task_steps`, `tool_executions`).
- [x] Desktop HUD (`zoro.ui`) integration with model/provider selector, AI state badge, directive prompt input, real-time approval prompt dialog, and benchmark runner.
- [x] Automated pytest suite: **125/125 tests passing** (86 Milestone 01 tests + 39 Milestone 02 tests) across **21 modules** with **86% line coverage**.
- **Status**: **FINAL ACCEPTANCE COMPLETED**

---

## Milestone 3: Windows Computer Control
- [x] Windows UI Automation and accessibility tree inspection via `pywinauto` and Win32.
- [x] Keyboard and mouse interaction controllers with coordinate-based fallback and pre-action verification.
- [x] Observe-Act-Verify feedback loop verifying post-action window and element state changes.
- [x] Desktop perception via multi-monitor screen capture (`mss`), active window cropping, and 15-minute retention cleanup.
- [x] 100% offline native Windows WinRT OCR using `Windows.Media.Ocr.OcrEngine` (word bounding boxes, zero external binaries).
- [x] Multi-modal local vision model interface (Ollama `llava`/`minicpm-v` with OCR fallback).
- [x] Secure Filesystem Agent with canonical path validation, traversal prevention (`..`), reparse-point / symlink protection, 50MB read limits, and safe deletion to Windows Recycle Bin (`SHFileOperationW`).
- [x] Controlled Shell Execution with 4 risk tiers (`TIER_1_SAFE` to `TIER_4_BLOCKED`), executable allowlist, structured argument parsing without `shell=True`, and child process containment in Windows Job Object.
- [x] Process Monitor tracking CPU/RAM, detecting hung windows (`IsHungAppWindow`), and safe process termination protecting supervisor PIDs.
- [x] Application Discovery across 32-bit and 64-bit Registry and Start Menu, launching with Job Object assignment and main window awaiting.
- [x] Window Manager controlling focus, minimize, maximize, restore, close, and resizing.
- [x] 4 Execution Profiles (Profile A: Read-Only, Profile B: Standard, Profile C: Restricted Modification, Profile D: High-Risk).
- [x] Resource Governor with sliding-window screenshot rate limiting, concurrency task slots, and system health thresholds.
- [x] Central Tool Registry integration (9 builtin computer tools) and 19 IPC Named Pipe JSON-RPC methods (`computer.*`).
- [x] SQLite schema migration `004_computer_control.sql` (5 tables: `computer_sessions`, `computer_actions`, `shell_executions`, `app_registry`, `screenshot_metadata`).
- [x] PySide6 Desktop HUD Computer Control & Sandbox Panel.
- [x] Automated pytest suite: **211/211 tests passing** across **33 modules** with **86% line coverage**.
- **Status**: **FINAL ACCEPTANCE COMPLETED**

---

## Milestone 4: High-Speed Local Voice Interaction
- [x] Audio Capture & Playback Subsystem (`zoro.voice.audio`): PortAudio/`sounddevice` input/output discovery, 16kHz mono capture stream, circular bounded ring buffer with overflow eviction, immediate playback cancellation (<10ms).
- [x] Voice Activity Detection (`zoro.voice.vad`): WebRTC VAD with hybrid RMS energy-floor gating (>1100x real-time speed, speech onset and termination tracking).
- [x] Local Wake-Word Detection (`zoro.voice.wake`): Offline dual-phrase detection ("Zoro" primary, "Hey Zoro" alternative, both enabled by default, independently configurable), Push-to-Talk fallback, self-voice suppression during TTS playback.
- [x] Speech-to-Text Subsystem (`zoro.voice.stt`): `FasterWhisperProvider` pinned to CPU `int8` (reserving 100% of 4GB GTX 1050 Ti VRAM for primary LLM), `WhisperCppProvider`, `MockSTTProvider`, and cascading `STTRegistry`.
- [x] Text-to-Speech Subsystem (`zoro.voice.tts`): Native Windows 11 SAPI5 in-memory synthesis (~100ms first-chunk, zero disk I/O, zero VRAM), `PiperTTSProvider`, `MockTTSProvider`, and cascading `TTSRegistry`.
- [x] Conversational Voice Engine (`zoro.voice.conversation`): `VoiceTurnManager` (multi-turn context, sentence-chunked streaming), `VoiceSessionManager` (privacy-compliant DB logging without raw audio, `clear_history`), `InterruptionManager` (barge-in keywords "stop"/"cancel" and high-energy speech onset).
- [x] Streaming Voice Pipeline (`zoro.voice.pipeline`): Asynchronous pipeline coordinating mic -> VAD -> wake -> STT -> orchestrator -> sentence-chunked TTS -> speaker.
- [x] Telemetry & Health Monitoring (`zoro.voice.monitoring`): `VoiceMetricsCollector` (running average STT, TTFT, TTS turnaround times) and `VoiceHealthMonitor`.
- [x] ZoroEngine Named Pipe Integration: 17 `voice.*` JSON-RPC methods and bidirectional EventBus notification broadcasting.
- [x] PySide6 Desktop HUD Voice Panel: Voice state pill, Enable/Disable toggle, Push-to-Talk, Stop Speaking, Wake-word listening toggle, and independent phrase checkboxes.
- [x] SQLite schema migration `005_voice_interaction.sql` (4 tables: `voice_sessions`, `voice_utterances`, `voice_metrics`, `voice_settings`).
- [x] Security & Adversarial Invariants: Emergency halt immediately terminates capture/playback, wake-words cannot authorize computer operations, raw audio bytes are never stored in database or audit logs.
- [x] Automated pytest suite: **266/266 tests passing** across **43 modules** with **86% overall line coverage** across `zoro.*`.
- **Status**: **FINAL ACCEPTANCE COMPLETED**

---

## Milestone 5: Persistent Personal Memory
- [x] Pre-implementation fix: Global Windows emergency hotkey (`Ctrl + Alt + Shift + K`) via dedicated Win32 message pump thread + in-focus Qt accelerator, working globally across all applications with registration failure detection.
- [x] Multi-tiered memory architecture across 5 distinct categories: Identity, Preference, Episodic, Project, and Schedule (`zoro.memory.models`).
- [x] SQLite schema migration `006_persistent_memory.sql` adding `memories` table and synchronized `memories_fts` FTS5 virtual table.
- [x] Local dense vector embedding engine (`zoro.memory.embeddings`) using local Ollama `all-minilm` (384-dimensional dense vectors, 45 MB footprint, ~340 ms warm latency, 0 VRAM contention) with offline fallback projector.
- [x] Hybrid Search combining dense vector cosine similarity (0.70 weight) and FTS5 BM25 keyword matching (0.30 weight).
- [x] Memory extraction engine (`zoro.memory.extractor`) parsing facts, explicit commands ("Remember", "Update preference", "Forget"), and schedule items.
- [x] Security credential exclusion and prompt-injection neutralization: passwords, API keys, and tokens are strictly blocked from memory persistence.
- [x] Preference deduplication and contradiction resolution: existing preferences are updated in place rather than accumulating contradictory duplicates.
- [x] Context-aware prompt grounding (`zoro.memory.context_builder`) injecting budgeted `<PERSISTENT_MEMORY>` blocks into the central Orchestrator.
- [x] ZoroEngine Named Pipe IPC integration with 7 `memory.*` JSON-RPC methods (`get_all`, `search`, `create`, `update`, `delete`, `delete_category`, `clear_all`).
- [x] Interactive PySide6 Desktop HUD Memory Management Panel (`zoro.ui.memory_panel` and `ZoroMemoryDialog`) with category filters, real-time search, editing dialogs, and security confirmation guard for bulk deletion.
- [x] Automated pytest suite: **302/302 tests passing** (281 legacy tests + 21 Milestone 05 tests) across **48 test modules**.
- [x] End-to-end integration verified on genuine local Ollama `qwen2.5:3b` model with persistence across simulated process restarts.
- **Status**: **FINAL ACCEPTANCE COMPLETED**

---

## Milestone 6: Proactive Intelligence & Timetable Awareness
- [x] Crash-safe persistent event and reminder management with decoupled lifecycles (`007_proactive_schedule.sql`).
- [x] Atomic reminder claiming via SQLite `BEGIN IMMEDIATE` transactions with `rowcount == 1` validation and stale claim recovery (60s cutoff).
- [x] Monotonic loop scheduling (`time.monotonic()`) and wall-clock jump detection with catch-up sweeps after system sleep/hibernation or manual time shifts.
- [x] Strict temporal validation, zero-hallucination ambiguity detection (prompting user for clarification), and non-drifting monthly recurrence clamping (`target_day_of_month` preservation).
- [x] Timetable and deadline intelligence with dynamic urgency scoring ($W_{priority} \times \frac{1}{\text{hours\_remaining}}$), overdue task tracking, and conflict detection.
- [x] Multi-tiered notification hierarchy: Native Windows 11 Toast / System Tray -> Desktop HUD Console -> Voice TTS announcement.
- [x] Split-interval quiet hours configuration supporting midnight boundaries (e.g. 23:00 to 07:00) with priority bypass for HIGH/URGENT alerts.
- [x] Deep work focus sessions with notification holding, countdown tracking, and completion alerts.
- [x] Deterministic operational daily briefing synthesizing today's agenda, deadlines in the next 72 hours, overdue items, and top 3 priorities without LLM hallucination.
- [x] Central Orchestrator integration with natural language scheduling commands, proactive prompt context injection, and automatic bridging to `memories` table under `MemoryCategory.SCHEDULE`.
- [x] PySide6 Desktop HUD Timetable Interface (`ZoroTimetableDialog`) with 5 tabs (Agenda, Events, Focus Mode, Settings, Alert History) and System Tray integration.
- [x] Automated pytest suite: **324/324 tests passing** (303 legacy tests + 21 Milestone 06 tests) across **51 test modules**.
- **Status**: **FINAL ACCEPTANCE COMPLETED**

---

## Milestone 7: Autonomous Multi-Agent Swarms
- [ ] Specialized agent roles (Researcher, Coder, System Monitor, Personal Assistant).
- [ ] Inter-agent communication protocol.
- [ ] Dynamic subagent invocation and task sharding.
- [ ] Self-verification and automated failure recovery.
- **Status**: PENDING

---

## Milestone 8: Secure Mobile Companion
- [ ] End-to-end encrypted remote bridge (zero public port forwarding).
- [ ] Mobile companion interface (PWA or Flutter).
- [ ] Remote task updates, notifications, and voice access.
- [ ] Hardware-gated remote permission verification.
- **Status**: PENDING
