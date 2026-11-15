"""Emergency Shutdown Controller and Halt State Manager."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

from zoro.config.paths import default_paths
from zoro.security.job_object import WindowsJobObject

logger = logging.getLogger(__name__)

# Win32 Process Access Flags
PROCESS_TERMINATE: int = 0x0001
PROCESS_QUERY_LIMITED_INFORMATION: int = 0x1000
SYNCHRONIZE: int = 0x00100000
EMERGENCY_PROCESS_ACCESS: int = (
    PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE
)  # 0x00101001

WAIT_OBJECT_0: int = 0x00000000
WAIT_TIMEOUT: int = 0x00000102
WAIT_FAILED: int = 0xFFFFFFFF

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    _KERNEL32 = None

    def _get_kernel32():
        global _KERNEL32
        if _KERNEL32 is None:
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            k32.OpenProcess.restype = wintypes.HANDLE
            k32.GetProcessTimes.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(FILETIME),
                ctypes.POINTER(FILETIME),
                ctypes.POINTER(FILETIME),
                ctypes.POINTER(FILETIME),
            ]
            k32.GetProcessTimes.restype = wintypes.BOOL
            k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
            k32.TerminateProcess.restype = wintypes.BOOL
            k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            k32.WaitForSingleObject.restype = wintypes.DWORD
            k32.CloseHandle.argtypes = [wintypes.HANDLE]
            k32.CloseHandle.restype = wintypes.BOOL
            _KERNEL32 = k32
        return _KERNEL32


def get_process_creation_filetime(pid: int) -> Optional[int]:
    """
    Retrieve the 64-bit raw FILETIME process creation timestamp on Windows.
    Returns 100-nanosecond intervals since Jan 1, 1601 (UTC).
    """
    if os.name != "nt":
        return None
    try:
        k32 = _get_kernel32()
        h_proc = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h_proc:
            return None
        try:
            ct, et, kt, ut = FILETIME(), FILETIME(), FILETIME(), FILETIME()
            if k32.GetProcessTimes(
                h_proc,
                ctypes.byref(ct),
                ctypes.byref(et),
                ctypes.byref(kt),
                ctypes.byref(ut),
            ):
                return (ct.dwHighDateTime << 32) | ct.dwLowDateTime
            return None
        finally:
            k32.CloseHandle(h_proc)
    except Exception as e:
        logger.debug("Failed to query process creation FILETIME for PID %d: %s", pid, e)
        return None


def terminate_process_by_validated_handle(
    pid: int,
    expected_filetime: Optional[int],
    exit_code: int = 137,
    timeout_ms: int = 5000,
) -> Tuple[bool, str]:
    """
    Execute handle-bound process termination with kernel timestamp validation.

    Guarantees elimination of TOCTOU race conditions:
    1. Open the recorded PID with:
       - PROCESS_TERMINATE (0x0001)
       - PROCESS_QUERY_LIMITED_INFORMATION (0x1000)
       - SYNCHRONIZE (0x00100000)
    2. Query process creation FILETIME directly on that opened handle.
    3. Compare against expected_filetime.
    4. If timestamps mismatch, refuse termination (guards against PID reuse).
    5. If matched, call TerminateProcess on the SAME validated handle.
    6. Wait for process termination via WaitForSingleObject.
    7. Ensure handle is closed reliably in finally block.
    """
    if os.name != "nt":
        return False, "Handle-bound termination requires Windows NT."
    if pid <= 0:
        return False, f"Invalid PID {pid}."

    k32 = _get_kernel32()
    h_proc = k32.OpenProcess(EMERGENCY_PROCESS_ACCESS, False, pid)
    if not h_proc:
        err = ctypes.get_last_error()
        return False, f"OpenProcess failed for PID {pid}: WinError {err}"

    try:
        ct, et, kt, ut = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        if not k32.GetProcessTimes(
            h_proc,
            ctypes.byref(ct),
            ctypes.byref(et),
            ctypes.byref(kt),
            ctypes.byref(ut),
        ):
            err = ctypes.get_last_error()
            return False, f"GetProcessTimes failed for PID {pid}: WinError {err}"

        actual_filetime = (ct.dwHighDateTime << 32) | ct.dwLowDateTime

        if expected_filetime is not None:
            # Check for timestamp match. Tolerance of 5_000_000 (500ms) for clock rounding if converted from Unix float.
            # For exact FILETIME match, diff is 0.
            diff = abs(actual_filetime - expected_filetime)
            if diff > 5_000_000:
                return False, (
                    f"PID reuse detected! Process handle creation FILETIME ({actual_filetime}) "
                    f"does not match recorded supervisor FILETIME ({expected_filetime}). "
                    f"Refusing termination to protect unrelated host process."
                )

        # Terminate through the SAME validated process handle
        if not k32.TerminateProcess(h_proc, exit_code):
            err = ctypes.get_last_error()
            # If process was already terminated/terminating:
            wait_res = k32.WaitForSingleObject(h_proc, 500)
            if wait_res == WAIT_OBJECT_0:
                return True, f"Process PID {pid} was already terminating and has exited."
            return False, f"TerminateProcess failed for PID {pid}: WinError {err}"

        # Wait for termination via WaitForSingleObject on the same handle
        wait_res = k32.WaitForSingleObject(h_proc, timeout_ms)
        if wait_res == WAIT_OBJECT_0:
            return True, f"Process PID {pid} terminated and reaped successfully via validated handle."
        elif wait_res == WAIT_TIMEOUT:
            return False, f"WaitForSingleObject timed out ({timeout_ms}ms) waiting for PID {pid} to terminate."
        else:
            err = ctypes.get_last_error()
            return False, f"WaitForSingleObject failed on PID {pid}: result {wait_res}, WinError {err}"
    finally:
        k32.CloseHandle(h_proc)


class EmergencyManager:
    """Controls the independent emergency shutdown and halt lock state."""

    def __init__(self, halt_lock_path: Optional[Path] = None, pid_path: Optional[Path] = None) -> None:
        self.halt_lock_path = halt_lock_path or default_paths.halt_lock_path
        self.pid_path = pid_path or default_paths.pid_path

    def is_halted(self) -> Tuple[bool, Optional[Dict[str, str]]]:
        """Check if ZORO is currently in an emergency halt state."""
        if not self.halt_lock_path.exists():
            return False, None
        
        try:
            content = self.halt_lock_path.read_text(encoding="utf-8")
            data = json.loads(content)
            return True, data
        except Exception:
            return True, {"reason": "Corrupted or manual halt lockfile present."}

    def record_pid(self, pid: Optional[int] = None) -> None:
        """Record the active runtime PID and 64-bit creation FILETIME to prevent PID reuse."""
        target_pid = pid or os.getpid()
        creation_filetime = get_process_creation_filetime(target_pid)
        create_time_unix: Optional[float] = None
        try:
            import psutil
            create_time_unix = float(psutil.Process(target_pid).create_time())
        except Exception as e:
            logger.debug("Could not query Unix create_time for PID %d: %s", target_pid, e)

        record_data = {
            "pid": target_pid,
            "creation_filetime": creation_filetime,
            "create_time": create_time_unix,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.pid_path.parent.mkdir(parents=True, exist_ok=True)
        self.pid_path.write_text(json.dumps(record_data, indent=2), encoding="utf-8")

    def get_recorded_pid_info(self) -> Tuple[Optional[int], Optional[int]]:
        """
        Retrieve the recorded runtime PID and 64-bit creation FILETIME.
        Safely handles missing, malformed, empty, legacy float, or plain-integer files.
        """
        if not self.pid_path.exists():
            return None, None
        try:
            content = self.pid_path.read_text(encoding="utf-8").strip()
            if not content:
                return None, None
            if content.startswith("{"):
                data = json.loads(content)
                pid = data.get("pid")
                creation_filetime = data.get("creation_filetime")
                if creation_filetime is not None:
                    return int(pid), int(creation_filetime)
                # Fallback from legacy float create_time
                create_time = data.get("create_time")
                if create_time is not None:
                    converted_ft = int((float(create_time) + 11644473600.0) * 10000000)
                    return int(pid), converted_ft
                return int(pid) if pid is not None else None, None
            # Legacy plain integer string fallback
            return int(content), None
        except Exception as e:
            logger.warning("Failed to parse PID record at %s (malformed): %s", self.pid_path, e)
            return None, None

    def get_recorded_pid(self) -> Optional[int]:
        """Retrieve the recorded runtime PID, if running."""
        pid, _ = self.get_recorded_pid_info()
        return pid

    def validate_target_process(self, pid: int, expected_filetime: Optional[int]) -> Tuple[bool, str]:
        """
        Validate whether the given PID is still the intended process without terminating it.
        Guards against Windows PID reuse.
        """
        if os.name != "nt":
            return False, "Process validation requires Windows NT."
        if pid <= 0:
            return False, f"Invalid PID {pid}."

        k32 = _get_kernel32()
        h_proc = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h_proc:
            err = ctypes.get_last_error()
            return False, f"Process PID {pid} does not exist or access denied (WinError {err})."

        try:
            ct, et, kt, ut = FILETIME(), FILETIME(), FILETIME(), FILETIME()
            if not k32.GetProcessTimes(
                h_proc,
                ctypes.byref(ct),
                ctypes.byref(et),
                ctypes.byref(kt),
                ctypes.byref(ut),
            ):
                err = ctypes.get_last_error()
                return False, f"GetProcessTimes failed for PID {pid} (WinError {err})."

            actual_filetime = (ct.dwHighDateTime << 32) | ct.dwLowDateTime
            if expected_filetime is not None:
                diff = abs(actual_filetime - expected_filetime)
                if diff > 5_000_000:
                    return False, (
                        f"PID reuse detected! Recorded FILETIME was {expected_filetime}, "
                        f"but active process creation FILETIME is {actual_filetime}. "
                        "Refusing to terminate unrelated process."
                    )
            return True, f"Process PID {pid} validated."
        finally:
            k32.CloseHandle(h_proc)

    def clear_pid(self) -> None:
        """Remove the PID record on normal shutdown."""
        try:
            if self.pid_path.exists():
                self.pid_path.unlink()
        except OSError:
            pass

    def trigger_emergency_kill(self, reason: str = "User initiated emergency kill switch.") -> bool:
        """
        Execute emergency kill:
        1. Write protected halt lockfile.
        2. Terminate Windows Job Object if named.
        3. Handle-bound process termination via validated process handle (no taskkill, no TOCTOU).
        """
        logger.critical("EMERGENCY KILL TRIGGERED: %s", reason)

        # 1. Write the halt lockfile
        try:
            self.halt_lock_path.parent.mkdir(parents=True, exist_ok=True)
            halt_data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "reason": reason,
                "triggered_by": os.environ.get("USERNAME", "owner"),
            }
            self.halt_lock_path.write_text(json.dumps(halt_data, indent=2), encoding="utf-8")
            logger.info("Emergency halt lock written to %s", self.halt_lock_path)
        except Exception as e:
            logger.error("Failed to write emergency halt lockfile: %s", e)

        # 2. Terminate Windows Job Object if named
        if WindowsJobObject.JOB_OBJECT_DEFAULT_NAME:
            WindowsJobObject.terminate_named_job(name=WindowsJobObject.JOB_OBJECT_DEFAULT_NAME, exit_code=137)

        # 3. Handle-bound Process Termination via validated Win32 handle
        target_pid, expected_filetime = self.get_recorded_pid_info()
        if target_pid and os.name == "nt":
            success, msg = terminate_process_by_validated_handle(
                target_pid,
                expected_filetime,
                exit_code=137,
                timeout_ms=5000,
            )
            if success:
                logger.info("Emergency handle-bound termination succeeded: %s", msg)
            else:
                logger.warning("Emergency handle-bound termination refused or failed: %s", msg)

        self.clear_pid()
        return True

    def resume(self) -> bool:
        """Clear the emergency halt lock to permit normal startup."""
        if not self.halt_lock_path.exists():
            logger.info("No active halt lock found.")
            return True
        
        try:
            self.halt_lock_path.unlink()
            logger.info("Emergency halt lock cleared successfully.")
            return True
        except PermissionError:
            logger.error(
                "Permission Denied: Clearing the halt lock requires elevated Administrator privileges! "
                "Run scripts/resume_zoro.bat as Administrator."
            )
            return False
        except Exception as e:
            logger.error("Failed to remove halt lock: %s", e)
            return False

