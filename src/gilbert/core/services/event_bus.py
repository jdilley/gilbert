"""Event bus service — wraps EventBus as a discoverable service."""

from gilbert.interfaces.events import EventBus
from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver


class EventBusService(Service):
    """Exposes an EventBus as a service with event_bus capability."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="event_bus",
            capabilities=frozenset({"event_bus", "pub_sub"}),
        )

    @property
    def bus(self) -> EventBus:
        return self._bus
