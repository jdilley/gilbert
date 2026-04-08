export interface GilbertEvent {
  event_type: string;
  data: Record<string, unknown>;
  source: string;
  timestamp: string;
}
