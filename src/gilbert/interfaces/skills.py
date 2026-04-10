"""Skill system data model — based on the Agent Skills open standard (agentskills.io)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SkillCatalogEntry:
    """Tier 1 metadata — cheap to load, used for listing and matching."""

    name: str
    description: str
    location: Path | None = None
    category: str = ""
    icon: str = ""
    required_role: str = "user"
    allowed_tools: list[str] = field(default_factory=list)
    scope: str = "global"
    owner_id: str = ""


@dataclass(frozen=True)
class SkillContent:
    """Tier 2 — full instructions loaded on activation."""

    catalog: SkillCatalogEntry
    instructions: str
    resources: list[str] = field(default_factory=list)
