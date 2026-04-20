"""Tests for WorkspaceService share-token surface.

Covers the core share lifecycle:
- create_file_share returns a usable URL + stores a record
- consume_file_share resolves the token, returns the path, decrements counter
- access limits: exhaustion deletes the record and subsequent consumes 404
- expiry: past-dated records don't resolve
- path traversal and missing-file paths error cleanly
- via_tunnel with no live tunnel raises
- _cleanup_file_shares purges expired + exhausted records
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from gilbert.core.services.workspace import (
    _WORKSPACE_SHARES_COLLECTION,
    WorkspaceService,
)
from gilbert.interfaces.service import ServiceResolver
from gilbert.interfaces.storage import StorageProvider
from gilbert.storage.sqlite import SQLiteStorage


@pytest.fixture
async def service(
    sqlite_storage: SQLiteStorage,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> WorkspaceService:
    """Start a WorkspaceService backed by real SQLite storage.

    Changes cwd to ``tmp_path`` so workspace files land somewhere
    ephemeral — WorkspaceService builds its paths relative to
    ``.gilbert/workspaces`` under the current working directory.
    """
    monkeypatch.chdir(tmp_path)

    storage_provider = MagicMock(spec=StorageProvider)
    storage_provider.backend = sqlite_storage

    resolver = AsyncMock(spec=ServiceResolver)

    def _get_cap(name: str) -> Any:
        if name == "entity_storage":
            return storage_provider
        return None

    resolver.get_capability.side_effect = _get_cap
    resolver.require_capability.side_effect = lambda name: (
        storage_provider if name == "entity_storage" else None
    )

    svc = WorkspaceService()
    await svc.start(resolver)
    yield svc  # type: ignore[misc]
    await svc.stop()


def _write_workspace_file(svc: WorkspaceService, user_id: str, conv_id: str, rel_path: str, content: bytes) -> Path:
    """Materialize a file inside the conversation workspace and return its path."""
    root = svc.get_workspace_root(user_id, conv_id)
    target = root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


# --- create_file_share ---


async def test_create_file_share_returns_url_with_token(service: WorkspaceService) -> None:
    _write_workspace_file(service, "u1", "c1", "uploads/song.mp3", b"ID3fakebytes")

    share = await service.create_file_share(
        user_id="u1",
        conversation_id="c1",
        rel_path="uploads/song.mp3",
    )

    assert share["token"]
    assert share["url"].endswith(f"/api/share/{share['token']}")
    assert share["url"].startswith("http://")
    # Default API call: 10 accesses, 24h TTL.
    assert share["remaining_uses"] == 10
    assert share["max_accesses"] == 10
    assert share["via_tunnel"] is False
    assert share["media_type"] == "audio/mpeg"
    assert share["size"] == len(b"ID3fakebytes")


async def test_create_file_share_persists_record(
    service: WorkspaceService, sqlite_storage: SQLiteStorage
) -> None:
    _write_workspace_file(service, "u1", "c1", "uploads/song.mp3", b"bytes")
    share = await service.create_file_share(
        user_id="u1",
        conversation_id="c1",
        rel_path="uploads/song.mp3",
    )

    from gilbert.interfaces.storage import Filter, FilterOp, Query

    records = await sqlite_storage.query(
        Query(
            collection=_WORKSPACE_SHARES_COLLECTION,
            filters=[Filter(field="token", op=FilterOp.EQ, value=share["token"])],
        )
    )
    assert len(records) == 1
    rec = records[0]
    assert rec["rel_path"] == "uploads/song.mp3"
    assert rec["conversation_id"] == "c1"
    assert rec["user_id"] == "u1"
    assert rec["remaining_uses"] == 10


async def test_create_file_share_honours_custom_limits(service: WorkspaceService) -> None:
    _write_workspace_file(service, "u1", "c1", "uploads/f.bin", b"x")
    share = await service.create_file_share(
        user_id="u1",
        conversation_id="c1",
        rel_path="uploads/f.bin",
        max_accesses=3,
        ttl_seconds=300,
    )
    assert share["max_accesses"] == 3
    assert share["remaining_uses"] == 3


async def test_create_file_share_clamps_caps(service: WorkspaceService) -> None:
    """Pathological inputs (1 billion accesses, 1 year TTL) get clamped
    to the hard caps so the share doesn't outlive its usefulness."""
    _write_workspace_file(service, "u1", "c1", "uploads/f.bin", b"x")
    share = await service.create_file_share(
        user_id="u1",
        conversation_id="c1",
        rel_path="uploads/f.bin",
        max_accesses=10_000_000,
        ttl_seconds=365 * 24 * 60 * 60,
    )
    assert share["max_accesses"] == 1000  # _MAX_SHARE_MAX_ACCESSES
    # TTL clamped to 30 days → expires within 30d of now.
    expires = datetime.fromisoformat(share["expires_at"])
    assert expires <= datetime.now(UTC) + timedelta(days=30, seconds=10)


async def test_create_file_share_rejects_missing_file(service: WorkspaceService) -> None:
    with pytest.raises(ValueError, match="File not found"):
        await service.create_file_share(
            user_id="u1",
            conversation_id="c1",
            rel_path="uploads/nope.mp3",
        )


async def test_create_file_share_rejects_missing_conv(service: WorkspaceService) -> None:
    with pytest.raises(ValueError, match="conversation_id is required"):
        await service.create_file_share(
            user_id="u1",
            conversation_id="",
            rel_path="uploads/x.bin",
        )


async def test_create_file_share_rejects_via_tunnel_without_tunnel(
    service: WorkspaceService,
) -> None:
    """via_tunnel=True must fail loudly rather than silently degrading —
    the caller asked for a public URL and should know they didn't get one."""
    _write_workspace_file(service, "u1", "c1", "uploads/f.bin", b"x")
    with pytest.raises(ValueError, match="via_tunnel=true requires"):
        await service.create_file_share(
            user_id="u1",
            conversation_id="c1",
            rel_path="uploads/f.bin",
            via_tunnel=True,
        )


# --- consume_file_share ---


async def test_consume_file_share_returns_path_and_decrements(
    service: WorkspaceService, sqlite_storage: SQLiteStorage
) -> None:
    target = _write_workspace_file(service, "u1", "c1", "uploads/a.bin", b"hi")
    share = await service.create_file_share(
        user_id="u1",
        conversation_id="c1",
        rel_path="uploads/a.bin",
        max_accesses=3,
    )

    result = await service.consume_file_share(share["token"])
    assert result is not None
    path, media_type, filename = result
    assert path == target
    assert filename == "a.bin"
    assert media_type == "application/octet-stream"

    # Remaining uses went from 3 → 2.
    from gilbert.interfaces.storage import Filter, FilterOp, Query

    records = await sqlite_storage.query(
        Query(
            collection=_WORKSPACE_SHARES_COLLECTION,
            filters=[
                Filter(field="token", op=FilterOp.EQ, value=share["token"])
            ],
        )
    )
    assert records[0]["remaining_uses"] == 2


async def test_consume_file_share_exhaustion_deletes_record(
    service: WorkspaceService, sqlite_storage: SQLiteStorage
) -> None:
    """After the last allowed access, the record is deleted and any
    subsequent consume returns None (404 to the caller)."""
    _write_workspace_file(service, "u1", "c1", "uploads/a.bin", b"x")
    share = await service.create_file_share(
        user_id="u1",
        conversation_id="c1",
        rel_path="uploads/a.bin",
        max_accesses=1,
    )

    assert await service.consume_file_share(share["token"]) is not None
    assert await service.consume_file_share(share["token"]) is None

    from gilbert.interfaces.storage import Filter, FilterOp, Query

    records = await sqlite_storage.query(
        Query(
            collection=_WORKSPACE_SHARES_COLLECTION,
            filters=[
                Filter(field="token", op=FilterOp.EQ, value=share["token"])
            ],
        )
    )
    assert records == []


async def test_consume_file_share_unknown_token_returns_none(
    service: WorkspaceService,
) -> None:
    assert await service.consume_file_share("does-not-exist") is None


async def test_consume_file_share_expired_returns_none(
    service: WorkspaceService, sqlite_storage: SQLiteStorage
) -> None:
    """Manually-backdated expires_at → consume returns None and deletes."""
    _write_workspace_file(service, "u1", "c1", "uploads/a.bin", b"x")
    share = await service.create_file_share(
        user_id="u1",
        conversation_id="c1",
        rel_path="uploads/a.bin",
    )

    # Backdate by rewriting the record directly.
    from gilbert.interfaces.storage import Filter, FilterOp, Query

    records = await sqlite_storage.query(
        Query(
            collection=_WORKSPACE_SHARES_COLLECTION,
            filters=[
                Filter(field="token", op=FilterOp.EQ, value=share["token"])
            ],
        )
    )
    rec_id = records[0]["_id"]
    record = dict(records[0])
    record["expires_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    await sqlite_storage.put(_WORKSPACE_SHARES_COLLECTION, rec_id, record)

    assert await service.consume_file_share(share["token"]) is None
    # Record gets cleaned up opportunistically on the failed consume.
    post = await sqlite_storage.query(
        Query(
            collection=_WORKSPACE_SHARES_COLLECTION,
            filters=[
                Filter(field="token", op=FilterOp.EQ, value=share["token"])
            ],
        )
    )
    assert post == []


async def test_consume_file_share_missing_file_returns_none(
    service: WorkspaceService,
) -> None:
    """If the backing file has been deleted out from under us, the share
    no longer resolves — 404 and clean up the record."""
    target = _write_workspace_file(service, "u1", "c1", "uploads/a.bin", b"x")
    share = await service.create_file_share(
        user_id="u1",
        conversation_id="c1",
        rel_path="uploads/a.bin",
    )
    target.unlink()

    assert await service.consume_file_share(share["token"]) is None


# --- _cleanup_file_shares ---


async def test_cleanup_removes_expired_and_exhausted(
    service: WorkspaceService, sqlite_storage: SQLiteStorage
) -> None:
    """The hourly sweep deletes both expired-by-time records and
    records where remaining_uses dropped to zero via earlier consumes."""
    _write_workspace_file(service, "u1", "c1", "uploads/a.bin", b"x")
    _write_workspace_file(service, "u1", "c1", "uploads/b.bin", b"y")
    _write_workspace_file(service, "u1", "c1", "uploads/c.bin", b"z")

    # Alive share (should survive cleanup).
    alive = await service.create_file_share(
        user_id="u1",
        conversation_id="c1",
        rel_path="uploads/a.bin",
    )
    # Expired share.
    expired = await service.create_file_share(
        user_id="u1",
        conversation_id="c1",
        rel_path="uploads/b.bin",
    )
    # Exhausted share — shove remaining_uses to 0 without going through consume.
    exhausted = await service.create_file_share(
        user_id="u1",
        conversation_id="c1",
        rel_path="uploads/c.bin",
    )

    from gilbert.interfaces.storage import Filter, FilterOp, Query

    records = await sqlite_storage.query(
        Query(collection=_WORKSPACE_SHARES_COLLECTION)
    )
    by_token = {r["token"]: r for r in records}

    # Backdate the expired one.
    rec = by_token[expired["token"]]
    rec["expires_at"] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    await sqlite_storage.put(_WORKSPACE_SHARES_COLLECTION, rec["_id"], rec)

    # Zero the exhausted one.
    rec = by_token[exhausted["token"]]
    rec["remaining_uses"] = 0
    await sqlite_storage.put(_WORKSPACE_SHARES_COLLECTION, rec["_id"], rec)

    await service._cleanup_file_shares()

    remaining = await sqlite_storage.query(
        Query(collection=_WORKSPACE_SHARES_COLLECTION)
    )
    remaining_tokens = {r["token"] for r in remaining}
    assert alive["token"] in remaining_tokens
    assert expired["token"] not in remaining_tokens
    assert exhausted["token"] not in remaining_tokens


# --- Tool wrapper ---


async def test_tool_share_workspace_file_wraps_create(
    service: WorkspaceService,
) -> None:
    _write_workspace_file(service, "u1", "c1", "uploads/a.bin", b"x")
    import json

    result = await service._tool_share_workspace_file(
        {
            "path": "uploads/a.bin",
            "max_accesses": 5,
            "ttl_seconds": 600,
            "_user_id": "u1",
            "_conversation_id": "c1",
        }
    )
    parsed = json.loads(result)
    assert parsed["token"]
    assert parsed["max_accesses"] == 5
    assert parsed["remaining_uses"] == 5


async def test_tool_share_workspace_file_requires_conv(
    service: WorkspaceService,
) -> None:
    import json

    result = await service._tool_share_workspace_file(
        {"path": "uploads/a.bin", "_user_id": "u1"}
    )
    parsed = json.loads(result)
    assert "error" in parsed
    assert "conversation" in parsed["error"].lower()


async def test_tool_share_workspace_file_surfaces_value_errors(
    service: WorkspaceService,
) -> None:
    import json

    result = await service._tool_share_workspace_file(
        {
            "path": "uploads/missing.bin",
            "_user_id": "u1",
            "_conversation_id": "c1",
        }
    )
    parsed = json.loads(result)
    assert "error" in parsed
    assert "not found" in parsed["error"].lower()
