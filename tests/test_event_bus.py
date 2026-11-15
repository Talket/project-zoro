"""Tests for AsyncEventBus publish/subscribe and error isolation."""

import asyncio
import pytest
from zoro.core.event_bus import AsyncEventBus


@pytest.mark.asyncio
async def test_event_bus_publish_subscribe():
    bus = AsyncEventBus()
    received = []

    async def handler(topic: str, data: dict):
        received.append((topic, data))

    await bus.subscribe("test.topic", handler)
    await bus.publish("test.topic", {"msg": "hello"})

    assert len(received) == 1
    assert received[0] == ("test.topic", {"msg": "hello"})

    # Test unsubscribe
    await bus.unsubscribe("test.topic", handler)
    await bus.publish("test.topic", {"msg": "hello again"})
    assert len(received) == 1


@pytest.mark.asyncio
async def test_event_bus_wildcard_subscription():
    bus = AsyncEventBus()
    received = []

    async def wildcard_handler(topic: str, data: dict):
        received.append((topic, data))

    await bus.subscribe("system.*", wildcard_handler)
    await bus.publish("system.health", {"status": "ok"})
    await bus.publish("system.alert", {"level": "warn"})
    await bus.publish("user.login", {"user": "admin"})

    assert len(received) == 2
    assert received[0] == ("system.health", {"status": "ok"})
    assert received[1] == ("system.alert", {"level": "warn"})


@pytest.mark.asyncio
async def test_event_bus_handler_exception_isolation():
    bus = AsyncEventBus()
    received = []

    async def faulty_handler(topic: str, data: dict):
        raise ValueError("Simulated fault")

    async def good_handler(topic: str, data: dict):
        received.append((topic, data))

    await bus.subscribe("test.fault", faulty_handler)
    await bus.subscribe("test.fault", good_handler)

    # Faulty handler should not crash publisher or stop good handler
    await bus.publish("test.fault", {"key": "value"})
    assert len(received) == 1
    assert received[0] == ("test.fault", {"key": "value"})
