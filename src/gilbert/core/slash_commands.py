"""Slash command parsing — shell-style invocation of tools from chat.

This module is pure: it takes text + a ``ToolDefinition`` and produces an
``arguments`` dict that can be passed straight to ``ToolProvider.execute_tool``.
It does no service discovery, no RBAC, and no execution — that's the
caller's job (see ``core/services/ai.py``).

Syntax
------

A slash command starts with ``/``, followed by the command name, followed
by optional arguments::

    /announce "hello there" speakers
    /announce text="hello there" destination=speakers
    /announce "hello there" --destination=speakers

Arguments are tokenized with :func:`shlex.split` so quoting works the
same as a POSIX shell. After tokenization, tokens are classified:

- ``key=value`` or ``--key=value`` → keyword argument named ``key``
- ``--key value`` → keyword argument named ``key`` with the next token as value
- anything else → positional argument

Positional arguments are assigned to the tool's parameters in declaration
order (skipping parameters already supplied as keywords).

Type coercion is per :class:`ToolParameterType`:

- STRING: passed through verbatim
- INTEGER: ``int(token)``
- NUMBER: ``float(token)``
- BOOLEAN: case-insensitive ``true/yes/1/on`` → ``True`` (else ``False``)
- ARRAY: JSON array if the token starts with ``[``; otherwise split on commas
- OBJECT: JSON object (must start with ``{``)
"""

from __future__ import annotations

import json
import re
import shlex
from typing import Any

from gilbert.interfaces.tools import (
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
)

# A valid slash-command name: ``/`` then an identifier-ish token, optionally
# prefixed with ``<namespace>.`` for plugin-sourced commands (e.g.
# ``/currev.time_logs``). We deliberately exclude ``/path/to/file`` or a
# bare ``/`` so users can still paste paths without accidentally triggering
# command resolution.
_SEGMENT = r"[a-zA-Z][a-zA-Z0-9_\-]*"
_COMMAND_NAME_RE = re.compile(rf"^/({_SEGMENT}(?:\.{_SEGMENT})?)(?:\s|$)")


class SlashCommandError(ValueError):
    """Raised when a slash command cannot be parsed into valid arguments.

    The message is intended to be shown directly to the user as feedback
    in chat, so it should be actionable and include a usage hint when
    possible.
    """


def extract_command_name(text: str) -> str | None:
    """Return the command name if *text* looks like a slash command.

    Recognizes both bare ``/announce`` and namespaced ``/namespace.command``
    forms (namespaces are used to scope plugin-provided tools away from
    core ones). Returns ``None`` if *text* does not start with ``/``
    followed by an identifier-style token, so plain text like
    ``/path/to/file`` passes through unchanged.
    """
    if not text:
        return None
    match = _COMMAND_NAME_RE.match(text)
    if match is None:
        return None
    return match.group(1)


def format_usage(tool_def: ToolDefinition, full_command: str | None = None) -> str:
    """Build a one-line usage string like ``/cmd <a:string> [b:int]``.

    *full_command* is the resolved command name the caller sees (including
    any plugin namespace prefix). When omitted it falls back to the bare
    ``tool_def.slash_command`` or the tool name, useful for unit tests
    where there is no discovery layer.
    """
    cmd = full_command or tool_def.slash_command or tool_def.name
    parts = [f"/{cmd}"]
    for p in tool_def.parameters:
        if _is_injected_param(p.name):
            continue
        token = f"{p.name}:{p.type.value}"
        parts.append(f"<{token}>" if p.required else f"[{token}]")
    return " ".join(parts)


def parse_slash_command(
    text: str,
    tool_def: ToolDefinition,
    full_command: str | None = None,
) -> dict[str, Any]:
    """Parse *text* into an arguments dict for *tool_def*.

    When the caller already knows the full command name — for example,
    because it did a multi-word lookup like ``/radio start`` — it can
    pass *full_command* so the parser strips exactly the right prefix
    and uses the right name in usage hints. Otherwise the first
    identifier-shaped word after ``/`` is used (single-word commands).

    Raises :class:`SlashCommandError` if the text is malformed, a required
    parameter is missing, or a value can't be coerced to the parameter's
    declared type.
    """
    if full_command is None:
        full_command = extract_command_name(text)
    if full_command is None:
        raise SlashCommandError(
            "Not a slash command — must start with /<name>."
        )

    # Use the resolved full name in error messages so hints match what
    # the user typed (including any plugin namespace or group prefix).
    usage = format_usage(tool_def, full_command=full_command)

    prefix = "/" + full_command
    stripped = text.lstrip()
    if not stripped.startswith(prefix):
        raise SlashCommandError(
            f"Expected command prefix {prefix!r}. Usage: {usage}"
        )
    remainder = stripped[len(prefix):].strip()

    try:
        tokens = shlex.split(remainder) if remainder else []
    except ValueError as exc:
        raise SlashCommandError(
            f"Could not parse arguments: {exc}. Usage: {usage}"
        ) from exc

    # Parameters, excluding injected-context names (``_user_id`` etc.) so
    # users can't spoof them and so positional indexing skips them.
    params = [p for p in tool_def.parameters if not _is_injected_param(p.name)]
    by_name = {p.name: p for p in params}

    positional: list[str] = []
    keywords: dict[str, str] = {}

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        # ``--key=value`` or ``key=value``
        kv = _split_keyword(tok)
        if kv is not None:
            key, value = kv
            keywords[key] = value
            i += 1
            continue
        # ``--key value`` (next token as value)
        if tok.startswith("--") and len(tok) > 2 and "=" not in tok:
            key = tok[2:]
            if i + 1 >= len(tokens):
                raise SlashCommandError(
                    f"Flag --{key} requires a value. "
                    f"Usage: {usage}"
                )
            keywords[key] = tokens[i + 1]
            i += 2
            continue
        positional.append(tok)
        i += 1

    # Validate keyword names up front for friendlier errors
    for k in keywords:
        if k not in by_name:
            known = ", ".join(p.name for p in params) or "(none)"
            raise SlashCommandError(
                f"Unknown parameter '{k}'. Known parameters: {known}. "
                f"Usage: {usage}"
            )

    # Assign positional arguments to parameters that weren't supplied as
    # keywords, in declaration order.
    arguments: dict[str, Any] = {}
    positional_iter = iter(positional)
    for param in params:
        if param.name in keywords:
            raw = keywords[param.name]
        else:
            try:
                raw = next(positional_iter)
            except StopIteration:
                if param.required and param.default is None:
                    raise SlashCommandError(
                        f"Missing required parameter '{param.name}'. "
                        f"Usage: {usage}"
                    ) from None
                continue
        try:
            arguments[param.name] = _coerce(raw, param)
        except SlashCommandError:
            raise
        except Exception as exc:
            raise SlashCommandError(
                f"Invalid value for '{param.name}': {exc}. "
                f"Usage: {usage}"
            ) from exc

    # Reject leftover positional args — usually a mistake
    leftover = list(positional_iter)
    if leftover:
        raise SlashCommandError(
            f"Unexpected extra arguments: {leftover}. "
            f"Usage: {usage}"
        )

    # Apply enum validation
    for param in params:
        if param.enum is None or param.name not in arguments:
            continue
        value = arguments[param.name]
        if value not in param.enum:
            choices = ", ".join(param.enum)
            raise SlashCommandError(
                f"'{param.name}' must be one of: {choices} (got {value!r})."
            )

    return arguments


# ---- internals ----


_KEYWORD_RE = re.compile(r"^(?:--)?([a-zA-Z_][a-zA-Z0-9_]*)=(.*)$")


def _split_keyword(token: str) -> tuple[str, str] | None:
    """Match ``key=value`` or ``--key=value`` → ``(key, value)`` or None."""
    m = _KEYWORD_RE.match(token)
    if m is None:
        return None
    return m.group(1), m.group(2)


def _is_injected_param(name: str) -> bool:
    """Injected context parameters (``_user_id``, etc.) are never user-set."""
    return name.startswith("_")


_TRUE_LITERALS = frozenset({"true", "yes", "1", "on", "y", "t"})
_FALSE_LITERALS = frozenset({"false", "no", "0", "off", "n", "f"})


def _coerce(raw: str, param: ToolParameter) -> Any:
    """Convert a string token to the parameter's declared type."""
    if param.type == ToolParameterType.STRING:
        return raw
    if param.type == ToolParameterType.INTEGER:
        return int(raw)
    if param.type == ToolParameterType.NUMBER:
        return float(raw)
    if param.type == ToolParameterType.BOOLEAN:
        low = raw.strip().lower()
        if low in _TRUE_LITERALS:
            return True
        if low in _FALSE_LITERALS:
            return False
        raise SlashCommandError(
            f"'{param.name}' must be a boolean (true/false/yes/no/1/0), "
            f"got {raw!r}."
        )
    if param.type == ToolParameterType.ARRAY:
        stripped = raw.strip()
        if stripped.startswith("["):
            parsed = json.loads(stripped)
            if not isinstance(parsed, list):
                raise SlashCommandError(
                    f"'{param.name}' JSON value must be an array."
                )
            return parsed
        # Comma-separated fallback. Empty string → empty list; single
        # value with no commas → one-element list.
        if not stripped:
            return []
        return [item.strip() for item in stripped.split(",") if item.strip()]
    if param.type == ToolParameterType.OBJECT:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise SlashCommandError(
                f"'{param.name}' JSON value must be an object."
            )
        return parsed
    # Should never happen — all ToolParameterType values handled above.
    raise SlashCommandError(f"Unsupported parameter type: {param.type}")
