"""Standalone Emergency Kill Switch and Halt Controller for PROJECT ZORO.

Can be run independently of ZORO runtime, virtual environments, or complex dependencies.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from zoro.config.paths import default_paths
from zoro.security.emergency import EmergencyManager


def main() -> None:
    parser = argparse.ArgumentParser(description="PROJECT ZORO Independent Emergency Controller")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--kill", action="store_true", help="Trigger emergency kill and set halt state")
    group.add_argument("--status", action="store_true", help="Check emergency halt status")
    group.add_argument("--resume", action="store_true", help="Clear halt state and allow startup")
    parser.add_argument("--reason", type=str, default="Manual user kill switch trigger", help="Reason for emergency kill")

    args = parser.parse_args()
    mgr = EmergencyManager()

    if args.status:
        is_halted, data = mgr.is_halted()
        if is_halted:
            print("==================================================")
            print(" [!] ZORO IS CURRENTLY IN AN EMERGENCY HALT STATE")
            print("==================================================")
            if data:
                for k, v in data.items():
                    print(f"  {k}: {v}")
            print("\nTo resume normal operation, run:")
            print("  python scripts/emergency_kill.py --resume")
            print("  or double-click scripts/resume_zoro.bat (As Administrator)")
            sys.exit(1)
        else:
            print("[+] ZORO is NOT halted. Normal startup is permitted.")
            pid = mgr.get_recorded_pid()
            if pid:
                print(f"[+] Active runtime PID: {pid}")
            else:
                print("[-] Runtime is not currently active.")
            sys.exit(0)

    elif args.kill:
        print("[!] TRIGGERING EMERGENCY KILL...")
        mgr.trigger_emergency_kill(reason=args.reason)
        print("[+] Emergency kill signal dispatched. Process tree terminated.")
        print(f"[+] Halt lock written to {mgr.halt_lock_path}")
        sys.exit(0)

    elif args.resume:
        print("[*] Attempting to clear emergency halt state...")
        if mgr.resume():
            print("[+] Success: Emergency halt state cleared. ZORO may now be started.")
            sys.exit(0)
        else:
            print("[-] Failed to clear halt state. Please run this command as Administrator.")
            sys.exit(1)


if __name__ == "__main__":
    main()
