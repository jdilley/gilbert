import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useCallback,
  useState,
  type ReactNode,
} from "react";
import type { GilbertEvent } from "@/types/events";
import { useAuth } from "./useAuth";

type EventHandler = (event: GilbertEvent) => void;

interface WebSocketContextValue {
  subscribe: (eventType: string, handler: EventHandler) => () => void;
  connected: boolean;
}

const defaultValue: WebSocketContextValue = {
  subscribe: () => () => {},
  connected: false,
};

const WebSocketContext = createContext<WebSocketContextValue>(defaultValue);

export function WebSocketProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [connected, setConnected] = useState(false);
  const handlersRef = useRef<Map<string, Set<EventHandler>>>(new Map());
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout>>(undefined);

  const subscribe = useCallback(
    (eventType: string, handler: EventHandler) => {
      if (!handlersRef.current.has(eventType)) {
        handlersRef.current.set(eventType, new Set());
      }
      handlersRef.current.get(eventType)!.add(handler);
      return () => {
        handlersRef.current.get(eventType)?.delete(handler);
      };
    },
    [],
  );

  useEffect(() => {
    if (!user) return;

    let disposed = false;
    let backoff = 1000;

    function connect() {
      if (disposed) return;

      const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
      const ws = new WebSocket(`${proto}//${window.location.host}/ws/events`);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        backoff = 1000;
      };

      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;
        if (!disposed) {
          reconnectTimeout.current = setTimeout(connect, backoff);
          backoff = Math.min(backoff * 2, 30000);
        }
      };

      ws.onmessage = (event) => {
        try {
          const parsed: GilbertEvent = JSON.parse(event.data);
          // Dispatch to type-specific handlers
          handlersRef.current
            .get(parsed.event_type)
            ?.forEach((h) => h(parsed));
          // Dispatch to wildcard handlers
          handlersRef.current.get("*")?.forEach((h) => h(parsed));
        } catch {
          // ignore parse errors
        }
      };
    }

    connect();

    return () => {
      disposed = true;
      clearTimeout(reconnectTimeout.current);
      wsRef.current?.close();
    };
  }, [user]);

  return (
    <WebSocketContext.Provider value={{ subscribe, connected }}>
      {children}
    </WebSocketContext.Provider>
  );
}

export function useWebSocket(): WebSocketContextValue {
  return useContext(WebSocketContext);
}
