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
- [x] Automated pytest suite: **80/80 tests passing** across **16 modules** with **86% line coverage**.
- [x] Unnamed Job Object architecture eliminating namespace discovery.
- [x] Explicit Job Object handle duplication (`PROCESS_DUP_HANDLE`) boundary empirically verified and documented.
- [x] Emergency controller anti-PID-reuse validation using process creation timestamp matching.
- [x] Audit checkpoint crash consistency verified with fail-closed non-regeneration.
- [x] Empirical memory benchmarking: Core Engine RSS 36.5 MB, Full Stack RSS 70.9 MB.
- **Status**: **FINAL ACCEPTANCE COMPLETED**

---

## Milestone 2: Local AI Model Engine & Central Orchestration
- [ ] Automated benchmark harness execution across local model candidates (`Qwen 2.5 3B`, `Llama 3.2 3B`, `Phi-3.5-mini`, etc.).
- [ ] Native `llama-server.exe` / Ollama integration with exact layer offloading.
- [ ] Model Abstraction Layer (`BaseModelProvider`) with health checks and fallbacks.
- [ ] Central Orchestrator & Multi-Step Task Planner.
- [ ] Standardized Tool Registry with parameter validation.
- [ ] Outcome verification engine (verifying state changes before reporting success).
- **Status**: PENDING

---

## Milestone 3: Windows Computer Control
- [ ] Windows UI Automation and accessibility inspection.
- [ ] Keyboard and mouse interaction engine (`SendInput`).
- [ ] Filesystem agent (create, edit, search, organize, backup).
- [ ] Terminal and PowerShell execution engine with sandboxing.
- [ ] Playwright browser automation (navigate, extract, fill forms).
- [ ] Application window manager (focus, minimize, switch).
- **Status**: PENDING

---

## Milestone 4: High-Speed Local Voice Interaction
- [ ] CPU-optimized `openWakeWord` detector (<1% CPU, zero VRAM).
- [ ] Sub-300ms `faster-whisper` speech recognition pinned to CPU AVX2.
- [ ] Natural local `piper-tts` speech synthesis.
- [ ] Voice Activity Detection (Silero VAD) & conversational interruption.
- [ ] Audio privacy controls and visual listening indicator.
- **Status**: PENDING

---

## Milestone 5: Persistent Personal Memory
- [ ] Multi-tiered memory architecture (Identity, Preferences, Episodic, Projects, Schedules).
- [ ] Embedded vector index (`sqlite-vec` or local embeddings) for semantic search.
- [ ] Context-aware memory retrieval (dynamic prompt injection).
- [ ] Memory inspection, correction, and deletion controls.
- **Status**: PENDING

---

## Milestone 6: Proactive Intelligence & Timetable Awareness
- [ ] Event-driven scheduler and calendar/timetable manager.
- [ ] Activity pattern detection and deadline tracking.
- [ ] Non-intrusive contextual notifications and gentle nudges.
- [ ] Focus mode, quiet hours, and interruption throttling.
- **Status**: PENDING

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
