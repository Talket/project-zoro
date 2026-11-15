"""Wire protocol and JSON-RPC 2.0 framing for Windows Named Pipe IPC."""

from __future__ import annotations

import json
import struct
from typing import Any, Dict, Optional, Tuple, Union
from pydantic import BaseModel, Field

# Length prefix is a 4-byte big-endian unsigned integer (uint32)
LENGTH_HEADER_STRUCT = struct.Struct(">I")
HEADER_SIZE = LENGTH_HEADER_STRUCT.size
MAX_PAYLOAD_SIZE = 16 * 1024 * 1024  # 16 MiB


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Union[int, str]
    method: str
    params: Dict[str, Any] = Field(default_factory=dict)


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[Union[int, str]] = None
    result: Optional[Any] = None
    error: Optional[Dict[str, Any]] = None


class JsonRpcNotification(BaseModel):
    jsonrpc: str = "2.0"
    method: str
    params: Dict[str, Any] = Field(default_factory=dict)


def encode_message(payload: Dict[str, Any]) -> bytes:
    """Serialize dictionary to UTF-8 JSON and prepend 4-byte length prefix."""
    json_bytes = json.dumps(payload).encode("utf-8")
    payload_len = len(json_bytes)
    if payload_len > MAX_PAYLOAD_SIZE:
        raise ValueError(f"Payload size {payload_len} exceeds maximum allowed {MAX_PAYLOAD_SIZE}")
    header = LENGTH_HEADER_STRUCT.pack(payload_len)
    return header + json_bytes


def decode_message(buffer: bytes) -> Tuple[Optional[Dict[str, Any]], bytes]:
    """
    Attempt to decode one framed message from the buffer.
    Returns (decoded_dict, remaining_buffer). If incomplete, returns (None, buffer).
    """
    if len(buffer) < HEADER_SIZE:
        return None, buffer

    (payload_len,) = LENGTH_HEADER_STRUCT.unpack_from(buffer, 0)
    if payload_len > MAX_PAYLOAD_SIZE:
        raise ValueError(f"Corrupted frame: payload length {payload_len} exceeds limit.")

    total_msg_len = HEADER_SIZE + payload_len
    if len(buffer) < total_msg_len:
        return None, buffer

    json_bytes = buffer[HEADER_SIZE:total_msg_len]
    remaining = buffer[total_msg_len:]

    try:
        decoded = json.loads(json_bytes.decode("utf-8"))
        return decoded, remaining
    except Exception as e:
        raise ValueError(f"Failed to parse JSON payload: {e}") from e
