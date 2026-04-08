import { apiFetch } from "./client";
import type { CollectionGroup, CollectionData, EntityData } from "@/types/entities";

export async function fetchCollections(): Promise<{
  groups: CollectionGroup[];
}> {
  return apiFetch("/api/entities");
}

export async function fetchCollection(
  collection: string,
  params?: URLSearchParams,
): Promise<CollectionData> {
  const qs = params ? `?${params}` : "";
  return apiFetch(`/api/entities/${encodeURIComponent(collection)}${qs}`);
}

export async function fetchEntity(
  collection: string,
  entityId: string,
): Promise<EntityData> {
  return apiFetch(
    `/api/entities/${encodeURIComponent(collection)}/${encodeURIComponent(entityId)}`,
  );
}
