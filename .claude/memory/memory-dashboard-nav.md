# Dashboard & Nav Structure

## Summary
The frontend nav and dashboard are driven by a single RPC (`dashboard.get` in `core/services/web_api.py`) that returns a **grouped** nav structure filtered by the caller's role and by which capabilities are actually running. Top-level groups are *Chat*, *Inbox*, *MCP*, *Security*, *System*. Groups with children render as dropdowns on desktop and section headers + indented links on mobile.

## Details

### Backend — `_ws_dashboard_get`

Declares `nav_groups` as a list of dicts. Each group has:
- `key`, `label`, `description`, `icon`, `url` (default route when the group is clicked)
- `required_role` / `requires_capability` for the group itself
- `items` — list of child NavItems. Each item has label/description/icon/required_role/requires_capability plus **either** a `url` (navigation) or an `action` (RPC trigger; frontend shows a confirm dialog and invokes a named handler — e.g. `"restart_host"` calls `plugins.restart_host`). Empty items list = leaf group.

Filtering:
1. Each child's `requires_capability` is checked against the running service manager — if the service is missing or disabled, the child is dropped.
2. Each child's `required_role` is compared to `conn.user_level` via `AccessControlProvider.get_role_level`.
3. A non-leaf group whose every child is dropped disappears entirely.
4. A group's default `url` falls back to the first *visible* navigable child's URL if the hard-coded default is unreachable. Action items (no `url`) are skipped for this fallback — a group can't default-land on an RPC trigger.

The RPC returns both:
- `nav` — the filtered grouped structure (consumed by NavBar)
- `cards` — flat list of one card per visible top-level group, for the DashboardPage tile grid

### Frontend — `NavBar.tsx`

Uses `useQuery({ queryKey: ["dashboard", user?.user_id ?? "anon"] })`. **The user_id is intentional**: it scopes the cache per-user so a login/logout swap refetches automatically. Previously the cache key was just `["dashboard"]`, and the stale menu from the prior session would linger until a manual page refresh.

Rendering:
- **Desktop**: each group becomes a button in a horizontal nav. Leaf groups wrap a `<Link>`; groups with children render a `DropdownMenu` whose trigger is the group's button and whose content lists each child with icon + label + description. Dropdown items use `useNavigate().onClick(...)` rather than `render={<Link />}` because base-ui's trigger/item render-prop cloning gets fiddly when the child element has its own children.
- **Mobile**: the hamburger opens a `Sheet` drawer. Leaves render as flat rows; groups render as a muted section header followed by indented child links.

Icon mapping uses a string-keyed `ICONS` record so the backend returns lucide icon names (`"plug"`, `"shield"`, etc.) as strings rather than forcing the frontend to know every route. Colors are keyed per group (`GROUP_COLORS`).

### Route structure (App.tsx)

```
/                       → DashboardPage
/chat                   → ChatPage
/inbox                  → InboxPage
/mcp                    → redirect to /mcp/servers
/mcp/servers            → McpPage (servers Gilbert connects to)
/mcp/clients            → McpClientsPage (bearer tokens for external clients)
/security               → redirect to /security/users
/security/*             → RolesPage (tabs: Users, Roles, Tools, AI Profiles, Collections, Events, RPC)
/settings               → SettingsPage
/scheduler              → SchedulerPage
/entities               → EntitiesPage
/plugins                → PluginsPage
/system                 → SystemPage (service inspector/browser)
```

The `/security/*` subroute replaces the old `/roles/*` paths. The RolesPage's index now redirects to `/security/users` (the default tab) rather than showing Roles first.

### MCP path collision note

The backend MCP HTTP endpoint is at **`/api/mcp`**, not `/mcp`, because the frontend SPA routes live under `/mcp/*`. Before this was sorted out, navigating to `/mcp` in the SPA worked on first click but a browser refresh returned `{"error": "unauthorized"}` — the starlette `/mcp` route beat the SPA fallback. Moving the backend to `/api/mcp` freed the `/mcp/*` namespace for the SPA and made browser refreshes on MCP pages work correctly.

## Related
- `src/gilbert/core/services/web_api.py` — `_ws_dashboard_get` grouped nav
- `frontend/src/types/dashboard.ts` — `DashboardResponse` / `NavGroup` / `NavItem` types
- `frontend/src/components/layout/NavBar.tsx` — desktop dropdowns + mobile drawer
- `frontend/src/components/dashboard/DashboardPage.tsx` — tile grid from `cards`
- `frontend/src/components/roles/RolesPage.tsx` — /security/* tabs
- `frontend/src/App.tsx` — route table
- `memory-access-control.md` — the role filter behind `required_role`
- `memory-mcp.md` — why the backend MCP endpoint moved to `/api/mcp`
