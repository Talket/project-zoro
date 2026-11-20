# PROJECT ZORO

> **A Persistent, Highly Autonomous, Personal Artificial Intelligence for Windows 11**

PROJECT ZORO is a sophisticated, continuously running personal artificial intelligence inspired by the capabilities, intelligence, personality, and human-AI partnership demonstrated by JARVIS. Operating under strict **zero-cost** and **local-first** constraints, ZORO transforms an everyday Windows machine into a proactive, intelligent environment.

---

## Core Principles

1. **Zero-Cost Development**: No paid APIs, no subscriptions, no paid cloud infrastructure. Operates completely on free, open-source, and locally hosted technologies.
2. **Local-First Architecture**: Core reasoning, long-term memory, planning, and task execution run locally on the host machine. Complete privacy, zero external cloud dependency for essential functions.
3. **Hardware Aware**: Specifically tuned for the host hardware:
   - Intel Core i5-8300H (4C/8T AVX2)
   - 16 GB DDR4 System RAM
   - NVIDIA GeForce GTX 1050 Ti (4 GB GDDR5, Compute Capability 6.1)
   - Dynamic VRAM/RAM resource governor to guarantee laptop responsiveness.
4. **OS-Level Security**:
   - Independent Emergency Shutdown via kernel-level **Windows Job Objects**.
   - OS-enforced DACL boundary preventing agent self-modification or bypass of the halt state.
   - Cryptographically chained HMAC-SHA256 audit logs.
5. **Decoupled Architecture**:
   - Headless Core Runtime Engine managing lifecycle, storage, and models.
   - PySide6 Desktop Shell (HUD & System Tray) communicating via framed JSON-RPC 2.0 over Windows Named Pipes.
   - Serialized Single-Writer SQLite WAL storage for rock-solid concurrency.

---

## System Requirements

- **Operating System**: Windows 11 (64-bit) / Windows 10
- **Python**: 3.12+ (64-bit)
- **GPU**: NVIDIA GPU with CUDA support (4 GB VRAM minimum) or CPU with AVX2
- **Memory**: 16 GB RAM recommended

---

## Quick Start

### 1. Environment Setup
```powershell
# Clone / navigate to workspace
cd D:\downloads\PROJECTS\ZORO

# Initialize and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install foundation dependencies
pip install -r requirements.txt
```

### 2. Launching ZORO
```powershell
# Normal Desktop Mode (Spawns Core Runtime + Desktop UI Shell)
python -m zoro

# Headless Background Engine Only
python -m zoro --headless

# Desktop UI Shell Only (connects to running engine)
python -m zoro --ui
```

### 3. Emergency Controls
- **Global Keyboard Shortcut**: `Ctrl + Alt + Shift + K` (instant kernel-level termination across all Windows applications).
- **HUD Emergency Button**: Large red kill button in the desktop HUD header.
- **Batch / Script Kill Switch**: Double-click `scripts\emergency_kill.bat` or run:
  ```powershell
  python scripts/emergency_kill.py --kill
  ```
  *This issues an atomic kernel-level termination of the entire ZORO process tree via Windows Job Objects and creates an OS-protected halt lockfile.*
- **Status Inspection**:
  ```powershell
  python scripts/emergency_kill.py --status
  ```
- **Authorized Resumption**:
  ```powershell
  # Right-click scripts\resume_zoro.bat -> Run as Administrator, or:
  python scripts/emergency_kill.py --resume
  ```

---

## Project Structure

```
d:\downloads\PROJECTS\ZORO\
├── zoro/
│   ├── core/         # Orchestrator, lifecycle, event bus, NVML telemetry, governor
│   ├── config/       # Pydantic v2 settings & OS path resolution
│   ├── ipc/          # Windows Named Pipe protocol, server, and client
│   ├── storage/      # SQLite WAL manager, models, migration runner, SQL scripts
│   ├── security/     # Windows Job Object, permissions, DACL halt gate, audit logging, emergency hotkey
│   ├── models/       # Local AI model abstraction layer (Ollama / llama-server)
│   ├── computer/     # Windows computer control (UI automation, keyboard/mouse, OCR, screen capture)
│   ├── voice/        # High-speed local voice subsystem (VAD, wake word, STT, TTS)
│   ├── memory/       # Persistent personal memory, semantic vector indexing, hybrid search
│   ├── schedule/     # Proactive intelligence, timetable awareness, deadline tracking, notifications
│   └── ui/           # PySide6 desktop HUD, system tray, dark theme, memory & timetable panels
├── scripts/          # Supervisor, emergency kill switch, benchmarks, and launch scripts
├── benchmarks/       # Empirical model & hardware benchmarking harness
├── tests/            # Pytest automated test suite (326+ passing tests)
└── docs/             # Technical architecture and design specifications
```

---

## Roadmap Overview

- **Milestone 0**: Research, Hardware Benchmarks & Systems Architecture *(Completed)*
- **Milestone 1**: Core Foundation, IPC, OS Boundaries & Desktop Shell *(Completed)*
- **Milestone 2**: Local AI Model Engine & Central Orchestration *(Completed)*
- **Milestone 3**: Windows Computer Control (UI Automation, Shell, Filesystem) *(Completed)*
- **Milestone 4**: High-Speed Local Voice Interaction (openWakeWord, Whisper, Piper) *(Completed)*
- **Milestone 5**: Persistent Personal Memory Architecture & Semantic Vector Indexing *(Completed)*
- **Milestone 6**: Proactive Intelligence & Timetable Awareness *(Completed)*
- **Milestone 7**: Autonomous Multi-Agent Swarms & Self-Verification *(Next)*
- **Milestone 8**: Secure Mobile Companion Integration

For detailed documentation, refer to [ARCHITECTURE.md](ARCHITECTURE.md), [SECURITY.md](SECURITY.md), and [ROADMAP.md](ROADMAP.md).
