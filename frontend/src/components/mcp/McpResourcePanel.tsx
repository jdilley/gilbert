import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useWsApi } from "@/hooks/useWsApi";
import { Button } from "@/components/ui/button";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { FileTextIcon } from "lucide-react";
import type { McpResourceContent, McpResourceSpec, McpServer } from "@/types/mcp";

interface McpResourcePanelProps {
  server: McpServer;
}

/**
 * Inline panel that lists a server's MCP resources and lets the user
 * preview a resource's content inline. The list is fetched lazily the
 * first time the panel mounts (since the server has to be connected
 * and resources can be expensive to enumerate), and the preview is
 * fetched on-click with no caching so the user always sees the
 * freshest contents.
 */
export function McpResourcePanel({ server }: McpResourcePanelProps) {
  const api = useWsApi();
  const [selectedUri, setSelectedUri] = useState<string | null>(null);

  const { data: resources, isLoading, isError, error } = useQuery({
    queryKey: ["mcp-resources", server.id],
    queryFn: () => api.listMcpResources(server.id),
    enabled: server.connected,
    retry: false,
  });

  const previewQuery = useQuery({
    queryKey: ["mcp-resource", server.id, selectedUri],
    queryFn: () => api.readMcpResource(server.id, selectedUri!),
    enabled: server.connected && !!selectedUri,
    retry: false,
  });

  if (!server.connected) {
    return (
      <div className="text-xs text-muted-foreground italic">
        Server must be connected to browse resources.
      </div>
    );
  }

  if (isLoading) {
    return <LoadingSpinner text="Loading resources..." className="py-2" />;
  }

  if (isError) {
    return (
      <div className="text-xs text-destructive">
        {String(error).includes("501")
          ? "This server does not advertise any resources."
          : `Failed to load resources: ${String(error)}`}
      </div>
    );
  }

  const rows = resources ?? [];

  if (rows.length === 0) {
    return (
      <div className="text-xs text-muted-foreground italic">
        This server has no resources.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        Resources ({rows.length})
      </div>
      <div className="rounded-md border divide-y">
        {rows.map((resource) => (
          <ResourceRow
            key={resource.uri}
            resource={resource}
            selected={selectedUri === resource.uri}
            onSelect={() =>
              setSelectedUri((prev) =>
                prev === resource.uri ? null : resource.uri,
              )
            }
          />
        ))}
      </div>
      {selectedUri && (
        <ResourcePreview
          uri={selectedUri}
          loading={previewQuery.isLoading}
          error={previewQuery.isError ? String(previewQuery.error) : null}
          contents={previewQuery.data ?? null}
          onClose={() => setSelectedUri(null)}
        />
      )}
    </div>
  );
}

interface ResourceRowProps {
  resource: McpResourceSpec;
  selected: boolean;
  onSelect: () => void;
}

function ResourceRow({ resource, selected, onSelect }: ResourceRowProps) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full text-left px-3 py-2 hover:bg-muted/50 flex items-start gap-2 transition-colors ${
        selected ? "bg-muted/50" : ""
      }`}
    >
      <FileTextIcon className="size-4 mt-0.5 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium truncate">
          {resource.name || resource.uri}
        </div>
        <div className="text-xs text-muted-foreground font-mono truncate">
          {resource.uri}
        </div>
        {resource.description && (
          <div className="text-xs text-muted-foreground mt-0.5">
            {resource.description}
          </div>
        )}
      </div>
      <div className="text-xs text-muted-foreground shrink-0">
        {resource.mime_type || "—"}
        {resource.size != null && ` · ${formatSize(resource.size)}`}
      </div>
    </button>
  );
}

interface ResourcePreviewProps {
  uri: string;
  loading: boolean;
  error: string | null;
  contents: McpResourceContent[] | null;
  onClose: () => void;
}

function ResourcePreview({
  uri,
  loading,
  error,
  contents,
  onClose,
}: ResourcePreviewProps) {
  return (
    <div className="rounded-md border p-3 bg-muted/30">
      <div className="flex items-center justify-between mb-2">
        <code className="text-xs">{uri}</code>
        <Button variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
      {loading && <LoadingSpinner text="Loading..." className="py-2" />}
      {error && (
        <div className="text-xs text-destructive">Failed: {error}</div>
      )}
      {contents && contents.length > 0 && (
        <div className="space-y-2">
          {contents.map((c, i) => (
            <div key={i}>
              {c.kind === "text" ? (
                <pre className="text-xs whitespace-pre-wrap break-words max-h-64 overflow-y-auto font-mono">
                  {c.text || "(empty)"}
                </pre>
              ) : (
                <div className="text-xs text-muted-foreground italic">
                  {c.mime_type || "binary"} blob ({c.data.length} bytes)
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      {contents && contents.length === 0 && (
        <div className="text-xs text-muted-foreground italic">
          Empty resource.
        </div>
      )}
    </div>
  );
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
