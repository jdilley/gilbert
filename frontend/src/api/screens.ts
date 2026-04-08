import { apiFetch } from "./client";

export interface ConnectedScreen {
  name: string;
}

export async function fetchScreens(): Promise<ConnectedScreen[]> {
  return apiFetch("/screens/api");
}
