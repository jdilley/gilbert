/**
 * WarRoomFilesPanel — right-rail card on the war-room page that lists
 * workspace files in the goal's war-room workspace. Agents writing to
 * `workspace_*` tools while acting on a goal land their files here
 * (the AgentService routes the workspace ContextVar to the war-room
 * conv). The user can browse and download them.
 *
 * Subscribes to ``workspace.file.created`` and ``workspace.file.deleted``
 * scoped to this conversation so changes appear without a manual refresh.
 */

import {
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { DownloadIcon, FileIcon } from "lucide-react";
import { useWsApi } from "@/hooks/useWsApi";
import { useWebSocket } from "@/hooks/useWebSocket";
import { useEventBus } from "@/hooks/useEventBus";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { timeAgo } from "@/lib/timeAgo";
import type { WorkspaceFile } from "@/types/workspace";

function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return bytes.buffer;
}

interface Props {
  /** The war-room conversation id. Workspace tools an agent calls
   * while acting on the goal target this conv's workspace, so the
   * resulting files all share this id. */
  conversationId: string;
}

export function WarRoomFilesPanel({ conversationId }: Props) {
  const api = useWsApi();
  const { connected } = useWebSocket();
  const [files, setFiles] = useState<WorkspaceFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadFiles = useCallback(async () => {
    if (!conversationId || !connected) return;
    setLoading(true);
    setError(null);
    try {
      const result = await api.listWorkspaceFiles(conversationId);
      // Merge the three category buckets into one list — the war room
      // is mostly outputs (agent-written) but uploads/scratch may show
      // up if an agent uses those paths.
      const merged = [
        ...(result.outputs ?? []),
        ...(result.uploads ?? []),
        ...(result.scratch ?? []),
      ];
      merged.sort(
        (a, b) =>
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      );
      setFiles(merged);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load files.");
    } finally {
      setLoading(false);
    }
  }, [conversationId, connected, api]);

  useEffect(() => {
    loadFiles();
  }, [loadFiles]);

  // Live refresh on workspace file events for this conversation.
  const loadRef = useRef(loadFiles);
  loadRef.current = loadFiles;
  const handleEvent = useCallback(
    (event: { data?: { conversation_id?: string } }) => {
      if (event.data?.conversation_id === conversationId) {
        loadRef.current();
      }
    },
    [conversationId],
  );
  useEventBus("workspace.file.created", handleEvent);
  useEventBus("workspace.file.deleted", handleEvent);

  const handleDownload = useCallback(
    async (file: WorkspaceFile) => {
      try {
        const result = await api.downloadWorkspaceFile(
          file.rel_path,
          conversationId,
        );
        const buffer = base64ToArrayBuffer(result.content_base64);
        const blob = new Blob([buffer], {
          type: result.media_type || "application/octet-stream",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = result.filename || file.filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Download failed.");
      }
    },
    [api, conversationId],
  );

  return (
    <Card size="sm">
      <CardContent>
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold">Workspace files</h3>
            <Badge variant="secondary" className="text-[10px]">
              {files.length}
            </Badge>
          </div>
        </div>

        {error && (
          <div
            role="alert"
            className="mt-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs text-destructive"
          >
            {error}
          </div>
        )}

        {loading && files.length === 0 && (
          <div className="mt-3">
            <LoadingSpinner text="Loading files…" />
          </div>
        )}

        {!loading && files.length === 0 && (
          <div className="mt-3 rounded-md border border-dashed px-3 py-4 text-center text-xs text-muted-foreground">
            No files yet. Agents writing to <code>workspace_*</code> tools
            while acting on this goal will land artifacts here.
          </div>
        )}

        {files.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {files.map((f) => (
              <li
                key={f._id}
                className="flex items-start gap-2 rounded-md border bg-muted/20 px-2.5 py-1.5"
              >
                <FileIcon className="size-3.5 shrink-0 mt-1 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-1.5">
                    <span
                      className="text-sm font-medium truncate font-mono"
                      title={f.rel_path}
                    >
                      {f.filename}
                    </span>
                    <Badge
                      variant="outline"
                      className="text-[10px] uppercase"
                    >
                      {f.category}
                    </Badge>
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    {fmtSize(f.size)} · {timeAgo(f.created_at)}
                    {f.created_by ? ` · ${f.created_by}` : ""}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => handleDownload(f)}
                  className="rounded-full p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                  title="Download"
                  aria-label={`Download ${f.filename}`}
                >
                  <DownloadIcon className="size-3.5" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
