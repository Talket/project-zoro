"""Emergency Shutdown Controller and Halt State Manager."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

from zoro.config.paths import default_paths
from zoro.security.job_object import WindowsJobObject

logger = logging.getLogger(__name__)


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
        """Record the active runtime PID and creation timestamp to prevent PID reuse."""
        target_pid = pid or os.getpid()
        create_time: Optional[float] = None
        try:
            import psutil
            create_time = float(psutil.Process(target_pid).create_time())
        except Exception as e:
            logger.debug("Could not query process creation time for PID %d: %s", target_pid, e)

        record_data = {
            "pid": target_pid,
            "create_time": create_time,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        self.pid_path.parent.mkdir(parents=True, exist_ok=True)
        self.pid_path.write_text(json.dumps(record_data, indent=2), encoding="utf-8")

    def get_recorded_pid_info(self) -> Tuple[Optional[int], Optional[float]]:
        """
        Retrieve the recorded runtime PID and creation timestamp.
        Safely handles missing, malformed, empty, or legacy plain-integer files.
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
                create_time = data.get("create_time")
                return (
                    int(pid) if pid is not None else None,
                    float(create_time) if create_time is not None else None,
                )
            # Legacy plain integer string fallback
            return int(content), None
        except Exception as e:
            logger.warning("Failed to parse PID record at %s (malformed): %s", self.pid_path, e)
            return None, None

    def get_recorded_pid(self) -> Optional[int]:
        """Retrieve the recorded runtime PID, if running."""
        pid, _ = self.get_recorded_pid_info()
        return pid

    def validate_target_process(self, pid: int, expected_create_time: Optional[float]) -> Tuple[bool, str]:
        """
        Validate whether the given PID is still the intended process.
        Guards against Windows PID reuse: if a process exited and the OS assigned its PID
        to an unrelated application, creation time verification prevents killing the wrong process.
        """
        try:
            import psutil
            if not psutil.pid_exists(pid):
                return False, f"Process PID {pid} does not exist (already terminated)."
            proc = psutil.Process(pid)
            if expected_create_time is not None:
                actual_create_time = proc.create_time()
                # 0.5s tolerance for clock granularity / float rounding
                if abs(actual_create_time - expected_create_time) > 0.5:
                    return False, (
                        f"PID reuse detected! Recorded PID {pid} creation time was {expected_create_time}, "
                        f"but active process creation time is {actual_create_time}. "
                        "Refusing to terminate unrelated process."
                    )
            return True, f"Process PID {pid} validated."
        except Exception as e:
            return False, f"Process validation error for PID {pid}: {e}"

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
        3. Validated process tree termination via taskkill with PID reuse protection.
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

        # 3. Validated Process Tree Termination via taskkill
        target_pid, expected_create_time = self.get_recorded_pid_info()
        if target_pid and os.name == "nt":
            is_valid, validation_msg = self.validate_target_process(target_pid, expected_create_time)
            if is_valid:
                try:
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(target_pid)],
                        capture_output=True,
                        check=False,
                    )
                    logger.info("Executed taskkill on process tree for validated PID %d", target_pid)
                except Exception as e:
                    logger.error("Failed to execute taskkill: %s", e)
            else:
                logger.warning(
                    "Emergency kill skipped process termination to prevent accidental damage: %s",
                    validation_msg,
                )

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
