"""Windows Job Object wrapper for kernel-enforced process containment and emergency termination."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import sys
from typing import Optional

logger = logging.getLogger(__name__)

# Windows Constants
JOB_OBJECT_LIMIT_BREAKAWAY_OK = 0x00000800
JOB_OBJECT_LIMIT_SILENT_BREAKAWAY_OK = 0x00001000
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectBasicAccountingInformation = 1
JobObjectExtendedLimitInformation = 9
PROCESS_ALL_ACCESS = 0x1F0FFF
HANDLE_FLAG_INHERIT = 0x00000001


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class JOBOBJECT_BASIC_ACCOUNTING_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("TotalUserTime", ctypes.c_int64),
        ("TotalKernelTime", ctypes.c_int64),
        ("ThisPeriodTotalUserTime", ctypes.c_int64),
        ("ThisPeriodTotalKernelTime", ctypes.c_int64),
        ("TotalPageFaultCount", wintypes.DWORD),
        ("TotalProcesses", wintypes.DWORD),
        ("ActiveProcesses", wintypes.DWORD),
        ("TotalTerminatedProcesses", wintypes.DWORD),
    ]


JOB_OBJECT_DEFAULT_NAME = "Local\\ZoroJobObject"
JOB_OBJECT_TERMINATE = 0x0001
JOB_OBJECT_ALL_ACCESS = 0x1F001F


class WindowsJobObject:
    """Manages a Windows Job Object to contain ZORO processes and guarantee atomic kill."""

    def __init__(self, name: Optional[str] = JOB_OBJECT_DEFAULT_NAME) -> None:
        self.name = name
        self.handle: Optional[wintypes.HANDLE] = None
        self._is_windows = os.name == "nt"

    def create(self) -> bool:
        """Create and configure the Windows Job Object."""
        if not self._is_windows:
            logger.warning("Job Objects are only supported on Windows.")
            return True

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self.handle = kernel32.CreateJobObjectW(None, self.name)
        if not self.handle:
            # Fallback to unnamed job object if named fails
            err = ctypes.get_last_error()
            logger.warning("CreateJobObjectW failed for '%s' (err %d). Retrying with unnamed job.", self.name, err)
            self.handle = kernel32.CreateJobObjectW(None, None)
            if not self.handle:
                logger.error("Failed to create unnamed Job Object: error %d", ctypes.get_last_error())
                return False

        # Configure KILL_ON_JOB_CLOSE (and zero breakaway flags)
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

        success = kernel32.SetInformationJobObject(
            self.handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not success:
            err = ctypes.get_last_error()
            logger.error("Failed to set Job Object information: error %d", err)
            return False

        logger.info("Windows Job Object '%s' created and configured.", self.name)
        return True

    @classmethod
    def open_existing(cls, name: str = JOB_OBJECT_DEFAULT_NAME) -> Optional[WindowsJobObject]:
        """Open an existing named Job Object."""
        if os.name != "nt":
            return None

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        h_job = kernel32.OpenJobObjectW(JOB_OBJECT_ALL_ACCESS, False, name)
        if not h_job:
            logger.debug("OpenJobObjectW '%s' returned None (error %d)", name, ctypes.get_last_error())
            return None

        job = cls(name=name)
        job.handle = h_job
        return job

    @classmethod
    def terminate_named_job(cls, name: str = JOB_OBJECT_DEFAULT_NAME, exit_code: int = 137) -> bool:
        """Find an existing named Job Object and terminate all processes inside it."""
        job = cls.open_existing(name)
        if not job:
            return False
        try:
            return job.terminate_all(exit_code=exit_code)
        finally:
            job.close()

    def assign_process(self, pid: Optional[int] = None) -> bool:
        """Assign the specified PID (or current process if None) to the Job Object."""
        if not self._is_windows or not self.handle:
            return True

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        target_pid = pid or os.getpid()

        h_process = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, target_pid)
        if not h_process:
            err = ctypes.get_last_error()
            logger.error("Failed to open process %d: error %d", target_pid, err)
            return False

        try:
            success = kernel32.AssignProcessToJobObject(self.handle, h_process)
            if not success:
                err = ctypes.get_last_error()
                logger.error("Failed to assign process %d to Job Object: error %d", target_pid, err)
                return False
            logger.info("Process %d assigned to Job Object.", target_pid)
            return True
        finally:
            kernel32.CloseHandle(h_process)

    def terminate_all(self, exit_code: int = 137) -> bool:
        """Atomically terminate all processes associated with this Job Object."""
        if not self._is_windows or not self.handle:
            return True

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        success = kernel32.TerminateJobObject(self.handle, exit_code)
        if not success:
            err = ctypes.get_last_error()
            logger.error("Failed to terminate Job Object: error %d", err)
            return False
        logger.warning("Job Object terminated all processes with exit code %d.", exit_code)
        return True

    def query_limit_flags(self) -> Optional[int]:
        """Query kernel LimitFlags configured on this Job Object."""
        if not self._is_windows or not self.handle:
            return None

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        success = kernel32.QueryInformationJobObject(
            self.handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        )
        if not success:
            err = ctypes.get_last_error()
            logger.error("Failed to query Job Object limit information: error %d", err)
            return None
        return int(info.BasicLimitInformation.LimitFlags)

    def is_handle_inheritable(self) -> bool:
        """Query whether the Job Object handle has the HANDLE_FLAG_INHERIT flag set."""
        if not self._is_windows or not self.handle:
            return False

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        flags = wintypes.DWORD()
        success = kernel32.GetHandleInformation(self.handle, ctypes.byref(flags))
        if not success:
            err = ctypes.get_last_error()
            logger.error("Failed to get handle information: error %d", err)
            return False
        return bool(flags.value & HANDLE_FLAG_INHERIT)

    def query_active_process_count(self) -> int:
        """Query the number of currently active processes in the Job Object."""
        if not self._is_windows or not self.handle:
            return 0

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        acc = JOBOBJECT_BASIC_ACCOUNTING_INFORMATION()
        success = kernel32.QueryInformationJobObject(
            self.handle,
            JobObjectBasicAccountingInformation,
            ctypes.byref(acc),
            ctypes.sizeof(acc),
            None,
        )
        if not success:
            err = ctypes.get_last_error()
            logger.error("Failed to query Job Object accounting information: error %d", err)
            return 0
        return int(acc.ActiveProcesses)

    def close(self) -> None:
        """Close the Job Object handle."""
        if self._is_windows and self.handle:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.CloseHandle(self.handle)
            self.handle = None
