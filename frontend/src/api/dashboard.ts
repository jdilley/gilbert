import { apiFetch } from "./client";
import type { DashboardCard } from "@/types/dashboard";

export async function fetchDashboard(): Promise<{ cards: DashboardCard[] }> {
  return apiFetch<{ cards: DashboardCard[] }>("/api/dashboard");
}
