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
        """Record the active runtime PID."""
        target_pid = pid or os.getpid()
        self.pid_path.parent.mkdir(parents=True, exist_ok=True)
        self.pid_path.write_text(str(target_pid), encoding="utf-8")

    def get_recorded_pid(self) -> Optional[int]:
        """Retrieve the recorded runtime PID, if running."""
        if not self.pid_path.exists():
            return None
        try:
            content = self.pid_path.read_text(encoding="utf-8").strip()
            return int(content)
        except Exception:
            return None

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
        2. Terminate Job Object if handle available.
        3. Fallback: Force-kill process tree via taskkill.
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

        # 2. Terminate Windows Job Object
        terminated = WindowsJobObject.terminate_named_job(exit_code=137)
        if not terminated:
            job = WindowsJobObject()
            if job.create():
                job.terminate_all(exit_code=137)
                job.close()

        # 3. Fallback: taskkill process tree
        target_pid = self.get_recorded_pid()
        if target_pid and os.name == "nt":
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(target_pid)],
                    capture_output=True,
                    check=False,
                )
                logger.info("Executed taskkill on process tree for PID %d", target_pid)
            except Exception as e:
                logger.error("Failed to execute taskkill: %s", e)

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
