import { useEffect } from "react";
import { useWebSocket } from "./useWebSocket";
import type { GilbertEvent } from "@/types/events";

/**
 * Subscribe to a specific event type. Handler is called for each matching event.
 * Automatically subscribes on mount and unsubscribes on unmount.
 */
export function useEventBus(
  eventType: string,
  handler: (event: GilbertEvent) => void,
): void {
  const { subscribe } = useWebSocket();

  useEffect(() => {
    return subscribe(eventType, handler);
  }, [eventType, handler, subscribe]);
}
