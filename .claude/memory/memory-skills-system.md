# Skills System

## Summary
Agent Skills support (agentskills.io standard) for dynamically adding domain-specific instructions and tools to conversations. Users toggle skills on/off per conversation via a settings modal.

## Details

### Standard
Follows the Agent Skills open standard (agentskills.io). Skills are directories containing a `SKILL.md` file with YAML frontmatter (`name`, `description`, optional `allowed-tools`, `metadata`) and markdown instructions.

### Key Classes
- `SkillCatalogEntry` / `SkillContent` — data model in `src/gilbert/interfaces/skills.py`
  - `SkillCatalogEntry` has `scope` ("global"|"user") and `owner_id` fields for per-user scoping
- `SkillService` — core service in `src/gilbert/core/services/skills.py`
  - Implements `Service`, `ToolProvider`, `WsHandlerProvider`
  - Capabilities: `skills`, `ai_tools`, `ws_handlers`
  - Requires: `entity_storage`; Optional: `access_control`, `ai_chat`
  - AIService resolved lazily via `@property` (startup order independent)

### Skill Locations
- `skills/` — shipped with Gilbert (committed)
- `.gilbert/skills/` — global installed skills (admin), configurable via `skills.user_dir`
- `.gilbert/skills/users/<user_id>/` — per-user installed skills (invisible to other users)
- `.gilbert/skill-workspaces/<user_id>/<skill_name>/` — per-user script output sandbox

### Progressive Disclosure
1. **Catalog** (~100 tokens/skill): name + description loaded at startup
2. **Instructions** (<5000 tokens): full SKILL.md body loaded on activation
3. **Resources** (as needed): scripts/, references/, assets/ loaded by AI on demand

### Per-Conversation Activation
Active skills stored in conversation state under `active_skills` key (list of skill names). Managed via WS handlers (`skills.list`, `skills.conversation.active`, `skills.conversation.toggle`).

### AI Integration
- `_build_system_prompt()` in AIService injects active skill instructions after user memories
- Active skills' `allowed-tools` are additively merged into the tool set
- Skills provide 5 AI tools: `manage_skills` (user, scope-aware), `read_skill_file` (user), `run_skill_script` (user, workspace sandbox), `browse_skill_workspace` (user), `read_skill_workspace_file` (user)

### GitHub Installation
`manage_skills` tool with `action=install` clones repos to `.gilbert/skill-cache/`, scans for SKILL.md. Requires `scope` parameter — tool prompts AI to ask user for scope if not provided. Admins can install globally or for self; non-admins only for self. User-scoped catalog keys are namespaced as `"{owner_id}:{name}"`.

### Workspace Sandbox
Scripts run with `cwd` set to `.gilbert/skill-workspaces/<user_id>/<skill_name>/` (not the skill directory). Users can browse and download workspace files via WS handlers or AI tools.

### Frontend
- `SkillsModal` component in chat UI (sparkles icon in header)
- Groups skills by category with toggle checkboxes
- Types in `frontend/src/types/skills.ts`
- WS API methods in `useWsApi.ts`

### Configuration
```yaml
skills:
  enabled: true
  directories: ["skills"]
  cache_dir: ".gilbert/skill-cache"
  user_dir: ".gilbert/skills"
```

## Related
- [AI Service](memory-ai-service.md) — skills inject into system prompt and tool set
- [AI Context Profiles](memory-ai-context-profiles.md) — profiles provide baseline, skills add on top
- [Plugin System](memory-plugin-system.md) — similar GitHub fetch pattern
- `src/gilbert/interfaces/skills.py`
- `src/gilbert/core/services/skills.py`
- `frontend/src/components/chat/SkillsModal.tsx`
