# Slash Commands

## Summary
Users can invoke tools directly from the chat input as shell-style slash commands (e.g. `/announce "hello" speakers`), bypassing the AI entirely. Tool providers opt in by setting `ToolDefinition.slash_command`.

## Details

### Opt-in at the tool definition level
`ToolDefinition` (in `interfaces/tools.py`) has three slash-related fields:
- `slash_command: str | None` — when set, this tool is exposed as a slash command. Opt-in.
- `slash_group: str | None` — optional group prefix. When set, the user-visible form is `/<slash_group> <slash_command>` (e.g. `/radio start`). Services with 3+ related tools should use grouping; single-tool services stay top-level.
- `slash_help: str` — short help text for the autocomplete popover; falls back to `description`.

Not every tool makes sense as a slash command. Only opt in when the parameter layout translates sensibly to positional shell syntax.

### Parser
`core/slash_commands.py` is a pure module (no service). Key functions:
- `extract_command_name(text)` — returns the first identifier-shaped word after `/` (or `None`). Used by the dispatcher as a "this looks like a slash command" gate before doing longest-prefix lookup.
- `parse_slash_command(text, tool_def, full_command=None)` — tokenizes with `shlex`, maps positional + `key=value` / `--key=value` / `--key value` tokens to the tool's parameters in declaration order, coerces to the declared `ToolParameterType`. The `full_command` override lets callers pass a multi-word name (`"radio start"`) so the parser strips the correct prefix and echoes the right form in `Usage:` hints.
- `format_usage(tool_def, full_command=None)` — one-line usage string like `/radio start <genre:string>`. Accepts a pre-resolved full command name for grouped / namespaced forms.

Type coercion:
- STRING → passthrough
- INTEGER / NUMBER → `int()` / `float()`
- BOOLEAN → case-insensitive `true/yes/1/on` vs `false/no/0/off`
- ARRAY → JSON array if the token starts with `[`, else comma-split
- OBJECT → JSON object

Injected parameters (names starting with `_`, e.g. `_user_id`) are hidden from the user and skipped during positional assignment, and can't be set via keyword either.

### Execution path
`AIService.chat()` short-circuits at the top. It uses `_match_slash_command(text, registry)` to do a longest-prefix lookup against the RBAC-filtered command registry: grouped two-word keys like `"radio start"` win over bare one-word keys like `"radio"`. The matched full name is then passed to `_execute_slash_command()`, which:
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

### Plugin namespacing
Plugin tools are auto-prefixed with a namespace (e.g. `/currev.time_logs`) to prevent collisions with core tools. Namespace resolution in `AIService._resolve_slash_namespace`:

1. Class attribute `slash_namespace: str` on the provider service — plugins set this to pick a short, user-friendly prefix.
2. Fallback: sanitized plugin module name. Services whose `__class__.__module__` starts with `gilbert_plugin_` get the trailing segment (e.g. `gilbert_plugin_current_data_sync` → `current_data_sync`).
3. Core services (no match) get no prefix — bare `/command`.

The parser (`core/slash_commands.py`) accepts dotted names via `_COMMAND_NAME_RE = r"^/({segment}(?:\.{segment})?)(?:\s|$)"`. The frontend regex in `ChatInput.tsx` matches. Uniqueness within a namespace is enforced at discovery time with a runtime warning, and for core tools at test time via `tests/unit/test_slash_command_uniqueness.py`.

### Shared rooms
`_ws_chat_send` detects slash commands before the shared-room branch. If the message is a slash command, it bypasses the `mentions_gilbert` check (invoking a tool is always intentional), passes the untagged text through `chat()` (so the parser sees the leading `/`), and still broadcasts the result to room members via `chat.message.created`.

### Frontend
- `types/slash.ts` — `SlashCommand` / `SlashParameter` types
- `hooks/useWsApi.ts` — `listSlashCommands()` calls `slash.commands.list`
- `components/chat/ChatInput.tsx` — on `/` input, shows a popover above the textarea with filtered commands; Arrow keys navigate, Enter/Tab completes. Once a command name is selected, a parameter help strip shows the usage signature with the current parameter highlighted (based on a simple quote-aware token counter), including type, required flag, description, and enum choices. Unknown command typed → warning strip.

### Grouped commands (slash_group)
When a service exposes several related tools, declare `slash_group="radio"` alongside `slash_command="start"` so the full user-visible form becomes `/radio start`. The dispatcher composes the key at discovery time; the parser's `full_command` override handles the prefix stripping. The same leaf name (`stop`, `list`, `set`, etc.) can be reused across different groups without colliding — uniqueness is enforced on the `(group, command)` pair.

All services with 3+ slash-enabled tools in the current codebase use grouping: `/radio`, `/speaker`, `/timer`, `/acl`, `/config`, `/kb`, `/music`, `/user`, `/web`, `/db`, `/presence`. Single- or double-tool services stay top-level (`/announce`, `/greet`, `/rename`, `/memory`, `/publish_event`, `/display`, `/skills`).

### Extending
To add a new slash command: set `slash_command="name"` (optionally + `slash_group="group"`) and `slash_help="..."` on a `ToolDefinition`. Nothing else for core tools. For plugins, also set `slash_namespace = "short"` on the `Service` subclass. Autocomplete, execution, RBAC, namespacing, and chat rendering all work automatically.

### Standard practice
Per the main CLAUDE.md "Slash Commands" section and the "Slash Command Violations" checklist, **most tools should have a slash command**. Exceptions are documented: raw HTML/multi-line required inputs, opaque-ID-only inputs, complex structured arrays/objects, and mid-AI-turn callbacks. The "check the rules" audit includes slash command coverage.

## Related
- `src/gilbert/interfaces/tools.py` — `ToolDefinition.slash_command`
- `src/gilbert/core/slash_commands.py` — pure parser
- `src/gilbert/core/services/ai.py` — `_slash_commands_for_user`, `_execute_slash_command`, `_ws_slash_commands_list`
- `src/gilbert/core/services/audio_output.py` — `/announce` reference implementation
- `tests/unit/test_slash_commands.py` — parser tests
- `frontend/src/components/chat/ChatInput.tsx` — autocomplete UI
- `.claude/memory/memory-ai-service.md` — the broader AI service architecture
