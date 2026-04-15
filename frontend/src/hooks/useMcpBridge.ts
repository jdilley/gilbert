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

/** Per-request timeout for fetches to the local MCP server. Shorter
 *  than the server-side bridge timeout so a stuck handler surfaces
 *  a clear error back to Gilbert instead of letting the server time
 *  out with an opaque ``TimeoutError``. */
const FETCH_TIMEOUT_MS = 20_000;

/** Enable verbose bridge logging by running
 *  ``localStorage.setItem("gilbert.mcp.debug", "1")`` in DevTools.
 *  Logged output is prefixed with ``[mcp-bridge]``. */
function bridgeDebug(...args: unknown[]): void {
  try {
    if (localStorage.getItem("gilbert.mcp.debug") === "1") {
      // eslint-disable-next-line no-console
      console.debug("[mcp-bridge]", ...args);
    }
  } catch {
    // localStorage may be disabled in some contexts — silently skip.
  }
}

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

/**
 * Read a JSON-RPC response body, handling both ``application/json``
 * and ``text/event-stream`` content types. For SSE, we stream chunks
 * through a ``ReadableStream`` reader and return as soon as we see
 * the first complete event containing a JSON object — then cancel
 * the reader so the server can close its side. That matters for MCP
 * SDK servers that keep the HTTP response open for the session
 * lifetime: calling ``resp.text()`` on those would hang forever
 * because the stream never reaches EOF.
 */
async function readJsonRpcBody(
  resp: Response,
): Promise<Record<string, unknown>> {
  const contentType = (resp.headers.get("content-type") || "").toLowerCase();

  if (contentType.includes("application/json") || contentType === "") {
    const raw = await resp.text();
    if (!raw.trim()) return {};
    // Some SDKs lie about content-type, so fall back to SSE parsing
    // if plain JSON doesn't parse.
    try {
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") {
        throw new Error("JSON-RPC response must be an object");
      }
      return parsed as Record<string, unknown>;
    } catch (err) {
      if (raw.includes("data:")) {
        return parseSseText(raw);
      }
      throw err;
    }
  }

  if (contentType.includes("text/event-stream")) {
    return streamFirstSseEvent(resp);
  }

  // Unknown — try text then fall back
  const raw = await resp.text();
  if (!raw.trim()) return {};
  if (raw.includes("data:")) return parseSseText(raw);
  return JSON.parse(raw) as Record<string, unknown>;
}

function parseSseText(raw: string): Record<string, unknown> {
  for (const event of raw.split(/\r?\n\r?\n/)) {
    const dataLines = event
      .split(/\r?\n/)
      .filter((l) => l.startsWith("data:"))
      .map((l) => l.slice(5).trim())
      .filter((l) => l.length > 0);
    if (dataLines.length === 0) continue;
    const dataText = dataLines.join("");
    try {
      const parsed = JSON.parse(dataText);
      if (parsed && typeof parsed === "object") {
        return parsed as Record<string, unknown>;
      }
    } catch {
      // Event not a complete JSON — keep scanning.
    }
  }
  throw new Error(
    `SSE body has no parseable data events (${raw.slice(0, 120)})`,
  );
}

/** Stream an SSE response and return the first JSON object we see. */
async function streamFirstSseEvent(
  resp: Response,
): Promise<Record<string, unknown>> {
  const body = resp.body;
  if (!body) {
    throw new Error("response has no body");
  }
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      // eslint-disable-next-line no-cond-assign
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const event = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const dataLines = event
          .split(/\r?\n/)
          .filter((l) => l.startsWith("data:"))
          .map((l) => l.slice(5).trim())
          .filter((l) => l.length > 0);
        if (dataLines.length === 0) continue;
        const dataText = dataLines.join("");
        try {
          const parsed = JSON.parse(dataText);
          if (parsed && typeof parsed === "object") {
            // Got it — bail out so the server can close the stream.
            try {
              await reader.cancel();
            } catch {
              // ignore
            }
            return parsed as Record<string, unknown>;
          }
        } catch {
          // Not a complete JSON payload yet — continue reading.
        }
      }
    }
    throw new Error("SSE stream closed without a complete event");
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // ignore
    }
  }
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

  const controller = new AbortController();
  const timer = setTimeout(
    () => controller.abort(new DOMException("fetch timeout", "AbortError")),
    FETCH_TIMEOUT_MS,
  );

  bridgeDebug("POST", url, "method=", body.method, "session=", sessionId);
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      credentials: "omit",
      mode: "cors",
      signal: controller.signal,
    });
    bridgeDebug(
      "POST", url, "→", resp.status,
      "content-type=", resp.headers.get("content-type"),
      "session=", resp.headers.get("mcp-session-id"),
    );
    return resp;
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error(
        `fetch timeout after ${FETCH_TIMEOUT_MS}ms (method=${String(body.method)}) — ` +
          "local MCP server stalled or response body never closed",
      );
    }
    const message = err instanceof Error ? err.message : String(err);
    throw new Error(
      `fetch failed (${message}) — local MCP server unreachable or blocked by CORS/PNA`,
    );
  } finally {
    clearTimeout(timer);
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
  bridgeDebug("initialize ok — sessionId=", sessionId);
  const initResult = await readJsonRpcBody(initResp);
  if (initResult.error && typeof initResult.error === "object") {
    const e = initResult.error as { message?: string; code?: number };
    throw new Error(
      `initialize JSON-RPC error ${e.code ?? ""}: ${e.message ?? JSON.stringify(initResult.error)}`,
    );
  }
  bridgeDebug("initialize body parsed");

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
  // stream a single SSE ack. Any 2xx is acceptable; we drain the body
  // (bounded by the fetch AbortController) so the proxy can close the
  // connection.
  if (notifyResp.status >= 400) {
    throw new Error(
      `notifications/initialized HTTP ${notifyResp.status} ${notifyResp.statusText}`,
    );
  }
  try {
    if (notifyResp.body) {
      const reader = notifyResp.body.getReader();
      try {
        // Drain up to one chunk, then cancel — we don't care about
        // the content, we just want to release the connection.
        await reader.read();
        await reader.cancel();
      } finally {
        try {
          reader.releaseLock();
        } catch {
          // ignore
        }
      }
    }
  } catch {
    // ignore drain errors
  }
  bridgeDebug("notifications/initialized ok");

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
  bridgeDebug("proxyMcpCall", url, method);
  let sessionId = await ensureSession(url);
  bridgeDebug("proxyMcpCall sessionId=", sessionId);

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
    bridgeDebug("session expired, re-initializing", resp.status);
    forgetSession(url);
    sessionId = await ensureSession(url);
    resp = await postMcp(url, body, sessionId);
  }

  if (!resp.ok) {
    throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
  }

  const parsed = await readJsonRpcBody(resp);
  bridgeDebug("proxyMcpCall parsed", method, Object.keys(parsed));
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
        bridgeDebug("handler fired", { slug, method });
        if (!slug || !method) {
          return { ok: false, error: "missing server or method" };
        }
        const servers = loadLocalServers();
        const match = servers.find((s) => s.slug === slug);
        if (!match) {
          bridgeDebug("no match for slug in localStorage", slug, servers);
          return {
            ok: false,
            error: `unknown local MCP server ${slug}`,
          };
        }
        try {
          const result = await proxyMcpCall(match.url, method, params);
          bridgeDebug("handler reply ok", method);
          return { ok: true, result };
        } catch (err) {
          const message = err instanceof Error ? err.message : String(err);
          bridgeDebug("handler reply error", method, message);
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
