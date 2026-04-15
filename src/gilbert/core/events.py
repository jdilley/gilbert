"""In-memory event bus implementation."""

import asyncio
import fnmatch
import logging
from collections.abc import Callable

from gilbert.interfaces.events import Event, EventBus, EventHandler

logger = logging.getLogger(__name__)


class InMemoryEventBus(EventBus):
    """In-process async event bus using asyncio."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._pattern_subscribers: list[tuple[str, EventHandler]] = []

    def subscribe(self, event_type: str, handler: EventHandler) -> Callable[[], None]:
        self._subscribers.setdefault(event_type, []).append(handler)

        def unsubscribe() -> None:
            self._subscribers[event_type].remove(handler)

        return unsubscribe

    def subscribe_pattern(self, pattern: str, handler: EventHandler) -> Callable[[], None]:
        entry = (pattern, handler)
        self._pattern_subscribers.append(entry)

        def unsubscribe() -> None:
            self._pattern_subscribers.remove(entry)

        return unsubscribe

    async def publish(self, event: Event) -> None:
        handlers: list[EventHandler] = []
        handlers.extend(self._subscribers.get(event.event_type, []))
        for pattern, handler in self._pattern_subscribers:
            if fnmatch.fnmatch(event.event_type, pattern):
                handlers.append(handler)

        if not handlers:
            return

        results = await asyncio.gather(*(h(event) for h in handlers), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.error("Event handler error for %s: %s", event.event_type, result)
