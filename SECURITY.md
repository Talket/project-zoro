# PROJECT ZORO — Security Specification & Threat Model

## 1. Security Architecture & Threat Model

ZORO is designed with bounded autonomy and defense-in-depth principles. The assistant must never possess the capability to compromise the host system, escalate privileges, or evade user control.

---

## 2. Emergency Shutdown Architecture

### 2.1 The Host Security Boundary
- **Process Isolation via Windows Job Object**:
  When ZORO starts via `scripts/supervisor.py`, it instantiates a Win32 Job Object (`ZoroJobObject`) with the flags:
  - `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = TRUE`
  - `JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = FALSE`
  Every subprocess (tools, shell commands, agent workers) spawned by ZORO is forcibly contained within this Job Object. When the Emergency Controller calls `TerminateJobObject(hJob, 137)`, the Windows NT kernel immediately terminates all processes in the tree.
- **Protected Emergency Halt State**:
  The halt state is recorded in `%PROGRAMDATA%\Zoro\Security\halt.lock`. During setup, Windows Access Control Lists (DACLs) are applied via `icacls`:
  - `Administrators` and `SYSTEM`: Full Control (`F`).
  - Standard User (`%USERNAME%`): Read & Execute (`RX`), with explicit `DENY (DE,WD,AD)` on Delete, Write Data, and Append Data.
  Even if ZORO runs rogue Python scripts under the owner's account, the Windows Security Reference Monitor (SRM) enforces the `DENY` ACE, returning `ERROR_ACCESS_DENIED`.

### 2.2 Resumption Authorization
ZORO's boot sequence checks for `halt.lock` before initializing any subsystem. If `halt.lock` exists, execution aborts with exit code 1. Resumption is permitted **only** by running `scripts/resume_zoro.bat` with elevated Administrator privileges (UAC prompt).

---

## 3. Threat Mitigation Matrix

| Threat Vector | Capability of Compromised Agent | Defense Mechanism |
| :--- | :--- | :--- |
| **Agent Infinite Execution Loop** | Continuously dispatches tool calls and consumes CPU/RAM. | Event bus rate limiter + hardware watchdog + Job Object termination. |
| **Agent Modifying Emergency Tools** | Attempts to delete `emergency_kill.py` or modify `.bat` scripts. | OS DACL denies delete/write; security permissions gate hard-blocks access. |
| **Tampering with Audit Logs** | Modifies historical SQLite records to conceal actions. | Cryptographic HMAC-SHA256 hash chaining; breaks the chain on alteration. |
| **Process Tree Breakaway** | Spawns detached subprocess (`CREATE_NEW_PROCESS_GROUP`). | `JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0` traps all descendant processes. |
| **Spurious Boot Restart** | Automatically launches after reboot while in halted state. | Pre-flight halt lock check executes before any subsystem initialization. |
| **Unauthorized Privilege Escalation** | Attempts to execute commands as Administrator. | ZORO runs strictly at **Medium Mandatory Level**; refuses elevation prompts. |

---

## 4. Capability-Based Permission Gate

Actions are categorized into 5 privilege tiers:

1. **`READ_ONLY`**: Reading files, querying system telemetry, inspecting logs. Allowed automatically.
2. **`REVERSIBLE_CHANGE`**: Creating scratch files, updating application config, staging edits. Allowed with audit log.
3. **`IRREVERSIBLE_CHANGE`**: Deleting files, modifying existing source code, killing external processes. Requires explicit user confirmation.
4. **`SYSTEM_SETTING`**: Modifying Windows registry, changing environment variables, altering network adapters. Requires explicit confirmation and elevation warning.
5. **`EXTERNAL_COMMUNICATION`**: Sending network packets to non-local IP addresses, sending emails, external API queries. Requires user confirmation.

### Protected Paths (Hard-Locked)
The following paths are permanently blocked from agent modification, deletion, or renaming:
- `scripts/emergency_kill.*`
- `scripts/resume_zoro.*`
- `scripts/supervisor.*`
- `%PROGRAMDATA%\Zoro\Security\*`
- `.venv\*`
- Operating System system directories (`C:\Windows\*`, `System32`)
