# Knowledge Service (Document Store)

## Summary
Multi-backend document knowledge store with ChromaDB vector search. Indexes documents from local filesystem and Google Drive, supports semantic search via AI tools and web UI.

## Details

### Interface
- `src/gilbert/interfaces/knowledge.py` — `DocumentBackend` ABC, `DocumentMeta`, `DocumentContent`, `DocumentChunk`, `SearchResult`, `SearchResponse`, `DocumentType` enum
- Documents identified by `source_id:path` (document_id)

### Service
- `src/gilbert/core/services/knowledge.py` — `KnowledgeService`
- Capabilities: `knowledge`, `ai_tools`
- Aggregates multiple backends in `dict[str, DocumentBackend]`
- ChromaDB `PersistentClient` at `.gilbert/chromadb/`, collection "documents"
- Background sync via scheduler system job (default 5min)
- Change detection: compares `last_modified` against ChromaDB metadata

### Document Processing
- `src/gilbert/core/documents/extractors.py` — text extraction per type (text, MD, CSV, JSON, YAML, PDF via pypdf, Word via python-docx, Excel via openpyxl, PowerPoint via python-pptx)
- `src/gilbert/core/documents/chunking.py` — paragraph-based chunking with overlap, sentence sub-splitting, PDF page tracking

### Backends
- `src/gilbert/integrations/local_documents.py` — `LocalDocumentBackend`: recursive dir scan, path traversal prevention, extension-to-type mapping
- `src/gilbert/integrations/gdrive_documents.py` — `GoogleDriveDocumentBackend`: service account via GoogleService, exports Google-native docs as Office formats

### AI Tools (all default to "user" role)
- `search_documents` — semantic vector search
- `list_documents`, `list_document_sources` — browse
- `get_document` — retrieve full text
- `upload_document` (admin) — upload + auto-index
- `index_document` (admin) — manual re-indexing

### Web UI
- `/documents` — browse by source with filter tabs
- `/documents/search` — search interface with relevance scores
- `/documents/serve/{source_id}/{path}` — stream documents from any backend
- Dashboard card: "Documents" (user role)

### Dependencies (heavy)
- chromadb (pulls sentence-transformers + torch ~2GB)
- pypdf, python-docx, openpyxl, python-pptx

## Related
- `src/gilbert/core/services/scheduler.py` — runs periodic sync job
- `src/gilbert/core/services/google.py` — provides Drive API clients
- `tests/unit/test_knowledge_service.py` — 16 tests
