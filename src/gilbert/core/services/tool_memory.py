"""Tool memory service — per-user key-value store for tools and skills.

Tools and skills use this service to persist state across invocations,
scoped by user and namespace. Any tool can read/write any namespace,
enabling cross-tool collaboration within a user's memory space.

Summaries are injected into the AI system prompt so the AI is aware
of what tools have stored for the current user.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from gilbert.interfaces.service import Service, ServiceInfo, ServiceResolver

logger = logging.getLogger(__name__)

_COLLECTION = "tool_memories"


def _entity_id(user_id: str, namespace: str, key: str) -> str:
    """Deterministic entity ID from (user_id, namespace, key)."""
    raw = f"{user_id}:{namespace}:{key}"
    return f"tm_{hashlib.sha256(raw.encode()).hexdigest()[:16]}"


class ToolMemoryService(Service):
    """Per-user key-value store for tools and skills.

    Capabilities: tool_memory
    """

    def __init__(self) -> None:
        self._storage: Any = None  # StorageBackend

    def service_info(self) -> ServiceInfo:
        return ServiceInfo(
            name="tool_memory",
            capabilities=frozenset({"tool_memory"}),
            requires=frozenset({"entity_storage"}),
            optional=frozenset(),
        )

    async def start(self, resolver: ServiceResolver) -> None:
        from gilbert.interfaces.storage import IndexDefinition

        storage_svc = resolver.require_capability("entity_storage")
        self._storage = getattr(storage_svc, "backend", storage_svc)

        await self._storage.ensure_index(IndexDefinition(
            collection=_COLLECTION,
            fields=["user_id", "namespace"],
        ))
        await self._storage.ensure_index(IndexDefinition(
            collection=_COLLECTION,
            fields=["user_id"],
        ))

        logger.info("Tool memory service started")

    # ── Public API ──────────────────────────────────────────────

    async def get(self, user_id: str, namespace: str, key: str) -> Any | None:
        """Get a single value, or None if not found."""
        eid = _entity_id(user_id, namespace, key)
        record = await self._storage.get(_COLLECTION, eid)
        if record is None:
            return None
        if record.get("user_id") != user_id:
            return None
        return record.get("value")

    async def put(
        self, user_id: str, namespace: str, key: str, value: Any,
    ) -> None:
        """Store a value (upsert)."""
        eid = _entity_id(user_id, namespace, key)
        now = datetime.now(UTC).isoformat()

        existing = await self._storage.get(_COLLECTION, eid)
        created_at = existing.get("created_at", now) if existing else now

        await self._storage.put(_COLLECTION, eid, {
            "user_id": user_id,
            "namespace": namespace,
            "key": key,
            "value": value,
            "created_at": created_at,
            "updated_at": now,
        })

    async def delete(self, user_id: str, namespace: str, key: str) -> bool:
        """Delete a single entry. Returns True if it existed."""
        eid = _entity_id(user_id, namespace, key)
        record = await self._storage.get(_COLLECTION, eid)
        if record is None or record.get("user_id") != user_id:
            return False
        await self._storage.delete(_COLLECTION, eid)
        return True

    async def list_keys(self, user_id: str, namespace: str) -> list[str]:
        """List all keys in a namespace for a user."""
        records = await self._query_namespace(user_id, namespace)
        return [r.get("key", "") for r in records]

    async def get_all(self, user_id: str, namespace: str) -> dict[str, Any]:
        """Get all key-value pairs in a namespace for a user."""
        records = await self._query_namespace(user_id, namespace)
        return {r.get("key", ""): r.get("value") for r in records}

    async def delete_all(self, user_id: str, namespace: str) -> int:
        """Delete all entries in a namespace for a user. Returns count deleted."""
        records = await self._query_namespace(user_id, namespace)
        for r in records:
            eid = r.get("_id", "")
            if eid:
                await self._storage.delete(_COLLECTION, eid)
        return len(records)

    async def get_user_summaries(self, user_id: str) -> str:
        """Format all tool memories for a user (for AI system prompt).

        Returns a string grouped by namespace, or empty string if none.
        """
        from gilbert.interfaces.storage import Filter, FilterOp, Query

        records = await self._storage.query(Query(
            collection=_COLLECTION,
            filters=[Filter(field="user_id", op=FilterOp.EQ, value=user_id)],
        ))

        if not records:
            return ""

        # Group by namespace
        by_ns: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for r in records:
            by_ns[r.get("namespace", "unknown")].append(r)

        lines = [f"## Tool Memories for this user ({len(records)} stored)"]
        for ns in sorted(by_ns):
            lines.append(f"### {ns}")
            for r in by_ns[ns]:
                key = r.get("key", "")
                value = r.get("value")
                try:
                    val_str = json.dumps(value) if not isinstance(value, str) else value
                except (TypeError, ValueError):
                    val_str = str(value)
                lines.append(f"- {key}: {val_str}")

        return "\n".join(lines)

    # ── Internal ────────────────────────────────────────────────

    async def _query_namespace(
        self, user_id: str, namespace: str,
    ) -> list[dict[str, Any]]:
        """Query all records for a user+namespace."""
        from gilbert.interfaces.storage import Filter, FilterOp, Query

        return await self._storage.query(Query(
            collection=_COLLECTION,
            filters=[
                Filter(field="user_id", op=FilterOp.EQ, value=user_id),
                Filter(field="namespace", op=FilterOp.EQ, value=namespace),
            ],
        ))
