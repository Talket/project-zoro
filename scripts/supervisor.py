"""Process Supervisor launching ZORO within a Windows Job Object."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

# Add project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from zoro.security.emergency import EmergencyManager
from zoro.security.job_object import WindowsJobObject

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [Supervisor] %(message)s")
logger = logging.getLogger("Supervisor")


def main() -> None:
    # 1. Pre-flight check: Is ZORO halted?
    mgr = EmergencyManager()
    is_halted, halt_data = mgr.is_halted()
    if is_halted:
        logger.critical("CANNOT START ZORO: Active emergency halt state detected!")
        if halt_data:
            for k, v in halt_data.items():
                logger.critical("  %s: %s", k, v)
        logger.critical("To authorize resumption, run: python scripts/emergency_kill.py --resume")
        sys.exit(1)

    # 2. Instantiate and configure Windows Job Object
    job = WindowsJobObject()
    if not job.create():
        logger.error("Failed to create Windows Job Object. Aborting.")
        sys.exit(1)

    # Assign current supervisor process to Job Object
    job.assign_process(os.getpid())

    # 3. Determine python executable (prefer venv)
    venv_python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    python_exe = str(venv_python) if venv_python.exists() else sys.executable

    # 4. Launch ZORO runtime
    cmd = [python_exe, "-m", "zoro"]
    logger.info("Spawning ZORO process: %s", " ".join(cmd))
    
    try:
        proc = subprocess.Popen(cmd, cwd=str(PROJECT_ROOT))
        mgr.record_pid(proc.pid)
        job.assign_process(proc.pid)
        logger.info("ZORO started with PID %d. Supervisor running.", proc.pid)

        # Wait for child process
        ret = proc.wait()
        logger.info("ZORO exited with code %d.", ret)
        mgr.clear_pid()
    except KeyboardInterrupt:
        logger.info("Supervisor received interrupt. Terminating Job Object...")
        job.terminate_all(exit_code=0)
    finally:
        job.close()
        mgr.clear_pid()


if __name__ == "__main__":
    main()
