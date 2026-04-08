import { apiFetch } from "./client";
import type { DocumentSource, SearchResult } from "@/types/documents";

export async function fetchDocuments(): Promise<{
  sources: DocumentSource[];
}> {
  return apiFetch("/api/documents");
}

export async function searchDocuments(
  query: string,
  sourceId?: string,
): Promise<{ results: SearchResult[] }> {
  const params = new URLSearchParams({ q: query });
  if (sourceId) params.set("source", sourceId);
  return apiFetch(`/api/documents/search?${params}`);
}
