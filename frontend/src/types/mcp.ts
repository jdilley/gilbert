/**
 * MCP (Model Context Protocol) types — mirrors the dataclasses in
 * ``src/gilbert/core/services/mcp.py``. Env values and bearer tokens
 * arrive masked for non-owners/non-admins (``"****"`` sentinel); the
 * edit form sends the sentinel back unchanged to preserve the stored
 * secret. Visibility (``scope`` + allow-lists) is the sole access gate
 * for MCP tools — if you can see a server, you can use its tools.
 */

export type McpScope = "private" | "shared" | "public";
export type McpTransport = "stdio" | "http" | "sse";
export type McpAuthKind = "none" | "bearer" | "oauth";

export interface McpAuthConfig {
  kind: McpAuthKind;
  bearer_token: string;
  oauth_scopes: string[];
  oauth_client_name: string;
}

export interface McpServer {
  id: string;
  name: string;
  slug: string;
  transport: McpTransport;
  // Stdio-only
  command: string[];
  env: Record<string, string>;
  cwd: string | null;
  // Remote-only
  url: string | null;
  auth: McpAuthConfig;

  enabled: boolean;
  auto_start: boolean;
  scope: McpScope;
  owner_id: string;
  allowed_roles: string[];
  allowed_users: string[];
  tool_cache_ttl_seconds: number;

  allow_sampling: boolean;
  sampling_profile: string;
  sampling_budget_tokens: number;
  sampling_budget_window_seconds: number;
  sampling_budget_used: number;

  created_at: string | null;
  updated_at: string | null;
  last_connected_at: string | null;
  last_error: string | null;
  connected: boolean;
  tool_count: number;
  needs_oauth: boolean;
  retry_count: number;
  next_retry_at: string | null;
}

export interface McpServerDraft {
  id?: string;
  name: string;
  slug: string;
  transport: McpTransport;
  command: string[];
  env: Record<string, string>;
  cwd?: string | null;
  url?: string | null;
  auth: McpAuthConfig;
  enabled: boolean;
  auto_start: boolean;
  scope: McpScope;
  allowed_roles: string[];
  allowed_users: string[];
  tool_cache_ttl_seconds: number;
  allow_sampling: boolean;
  sampling_profile: string;
  sampling_budget_tokens: number;
  sampling_budget_window_seconds: number;
}

export interface McpToolSpec {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

/**
 * An external MCP client registered with Gilbert's MCP **server**
 * endpoint. Each client carries a bearer token that external agents
 * (Claude Desktop, Cursor, etc.) use to authenticate to ``/api/mcp``.
 * The token itself is never surfaced after creation — only the
 * 6-character prefix is shown for identification.
 */
export interface McpServerClient {
  id: string;
  name: string;
  description: string;
  owner_user_id: string;
  ai_profile: string;
  active: boolean;
  token_prefix: string;
  created_at: string | null;
  updated_at: string | null;
  last_used_at: string | null;
  last_ip: string;
}

export interface McpServerClientDraft {
  name: string;
  description: string;
  owner_user_id: string;
  ai_profile: string;
}

export interface McpResourceSpec {
  uri: string;
  name: string;
  description: string;
  mime_type: string;
  size: number | null;
}

export interface McpResourceContent {
  uri: string;
  kind: "text" | "blob";
  mime_type: string;
  text: string;
  data: string;
}
