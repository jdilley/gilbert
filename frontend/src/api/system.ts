import { apiFetch } from "./client";
import type { ServiceInfo } from "@/types/system";

export async function fetchServices(): Promise<{ services: ServiceInfo[] }> {
  return apiFetch("/api/system");
}
