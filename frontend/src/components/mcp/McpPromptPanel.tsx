import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useWsApi } from "@/hooks/useWsApi";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LoadingSpinner } from "@/components/ui/LoadingSpinner";
import { Badge } from "@/components/ui/badge";
import { MessageSquareIcon, CopyIcon, CheckIcon } from "lucide-react";
import type { McpServer } from "@/types/mcp";

interface McpPromptPanelProps {
  server: McpServer;
}

interface McpPromptArgument {
  name: string;
  description: string;
  required: boolean;
}

interface McpPromptSpec {
  name: string;
  title: string;
  description: string;
  arguments: McpPromptArgument[];
}

interface McpPromptMessage {
  role: "user" | "assistant" | "system";
  content: {
    type: string;
    text: string;
    mime_type: string;
    uri: string;
    data: string;
  };
}

interface McpPromptResult {
  description: string;
  messages: McpPromptMessage[];
}

/**
 * Inline panel that lists a server's MCP prompts and lets the user
 * render one with argument values. The rendered messages get a
 * copy-to-clipboard button so the user can paste them into the chat
 * input — Part 3.2 keeps the integration deliberately simple
 * (clipboard, not direct chat insertion) so it works no matter where
 * the user is when they browse prompts.
 */
export function McpPromptPanel({ server }: McpPromptPanelProps) {
  const api = useWsApi();
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [argValues, setArgValues] = useState<Record<string, string>>({});
  const [rendered, setRendered] = useState<McpPromptResult | null>(null);
  const [renderError, setRenderError] = useState<string | null>(null);
  const [rendering, setRendering] = useState(false);

  const { data: prompts, isLoading, isError, error } = useQuery({
    queryKey: ["mcp-prompts", server.id],
    queryFn: () => api.listMcpPrompts(server.id),
    enabled: server.connected,
    retry: false,
  });

  const selected = prompts?.find((p) => p.name === selectedName) ?? null;

  const runPrompt = async () => {
    if (!selectedName) return;
    // Require all required args.
    if (selected) {
      const missing = selected.arguments
        .filter((a) => a.required && !argValues[a.name])
        .map((a) => a.name);
      if (missing.length > 0) {
        setRenderError(`Missing required argument(s): ${missing.join(", ")}`);
        return;
      }
    }
    setRendering(true);
    setRenderError(null);
    try {
      const result = await api.renderMcpPrompt(
        server.id, selectedName, argValues,
      );
      setRendered(result);
    } catch (e) {
      setRenderError(String(e));
      setRendered(null);
    } finally {
      setRendering(false);
    }
  };

  const pick = (name: string) => {
    setSelectedName(name);
    setArgValues({});
    setRendered(null);
    setRenderError(null);
  };

  if (!server.connected) {
    return (
      <div className="text-xs text-muted-foreground italic">
        Server must be connected to browse prompts.
      </div>
    );
  }

  if (isLoading) {
    return <LoadingSpinner text="Loading prompts..." className="py-2" />;
  }

  if (isError) {
    return (
      <div className="text-xs text-destructive">
        {String(error).includes("501")
          ? "This server does not advertise any prompts."
          : `Failed to load prompts: ${String(error)}`}
      </div>
    );
  }

  const rows = prompts ?? [];

  if (rows.length === 0) {
    return (
      <div className="text-xs text-muted-foreground italic">
        This server has no prompts.
      </div>
    );
  }

  return (
    <div className="space-y-2">
      <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        Prompts ({rows.length})
      </div>
      <div className="rounded-md border divide-y">
        {rows.map((p) => (
          <PromptRow
            key={p.name}
            prompt={p}
            selected={selectedName === p.name}
            onSelect={() => pick(p.name)}
          />
        ))}
      </div>

      {selected && (
        <div className="rounded-md border p-3 bg-muted/30 space-y-3">
          <div className="text-sm font-medium">{selected.title || selected.name}</div>
          {selected.description && (
            <div className="text-xs text-muted-foreground">{selected.description}</div>
          )}
          {selected.arguments.length > 0 && (
            <div className="space-y-2">
              {selected.arguments.map((arg) => (
                <div key={arg.name}>
                  <Label
                    htmlFor={`prompt-arg-${arg.name}`}
                    className="text-xs"
                  >
                    {arg.name}
                    {arg.required && (
                      <span className="text-destructive ml-1">*</span>
                    )}
                  </Label>
                  <Input
                    id={`prompt-arg-${arg.name}`}
                    value={argValues[arg.name] ?? ""}
                    onChange={(e) =>
                      setArgValues((prev) => ({
                        ...prev,
                        [arg.name]: e.target.value,
                      }))
                    }
                    placeholder={arg.description}
                  />
                </div>
              ))}
            </div>
          )}
          <div className="flex gap-2">
            <Button size="sm" onClick={runPrompt} disabled={rendering}>
              {rendering ? "Rendering..." : "Render"}
            </Button>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setSelectedName(null)}
            >
              Close
            </Button>
          </div>
          {renderError && (
            <div className="text-xs text-destructive">{renderError}</div>
          )}
          {rendered && <RenderedPromptView result={rendered} />}
        </div>
      )}
    </div>
  );
}

interface PromptRowProps {
  prompt: McpPromptSpec;
  selected: boolean;
  onSelect: () => void;
}

function PromptRow({ prompt, selected, onSelect }: PromptRowProps) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full text-left px-3 py-2 hover:bg-muted/50 flex items-start gap-2 transition-colors ${
        selected ? "bg-muted/50" : ""
      }`}
    >
      <MessageSquareIcon className="size-4 mt-0.5 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium truncate">
          {prompt.title || prompt.name}
        </div>
        {prompt.description && (
          <div className="text-xs text-muted-foreground mt-0.5">
            {prompt.description}
          </div>
        )}
      </div>
      {prompt.arguments.length > 0 && (
        <Badge variant="outline" className="text-xs">
          {prompt.arguments.length} arg
          {prompt.arguments.length === 1 ? "" : "s"}
        </Badge>
      )}
    </button>
  );
}

interface RenderedPromptViewProps {
  result: McpPromptResult;
}

function RenderedPromptView({ result }: RenderedPromptViewProps) {
  const [copied, setCopied] = useState(false);

  const fullText = result.messages
    .map((m) => (m.content.type === "text" ? m.content.text : ""))
    .filter(Boolean)
    .join("\n\n");

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(fullText);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard API can fail in insecure contexts — silently ignore.
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Rendered ({result.messages.length} message
          {result.messages.length === 1 ? "" : "s"})
        </div>
        <Button size="sm" variant="outline" onClick={copy}>
          {copied ? (
            <>
              <CheckIcon className="size-3 mr-1" />
              Copied
            </>
          ) : (
            <>
              <CopyIcon className="size-3 mr-1" />
              Copy
            </>
          )}
        </Button>
      </div>
      <div className="space-y-2">
        {result.messages.map((m, i) => (
          <div
            key={i}
            className="rounded-md border p-2 text-xs bg-background"
          >
            <div className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1">
              {m.role}
            </div>
            {m.content.type === "text" ? (
              <pre className="whitespace-pre-wrap break-words font-mono">
                {m.content.text}
              </pre>
            ) : (
              <div className="italic text-muted-foreground">
                {m.content.type} content ({m.content.mime_type || "unknown"})
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

