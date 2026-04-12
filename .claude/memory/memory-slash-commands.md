# Slash Commands

## Summary
Users can invoke tools directly from the chat input as shell-style slash commands (e.g. `/announce "hello" speakers`), bypassing the AI entirely. Tool providers opt in by setting `ToolDefinition.slash_command`.

## Details

### Opt-in at the tool definition level
`ToolDefinition` (in `interfaces/tools.py`) has two optional fields:
- `slash_command: str | None` — when set, this tool is exposed as `/<slash_command>` in the chat input autocomplete and executable without the AI.
- `slash_help: str` — short help text for the autocomplete popover; falls back to `description`.

Not every tool makes sense as a slash command. Only opt in when the parameter layout translates sensibly to positional shell syntax.

### Parser
`core/slash_commands.py` is a pure module (no service). Key functions:
- `extract_command_name(text)` — returns the command name for `/word ...` inputs, `None` otherwise. Excludes `/path/to/file` and plain text that happens to start with `/`.
- `parse_slash_command(text, tool_def)` — tokenizes with `shlex`, maps positional + `key=value` / `--key=value` / `--key value` tokens to the tool's parameters in declaration order, coerces to the declared `ToolParameterType`. Raises `SlashCommandError` with an actionable `Usage: ...` hint on failure.
- `format_usage(tool_def)` — one-line usage string like `/announce <text:string> [destination:string]`.

Type coercion:
- STRING → passthrough
- INTEGER / NUMBER → `int()` / `float()`
- BOOLEAN → case-insensitive `true/yes/1/on` vs `false/no/0/off`
- ARRAY → JSON array if the token starts with `[`, else comma-split
- OBJECT → JSON object

Injected parameters (names starting with `_`, e.g. `_user_id`) are hidden from the user and skipped during positional assignment, and can't be set via keyword either.

### Execution path
`AIService.chat()` short-circuits at the top: if `extract_command_name(user_message)` returns a name present in `_slash_commands_for_user(user_ctx)`, it calls `_execute_slash_command()`, which:
1. Records the raw `/cmd ...` text as the user message (with author_id/author_name set so shared rooms render correctly).
2. Parses the arguments; parse errors become the assistant reply with `Usage:` hint.
3. Injects `_user_id`, `_user_name`, `_user_roles`, and `_room_members` into arguments (same as the AI-driven tool path).
4. Publishes `chat.tool.started` / `chat.tool.completed` events on the event bus.
5. Calls `provider.execute_tool(tool_def.name, arguments)`. `ToolOutput` UI blocks are extracted and serialized like the agentic loop does.
6. Appends an assistant `Message` with `tool_calls` / `tool_results` populated (matching the shape of AI-driven tool use), so the frontend renders them identically.
7. Persists the conversation and returns the standard `(response_text, conversation_id, ui_blocks, tool_usage)` tuple.

Unknown commands (`/somethingMadeUp`) get a friendly "Unknown slash command 'X'. Available: ..." error instead of being leaked to the AI.

### RBAC
`_slash_commands_for_user` calls `_discover_tools(user_ctx=user_ctx)` with NO profile — slash commands respect RBAC but ignore AI context profile filtering (profiles apply only to AI calls). Users only see commands their role permits.

### WebSocket RPC
- `slash.commands.list` (in `AIService.get_ws_handlers`) → returns the RBAC-filtered list for the caller, used by `ChatInput.tsx` to drive autocomplete. Each entry includes `command`, `tool_name`, `provider`, `description`, `help`, `usage`, `required_role`, and `parameters` (name/type/description/required/default/enum).
- ACL default: `everyone` (200) — filtered response is per-user-safe. Defined in `interfaces/acl.py` `DEFAULT_RPC_PERMISSIONS`.

### Shared rooms
`_ws_chat_send` detects slash commands before the shared-room branch. If the message is a slash command, it bypasses the `mentions_gilbert` check (invoking a tool is always intentional), passes the untagged text through `chat()` (so the parser sees the leading `/`), and still broadcasts the result to room members via `chat.message.created`.

### Frontend
- `types/slash.ts` — `SlashCommand` / `SlashParameter` types
- `hooks/useWsApi.ts` — `listSlashCommands()` calls `slash.commands.list`
- `components/chat/ChatInput.tsx` — on `/` input, shows a popover above the textarea with filtered commands; Arrow keys navigate, Enter/Tab completes. Once a command name is selected, a parameter help strip shows the usage signature with the current parameter highlighted (based on a simple quote-aware token counter), including type, required flag, description, and enum choices. Unknown command typed → warning strip.

### Extending
To add a new slash command: set `slash_command="name"` (and optionally `slash_help="..."`) on a `ToolDefinition`. Nothing else. Autocomplete, execution, RBAC, and chat rendering all work automatically.

## Related
- `src/gilbert/interfaces/tools.py` — `ToolDefinition.slash_command`
- `src/gilbert/core/slash_commands.py` — pure parser
- `src/gilbert/core/services/ai.py` — `_slash_commands_for_user`, `_execute_slash_command`, `_ws_slash_commands_list`
- `src/gilbert/core/services/audio_output.py` — `/announce` reference implementation
- `tests/unit/test_slash_commands.py` — parser tests
- `frontend/src/components/chat/ChatInput.tsx` — autocomplete UI
- `.claude/memory/memory-ai-service.md` — the broader AI service architecture
