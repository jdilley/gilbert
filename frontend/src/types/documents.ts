export interface DocumentNode {
  name: string;
  path: string;
  is_folder: boolean;
  children?: DocumentNode[];
  size?: number;
  modified?: string;
  added?: string;
  indexed?: string;
  external_url?: string;
}

export interface DocumentSource {
  source_id: string;
  source_name: string;
  tree: DocumentNode[];
}

export interface SearchResult {
  document_name: string;
  source_id: string;
  relevance: number;
  chunk_text: string;
  page_number?: number;
  doc_type?: string;
}
