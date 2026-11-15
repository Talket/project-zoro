"""Asynchronous in-memory publish/subscribe event bus for internal engine coordination."""

from __future__ import annotations

import asyncio
from collections import defaultdict
import fnmatch
import logging
from typing import Any, Callable, Coroutine, Dict, List, Set

logger = logging.getLogger(__name__)

EventHandler = Callable[[str, Dict[str, Any]], Coroutine[Any, Any, None]]


class AsyncEventBus:
    """Thread-safe, decoupled asynchronous event dispatcher."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, Set[EventHandler]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, pattern: str, handler: EventHandler) -> None:
        """Subscribe an async handler to an exact topic or wildcard pattern (e.g., 'system.*')."""
        async with self._lock:
            self._subscribers[pattern].add(handler)
            logger.debug("Subscribed %s to pattern '%s'", getattr(handler, "__name__", "handler"), pattern)

    async def unsubscribe(self, pattern: str, handler: EventHandler) -> None:
        """Remove a subscriber from a pattern."""
        async with self._lock:
            if pattern in self._subscribers:
                self._subscribers[pattern].discard(handler)
                if not self._subscribers[pattern]:
                    del self._subscribers[pattern]

    async def publish(self, topic: str, data: Dict[str, Any]) -> None:
        """
        Publish an event to all matching subscribers.
        Executes handlers concurrently with complete error isolation.
        """
        matched_handlers: Set[EventHandler] = set()

        async with self._lock:
            for pattern, handlers in self._subscribers.items():
                if fnmatch.fnmatch(topic, pattern):
                    matched_handlers.update(handlers)

        if not matched_handlers:
            return

        tasks = []
        for handler in matched_handlers:
            tasks.append(self._safe_execute(handler, topic, data))

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_execute(self, handler: EventHandler, topic: str, data: Dict[str, Any]) -> None:
        """Execute a single handler catching any unexpected exceptions."""
        try:
            await handler(topic, data)
        except Exception as e:
            logger.error("Exception in event handler %s for topic '%s': %s",
                         getattr(handler, "__name__", "handler"), topic, e, exc_info=True)
