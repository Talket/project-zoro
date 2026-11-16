"""Application Discovery and Registry for PROJECT ZORO.

Scans Windows Registry uninstall keys, Start Menu directories, and standard
system paths to discover installed applications and map them for autonomous control.
"""

from __future__ import annotations

import logging
import os
import winreg
from pathlib import Path
from typing import Optional

from zoro.computer.apps.models import AppInfo

logger = logging.getLogger(__name__)

# Built-in standard Windows applications
BUILTIN_WINDOWS_APPS = {
    "notepad": AppInfo(
        name="notepad",
        display_name="Notepad",
        executable_path=Path(r"C:\Windows\System32\notepad.exe"),
        publisher="Microsoft Corporation",
    ),
    "calc": AppInfo(
        name="calc",
        display_name="Calculator",
        executable_path=Path(r"C:\Windows\System32\calc.exe"),
        publisher="Microsoft Corporation",
    ),
    "explorer": AppInfo(
        name="explorer",
        display_name="File Explorer",
        executable_path=Path(r"C:\Windows\explorer.exe"),
        publisher="Microsoft Corporation",
    ),
    "mspaint": AppInfo(
        name="mspaint",
        display_name="Paint",
        executable_path=Path(r"C:\Windows\System32\mspaint.exe"),
        publisher="Microsoft Corporation",
    ),
    "cmd": AppInfo(
        name="cmd",
        display_name="Command Prompt",
        executable_path=Path(r"C:\Windows\System32\cmd.exe"),
        publisher="Microsoft Corporation",
    ),
    "powershell": AppInfo(
        name="powershell",
        display_name="Windows PowerShell",
        executable_path=Path(r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"),
        publisher="Microsoft Corporation",
    ),
}

UNINSTALL_REG_KEYS = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
]


class ApplicationRegistry:
    """Discovers, caches, and indexes desktop applications on Windows."""

    def __init__(self) -> None:
        self._apps: dict[str, AppInfo] = dict(BUILTIN_WINDOWS_APPS)
        self._scanned = False

    def scan_installed_applications(self, force_refresh: bool = False) -> list[AppInfo]:
        """Discovers applications from Windows Registry and Start Menu."""
        if self._scanned and not force_refresh:
            return list(self._apps.values())

        discovered: dict[str, AppInfo] = dict(BUILTIN_WINDOWS_APPS)

        # 1. Scan Registry uninstall keys
        if os.name == "nt":
            for root_hive, sub_key in UNINSTALL_REG_KEYS:
                try:
                    with winreg.OpenKey(root_hive, sub_key, 0, winreg.KEY_READ) as key:
                        num_subkeys = winreg.QueryInfoKey(key)[0]
                        for i in range(num_subkeys):
                            try:
                                subkey_name = winreg.EnumKey(key, i)
                                with winreg.OpenKey(key, subkey_name) as app_key:
                                    display_name = self._get_reg_value(app_key, "DisplayName")
                                    if not display_name or display_name.strip() == "":
                                        continue

                                    install_loc = self._get_reg_value(app_key, "InstallLocation")
                                    display_icon = self._get_reg_value(app_key, "DisplayIcon")
                                    version = self._get_reg_value(app_key, "DisplayVersion")
                                    publisher = self._get_reg_value(app_key, "Publisher")

                                    # Try to determine executable path
                                    exe_path: Optional[Path] = None
                                    if display_icon and display_icon.lower().endswith(".exe"):
                                        icon_clean = display_icon.split(",")[0].strip('"')
                                        if Path(icon_clean).exists():
                                            exe_path = Path(icon_clean)
                                    elif install_loc and Path(install_loc).exists():
                                        # Pick first .exe in install folder if found
                                        for p in Path(install_loc).glob("*.exe"):
                                            exe_path = p
                                            break

                                    key_id = display_name.lower().strip()
                                    if key_id not in discovered:
                                        discovered[key_id] = AppInfo(
                                            name=key_id,
                                            display_name=display_name.strip(),
                                            executable_path=exe_path,
                                            version=version,
                                            publisher=publisher,
                                        )
                            except Exception:
                                continue
                except Exception as e:
                    logger.debug("Failed reading registry hive %s: %s", sub_key, e)

        self._apps = discovered
        self._scanned = True
        return list(self._apps.values())

    def _get_reg_value(self, key: Any, value_name: str) -> Optional[str]:
        try:
            val, _ = winreg.QueryValueEx(key, value_name)
            return str(val) if val else None
        except Exception:
            return None

    def find_app(self, query: str) -> Optional[AppInfo]:
        """Finds an application by exact or partial name match."""
        q = query.lower().strip()
        # Direct lookup
        if q in self._apps:
            return self._apps[q]

        # Scan if not scanned yet
        if not self._scanned:
            self.scan_installed_applications()

        if q in self._apps:
            return self._apps[q]

        # Substring search in name or display_name
        for app in self._apps.values():
            if q in app.name or q in app.display_name.lower():
                return app

        return None
