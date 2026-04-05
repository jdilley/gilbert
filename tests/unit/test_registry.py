"""Tests for ServiceRegistry."""

import pytest

from gilbert.core.registry import ServiceRegistry


class MyInterface:
    pass


class MyImplementation(MyInterface):
    pass


class AnotherInterface:
    pass


def test_register_and_get() -> None:
    registry = ServiceRegistry()
    impl = MyImplementation()
    registry.register(MyInterface, impl)
    assert registry.get(MyInterface) is impl


def test_get_unregistered_raises() -> None:
    registry = ServiceRegistry()
    with pytest.raises(LookupError, match="MyInterface"):
        registry.get(MyInterface)


def test_has() -> None:
    registry = ServiceRegistry()
    assert not registry.has(MyInterface)
    registry.register(MyInterface, MyImplementation())
    assert registry.has(MyInterface)


def test_register_factory() -> None:
    registry = ServiceRegistry()
    call_count = 0

    def factory() -> MyImplementation:
        nonlocal call_count
        call_count += 1
        return MyImplementation()

    registry.register_factory(MyInterface, factory)
    assert registry.has(MyInterface)

    instance1 = registry.get(MyInterface)
    instance2 = registry.get(MyInterface)
    assert instance1 is instance2  # cached after first call
    assert call_count == 1


def test_register_overrides_factory() -> None:
    registry = ServiceRegistry()
    registry.register_factory(MyInterface, MyImplementation)
    direct = MyImplementation()
    registry.register(MyInterface, direct)
    assert registry.get(MyInterface) is direct
