"""Windows Named Pipe IPC Client for Desktop Shell communication."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

from zoro.config.settings import ZoroSettings, get_settings
from zoro.ipc.protocol import (
    decode_message,
    encode_message,
    JsonRpcRequest,
)

logger = logging.getLogger(__name__)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x00000080
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = -1
BUFFER_SIZE = 65536

ERROR_IO_PENDING = 997
ERROR_BROKEN_PIPE = 109
ERROR_NO_DATA = 232
ERROR_OPERATION_ABORTED = 995
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102

NotificationCallback = Callable[[str, Dict[str, Any]], None]


class OVERLAPPED(ctypes.Structure):
    """Win32 OVERLAPPED structure for asynchronous I/O."""

    _fields_ = [
        ("Internal", wintypes.LPVOID),
        ("InternalHigh", wintypes.LPVOID),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


_K32: Optional[ctypes.WinDLL] = None


def _get_kernel32() -> ctypes.WinDLL:
    """Configure 64-bit kernel32 Win32 function signatures."""
    global _K32
    if _K32 is not None:
        return _K32
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    k32.ReadFile.restype = wintypes.BOOL
    k32.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    k32.WriteFile.restype = wintypes.BOOL
    k32.WriteFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_char_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    k32.CloseHandle.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CreateEventW.restype = wintypes.HANDLE
    k32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.GetOverlappedResult.restype = wintypes.BOOL
    k32.GetOverlappedResult.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL
    ]
    if hasattr(k32, "CancelIoEx"):
        k32.CancelIoEx.restype = wintypes.BOOL
        k32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    _K32 = k32
    return _K32


class NamedPipeClient:
    """IPC Client connecting the PySide6 UI Shell to the Core Runtime Engine."""

    def __init__(self, pipe_name: Optional[str] = None, settings: Optional[ZoroSettings] = None) -> None:
        self.settings = settings or get_settings()
        self.pipe_name = pipe_name or self.settings.pipe_name
        self.handle = None
        self._is_connected = False
        self._is_running = False
        self._pending_requests: Dict[int, Dict[str, Any]] = {}
        self._request_counter = 0
        self._notification_handlers: Dict[str, NotificationCallback] = {}
        self._reader_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def register_notification_handler(self, method: str, callback: NotificationCallback) -> None:
        """Register a callback for unsolicited notifications (e.g. 'telemetry.update')."""
        self._notification_handlers[method] = callback

    def connect(self, timeout_ms: int = 2000) -> bool:
        """Attempt connection to the Named Pipe with overlapped I/O flags and retry window."""
        if os.name != "nt":
            return False

        kernel32 = _get_kernel32()
        start = time.time()
        timeout_sec = timeout_ms / 1000.0

        while time.time() - start < timeout_sec:
            h_file = kernel32.CreateFileW(
                self.pipe_name,
                GENERIC_READ | GENERIC_WRITE,
                0,
                None,
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OVERLAPPED,
                None,
            )

            if h_file not in (INVALID_HANDLE_VALUE, 0, 0xFFFFFFFFFFFFFFFF, None):
                self.handle = h_file
                self._is_connected = True
                self._is_running = True
                logger.info("Connected to Named Pipe server at %s", self.pipe_name)

                if self._reader_thread and self._reader_thread.is_alive():
                    self._reader_thread.join(timeout=0.5)

                self._reader_thread = threading.Thread(target=self._reader_loop, name="zoro-pipe-client-reader", daemon=True)
                self._reader_thread.start()
                return True

            time.sleep(0.05)

        return False

    def _reader_loop(self) -> None:
        """Background loop reading responses and notifications from the pipe asynchronously."""
        kernel32 = _get_kernel32()
        read_buf = ctypes.create_string_buffer(BUFFER_SIZE)
        accumulator = b""

        while self._is_running and self._is_connected and self.handle:
            success, n_bytes = self._overlapped_read(kernel32, read_buf, BUFFER_SIZE, timeout_ms=250)
            if not success:
                if n_bytes == -1:  # Disconnected
                    logger.warning("Pipe read failed or server disconnected.")
                    self._is_connected = False
                    break
                continue

            accumulator += read_buf.raw[:n_bytes]

            while accumulator:
                try:
                    msg, accumulator = decode_message(accumulator)
                except ValueError as e:
                    logger.error("IPC client decoding error: %s", e)
                    accumulator = b""
                    break

                if msg is None:
                    break

                self._process_message(msg)

        # Cleanup on disconnection
        self._is_connected = False
        if self.handle:
            kernel32.CloseHandle(self.handle)
            self.handle = None

        # Fail pending requests so callers do not hang
        with self._lock:
            for req_id, entry in list(self._pending_requests.items()):
                entry["response"] = {"error": {"code": -32001, "message": "Pipe connection lost."}}
                entry["event"].set()
            self._pending_requests.clear()

    def _overlapped_read(self, kernel32: ctypes.WinDLL, buf: Any, size: int, timeout_ms: int = 250) -> Tuple[bool, int]:
        """Perform an overlapped read with a timeout."""
        ov = OVERLAPPED()
        ov.hEvent = kernel32.CreateEventW(None, True, False, None)
        try:
            bytes_read = wintypes.DWORD()
            ret = kernel32.ReadFile(self.handle, buf, size, None, ctypes.byref(ov))
            err = ctypes.get_last_error()
            if not ret:
                if err == ERROR_IO_PENDING:
                    wait_res = kernel32.WaitForSingleObject(ov.hEvent, timeout_ms)
                    if wait_res == WAIT_OBJECT_0:
                        transferred = wintypes.DWORD()
                        if kernel32.GetOverlappedResult(self.handle, ctypes.byref(ov), ctypes.byref(transferred), False):
                            return True, transferred.value
                        return False, -1
                    elif wait_res == WAIT_TIMEOUT:
                        kernel32.CancelIoEx(self.handle, ctypes.byref(ov))
                        return False, 0
                    else:
                        return False, -1
                elif err in (ERROR_BROKEN_PIPE, ERROR_NO_DATA, ERROR_OPERATION_ABORTED):
                    return False, -1
                else:
                    return False, -1
            else:
                transferred = wintypes.DWORD()
                kernel32.GetOverlappedResult(self.handle, ctypes.byref(ov), ctypes.byref(transferred), False)
                return True, transferred.value
        finally:
            kernel32.CloseHandle(ov.hEvent)

    def _process_message(self, msg: Dict[str, Any]) -> None:
        """Process incoming JSON-RPC response or notification."""
        req_id = msg.get("id")
        method = msg.get("method")

        if req_id is not None and req_id in self._pending_requests:
            with self._lock:
                entry = self._pending_requests.pop(req_id, None)
            if entry:
                entry["response"] = msg
                entry["event"].set()
        elif method:
            handler = self._notification_handlers.get(method)
            if handler:
                params = msg.get("params", {})
                try:
                    handler(method, params)
                except Exception as e:
                    logger.error("Error in notification handler for '%s': %s", method, e)

    def send_request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 5.0) -> Any:
        """Send JSON-RPC request to server and await result."""
        if not self._is_connected or not self.handle:
            raise ConnectionError("Not connected to Named Pipe server.")

        with self._lock:
            self._request_counter += 1
            req_id = self._request_counter
            event = threading.Event()
            entry = {"event": event, "response": None}
            self._pending_requests[req_id] = entry

        req = JsonRpcRequest(id=req_id, method=method, params=params or {})
        payload = encode_message(req.model_dump())

        kernel32 = _get_kernel32()
        ov = OVERLAPPED()
        ov.hEvent = kernel32.CreateEventW(None, True, False, None)
        try:
            bytes_written = wintypes.DWORD()
            ret = kernel32.WriteFile(self.handle, payload, len(payload), None, ctypes.byref(ov))
            err = ctypes.get_last_error()
            if not ret and err == ERROR_IO_PENDING:
                wait_res = kernel32.WaitForSingleObject(ov.hEvent, int(timeout * 1000))
                if wait_res == WAIT_OBJECT_0:
                    kernel32.GetOverlappedResult(self.handle, ctypes.byref(ov), ctypes.byref(bytes_written), False)
                else:
                    kernel32.CancelIoEx(self.handle, ctypes.byref(ov))
                    with self._lock:
                        self._pending_requests.pop(req_id, None)
                    raise TimeoutError(f"Request '{method}' write timed out.")
            elif not ret:
                with self._lock:
                    self._pending_requests.pop(req_id, None)
                raise ConnectionError(f"Failed to write to Named Pipe (WinError {err}).")
        finally:
            kernel32.CloseHandle(ov.hEvent)

        signaled = event.wait(timeout=timeout)
        if not signaled:
            with self._lock:
                self._pending_requests.pop(req_id, None)
            raise TimeoutError(f"Request '{method}' (id={req_id}) timed out waiting for response.")

        response = entry.get("response", {})
        if "error" in response and response["error"]:
            raise RuntimeError(f"RPC Error: {response['error'].get('message', 'Unknown error')}")

        return response.get("result")

    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self._is_connected

    def close(self) -> None:
        """Close connection cleanly."""
        self._is_running = False
        self._is_connected = False
        if self.handle and os.name == "nt":
            kernel32 = _get_kernel32()
            try:
                kernel32.CancelIoEx(self.handle, None)
            except Exception as e:
                logger.debug("CancelIoEx error: %s", e)
            kernel32.CloseHandle(self.handle)
            self.handle = None
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
        logger.info("Named Pipe client closed.")
