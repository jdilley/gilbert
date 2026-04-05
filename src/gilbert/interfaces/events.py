"""Event system interface — pub/sub for decoupled communication."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable


@dataclass(frozen=True)
class Event:
    """An immutable event that flows through the event bus."""

    event_type: str
    data: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)


EventHandler = Callable[[Event], Awaitable[None]]


class EventBus(ABC):
    """Publish-subscribe event system."""

    @abstractmethod
    def subscribe(self, event_type: str, handler: EventHandler) -> Callable[[], None]:
        """Subscribe to events of a specific type. Returns an unsubscribe callable."""
        ...

    @abstractmethod
    async def publish(self, event: Event) -> None:
        """Publish an event to all matching subscribers."""
        ...

    @abstractmethod
    def subscribe_pattern(self, pattern: str, handler: EventHandler) -> Callable[[], None]:
        """Subscribe with a glob pattern (e.g., 'device.*'). Returns an unsubscribe callable."""
        ...
