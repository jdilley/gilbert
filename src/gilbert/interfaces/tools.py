"""Tool system interface — provider-agnostic tool definitions and the ToolProvider protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class ToolParameterType(StrEnum):
    """JSON Schema types for tool parameters."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ARRAY = "array"
    OBJECT = "object"


@dataclass(frozen=True)
class ToolParameter:
    """A single parameter in a tool's input schema."""

    name: str
    type: ToolParameterType
    description: str
    required: bool = True
    enum: list[str] | None = None
    default: Any = None


@dataclass(frozen=True)
class ToolDefinition:
    """Provider-agnostic definition of a callable tool."""

    name: str
    description: str
    parameters: list[ToolParameter] = field(default_factory=list)
    required_role: str = "user"
    # Optional slash-command exposure. When set, this tool becomes callable
    # directly from the chat input as ``/<slash_command> <args>`` and shows
    # up in the slash-command autocomplete. Opt-in because not every tool
    # has a sensible shell-style form.
    slash_command: str | None = None
    # Optional group name. When set, the full invocation becomes
    # ``/<slash_group> <slash_command> <args>``, letting a service expose
    # several related commands under one prefix (e.g. ``/radio start``,
    # ``/radio stop``, ``/radio skip``). Plugins still get their namespace
    # prefixed on top: ``/<plugin_ns>.<slash_group> <slash_command>``.
    slash_group: str | None = None
    slash_help: str = ""  # short help text; falls back to ``description``

    def to_json_schema(self) -> dict[str, Any]:
        """Convert parameters to JSON Schema format (used by most AI providers)."""
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in self.parameters:
            prop: dict[str, Any] = {
                "type": param.type.value,
                "description": param.description,
            }
            if param.enum is not None:
                prop["enum"] = param.enum
            properties[param.name] = prop
            if param.required:
                required.append(param.name)
        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        return schema


@dataclass(frozen=True)
class ToolCall:
    """An AI-requested tool invocation."""

    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    """The result of executing a tool call."""

    tool_call_id: str
    content: str
    is_error: bool = False


@runtime_checkable
class ToolProvider(Protocol):
    """Protocol for services that expose tools to the AI.

    Any service that provides AI-callable tools should implement this
    protocol and declare the ``ai_tools`` capability in its ServiceInfo.
    """

    @property
    def tool_provider_name(self) -> str:
        """Human-readable name for this tool provider."""
        ...

    def get_tools(self) -> list[ToolDefinition]:
        """Return the tool definitions this provider offers."""
        ...

    async def execute_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Execute a named tool with the given arguments. Returns result as string.

        Raises KeyError if the tool name is not recognized.
        Raises ValueError for invalid arguments.
        """
        ...
