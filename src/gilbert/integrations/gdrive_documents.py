"""Google Drive document backend — serves documents from Drive folders via service account."""

import asyncio
import io
import logging
import mimetypes
from typing import Any, AsyncIterator

from gilbert.interfaces.knowledge import (
    DocumentBackend,
    DocumentContent,
    DocumentMeta,
    DocumentType,
)

logger = logging.getLogger(__name__)

_STREAM_CHUNK_SIZE = 65536

# Map Google MIME types to our DocumentType
_GOOGLE_MIME_MAP: dict[str, DocumentType] = {
    "application/vnd.google-apps.document": DocumentType.WORD,
    "application/vnd.google-apps.spreadsheet": DocumentType.EXCEL,
    "application/vnd.google-apps.presentation": DocumentType.POWERPOINT,
}

# Export MIME types for Google-native formats
_EXPORT_MAP: dict[str, str] = {
    "application/vnd.google-apps.document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.google-apps.spreadsheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.google-apps.presentation": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

_EXT_TYPE_MAP: dict[str, DocumentType] = {
    "text/plain": DocumentType.TEXT,
    "text/markdown": DocumentType.MARKDOWN,
    "text/csv": DocumentType.CSV,
    "application/json": DocumentType.JSON,
    "application/x-yaml": DocumentType.YAML,
    "application/pdf": DocumentType.PDF,
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": DocumentType.WORD,
    "application/msword": DocumentType.WORD,
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": DocumentType.EXCEL,
    "application/vnd.ms-excel": DocumentType.EXCEL,
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": DocumentType.POWERPOINT,
    "application/vnd.ms-powerpoint": DocumentType.POWERPOINT,
}


def _type_from_mime(mime: str, name: str) -> DocumentType:
    """Determine document type from MIME type and filename."""
    # Check Google-native types first
    if mime in _GOOGLE_MIME_MAP:
        return _GOOGLE_MIME_MAP[mime]
    # Check standard MIME types
    if mime in _EXT_TYPE_MAP:
        return _EXT_TYPE_MAP[mime]
    # Fallback to extension
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    from gilbert.integrations.local_documents import _EXT_MAP

    return _EXT_MAP.get(ext, DocumentType.UNKNOWN)


class GoogleDriveDocumentBackend(DocumentBackend):
    """Serves documents from a Google Drive folder or shared drive."""

    def __init__(
        self,
        name: str,
        account: str,
        folder_id: str = "",
        shared_drive_id: str = "",
    ) -> None:
        self._name = name
        self._account = account
        self._folder_id = folder_id
        self._shared_drive_id = shared_drive_id
        self._drive: Any = None
        self._file_cache: dict[str, dict[str, Any]] = {}
        # Lock to serialize Drive API calls — httplib2 is not thread-safe
        self._api_lock = asyncio.Lock()

    @property
    def source_id(self) -> str:
        return f"gdrive:{self._name}"

    @property
    def display_name(self) -> str:
        return f"Google Drive: {self._name}"

    async def initialize(self, config: dict[str, object]) -> None:
        google_svc = config.get("_google_service")
        if google_svc is None:
            raise RuntimeError("Google service required for Drive backend")
        self._drive = google_svc.build_service(
            self._account, "drive", "v3",
        )
        logger.info(
            "Google Drive backend '%s' initialized (folder=%s, shared_drive=%s)",
            self._name,
            self._folder_id or "(root)",
            self._shared_drive_id or "(none)",
        )

    async def close(self) -> None:
        self._drive = None
        self._file_cache.clear()

    def _is_google_native(self, mime: str) -> bool:
        return mime in _EXPORT_MAP

    async def _list_files(self, prefix: str = "") -> list[dict[str, Any]]:
        """List files from Drive recursively, handling pagination and subfolders."""
        if self._drive is None:
            return []

        root = self._folder_id or "root"
        files: list[dict[str, Any]] = []
        await self._list_files_recursive(root, "", prefix, files)
        return files

    async def _list_files_recursive(
        self, folder_id: str, path_prefix: str, filter_prefix: str,
        out: list[dict[str, Any]],
    ) -> None:
        """Recursively list files in a folder and its subfolders."""
        if self._drive is None:
            return

        query_parts = [f"'{folder_id}' in parents", "trashed = false"]
        q = " and ".join(query_parts)
        kwargs: dict[str, Any] = {
            "q": q,
            "fields": "nextPageToken, files(id, name, mimeType, size, modifiedTime, md5Checksum, webViewLink)",
            "pageSize": 100,
            "includeItemsFromAllDrives": True,
            "supportsAllDrives": True,
        }

        page_token: str | None = None
        subfolders: list[tuple[str, str]] = []  # (folder_id, path)

        while True:
            if page_token:
                kwargs["pageToken"] = page_token
            try:
                async with self._api_lock:
                    result = await asyncio.to_thread(
                        self._drive.files().list(**kwargs).execute
                    )
            except Exception:
                logger.warning("Drive API error listing folder %s", folder_id, exc_info=True)
                return
            for f in result.get("files", []):
                name = f.get("name", "")
                full_path = f"{path_prefix}{name}" if not path_prefix else f"{path_prefix}/{name}"

                if f.get("mimeType") == "application/vnd.google-apps.folder":
                    subfolders.append((f["id"], full_path))
                    continue

                if filter_prefix and not full_path.startswith(filter_prefix):
                    continue

                # Skip files we can't extract text from
                doc_type = _type_from_mime(f.get("mimeType", ""), name)
                if doc_type == DocumentType.UNKNOWN:
                    continue

                f["_path"] = full_path
                out.append(f)
                self._file_cache[full_path] = f

            page_token = result.get("nextPageToken")
            if not page_token:
                break

        # Recurse into subfolders
        for sub_id, sub_path in subfolders:
            await self._list_files_recursive(sub_id, sub_path, filter_prefix, out)

    def _file_to_meta(self, f: dict[str, Any]) -> DocumentMeta:
        """Convert a Drive file to DocumentMeta."""
        mime = f.get("mimeType", "")
        name = f.get("name", "")
        path = f.get("_path", name)  # full path including subfolders
        return DocumentMeta(
            source_id=self.source_id,
            path=path,
            name=name,
            document_type=_type_from_mime(mime, name),
            size_bytes=int(f.get("size", 0)),
            last_modified=f.get("modifiedTime", ""),
            mime_type=mime,
            checksum=f.get("md5Checksum", f.get("modifiedTime", "")),
            external_url=f.get("webViewLink", ""),
            metadata={"file_id": f.get("id", "")},
        )

    async def list_documents(self, prefix: str = "") -> list[DocumentMeta]:
        files = await self._list_files(prefix)
        return [self._file_to_meta(f) for f in files]

    async def get_metadata(self, path: str) -> DocumentMeta | None:
        cached = self._file_cache.get(path)
        if cached:
            return self._file_to_meta(cached)
        # Fetch fresh
        files = await self._list_files()
        for f in files:
            if f.get("_path", f.get("name", "")) == path:
                return self._file_to_meta(f)
        return None

    async def get_document(self, path: str) -> DocumentContent | None:
        meta = await self.get_metadata(path)
        if meta is None:
            return None

        file_id = meta.metadata.get("file_id", "")
        if not file_id:
            return None

        data = await self._download_file(file_id, meta.mime_type)
        if data is None:
            return None

        return DocumentContent(meta=meta, data=data)

    async def _download_file(self, file_id: str, mime_type: str) -> bytes | None:
        """Download a file from Drive. Exports Google-native formats."""
        if self._drive is None:
            return None

        try:
            if self._is_google_native(mime_type):
                export_mime = _EXPORT_MAP[mime_type]
                request = self._drive.files().export_media(
                    fileId=file_id, mimeType=export_mime
                )
            else:
                request = self._drive.files().get_media(fileId=file_id)

            from googleapiclient.http import MediaIoBaseDownload

            buf = io.BytesIO()
            downloader = MediaIoBaseDownload(buf, request)

            def _do_download() -> bytes:
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                return buf.getvalue()

            async with self._api_lock:
                return await asyncio.to_thread(_do_download)
        except Exception:
            logger.warning("Failed to download file %s", file_id, exc_info=True)
            return None

    async def upload_document(
        self, path: str, data: bytes, mime_type: str = ""
    ) -> DocumentMeta:
        if self._drive is None:
            raise RuntimeError("Drive not initialized")

        from googleapiclient.http import MediaIoBaseUpload

        file_metadata: dict[str, Any] = {"name": path}
        if self._folder_id:
            file_metadata["parents"] = [self._folder_id]

        if not mime_type:
            import mimetypes as mt
            mime_type = mt.guess_type(path)[0] or "application/octet-stream"

        media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime_type)

        kwargs: dict[str, Any] = {
            "body": file_metadata,
            "media_body": media,
            "fields": "id, name, mimeType, size, modifiedTime, md5Checksum",
        }
        if self._shared_drive_id:
            kwargs["supportsAllDrives"] = True

        async with self._api_lock:
            result = await asyncio.to_thread(
                self._drive.files().create(**kwargs).execute
            )
        self._file_cache[result["name"]] = result
        logger.info("Uploaded to Drive: %s", path)
        return self._file_to_meta(result)

    async def delete_document(self, path: str) -> None:
        cached = self._file_cache.get(path)
        if cached is None:
            raise KeyError(f"Document not found: {path}")
        file_id = cached.get("id", "")
        if self._drive is None:
            raise RuntimeError("Drive not initialized")

        kwargs: dict[str, Any] = {"fileId": file_id}
        if self._shared_drive_id:
            kwargs["supportsAllDrives"] = True

        async with self._api_lock:
            await asyncio.to_thread(self._drive.files().delete(**kwargs).execute)
        self._file_cache.pop(path, None)

    async def stream_document(self, path: str) -> AsyncIterator[bytes]:
        content = await self.get_document(path)
        if content is None:
            return
        # Yield in chunks
        data = content.data
        offset = 0
        while offset < len(data):
            yield data[offset:offset + _STREAM_CHUNK_SIZE]
            offset += _STREAM_CHUNK_SIZE
