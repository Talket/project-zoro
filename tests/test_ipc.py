"""Tests for IPC wire framing, Windows Named Pipe server/client, and reconnection."""

import asyncio
import os
import time
import pytest
from zoro.ipc.pipe_client import NamedPipeClient
from zoro.ipc.pipe_server import NamedPipeServer
from zoro.ipc.protocol import (
    decode_message,
    encode_message,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    MAX_PAYLOAD_SIZE,
)


def test_frame_encode_decode_roundtrip():
    payload = {"jsonrpc": "2.0", "id": 1, "method": "test.ping", "params": {"data": 123}}
    encoded = encode_message(payload)
    assert len(encoded) > 4

    decoded, remaining = decode_message(encoded)
    assert decoded == payload
    assert remaining == b""


def test_partial_buffer_handling():
    payload = {"jsonrpc": "2.0", "id": 1, "method": "test.ping"}
    encoded = encode_message(payload)

    # Incomplete header
    decoded, remaining = decode_message(encoded[:2])
    assert decoded is None
    assert remaining == encoded[:2]

    # Incomplete body
    decoded, remaining = decode_message(encoded[: len(encoded) - 2])
    assert decoded is None


def test_oversized_payload_rejected():
    large_payload = {"data": "x" * (MAX_PAYLOAD_SIZE + 10)}
    with pytest.raises(ValueError):
        encode_message(large_payload)


@pytest.mark.asyncio
async def test_named_pipe_roundtrip_and_reconnection():
    """
    Real Named Pipe integration test:
    1. Start server and client.
    2. Request-response roundtrip.
    3. Terminate server -> client detects disconnect.
    4. Restart server.
    5. Client reconnects -> exchange second message.
    """
    if os.name != "nt":
        pytest.skip("Named Pipe tests require Windows NT.")

    pipe_name = r"\\.\pipe\zoro-reconnect-test"
    loop = asyncio.get_running_loop()

    # 1. Start Server 1
    server1 = NamedPipeServer(pipe_name=pipe_name)
    async def handle_ping(params):
        return {"pong": params.get("msg", "default")}
    server1.register_handler("test.ping", handle_ping)
    server1.start(loop=loop)
    time.sleep(0.1)

    # 2. Connect Client
    client = NamedPipeClient(pipe_name=pipe_name)
    connected = client.connect()
    assert connected is True
    assert client.is_connected() is True

    # 3. Request-Response Message 1 (run on thread to avoid blocking asyncio event loop)
    res1 = await asyncio.to_thread(client.send_request, "test.ping", {"msg": "hello_v1"}, timeout=3.0)
    assert res1 == {"pong": "hello_v1"}

    # 4. Terminate Server 1
    server1.stop()
    time.sleep(0.2)

    # 5. Verify client detects disconnection on next attempt
    try:
        await asyncio.to_thread(client.send_request, "test.ping", {"msg": "fail_msg"}, timeout=1.0)
    except (ConnectionError, RuntimeError, TimeoutError):
        pass  # Expected connection drop
    assert client.is_connected() is False

    # 6. Restart Server 2 on the same pipe name
    server2 = NamedPipeServer(pipe_name=pipe_name)
    server2.register_handler("test.ping", handle_ping)
    server2.start(loop=loop)
    time.sleep(0.1)

    # 7. Reconnect client
    reconnected = client.connect()
    assert reconnected is True
    assert client.is_connected() is True

    # 8. Request-Response Message 2
    res2 = await asyncio.to_thread(client.send_request, "test.ping", {"msg": "hello_v2"}, timeout=3.0)
    assert res2 == {"pong": "hello_v2"}

    # Cleanup
    client.close()
    server2.stop()


@pytest.mark.asyncio
async def test_unsolicited_notification_broadcast():
    """Verify server can broadcast unsolicited notifications to client."""
    if os.name != "nt":
        pytest.skip("Named Pipe tests require Windows NT.")

    pipe_name = r"\\.\pipe\zoro-notif-test"
    loop = asyncio.get_running_loop()

    server = NamedPipeServer(pipe_name=pipe_name)
    server.start(loop=loop)
    time.sleep(0.1)

    client = NamedPipeClient(pipe_name=pipe_name)
    received_notifs = []

    def on_notif(method, params):
        received_notifs.append((method, params))

    client.register_notification_handler("system.alert", on_notif)
    assert client.connect() is True
    time.sleep(0.1)

    # Broadcast notification from server
    server.broadcast_notification("system.alert", {"level": "warning", "code": 101})
    time.sleep(0.2)

    assert len(received_notifs) == 1
    assert received_notifs[0][0] == "system.alert"
    assert received_notifs[0][1]["level"] == "warning"

    client.close()
    server.stop()
