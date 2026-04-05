"""Service registry — lightweight dependency injection container."""

from __future__ import annotations

from typing import Any, Callable, TypeVar

T = TypeVar("T")


class ServiceRegistry:
    """Simple service locator mapping interface types to implementations."""

    def __init__(self) -> None:
        self._services: dict[type, Any] = {}
        self._factories: dict[type, Callable[..., Any]] = {}

    def register(self, interface: type[T], implementation: T) -> None:
        """Register a concrete instance for an interface type."""
        self._services[interface] = implementation

    def get(self, interface: type[T]) -> T:
        """Retrieve the implementation for an interface type."""
        if interface in self._services:
            return self._services[interface]  # type: ignore[return-value]
        if interface in self._factories:
            instance = self._factories[interface]()
            self._services[interface] = instance
            return instance  # type: ignore[return-value]
        raise LookupError(f"No implementation registered for {interface.__name__}")

    def register_factory(self, interface: type[T], factory: Callable[..., T]) -> None:
        """Register a lazy factory that creates the implementation on first access."""
        self._factories[interface] = factory

    def has(self, interface: type) -> bool:
        """Check if an implementation is registered for an interface."""
        return interface in self._services or interface in self._factories
