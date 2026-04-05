# Access Control Service (RBAC)

## Summary
Hierarchical role-based access control with numeric levels, per-tool permissions, overrides, and enforcement at both AI tool execution and web route levels.

## Details

### Role Hierarchy
- `admin` (level 0) — full access, immutable
- `user` (level 100) — standard access, immutable
- `everyone` (level 200) — minimum access, immutable
- Custom roles can be added at any level; lower number = more privileged
- User's effective level = min(levels of assigned roles); SYSTEM = -1 (bypasses all)

### Service
- `src/gilbert/core/services/access_control.py` — `AccessControlService`
- Capabilities: `access_control`, `ai_tools`
- Stores roles in `acl_roles` collection, overrides in `acl_tool_overrides`
- In-memory cache refreshed on mutations
- Seeds built-in roles on startup (idempotent)

### Permission Flow
1. `ToolDefinition.required_role` (default: "user") declares minimum role
2. `AIService._discover_tools(user_ctx)` filters tools by effective level
3. `AIService._execute_tool_calls()` does defense-in-depth re-check
4. Web routes use `require_role("admin")` dependency (hierarchy-aware)
5. Tool overrides in entity store can change any tool's required role

### Tool Annotations (baseline)
- **admin**: create_user, sync_users, update_persona, reset_persona, set_configuration, store_entity, all ACL write tools
- **user** (default): play_audio, announce, set_timer, play_track, etc.
- **everyone**: list_*, get_*, search_*, describe_*, synthesize, check_presence

### Web Route Protection
- `/system` → admin only
- `/entities/*` → admin only
- `/chat/*` → authenticated (existing)

## Related
- `src/gilbert/interfaces/tools.py` — `required_role` field on ToolDefinition
- `src/gilbert/core/services/ai.py` — permission enforcement in tool discovery/execution
- `src/gilbert/web/auth.py` — hierarchy-aware `require_role()` dependency
- `tests/unit/test_access_control.py` — 34 tests
