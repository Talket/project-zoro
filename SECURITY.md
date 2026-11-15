# PROJECT ZORO — Security Specification & Threat Model

## 1. Security Philosophy & Threat Model Principles

PROJECT ZORO operates on principles of bounded autonomy, fail-closed defenses, and defense-in-depth. 
No component of the artificial intelligence makes claims of being "tamper-proof" or "impossible to bypass." Instead, the architecture establishes well-defined security boundaries, cryptographic tamper-evidence, and kernel-enforced process containment.

### The Three Threat Levels

| Threat Level | Adversary / Failure Mode | Defense Mechanism & Architectural Guarantee | Residual Risks & Boundaries |
| :--- | :--- | :--- | :--- |
| **Level 1: Accidental Breakaway & Runaway Workloads** | Unhandled exceptions, infinite tool loops, hung worker threads, or subprocesses spawned with `CREATE_NEW_PROCESS_GROUP`. | **Fully Mitigated**: Windows Job Object process containment traps all direct descendant processes. Kernel-level `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` and zero-breakaway enforcement guarantee atomic termination of the contained process tree on supervisor exit or emergency trigger. | None within standard process trees. |
| **Level 2: Malicious Code at Same User Privilege** | Compromised code running within ZORO's interactive desktop session attempting to conceal actions, tamper with logs, or persist beyond a kill signal. | **Tamper-Evident & Contained**: Unnamed Job Objects prevent same-user handle retention or attribute tampering. DPAPI encryption at rest and external HMAC checkpointing make log tampering and tail deletion detectable upon verification. Filesystem locks prevent concurrent state deletion. | **Known Boundary**: A same-user process executing arbitrary code can invoke DPAPI under the same user session, terminate processes, or spawn detached tasks via out-of-band OS brokers (e.g., WMI, COM, Task Scheduler). True privilege isolation requires a separate-service security principal. |
| **Level 3: Elevated Administrator / SYSTEM** | An attacker or compromised process with elevated administrative privileges on the Windows host. | **Outside Security Boundary**: Standard Windows security model: an elevated Administrator or SYSTEM token can bypass any same-user DACL, read arbitrary process memory, terminate Job Objects, or delete system locks. ZORO does not run as Administrator and rejects UAC elevation prompts. | Elevated attackers can override any user-mode boundary. |

---

## 2. Process Containment & Emergency Shutdown Architecture

### 2.1 Windows Job Object Process Containment

Process containment is managed via the Win32 Job Object API (`zoro/security/job_object.py` and `scripts/supervisor.py`):

1. **Unnamed Job Object Architecture (Production Default)**:
   - In production, ZORO uses an **UNNAMED** Job Object (`WindowsJobObject(name=None)`).
   - **Why Named Job Objects are Avoided**: Win32 security analysis confirms that creating a named Job Object (`Local\ZoroJobObject`) with default security attributes assigns a DACL granting `JOB_OBJECT_ALL_ACCESS` (0x1F003F) to the creating user's SID. Consequently, any process running in the same user session could call `OpenJobObjectW` and:
     - Retain an additional handle, preventing `KILL_ON_JOB_CLOSE` from firing when the supervisor terminates (the kernel requires the *last* handle to close).
     - Call `SetInformationJobObject` with `JOB_OBJECT_SET_ATTRIBUTES` to clear `LimitFlags = 0` or enable breakaway.
   - **Unnamed Job Protection**: Because the Job Object has no name in the Windows Object Manager namespace, `OpenJobObjectW(..., None)` returns `ERROR_INVALID_PARAMETER` (87). No external process can discover, open, or hold a handle to it.
2. **Handle Ownership & Non-Inheritance**:
   - The handle is created solely by the Supervisor process with `NULL` security attributes.
   - **Kernel Guarantee**: `GetHandleInformation` verifies `HANDLE_FLAG_INHERIT == 0`. Child processes do NOT inherit the handle in their handle table (`ERROR_INVALID_HANDLE` 6 on access attempts).
   - Because only the Supervisor holds the handle, the Supervisor's exit or termination is guaranteed to close the *last handle* in existence.
3. **Kernel Limit Configuration**:
   - `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE (0x00002000)`: Configured in `JOBOBJECT_EXTENDED_LIMIT_INFORMATION`. When the Supervisor closes its handle, crashes, or is killed, the Windows NT kernel immediately terminates every process contained within the job.
   - `JOB_OBJECT_LIMIT_BREAKAWAY_OK (0x00000800)`: Explicitly 0 (Disabled).
   - `JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK (0x00001000)`: Explicitly 0 (Disabled).
   - Any child process attempting to spawn a process with `CREATE_BREAKAWAY_FROM_JOB` is denied by the Windows kernel with `ERROR_ACCESS_DENIED`.
4. **Scope of Process Containment**:
   - **Contained**: All direct child, grandchild, and descendant processes created via Win32 `CreateProcess` or Python `subprocess.Popen` are automatically assigned to the Job Object.
   - **Not Contained (Brokered Execution)**: Processes launched through external operating system brokers or RPC services (e.g., scheduled tasks via `schtasks.exe`, COM objects via `CoCreateInstance`, or WMI process creation) execute outside the caller's process tree and are NOT assigned to the Job Object unless an external monitor explicitly captures their PIDs.
5. **Explicit Handle Duplication Security Boundary**:
   - While an unnamed Job Object cannot be opened by name (`OpenJobObjectW` fails with `ERROR_INVALID_PARAMETER`), any malicious process executing under the **same Windows user identity** has `PROCESS_ALL_ACCESS` or `PROCESS_DUP_HANDLE` rights against other same-user processes.
   - Empirical tests prove that a same-user process can call `OpenProcess(PROCESS_DUP_HANDLE)` against the supervisor and call `DuplicateHandle` to duplicate the supervisor's unnamed Job Object handle into its own handle table.
   - If a malicious process retains this duplicated handle, the Job Object reference count remains $\ge 1$, preventing `KILL_ON_JOB_CLOSE` from terminating child processes when the supervisor dies until the duplicated handle is also closed.
   - Process DACLs cannot prevent this between processes sharing the same Windows SID, because the user token is the owner of the process object and inherently retains `WRITE_DAC` rights. True isolation against arbitrary same-user malware requires separate security principals (e.g. running the supervisor under a dedicated Windows Service), which is outside standard user-mode desktop execution.

### 2.2 Emergency Shutdown Mechanism & Anti-PID-Reuse Protection

Emergency shutdown operates through a coordinated sequence:

1. **Independent Invocation**: `scripts/emergency_kill.py` can be executed from a desktop shortcut (`emergency_kill.bat`) or shell.
2. **Execution Sequence**:
   - **Step 1: Write Halt Lock**: Writes the emergency halt state to `%PROGRAMDATA%\Zoro\Security\halt.lock` (or repository data directory).
   - **Step 2: PID & Process Creation Timestamp Validation**:
     - Reads the supervisor PID and process creation timestamp from `zoro.pid`.
     - Validates the target process via `EmergencyManager.validate_target_process()`.
     - **Anti-PID-Reuse Guard**: If Windows has recycled the PID for an unrelated process, the process creation timestamp will not match. The controller detects this and **strictly refuses termination**, logging a warning and preventing accidental damage to unrelated applications.
     - Safely handles missing, empty, or malformed PID records without crashing.
   - **Step 3: Terminate Supervisor Process**: Terminates the validated supervisor process tree via `taskkill /F /T /PID <pid>`.
   - **Step 4: Kernel Job Object Termination**: Terminating the supervisor closes its handle to the unnamed Job Object. The Windows NT kernel immediately executes `KILL_ON_JOB_CLOSE`, killing all contained processes.
   - **Step 5: Cleanup**: Clears runtime PID records.
3. **Fail-Closed Pre-flight Boot Gate**:
   - `ZoroEngine.initialize()` and `zoro.__main__` check for `halt.lock` before initializing any subsystem.
   - If `halt.lock` exists, startup aborts immediately with exit code 1.
   - Resumption requires explicitly running `python scripts/emergency_kill.py --resume` or `scripts/resume_zoro.bat`.

### 2.3 Win32 Access Mask Reference (Modern Windows SDK)

The Job Object access rights are defined in `winnt.h`:
- `JOB_OBJECT_ASSIGN_PROCESS (0x0001)`: Assign processes to the job.
- `JOB_OBJECT_SET_ATTRIBUTES (0x0002)`: Set job limits and flags.
- `JOB_OBJECT_QUERY (0x0004)`: Query accounting and limits.
- `JOB_OBJECT_TERMINATE (0x0008)`: Terminate all processes in the job.
- `JOB_OBJECT_SET_SECURITY_ATTRIBUTES (0x0010)`: Set security attributes.
- `JOB_OBJECT_IMPERSONATE (0x0020)`: Added in Windows 7 / Server 2008 R2 (the 0x20 bit).
- `STANDARD_RIGHTS_REQUIRED (0x000F0000)` & `SYNCHRONIZE (0x00100000)`.
- **Modern SDK `JOB_OBJECT_ALL_ACCESS`**: `0x001F003F` (includes `0x0020` impersonation flag).
- **Legacy SDK `JOB_OBJECT_ALL_ACCESS`**: `0x001F001F` (pre-Windows 7 headers).

---

## 3. Cryptographic Audit Logging & Crash Consistency

### 3.1 Hash Chaining & HMAC Protection

Security-sensitive operations are logged in SQLite (`audit_records` table) with cryptographic verification:

- **HMAC-SHA256**: Each record computes an HMAC signature over `(prev_hash, timestamp, actor, action, resource, details_json)`.
- **Sequential Chaining**: `prev_hash` links each record to its immediate predecessor. The genesis record links to `00000000`.
- **Middle Deletion & Alteration**: Modifying any field invalidates `record_hash`. Deleting an intermediate record breaks sequence IDs and `prev_hash` chaining.

### 3.2 Tail-Deletion Detection via External Checkpoint

Deleting trailing records cannot be caught by DB hash chaining alone (records 1..$M$ remain valid). ZORO uses an independent, trusted checkpoint:

- **Checkpoint File**: Stored at `data/security/audit.checkpoint`.
- **Checkpoint Payload**: `last_sequence_id`, `last_record_hash`, `timestamp`, and DPAPI-HMAC `signature`.
- **Atomic Writes**: Uses `NamedTemporaryFile`, followed by `os.fsync(f.fileno())` and atomic `os.replace()`.
- **Fail-Closed Dual Verification**:
  - `verify_integrity()` checks database hash continuity and checkpoint HMAC validity.
  - Verifies that `db_last_id == checkpoint.last_sequence_id` and `db_last_hash == checkpoint.last_record_hash`.
  - Distinguishes **tail deletion** (`db_last_id < cp_seq`) from **crash inconsistency** (`db_last_id > cp_seq`). Both fail closed.

### 3.3 Checkpoint Crash Consistency & Recovery Policy

- **Crash Scenarios & Behavior**:
  1. *Crash during temporary file creation*: Stray `.tmp` files in the directory are ignored; the valid atomic checkpoint remains intact.
  2. *Crash after file flush, during replacement*: `os.replace()` on Windows NTFS (`MoveFileExW`) is an atomic directory metadata transaction. Either the previous or new checkpoint is present.
  3. *Crash after database commit before checkpoint write*: Database is ahead of checkpoint (`db_last_id > cp_seq`). `verify_integrity()` detects the mismatch and fails closed.
- **Fail-Closed Policy (No Silent Regeneration)**:
  - The runtime **NEVER silently regenerates or updates the checkpoint** upon detecting an integrity mismatch.
  - All historical audit records in SQLite remain intact and recoverable for forensic investigation.
  - If investigation confirms an interrupted write, re-anchoring requires calling `AuditLogger.recover_checkpoint_manually()` under explicit owner instruction.

### 3.4 Windows DPAPI Key Lifecycle & Boundaries

The 256-bit HMAC key is managed by Windows DPAPI via `zoro/security/dpapi.py`:

- **At-Rest Protection**: Key ciphertext is encrypted via `CryptProtectData` with `CRYPTPROTECT_UI_FORBIDDEN` and stored in `data/security/audit.key`.
- **Decryption Fail-Closed Policy**: If `audit.key` exists but decryption fails, `AuditKeyManager.get_or_create_key()` logs a critical error and raises `RuntimeError`. It strictly refuses to overwrite the existing key or silently generate a new one, protecting historical audit logs from permanent invalidation.
- **Explicit Threat Boundaries**:
  - **What DPAPI Protects**: Protects stored key material at rest against offline disk extraction, volume theft, and access from other Windows user profiles.
  - **What DPAPI Does NOT Protect**: Does NOT isolate secrets from malicious software executing under the **same Windows user identity**. Because DPAPI derives keys from the active logon token, any executable running under the owner's account can invoke `CryptUnprotectData`. Plaintext keys are never stored in settings or files.

---

## 4. Capability-Based Permission Gate

Actions are categorized into 5 privilege tiers (`zoro/security/permissions.py`):

1. **`READ_ONLY`**: Reading files, querying system telemetry, inspecting logs. Allowed automatically.
2. **`REVERSIBLE_CHANGE`**: Creating scratch files, updating application config, staging edits. Allowed with audit log.
3. **`IRREVERSIBLE_CHANGE`**: Deleting files, modifying source code, killing external processes. Requires user confirmation.
4. **`SYSTEM_SETTING`**: Modifying Windows registry, altering environment variables. Requires confirmation and elevation warning.
5. **`EXTERNAL_COMMUNICATION`**: Sending outbound network packets, external API queries. Requires user confirmation.

### Permanently Protected Paths

The following paths are permanently blocked from agent modification, deletion, or renaming:
- `scripts/emergency_kill.*`
- `scripts/resume_zoro.*`
- `scripts/supervisor.*`
- `%PROGRAMDATA%\Zoro\Security\*`
- `data/security/*`
- `.venv\*`
- Windows Operating System system directories (`C:\Windows\*`, `System32`)
