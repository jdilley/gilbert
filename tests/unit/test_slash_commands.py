"""Tests for the slash command parser."""

import pytest

from gilbert.core.slash_commands import (
    SlashCommandError,
    extract_command_name,
    format_usage,
    parse_slash_command,
)
from gilbert.interfaces.tools import (
    ToolDefinition,
    ToolParameter,
    ToolParameterType,
)

# --- Fixtures -------------------------------------------------------------


def _def(
    name: str = "announce",
    slash: str | None = "announce",
    params: list[ToolParameter] | None = None,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        description="test",
        parameters=params or [],
        slash_command=slash,
    )


@pytest.fixture
def announce_def() -> ToolDefinition:
    return _def(
        params=[
            ToolParameter(
                name="text",
                type=ToolParameterType.STRING,
                description="Text to speak",
                required=True,
            ),
            ToolParameter(
                name="destination",
                type=ToolParameterType.STRING,
                description="Where to play",
                required=False,
                enum=["chat", "speakers"],
                default="chat",
            ),
            ToolParameter(
                name="volume",
                type=ToolParameterType.INTEGER,
                description="0-100",
                required=False,
            ),
            ToolParameter(
                name="speaker_names",
                type=ToolParameterType.ARRAY,
                description="Speaker targets",
                required=False,
            ),
        ],
    )


# --- extract_command_name ------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("/announce", "announce"),
        ("/announce hello", "announce"),
        ("/an_nounce", "an_nounce"),
        ("/do-it", "do-it"),
        ("/X", "X"),
        ("  /announce", None),  # leading whitespace — not a command
        ("/", None),
        ("/123abc", None),  # must start with a letter
        ("/path/to/file", None),  # nested slash — not a command
        ("announce", None),
        ("", None),
        ("/ announce", None),
    ],
)
def test_extract_command_name(text: str, expected: str | None) -> None:
    assert extract_command_name(text) == expected


# --- format_usage --------------------------------------------------------


def test_format_usage_shows_required_and_optional(announce_def: ToolDefinition) -> None:
    usage = format_usage(announce_def)
    assert usage.startswith("/announce")
    assert "<text:string>" in usage
    assert "[destination:string]" in usage
    assert "[volume:integer]" in usage
    assert "[speaker_names:array]" in usage


# --- Happy paths ---------------------------------------------------------


def test_positional_args(announce_def: ToolDefinition) -> None:
    args = parse_slash_command('/announce "hello there" speakers', announce_def)
    assert args == {"text": "hello there", "destination": "speakers"}


def test_keyword_args(announce_def: ToolDefinition) -> None:
    args = parse_slash_command(
        '/announce text="hello there" destination=speakers', announce_def
    )
    assert args == {"text": "hello there", "destination": "speakers"}


def test_double_dash_keyword(announce_def: ToolDefinition) -> None:
    args = parse_slash_command(
        '/announce --text="hi" --destination=speakers', announce_def
    )
    assert args["text"] == "hi"
    assert args["destination"] == "speakers"


def test_double_dash_space_separated(announce_def: ToolDefinition) -> None:
    args = parse_slash_command(
        '/announce --text hello --destination speakers', announce_def
    )
    assert args["text"] == "hello"
    assert args["destination"] == "speakers"


def test_mixed_positional_and_keyword(announce_def: ToolDefinition) -> None:
    args = parse_slash_command(
        '/announce "hello there" destination=speakers volume=75', announce_def
    )
    assert args == {
        "text": "hello there",
        "destination": "speakers",
        "volume": 75,
    }


def test_only_required(announce_def: ToolDefinition) -> None:
    args = parse_slash_command('/announce "just this"', announce_def)
    assert args == {"text": "just this"}


# --- Type coercion -------------------------------------------------------


def test_integer_coercion(announce_def: ToolDefinition) -> None:
    args = parse_slash_command('/announce "hi" volume=42', announce_def)
    assert args["volume"] == 42
    assert isinstance(args["volume"], int)


def test_integer_coercion_failure(announce_def: ToolDefinition) -> None:
    with pytest.raises(SlashCommandError, match="Invalid value for 'volume'"):
        parse_slash_command('/announce "hi" volume=loud', announce_def)


def test_boolean_coercion() -> None:
    tool = _def(
        params=[
            ToolParameter(
                name="enabled",
                type=ToolParameterType.BOOLEAN,
                description="on/off",
                required=True,
            ),
        ]
    )
    assert parse_slash_command("/announce true", tool)["enabled"] is True
    assert parse_slash_command("/announce YES", tool)["enabled"] is True
    assert parse_slash_command("/announce 1", tool)["enabled"] is True
    assert parse_slash_command("/announce false", tool)["enabled"] is False
    assert parse_slash_command("/announce off", tool)["enabled"] is False
    with pytest.raises(SlashCommandError, match="must be a boolean"):
        parse_slash_command("/announce maybe", tool)


def test_number_coercion() -> None:
    tool = _def(
        params=[
            ToolParameter(
                name="pi",
                type=ToolParameterType.NUMBER,
                description="pi",
                required=True,
            ),
        ]
    )
    args = parse_slash_command("/announce 3.14", tool)
    assert args["pi"] == pytest.approx(3.14)


def test_array_comma_separated(announce_def: ToolDefinition) -> None:
    args = parse_slash_command(
        '/announce "hi" destination=speakers speaker_names="entry,garage,shop"',
        announce_def,
    )
    assert args["speaker_names"] == ["entry", "garage", "shop"]


def test_array_with_spaces_in_names(announce_def: ToolDefinition) -> None:
    # Positional slots can't be skipped, so use a keyword for speaker_names
    # and skip the volume slot. Quoted tokens preserve inner spaces; the
    # array coercer then splits on commas.
    args = parse_slash_command(
        '/announce "hi" speakers speaker_names="entry room,garage"',
        announce_def,
    )
    assert args["speaker_names"] == ["entry room", "garage"]


def test_array_json_form(announce_def: ToolDefinition) -> None:
    args = parse_slash_command(
        '/announce "hi" speakers speaker_names=\'["entry","garage"]\'',
        announce_def,
    )
    assert args["speaker_names"] == ["entry", "garage"]


def test_array_empty_string() -> None:
    tool = _def(
        params=[
            ToolParameter(
                name="items",
                type=ToolParameterType.ARRAY,
                description="items",
                required=False,
            ),
        ]
    )
    args = parse_slash_command('/announce ""', tool)
    assert args["items"] == []


def test_object_coercion() -> None:
    tool = _def(
        params=[
            ToolParameter(
                name="meta",
                type=ToolParameterType.OBJECT,
                description="metadata",
                required=True,
            ),
        ]
    )
    args = parse_slash_command(
        '/announce \'{"a": 1, "b": "two"}\'', tool
    )
    assert args["meta"] == {"a": 1, "b": "two"}


def test_object_requires_object_not_array() -> None:
    tool = _def(
        params=[
            ToolParameter(
                name="meta",
                type=ToolParameterType.OBJECT,
                description="metadata",
                required=True,
            ),
        ]
    )
    with pytest.raises(SlashCommandError, match="must be an object"):
        parse_slash_command('/announce \'[1,2]\'', tool)


# --- Errors --------------------------------------------------------------


def test_missing_required_param(announce_def: ToolDefinition) -> None:
    with pytest.raises(SlashCommandError, match="Missing required parameter 'text'"):
        parse_slash_command("/announce", announce_def)


def test_unknown_keyword(announce_def: ToolDefinition) -> None:
    with pytest.raises(SlashCommandError, match="Unknown parameter 'pitch'"):
        parse_slash_command('/announce "hi" pitch=high', announce_def)


def test_extra_positional(announce_def: ToolDefinition) -> None:
    with pytest.raises(SlashCommandError, match="Unexpected extra arguments"):
        parse_slash_command(
            '/announce "hi" chat 50 "entry" "extra" "more"', announce_def
        )


def test_enum_validation(announce_def: ToolDefinition) -> None:
    with pytest.raises(SlashCommandError, match="must be one of"):
        parse_slash_command('/announce "hi" destination=radio', announce_def)


def test_unterminated_quote(announce_def: ToolDefinition) -> None:
    with pytest.raises(SlashCommandError, match="Could not parse arguments"):
        parse_slash_command('/announce "unterminated', announce_def)


def test_not_a_slash_command(announce_def: ToolDefinition) -> None:
    with pytest.raises(SlashCommandError, match="must start with"):
        parse_slash_command("announce hello", announce_def)


# --- Injected params are ignored -----------------------------------------


def test_injected_params_skipped_in_positional_order() -> None:
    # ``_user_id`` is injected by the executor — the parser must skip it so
    # positional arguments go to the real parameters.
    tool = _def(
        params=[
            ToolParameter(
                name="text",
                type=ToolParameterType.STRING,
                description="t",
                required=True,
            ),
            ToolParameter(
                name="_user_id",
                type=ToolParameterType.STRING,
                description="injected",
                required=False,
            ),
            ToolParameter(
                name="destination",
                type=ToolParameterType.STRING,
                description="where",
                required=False,
            ),
        ]
    )
    args = parse_slash_command('/announce "hi" speakers', tool)
    assert args == {"text": "hi", "destination": "speakers"}
    assert "_user_id" not in args


def test_injected_params_cannot_be_set_by_user() -> None:
    tool = _def(
        params=[
            ToolParameter(
                name="text",
                type=ToolParameterType.STRING,
                description="t",
                required=True,
            ),
            ToolParameter(
                name="_user_id",
                type=ToolParameterType.STRING,
                description="injected",
                required=False,
            ),
        ]
    )
    with pytest.raises(SlashCommandError, match="Unknown parameter '_user_id'"):
        parse_slash_command('/announce "hi" _user_id=hacker', tool)
