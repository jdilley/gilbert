"""Static uniqueness check for slash commands across core services.

This test walks every Python source file under ``src/gilbert/core/services/``
and ``src/gilbert/integrations/`` (the two layers that define core tools),
extracts every ``ToolDefinition`` that declares a ``slash_command`` and
asserts that no two tools claim the same fully-qualified slash command
in the same group. Core services all share the empty plugin namespace,
so any collision here is a real conflict the user would see in chat
autocomplete.

The full key used for uniqueness is ``(slash_group or "", slash_command)``
so the same leaf name (e.g. ``"stop"``) can appear under different
groups (``/radio stop`` vs ``/speaker stop``) without colliding.

Plugin-sourced tools live outside this directory tree and are
automatically namespaced by ``AIService._resolve_slash_namespace``, so
they are not subject to this check.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

# Directories that define core (non-plugin) tools.
_ROOTS = [
    Path(__file__).parents[2] / "src" / "gilbert" / "core" / "services",
    Path(__file__).parents[2] / "src" / "gilbert" / "integrations",
]


def _string_value(node: ast.AST | None) -> str | None:
    """Return the literal string value of an AST node, or None."""
    if node is None:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _iter_tool_definitions(tree: ast.AST):
    """Yield every ``ToolDefinition(...)`` call found in *tree*.

    Matches both the direct ``ToolDefinition(...)`` form and the
    qualified ``gilbert.interfaces.tools.ToolDefinition(...)`` form.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_direct = isinstance(func, ast.Name) and func.id == "ToolDefinition"
        is_qualified = isinstance(func, ast.Attribute) and func.attr == "ToolDefinition"
        if is_direct or is_qualified:
            yield node


def _extract_kwargs(call: ast.Call) -> dict[str, ast.AST]:
    return {kw.arg: kw.value for kw in call.keywords if kw.arg is not None}


def _collect_slash_commands() -> dict[tuple[str, str], list[str]]:
    """Map ``(group, command)`` → list of ``"file:tool_name"`` locations."""
    registry: dict[tuple[str, str], list[str]] = {}
    for root in _ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            for call in _iter_tool_definitions(tree):
                kwargs = _extract_kwargs(call)
                slash_cmd = _string_value(kwargs.get("slash_command"))
                if not slash_cmd:
                    continue
                slash_group = _string_value(kwargs.get("slash_group")) or ""
                tool_name = _string_value(kwargs.get("name")) or "(unknown)"
                rel = path.relative_to(root.parents[3])
                registry.setdefault((slash_group, slash_cmd), []).append(f"{rel}:{tool_name}")
    return registry


def _full_form(group: str, cmd: str) -> str:
    """Render a (group, command) key as ``/group cmd`` or ``/cmd``."""
    return f"/{group} {cmd}" if group else f"/{cmd}"


def test_slash_commands_are_unique_across_core_services() -> None:
    registry = _collect_slash_commands()
    duplicates = {key: locs for key, locs in registry.items() if len(locs) > 1}
    if duplicates:
        lines = ["Duplicate slash command values detected:"]
        for (group, cmd), locs in sorted(duplicates.items()):
            lines.append(f"  {_full_form(group, cmd)}:")
            for loc in locs:
                lines.append(f"    - {loc}")
        raise AssertionError("\n".join(lines))


def test_slash_commands_are_identifier_shaped() -> None:
    """Every ``slash_command`` and ``slash_group`` must be a bare identifier.

    Dots are reserved for plugin namespacing, which is applied at
    discovery time by ``AIService._resolve_slash_namespace``. Spaces are
    reserved for group/subcommand composition, which is applied
    automatically from ``slash_group``. A tool definition that hard-codes
    either is almost certainly a bug.
    """
    identifier = re.compile(r"[a-zA-Z][a-zA-Z0-9_\-]*")
    bad: list[tuple[str, list[str]]] = []
    for (group, cmd), locs in _collect_slash_commands().items():
        if not identifier.fullmatch(cmd):
            bad.append((f"slash_command={cmd!r}", locs))
        if group and not identifier.fullmatch(group):
            bad.append((f"slash_group={group!r}", locs))
    if bad:
        lines = ["slash_command/slash_group values must be bare identifiers:"]
        for label, locs in bad:
            lines.append(f"  {label} at {', '.join(locs)}")
        raise AssertionError("\n".join(lines))


def test_at_least_one_slash_command_is_registered() -> None:
    """Sanity check: the project should have many slash commands by now."""
    registry = _collect_slash_commands()
    # Somewhat arbitrary floor — plenty of headroom for future additions,
    # but catches "the regex broke and matched nothing".
    assert len(registry) >= 20, f"Expected at least 20 core slash commands, found {len(registry)}"
