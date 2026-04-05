"""Tests for InMemoryEventBus."""

import pytest

from gilbert.core.events import InMemoryEventBus
from gilbert.interfaces.events import Event


@pytest.fixture
def bus() -> InMemoryEventBus:
    return InMemoryEventBus()


async def test_subscribe_and_publish(bus: InMemoryEventBus) -> None:
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe("test.event", handler)
    event = Event(event_type="test.event", data={"key": "value"})
    await bus.publish(event)

    assert len(received) == 1
    assert received[0].data == {"key": "value"}


async def test_unsubscribe(bus: InMemoryEventBus) -> None:
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    unsubscribe = bus.subscribe("test.event", handler)
    await bus.publish(Event(event_type="test.event"))
    assert len(received) == 1

    unsubscribe()
    await bus.publish(Event(event_type="test.event"))
    assert len(received) == 1  # no new events


async def test_no_cross_talk(bus: InMemoryEventBus) -> None:
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe("type.a", handler)
    await bus.publish(Event(event_type="type.b"))

    assert len(received) == 0


async def test_pattern_subscribe(bus: InMemoryEventBus) -> None:
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    bus.subscribe_pattern("device.*", handler)
    await bus.publish(Event(event_type="device.state_changed"))
    await bus.publish(Event(event_type="device.added"))
    await bus.publish(Event(event_type="automation.triggered"))

    assert len(received) == 2


async def test_pattern_unsubscribe(bus: InMemoryEventBus) -> None:
    received: list[Event] = []

    async def handler(event: Event) -> None:
        received.append(event)

    unsubscribe = bus.subscribe_pattern("device.*", handler)
    await bus.publish(Event(event_type="device.added"))
    assert len(received) == 1

    unsubscribe()
    await bus.publish(Event(event_type="device.added"))
    assert len(received) == 1


async def test_multiple_subscribers(bus: InMemoryEventBus) -> None:
    results: list[str] = []

    async def handler_a(event: Event) -> None:
        results.append("a")

    async def handler_b(event: Event) -> None:
        results.append("b")

    bus.subscribe("test.event", handler_a)
    bus.subscribe("test.event", handler_b)
    await bus.publish(Event(event_type="test.event"))

    assert sorted(results) == ["a", "b"]


async def test_handler_error_does_not_crash_bus(bus: InMemoryEventBus) -> None:
    received: list[Event] = []

    async def bad_handler(event: Event) -> None:
        raise ValueError("boom")

    async def good_handler(event: Event) -> None:
        received.append(event)

    bus.subscribe("test.event", bad_handler)
    bus.subscribe("test.event", good_handler)
    await bus.publish(Event(event_type="test.event"))

    assert len(received) == 1


async def test_publish_with_no_subscribers(bus: InMemoryEventBus) -> None:
    # Should not raise
    await bus.publish(Event(event_type="nobody.listening"))
