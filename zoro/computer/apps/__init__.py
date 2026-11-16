"""Application Discovery & Control for PROJECT ZORO."""

from zoro.computer.apps.application_controller import ApplicationController
from zoro.computer.apps.application_launcher import ApplicationLauncher
from zoro.computer.apps.application_registry import (
    BUILTIN_WINDOWS_APPS,
    ApplicationRegistry,
)
from zoro.computer.apps.models import AppInfo

__all__ = [
    "AppInfo",
    "ApplicationController",
    "ApplicationLauncher",
    "ApplicationRegistry",
    "BUILTIN_WINDOWS_APPS",
]
