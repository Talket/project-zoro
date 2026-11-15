"""Windows Named Pipe IPC Server providing secure local JSON-RPC 2.0 communication."""

from __future__ import annotations

import asyncio
import ctypes
from ctypes import wintypes
import logging
import os
import threading
from typing import Any, Callable, Coroutine, Dict, Optional, Tuple

from zoro.config.settings import ZoroSettings, get_settings
from zoro.ipc.protocol import (
    decode_message,
    encode_message,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
)

logger = logging.getLogger(__name__)

# Win32 Constants
FILE_FLAG_OVERLAPPED = 0x40000000
PIPE_ACCESS_DUPLEX = 0x00000003
PIPE_TYPE_BYTE = 0x00000000
PIPE_READMODE_BYTE = 0x00000000
PIPE_WAIT = 0x00000000
PIPE_UNLIMITED_INSTANCES = 255
BUFFER_SIZE = 65536
INVALID_HANDLE_VALUE = -1

ERROR_IO_PENDING = 997
ERROR_PIPE_CONNECTED = 535
ERROR_BROKEN_PIPE = 109
ERROR_NO_DATA = 232
ERROR_OPERATION_ABORTED = 995
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102

HandlerFunc = Callable[[Dict[str, Any]], Coroutine[Any, Any, Any]]


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
    k32.CreateNamedPipeW.restype = wintypes.HANDLE
    k32.CreateNamedPipeW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID
    ]
    k32.ConnectNamedPipe.restype = wintypes.BOOL
    k32.ConnectNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    k32.DisconnectNamedPipe.restype = wintypes.BOOL
    k32.DisconnectNamedPipe.argtypes = [wintypes.HANDLE]
    k32.ReadFile.restype = wintypes.BOOL
    k32.ReadFile.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p
    ]
    k32.WriteFile.restype = wintypes.BOOL
    k32.WriteFile.argtypes = [
        wintypes.HANDLE, ctypes.c_char_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p
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


class NamedPipeServer:
    """Windows Named Pipe server handling framed JSON-RPC 2.0 commands."""

    def __init__(self, pipe_name: Optional[str] = None, settings: Optional[ZoroSettings] = None) -> None:
        self.settings = settings or get_settings()
        self.pipe_name = pipe_name or self.settings.pipe_name
        self._handlers: Dict[str, HandlerFunc] = {}
        self._is_running = False
        self._current_pipe_handle = None
        self._server_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def register_handler(self, method: str, handler: HandlerFunc) -> None:
        """Register an async handler for a specific JSON-RPC method."""
        self._handlers[method] = handler

    def start(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Start the Named Pipe server listening thread."""
        if self._is_running:
            return
        try:
            self._loop = loop or asyncio.get_running_loop()
        except RuntimeError:
            self._loop = loop
        self._is_running = True
        self._server_thread = threading.Thread(target=self._run_server, name="zoro-named-pipe-server", daemon=True)
        self._server_thread.start()
        logger.info("Named Pipe server started on %s", self.pipe_name)

    def _run_server(self) -> None:
        """Internal server loop managing Windows Named Pipe lifecycle."""
        if os.name != "nt":
            logger.warning("Named pipes only supported on Windows.")
            return

        kernel32 = _get_kernel32()

        while self._is_running:
            h_pipe = kernel32.CreateNamedPipeW(
                self.pipe_name,
                PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                PIPE_UNLIMITED_INSTANCES,
                BUFFER_SIZE,
                BUFFER_SIZE,
                0,
                None,
            )

            if h_pipe in (INVALID_HANDLE_VALUE, 0, 0xFFFFFFFFFFFFFFFF, None):
                err = ctypes.get_last_error()
                logger.error("CreateNamedPipe failed with error %d", err)
                break

            with self._lock:
                self._current_pipe_handle = h_pipe

            logger.debug("Waiting for IPC client connection...")
            connected = self._wait_for_client(kernel32, h_pipe)
            if not connected or not self._is_running:
                kernel32.CloseHandle(h_pipe)
                with self._lock:
                    if self._current_pipe_handle == h_pipe:
                        self._current_pipe_handle = None
                continue

            logger.info("IPC client connected to %s", self.pipe_name)
            self._handle_client(kernel32, h_pipe)

            # Disconnect and cleanup instance
            kernel32.DisconnectNamedPipe(h_pipe)
            kernel32.CloseHandle(h_pipe)
            with self._lock:
                if self._current_pipe_handle == h_pipe:
                    self._current_pipe_handle = None

    def _wait_for_client(self, kernel32: ctypes.WinDLL, h_pipe: wintypes.HANDLE) -> bool:
        """Wait asynchronously for a client to connect."""
        ov = OVERLAPPED()
        ov.hEvent = kernel32.CreateEventW(None, True, False, None)
        try:
            ret = kernel32.ConnectNamedPipe(h_pipe, ctypes.byref(ov))
            err = ctypes.get_last_error()
            logger.debug("ConnectNamedPipe returned %s, err=%d", ret, err)
            if ret or err == ERROR_PIPE_CONNECTED:
                return True
            if err == ERROR_IO_PENDING:
                while self._is_running:
                    wait_res = kernel32.WaitForSingleObject(ov.hEvent, 200)
                    if wait_res == WAIT_OBJECT_0:
                        return True
                    elif wait_res == WAIT_TIMEOUT:
                        continue
                    else:
                        break
                kernel32.CancelIoEx(h_pipe, ctypes.byref(ov))
                return False
            return False
        finally:
            kernel32.CloseHandle(ov.hEvent)

    def _handle_client(self, kernel32: ctypes.WinDLL, h_pipe: wintypes.HANDLE) -> None:
        """Read and process messages from the connected client asynchronously."""
        read_buf = ctypes.create_string_buffer(BUFFER_SIZE)
        accumulator = b""

        while self._is_running:
            success, n_bytes = self._overlapped_read(kernel32, h_pipe, read_buf, BUFFER_SIZE, timeout_ms=250)
            if not success:
                if n_bytes == -1:  # Disconnection or broken pipe
                    logger.debug("Client disconnected or pipe broken.")
                    break
                continue  # Timed out, check self._is_running and retry

            accumulator += read_buf.raw[:n_bytes]

            while accumulator:
                try:
                    msg, accumulator = decode_message(accumulator)
                except ValueError as e:
                    logger.error("IPC framing error: %s", e)
                    accumulator = b""
                    break

                if msg is None:
                    break

                self._dispatch_message(h_pipe, msg)

    def _overlapped_read(
        self, kernel32: ctypes.WinDLL, h_pipe: wintypes.HANDLE, buf: Any, size: int, timeout_ms: int = 250
    ) -> Tuple[bool, int]:
        """Perform an overlapped read with a timeout."""
        ov = OVERLAPPED()
        ov.hEvent = kernel32.CreateEventW(None, True, False, None)
        try:
            bytes_read = wintypes.DWORD()
            ret = kernel32.ReadFile(h_pipe, buf, size, None, ctypes.byref(ov))
            err = ctypes.get_last_error()
            if not ret:
                if err == ERROR_IO_PENDING:
                    wait_res = kernel32.WaitForSingleObject(ov.hEvent, timeout_ms)
                    if wait_res == WAIT_OBJECT_0:
                        transferred = wintypes.DWORD()
                        if kernel32.GetOverlappedResult(h_pipe, ctypes.byref(ov), ctypes.byref(transferred), False):
                            return True, transferred.value
                        return False, -1
                    elif wait_res == WAIT_TIMEOUT:
                        kernel32.CancelIoEx(h_pipe, ctypes.byref(ov))
                        return False, 0
                    else:
                        return False, -1
                elif err in (ERROR_BROKEN_PIPE, ERROR_NO_DATA, ERROR_OPERATION_ABORTED):
                    return False, -1
                else:
                    return False, -1
            else:
                transferred = wintypes.DWORD()
                kernel32.GetOverlappedResult(h_pipe, ctypes.byref(ov), ctypes.byref(transferred), False)
                return True, transferred.value
        finally:
            kernel32.CloseHandle(ov.hEvent)

    def _dispatch_message(self, h_pipe: wintypes.HANDLE, msg: Dict[str, Any]) -> None:
        """Route JSON-RPC request to async handler and send response."""
        req_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params", {})

        if not method or req_id is None:
            return

        handler = self._handlers.get(method)
        if not handler:
            response = JsonRpcResponse(
                id=req_id,
                error={"code": -32601, "message": f"Method '{method}' not found."},
            )
            self._send_payload(h_pipe, response.model_dump())
            return

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._execute_and_respond(h_pipe, req_id, handler, params), self._loop
            )
        else:
            # Fallback inline execution
            try:
                loop = asyncio.new_event_loop()
                result = loop.run_until_complete(handler(params))
                loop.close()
                response = JsonRpcResponse(id=req_id, result=result)
            except Exception as e:
                response = JsonRpcResponse(id=req_id, error={"code": -32000, "message": str(e)})
            self._send_payload(h_pipe, response.model_dump())

    async def _execute_and_respond(
        self, h_pipe: wintypes.HANDLE, req_id: Any, handler: HandlerFunc, params: Dict[str, Any]
    ) -> None:
        """Execute async handler and reply to the pipe."""
        try:
            result = await handler(params)
            response = JsonRpcResponse(id=req_id, result=result)
        except Exception as e:
            logger.error("Handler error for req %s: %s", req_id, e, exc_info=True)
            response = JsonRpcResponse(id=req_id, error={"code": -32000, "message": str(e)})

        self._send_payload(h_pipe, response.model_dump())

    def _send_payload(self, h_pipe: wintypes.HANDLE, payload: Dict[str, Any]) -> None:
        """Send framed payload to pipe handle asynchronously."""
        if not self._is_running:
            return
        try:
            data = encode_message(payload)
            kernel32 = _get_kernel32()
            ov = OVERLAPPED()
            ov.hEvent = kernel32.CreateEventW(None, True, False, None)
            try:
                ret = kernel32.WriteFile(h_pipe, data, len(data), None, ctypes.byref(ov))
                err = ctypes.get_last_error()
                if not ret and err == ERROR_IO_PENDING:
                    wait_res = kernel32.WaitForSingleObject(ov.hEvent, 3000)
                    if wait_res == WAIT_OBJECT_0:
                        written = wintypes.DWORD()
                        kernel32.GetOverlappedResult(h_pipe, ctypes.byref(ov), ctypes.byref(written), False)
                    else:
                        kernel32.CancelIoEx(h_pipe, ctypes.byref(ov))
            finally:
                kernel32.CloseHandle(ov.hEvent)
        except Exception as e:
            logger.error("Failed to write to pipe: %s", e)

    def broadcast_notification(self, method: str, params: Dict[str, Any]) -> None:
        """Send an unsolicited notification to the currently connected client."""
        with self._lock:
            h_pipe = self._current_pipe_handle

        if h_pipe:
            notif = JsonRpcNotification(method=method, params=params)
            self._send_payload(h_pipe, notif.model_dump())

    def stop(self) -> None:
        """Stop the Named Pipe server cleanly."""
        self._is_running = False
        with self._lock:
            h_pipe = self._current_pipe_handle

        if os.name == "nt" and h_pipe:
            kernel32 = _get_kernel32()
            try:
                kernel32.CancelIoEx(h_pipe, None)
            except Exception as e:
                logger.debug("CancelIoEx error: %s", e)
            kernel32.CloseHandle(h_pipe)
            with self._lock:
                self._current_pipe_handle = None

        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=1.0)

        logger.info("Named Pipe server stopped.")
