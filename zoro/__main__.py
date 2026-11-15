"""Main entry point for PROJECT ZORO."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import threading
from typing import Optional

from colorama import Fore, Style, init

from zoro.config.settings import get_settings
from zoro.core.engine import ZoroEngine
from zoro.security.emergency import EmergencyManager
from zoro.ui.app import ZoroDesktopApp

init(autoreset=True)

logging.basicConfig(
    level=logging.INFO,
    format=f"{Fore.CYAN}%(asctime)s{Style.RESET_ALL} [{Fore.BLUE}%(levelname)s{Style.RESET_ALL}] [%(name)s] %(message)s",
)
logger = logging.getLogger("ZoroMain")


def run_engine_async(engine: ZoroEngine) -> None:
    """Run engine inside an asyncio event loop."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(engine.run())
    finally:
        loop.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="PROJECT ZORO: Autonomous Personal Artificial Intelligence")
    parser.add_argument("--headless", action="store_true", help="Run Core Runtime Engine only without Desktop UI")
    parser.add_argument("--ui", action="store_true", help="Run Desktop UI Shell only (connects to running engine)")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")

    args = parser.parse_args()
    settings = get_settings()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # 1. Preflight emergency check
    emergency_mgr = EmergencyManager()
    is_halted, halt_data = emergency_mgr.is_halted()
    if is_halted:
        print(f"\n{Fore.RED}======================================================{Style.RESET_ALL}")
        print(f"{Fore.RED} [!] CRITICAL: ZORO IS CURRENTLY IN AN EMERGENCY HALT STATE{Style.RESET_ALL}")
        print(f"{Fore.RED}======================================================{Style.RESET_ALL}")
        if halt_data:
            for k, v in halt_data.items():
                print(f"  {k}: {v}")
        print(f"\n{Fore.YELLOW}To resume normal operation, execute:{Style.RESET_ALL}")
        print("  python scripts/emergency_kill.py --resume")
        print("  or double-click scripts/resume_zoro.bat (As Administrator)\n")
        sys.exit(1)

    print(f"{Fore.CYAN}======================================================{Style.RESET_ALL}")
    print(f"{Fore.CYAN}            PROJECT ZORO -- ONLINE                    {Style.RESET_ALL}")
    print(f"{Fore.CYAN}======================================================{Style.RESET_ALL}")

    if args.headless:
        # Headless mode: run engine directly on main thread
        logger.info("Starting ZORO in Headless Engine mode...")
        engine = ZoroEngine(settings=settings)
        asyncio.run(engine.run())

    elif args.ui:
        # UI mode only: connect to already running engine
        logger.info("Starting ZORO Desktop UI Shell only...")
        app = ZoroDesktopApp(settings=settings)
        sys.exit(app.run())

    else:
        # Default Full Mode: Spawn engine in background thread, run UI on main thread
        logger.info("Starting ZORO Full System (Core Engine + Desktop Shell)...")
        engine = ZoroEngine(settings=settings)
        engine_thread = threading.Thread(target=run_engine_async, args=(engine,), name="zoro-engine-thread", daemon=True)
        engine_thread.start()

        # Run Qt UI on main thread (required by Qt)
        app = ZoroDesktopApp(settings=settings)
        exit_code = app.run()

        # When UI exits, stop engine
        logger.info("Desktop UI closed. Stopping Core Engine...")
        engine.lifecycle.request_shutdown()
        engine_thread.join(timeout=5.0)
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
