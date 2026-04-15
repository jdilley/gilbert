/**
 * Browser-side MCP bridge.
 *
 * Forwards MCP JSON-RPC requests from Gilbert to MCP servers the user
 * has configured locally in their browser. The flow:
 *
 *   1. User adds `{slug, name, url}` entries in /mcp/local → localStorage.
 *   2. On WS connect, the bridge sends `mcp.bridge.announce` listing
 *      the slugs. Gilbert registers ephemeral session MCP clients
 *      keyed by the caller's user id and probes each one with
 *      `tools/list` (which comes back through us as an
 *      `mcp.bridge.call`).
 *   3. At AI-call time, Gilbert sends `mcp.bridge.call` frames of the
 *      shape `{server, method, params}`. The bridge builds a JSON-RPC
 *      2.0 body, POSTs it to the localStorage URL for that slug, and
 *      replies with `{ok: true, result}` (or `{ok: false, error}`).
 *
 * The server never learns the URL — that lives only in the browser.
 * The bridge is a pure transport proxy: it doesn't interpret method
 * names or result shapes.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/api/client";
import { useWebSocket } from "./useWebSocket";

export interface LocalMcpServer {
  slug: string;
  name: string;
  url: string;
}

export interface BridgeAnnounceResult {
  slug?: string;
  ok: boolean;
  error?: string;
  tool_count?: number;
}

const STORAGE_KEY = "gilbert.mcp.localServers";
const CHANGE_EVENT = "gilbert.mcp.localServers.changed";

export function loadLocalServers(): LocalMcpServer[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (e): e is LocalMcpServer =>
        !!e &&
        typeof e === "object" &&
        typeof (e as LocalMcpServer).slug === "string" &&
        typeof (e as LocalMcpServer).name === "string" &&
        typeof (e as LocalMcpServer).url === "string",
    );
  } catch {
    return [];
  }
}

export function saveLocalServers(servers: LocalMcpServer[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(servers));
  // Notify in-tab listeners (settings page ↔ bridge hook) since the
  // `storage` event only fires cross-tab.
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT));
}

/**
 * Hook for the settings page: tracks the localStorage entries with
 * React state so edits render immediately. Also exposes an `announce`
 * callback that re-sends the list to Gilbert after a change.
 */
export function useLocalMcpServers(): {
  servers: LocalMcpServer[];
  setServers: (next: LocalMcpServer[]) => void;
  announce: () => Promise<BridgeAnnounceResult[]>;
} {
  const [servers, setState] = useState<LocalMcpServer[]>(() =>
    loadLocalServers(),
  );
  const { rpc } = useWebSocket();

  useEffect(() => {
    const reload = () => setState(loadLocalServers());
    window.addEventListener(CHANGE_EVENT, reload);
    window.addEventListener("storage", reload);
    return () => {
      window.removeEventListener(CHANGE_EVENT, reload);
      window.removeEventListener("storage", reload);
    };
  }, []);

  const setServers = useCallback((next: LocalMcpServer[]) => {
    saveLocalServers(next);
    setState(next);
  }, []);

  const announce = useCallback(async (): Promise<BridgeAnnounceResult[]> => {
    const current = loadLocalServers();
    const resp = await rpc<{ results: BridgeAnnounceResult[] }>({
      type: "mcp.bridge.announce",
      servers: current.map((s) => ({ slug: s.slug, name: s.name })),
    } as Record<string, unknown>);
    return resp.results ?? [];
  }, [rpc]);

  return { servers, setServers, announce };
}

/**
 * MCP streamable-HTTP client logic.
 *
 * The MCP spec requires a three-step handshake before any real call:
 *   1. POST `initialize` — server may respond with an `Mcp-Session-Id`
 *      header that must be included in every subsequent request.
 *   2. POST `notifications/initialized` — a notification (no `id`), tells
 *      the server the client is ready.
 *   3. Normal requests (`tools/list`, `tools/call`, …).
 *
 * We cache the session id per target URL in-module so the handshake
 * only runs once per local-server entry, and serialize concurrent
 * first-time initializations behind a shared promise so we don't send
 * a thundering herd of `initialize` requests when `tools/list` and
 * `tools/call` fire back-to-back.
 *
 * On HTTP 404/400 we assume the session has been evicted (server
 * restart, TTL expiry, etc.) and retry once after re-initialising.
 *
 * `Mcp-Session-Id` is a custom response header — it will only be
 * visible to JS if the server (or the proxy in front of it) lists it
 * in `Access-Control-Expose-Headers`. If it isn't visible we proceed
 * without a session id, which works for stateless servers that don't
 * use sessions at all but will fail noisily for any server that
 * does. The settings page documents this.
 */

const MCP_PROTOCOL_VERSION = "2025-03-26";

let _jsonrpcCounter = 0;

/** Cached session id per MCP URL. An empty string means "handshake
 *  succeeded but the server didn't return a session id" — valid for
 *  stateless MCP servers. A missing entry means "never initialized". */
const sessionsByUrl = new Map<string, string>();
/** In-flight `initialize` promise per URL, so concurrent first calls
 *  share a single handshake instead of stampeding. */
const initLocks = new Map<string, Promise<string | null>>();

function nextJsonRpcId(): number {
  _jsonrpcCounter += 1;
  return _jsonrpcCounter;
}

async function readJsonRpcBody(
  resp: Response,
): Promise<Record<string, unknown>> {
  const raw = await resp.text();
  if (!raw.trim()) {
    // A notification response may legitimately have an empty body.
    return {};
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    // SSE stream: collect `data:` lines and parse the last JSON payload.
    const dataLines = raw
      .split(/\r?\n/)
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).trim())
      .filter((l) => l.length > 0);
    if (dataLines.length === 0) {
      throw new Error(
        `unparseable response (${raw.slice(0, 120)}${raw.length > 120 ? "…" : ""})`,
      );
    }
    parsed = JSON.parse(dataLines[dataLines.length - 1]);
  }
  if (!parsed || typeof parsed !== "object") {
    throw new Error("JSON-RPC response must be an object");
  }
  return parsed as Record<string, unknown>;
}

async function postMcp(
  url: string,
  body: Record<string, unknown>,
  sessionId: string | null,
): Promise<Response> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    accept: "application/json, text/event-stream",
    "mcp-protocol-version": MCP_PROTOCOL_VERSION,
  };
  if (sessionId) headers["mcp-session-id"] = sessionId;
  try {
    return await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      credentials: "omit",
      mode: "cors",
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    throw new Error(
      `fetch failed (${message}) — local MCP server unreachable or blocked by CORS/PNA`,
    );
  }
}

async function doInitialize(url: string): Promise<string | null> {
  // Step 1: initialize (a real request; expects a response).
  const initBody = {
    jsonrpc: "2.0",
    id: nextJsonRpcId(),
    method: "initialize",
    params: {
      protocolVersion: MCP_PROTOCOL_VERSION,
      capabilities: {},
      clientInfo: {
        name: "gilbert-browser-bridge",
        version: "1.0.0",
      },
    },
  };
  const initResp = await postMcp(url, initBody, null);
  if (!initResp.ok) {
    throw new Error(`initialize HTTP ${initResp.status} ${initResp.statusText}`);
  }
  const sessionId = initResp.headers.get("mcp-session-id");
  const initResult = await readJsonRpcBody(initResp);
  if (initResult.error && typeof initResult.error === "object") {
    const e = initResult.error as { message?: string; code?: number };
    throw new Error(
      `initialize JSON-RPC error ${e.code ?? ""}: ${e.message ?? JSON.stringify(initResult.error)}`,
    );
  }

  // Step 2: notifications/initialized (a notification — no id, no
  // response body expected, but we still await the POST so we know
  // the server received it before we fire the real request).
  const notifyBody = {
    jsonrpc: "2.0",
    method: "notifications/initialized",
    params: {},
  };
  const notifyResp = await postMcp(url, notifyBody, sessionId);
  // Some servers return 200 with an empty body, some return 202, some
  // stream a single SSE ack. Any 2xx is acceptable; we discard the body.
  if (notifyResp.status >= 400) {
    throw new Error(
      `notifications/initialized HTTP ${notifyResp.status} ${notifyResp.statusText}`,
    );
  }
  await notifyResp.text().catch(() => undefined);

  return sessionId;
}

async function ensureSession(url: string): Promise<string | null> {
  const cached = sessionsByUrl.get(url);
  if (cached !== undefined) return cached || null;

  const inflight = initLocks.get(url);
  if (inflight) return inflight;

  const initPromise = (async () => {
    try {
      const sid = await doInitialize(url);
      sessionsByUrl.set(url, sid ?? "");
      return sid;
    } finally {
      initLocks.delete(url);
    }
  })();
  initLocks.set(url, initPromise);
  return initPromise;
}

function forgetSession(url: string): void {
  sessionsByUrl.delete(url);
  initLocks.delete(url);
}

async function proxyMcpCall(
  url: string,
  method: string,
  params: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  let sessionId = await ensureSession(url);

  const body = {
    jsonrpc: "2.0" as const,
    id: nextJsonRpcId(),
    method,
    params,
  };

  let resp = await postMcp(url, body, sessionId);

  // Session-expired retry: 404 / 400 usually means the server lost the
  // session (restart, TTL eviction, proxy dropped the header). Drop
  // the cached id and try once more with a fresh handshake.
  if (resp.status === 404 || resp.status === 400) {
    forgetSession(url);
    sessionId = await ensureSession(url);
    resp = await postMcp(url, body, sessionId);
  }

  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
  }

  const parsed = await readJsonRpcBody(resp);
  if (parsed.error && typeof parsed.error === "object") {
    const e = parsed.error as { message?: string; code?: number };
    throw new Error(
      `JSON-RPC error ${e.code ?? ""}: ${e.message ?? JSON.stringify(parsed.error)}`,
    );
  }
  const result = parsed.result;
  if (!result || typeof result !== "object") {
    return {};
  }
  return result as Record<string, unknown>;
}

/**
 * Mount the MCP bridge: registers the `mcp.bridge.call` handler and
 * announces the user's local servers whenever the WS connects.
 */
export function useMcpBridge(): void {
  const { registerServerHandler, rpc, connected } = useWebSocket();
  const connectedRef = useRef(connected);
  connectedRef.current = connected;

  // Register the server-initiated handler once.
  useEffect(() => {
    const unregister = registerServerHandler(
      "mcp.bridge.call",
      async (frame) => {
        const f = frame as unknown as Record<string, unknown>;
        const slug = String(f.server ?? "");
        const method = String(f.method ?? "");
        const params = (f.params as Record<string, unknown>) ?? {};
        if (!slug || !method) {
          return { ok: false, error: "missing server or method" };
        }
        const servers = loadLocalServers();
        const match = servers.find((s) => s.slug === slug);
        if (!match) {
          return {
            ok: false,
            error: `unknown local MCP server ${slug}`,
          };
        }
        try {
          const result = await proxyMcpCall(match.url, method, params);
          return { ok: true, result };
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          return { ok: false, error: message };
        }
      },
    );
    return unregister;
  }, [registerServerHandler]);

  // Announce whenever the WS connects (and on local-store changes
  // while already connected).
  useEffect(() => {
    if (!connected) return;

    const doAnnounce = async () => {
      const servers = loadLocalServers();
      try {
        await rpc({
          type: "mcp.bridge.announce",
          servers: servers.map((s) => ({ slug: s.slug, name: s.name })),
        } as Record<string, unknown>);
      } catch (err) {
        if (err instanceof ApiError && err.status === 408) {
          // RPC timeout on reconnect is harmless — the next announce
          // covers it.
          return;
        }
        // Leave the console clean; this fires on every reconnect.
        // eslint-disable-next-line no-console
        console.warn("mcp.bridge.announce failed", err);
      }
    };

    void doAnnounce();

    const onChange = () => {
      if (connectedRef.current) void doAnnounce();
    };
    window.addEventListener(CHANGE_EVENT, onChange);
    return () => window.removeEventListener(CHANGE_EVENT, onChange);
  }, [connected, rpc]);
}
