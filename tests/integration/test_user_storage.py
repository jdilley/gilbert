"""Integration tests for StorageUserBackend — hits a real test SQLite database."""

import pytest

from gilbert.storage.sqlite import SQLiteStorage
from gilbert.storage.user_storage import StorageUserBackend


@pytest.fixture
async def user_backend(sqlite_storage: SQLiteStorage) -> StorageUserBackend:
    backend = StorageUserBackend(sqlite_storage)
    await backend.ensure_indexes()
    return backend


# --- User CRUD ---


async def test_create_and_get_user(user_backend: StorageUserBackend) -> None:
    user = await user_backend.create_user(
        "u1",
        {
            "username": "testuser",
            "email": "test@example.com",
            "display_name": "Test User",
        },
    )
    assert user["_id"] == "u1"
    assert user["email"] == "test@example.com"

    fetched = await user_backend.get_user("u1")
    assert fetched is not None
    assert fetched["email"] == "test@example.com"
    assert fetched["is_root"] is False
    assert fetched["roles"] == []


async def test_get_user_not_found(user_backend: StorageUserBackend) -> None:
    assert await user_backend.get_user("nonexistent") is None


async def test_get_user_by_username(user_backend: StorageUserBackend) -> None:
    await user_backend.create_user(
        "u1", {"username": "alice", "email": "alice@example.com", "display_name": "Alice"}
    )

    user = await user_backend.get_user_by_username("alice")
    assert user is not None
    assert user["_id"] == "u1"

    # Case-insensitive
    user2 = await user_backend.get_user_by_username("Alice")
    assert user2 is not None
    assert user2["_id"] == "u1"


async def test_get_user_by_username_not_found(user_backend: StorageUserBackend) -> None:
    assert await user_backend.get_user_by_username("nobody") is None


async def test_get_user_by_email(user_backend: StorageUserBackend) -> None:
    await user_backend.create_user(
        "u1", {"username": "alice", "email": "alice@example.com", "display_name": "Alice"}
    )
    await user_backend.create_user(
        "u2", {"username": "bob", "email": "bob@example.com", "display_name": "Bob"}
    )

    user = await user_backend.get_user_by_email("bob@example.com")
    assert user is not None
    assert user["_id"] == "u2"


async def test_get_user_by_email_not_found(user_backend: StorageUserBackend) -> None:
    assert await user_backend.get_user_by_email("nobody@example.com") is None


async def test_update_user(user_backend: StorageUserBackend) -> None:
    await user_backend.create_user("u1", {"email": "test@example.com", "display_name": "Old"})
    await user_backend.update_user("u1", {"display_name": "New"})

    user = await user_backend.get_user("u1")
    assert user is not None
    assert user["display_name"] == "New"
    assert user["email"] == "test@example.com"  # Unchanged fields preserved


async def test_update_user_not_found(user_backend: StorageUserBackend) -> None:
    with pytest.raises(KeyError):
        await user_backend.update_user("nonexistent", {"display_name": "X"})


async def test_delete_user(user_backend: StorageUserBackend) -> None:
    await user_backend.create_user(
        "u1", {"username": "test", "email": "test@example.com", "display_name": "Test"}
    )
    await user_backend.delete_user("u1")
    assert await user_backend.get_user("u1") is None


async def test_list_users(user_backend: StorageUserBackend) -> None:
    await user_backend.create_user(
        "u1", {"username": "alice", "email": "alice@example.com", "display_name": "Alice"}
    )
    await user_backend.create_user(
        "u2", {"username": "bob", "email": "bob@example.com", "display_name": "Bob"}
    )

    users = await user_backend.list_users()
    assert len(users) == 2
    emails = {u["email"] for u in users}
    assert emails == {"alice@example.com", "bob@example.com"}


async def test_list_users_with_limit(user_backend: StorageUserBackend) -> None:
    for i in range(5):
        await user_backend.create_user(
            f"u{i}", {"username": f"u{i}", "email": f"u{i}@example.com", "display_name": f"U{i}"}
        )

    users = await user_backend.list_users(limit=2)
    assert len(users) == 2


# --- Provider links ---


async def test_add_and_lookup_provider_link(user_backend: StorageUserBackend) -> None:
    await user_backend.create_user(
        "u1", {"username": "test", "email": "test@example.com", "display_name": "Test"}
    )

    # Store the provider user.
    await user_backend.put_provider_user(
        "google",
        "g123",
        {
            "local_user_id": "u1",
            "email": "test@example.com",
        },
    )

    await user_backend.add_provider_link("u1", "google", "g123")

    # Verify the link is on the user entity.
    user = await user_backend.get_user("u1")
    assert user is not None
    assert len(user["provider_links"]) == 1
    assert user["provider_links"][0]["provider_type"] == "google"

    # Look up by provider link.
    found = await user_backend.get_user_by_provider_link("google", "g123")
    assert found is not None
    assert found["_id"] == "u1"


async def test_remove_provider_link(user_backend: StorageUserBackend) -> None:
    await user_backend.create_user(
        "u1", {"username": "test", "email": "test@example.com", "display_name": "Test"}
    )
    await user_backend.add_provider_link("u1", "google", "g123")
    await user_backend.remove_provider_link("u1", "google")

    user = await user_backend.get_user("u1")
    assert user is not None
    assert user["provider_links"] == []


async def test_add_provider_link_replaces_same_type(user_backend: StorageUserBackend) -> None:
    await user_backend.create_user(
        "u1", {"username": "test", "email": "test@example.com", "display_name": "Test"}
    )
    await user_backend.add_provider_link("u1", "google", "g123")
    await user_backend.add_provider_link("u1", "google", "g456")

    user = await user_backend.get_user("u1")
    assert user is not None
    assert len(user["provider_links"]) == 1
    assert user["provider_links"][0]["provider_user_id"] == "g456"


# --- Roles ---


async def test_set_and_get_roles(user_backend: StorageUserBackend) -> None:
    await user_backend.create_user(
        "u1", {"username": "test", "email": "test@example.com", "display_name": "Test"}
    )
    await user_backend.set_roles("u1", {"admin", "user"})

    roles = await user_backend.get_roles("u1")
    assert roles == {"admin", "user"}


async def test_get_roles_not_found(user_backend: StorageUserBackend) -> None:
    with pytest.raises(KeyError):
        await user_backend.get_roles("nonexistent")


# --- Provider users (remote cache) ---


async def test_put_and_get_provider_user(user_backend: StorageUserBackend) -> None:
    await user_backend.put_provider_user(
        "google",
        "g123",
        {
            "email": "test@example.com",
            "display_name": "Test",
            "raw": {"orgUnit": "/Engineering"},
        },
    )

    pu = await user_backend.get_provider_user("google", "g123")
    assert pu is not None
    assert pu["email"] == "test@example.com"
    assert pu["provider_type"] == "google"
    assert pu["provider_user_id"] == "g123"
    assert "synced_at" in pu


async def test_get_provider_user_not_found(user_backend: StorageUserBackend) -> None:
    assert await user_backend.get_provider_user("google", "nonexistent") is None


async def test_list_provider_users(user_backend: StorageUserBackend) -> None:
    await user_backend.put_provider_user("google", "g1", {"email": "a@example.com"})
    await user_backend.put_provider_user("google", "g2", {"email": "b@example.com"})
    await user_backend.put_provider_user("zoho", "z1", {"email": "c@example.com"})

    google_users = await user_backend.list_provider_users("google")
    assert len(google_users) == 2

    zoho_users = await user_backend.list_provider_users("zoho")
    assert len(zoho_users) == 1
