# PROJECT ZORO — Security Specification & Threat Model

## 1. Security Philosophy & Threat Model Principles

PROJECT ZORO operates on principles of bounded autonomy, fail-closed defenses, and defense-in-depth. 
No component of the artificial intelligence makes unfounded claims of being "tamper-proof." Instead, the architecture establishes well-defined security boundaries, cryptographic tamper-evidence, and kernel-enforced process containment.

### The Three Threat Levels

| Threat Level | Adversary / Failure Mode | Defense Mechanism & Architectural Guarantee |
| :--- | :--- | :--- |
| **Level 1: Accidental Breakaway & Runaway Workloads** | Unhandled exceptions, infinite tool loops, hung worker threads, or subprocesses spawned with `CREATE_NEW_PROCESS_GROUP`. | **Fully Mitigated**: Windows Job Object process containment traps all descendant processes. Kernel-level `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and zero-breakaway enforcement guarantee atomic termination of the entire process tree on supervisor exit or emergency trigger. |
| **Level 2: Malicious Child at Same User Privilege** | Compromised code running within ZORO's interactive desktop session attempting to conceal its actions, tamper with logs, or persist beyond a kill signal. | **Tamper-Evident & Contained**: Job Object prevents process removal (Windows NT kernel provides no API to remove an assigned process). DPAPI and external HMAC checkpointing make log tampering and tail deletion detectable upon verification. Filesystem locks prevent concurrent state tampering. *Limitation*: A same-user process with arbitrary memory read access can theoretically invoke DPAPI while running under the same user token; true process isolation requires the future separate-service architecture. |
| **Level 3: Elevated Administrator / SYSTEM** | An attacker or compromised process with elevated administrative privileges on the Windows host. | **Outside Security Boundary**: Standard Windows security model: an elevated Administrator or SYSTEM token can bypass any same-user DACL, read arbitrary process memory, alter Job Objects, or delete system locks. ZORO does not run as Administrator and refuses UAC elevation prompts. |

---

## 2. Process Containment & Emergency Shutdown Architecture

### 2.1 Windows Job Object Process Containment

Process lifecycle and emergency containment are managed via the Win32 Job Object API (`zoro/security/job_object.py` and `scripts/supervisor.py`):

1. **Handle Ownership & Non-Inheritance**:
   - The Job Object handle is created by the Supervisor process via `CreateJobObjectW(NULL, "Local\\ZoroJobObject")`.
   - By passing `NULL` security attributes, the handle is non-inheritable.
   - **Kernel Guarantee**: `GetHandleInformation` verifies `HANDLE_FLAG_INHERIT == 0`. Child processes do NOT inherit the handle in their handle table. Any attempt by a child process to call `TerminateJobObject` or `SetInformationJobObject` using the parent's handle value is rejected by the kernel with `ERROR_INVALID_HANDLE` (WinError 6).
2. **Kernel Limit Configuration**:
   - `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x00002000)`: Configured in `JOBOBJECT_EXTENDED_LIMIT_INFORMATION`. When the Supervisor closes its handle or crashes, the Windows NT kernel automatically and atomically terminates every process contained within the job.
   - `JOB_OBJECT_LIMIT_BREAKAWAY_OK (0x00000800)`: **Explicitly set to 0 (Disabled)**.
   - `JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK (0x00001000)`: **Explicitly set to 0 (Disabled)**.
   - Any child process attempting to spawn a process using the `CREATE_BREAKAWAY_FROM_JOB` flag is denied by the Windows kernel with `ERROR_ACCESS_DENIED`.
3. **Descendant Containment**:
   - Every child, grandchild, and descendant process spawned by any process in the Job Object is automatically and immutably assigned to the Job Object by the kernel.
   - The Windows NT kernel provides no function to remove an assigned process from a Job Object; once assigned, containment lasts until process termination.

### 2.2 Independent Emergency Controller & Halt State

Emergency shutdown operates independently of the ZORO runtime, orchestrator, and agents:

- **Independent Script**: `scripts/emergency_kill.py` can be executed directly from PowerShell, CMD, or desktop shortcut (`scripts/emergency_kill.bat`).
- **Atomic Termination Sequence**:
  1. Writes the emergency halt state to `%PROGRAMDATA%\Zoro\Security\halt.lock` (or repository data path).
  2. Dispatches `WindowsJobObject.terminate_named_job(exit_code=137)` to trigger immediate kernel-level termination of the job.
  3. Executes fallback process tree termination via `taskkill /F /T /PID <target_pid>`.
  4. Clears active PID records.
- **Fail-Closed Pre-flight Boot Gate**:
  - `ZoroEngine.initialize()` and `zoro.__main__` check for `halt.lock` before initializing any subsystem.
  - If `halt.lock` exists, startup is immediately aborted with exit code 1.
  - Resumption is permitted **only** after explicitly clearing the lock via `python scripts/emergency_kill.py --resume` or `scripts/resume_zoro.bat`.

---

## 3. Cryptographic Audit Logging & Tamper-Evidence

### 3.1 Hash Chaining & HMAC Protection

All security-sensitive operations (startup, shutdown, permission decisions, IPC events) are logged in SQLite (`audit_records` table) with cryptographic verification:

- **HMAC-SHA256**: Each record computes an HMAC signature over `(prev_hash, timestamp, actor, action, resource, details_json)`.
- **Sequential Chaining**: `prev_hash` links each record to its immediate predecessor. The initial genesis record links to an 8-zero seed string (`00000000`).
- **Middle Deletion & Record Modification Detection**: Modifying any field in an existing record invalidates its `record_hash`. Deleting an intermediate record breaks the `prev_hash` link to subsequent records, causing `verify_integrity()` to fail.

### 3.2 Tail-Deletion Detection via External Checkpoint

Sequential IDs and hash chaining alone cannot detect deletion of the trailing records of a chain (e.g. records 8-10 deleted from a 10-record log leave records 1-7 forming an unbroken chain). ZORO addresses this via an independent, trusted audit checkpoint:

- **Checkpoint File**: Stored at `data/security/audit.checkpoint`.
- **Checkpoint Data**:
  ```json
  {
    "last_sequence_id": 142,
    "last_record_hash": "a1b2c3d4...",
    "timestamp": "2026-11-15T16:00:00Z",
    "signature": "e5f6g7h8..."
  }
  ```
- **HMAC Sealed**: The checkpoint records the exact sequence ID and hash of the latest committed audit record, signed with an HMAC-SHA256 signature using the DPAPI key.
- **Atomic Writes**: Writes use `tempfile` + `os.fsync` + `os.replace` to ensure zero-byte or partially written files cannot corrupt the checkpoint state during sudden system power loss.
- **Fail-Closed Verification**: `verify_integrity()` verifies:
  1. Database record hash continuity from genesis to the last DB record.
  2. Checkpoint signature validity.
  3. Consistency between checkpoint `last_sequence_id` / `last_record_hash` and the actual database state.
  4. If database records are truncated or fewer than the checkpoint records, or if the checkpoint signature is modified, integrity verification fails immediately.

### 3.3 Windows DPAPI Key Lifecycle & Limitations

The HMAC key used for audit record and checkpoint signing is managed by Windows Data Protection API (DPAPI) via `zoro/security/dpapi.py`:

- **At-Rest Protection**:
  The raw 256-bit cryptographic key is encrypted via `CryptProtectData` with `CRYPTPROTECT_UI_FORBIDDEN`. The ciphertext is stored in `data/security/audit.key`.
- **Decryption Fail-Closed Policy**:
  If `audit.key` exists but cannot be decrypted (e.g. corrupted ciphertext or invalid user credential context), `AuditKeyManager.get_or_create_key()` logs a critical security alert and raises `RuntimeError`. It **strictly refuses** to overwrite the existing key or silently generate a new one, preventing the permanent invalidation of historical audit trails.
- **Explicit DPAPI Threat Boundary**:
  - **What DPAPI Protects**: Protects the key against offline disk extraction, unauthenticated access, and other standard user accounts on the same Windows host.
  - **What DPAPI Does NOT Protect**: Does NOT protect against other code executing under the **same Windows user identity**. Because DPAPI derives encryption keys from the currently logged-in user's profile, any executable or script running in the owner's session can call `CryptUnprotectData`. Plaintext keys are never stored in settings files or repositories.

---

## 4. Capability-Based Permission Gate

Actions are categorized into 5 privilege tiers (`zoro/security/permissions.py`):

1. **`READ_ONLY`**: Reading files, querying system telemetry, inspecting logs. Allowed automatically.
2. **`REVERSIBLE_CHANGE`**: Creating scratch files, updating application config, staging edits. Allowed with audit log.
3. **`IRREVERSIBLE_CHANGE`**: Deleting files, modifying existing source code, killing external processes. Requires explicit user confirmation.
4. **`SYSTEM_SETTING`**: Modifying Windows registry, changing environment variables, altering network adapters. Requires explicit confirmation and elevation warning.
5. **`EXTERNAL_COMMUNICATION`**: Sending network packets to non-local IP addresses, sending emails, external API queries. Requires user confirmation.

### Permanently Protected Paths

The following paths are permanently blocked from agent modification, deletion, or renaming:
- `scripts/emergency_kill.*`
- `scripts/resume_zoro.*`
- `scripts/supervisor.*`
- `%PROGRAMDATA%\Zoro\Security\*`
- `data/security/*`
- `.venv\*`
- Windows Operating System system directories (`C:\Windows\*`, `System32`)
