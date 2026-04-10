import { useState, useCallback, useRef, useEffect } from "react";
import { useEventBus } from "@/hooks/useEventBus";
import { ChevronRightIcon, CheckIcon, XIcon, LoaderIcon } from "lucide-react";
import type { GilbertEvent } from "@/types/events";

interface ToolCallState {
  tool_name: string;
  tool_call_id: string;
  arguments?: Record<string, unknown>;
  status: "running" | "done" | "error";
  result_preview?: string;
}

interface ThinkingPanelProps {
  conversationId: string | null;
}

export function ThinkingPanel({ conversationId }: ThinkingPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [toolCalls, setToolCalls] = useState<ToolCallState[]>([]);
  const conversationIdRef = useRef(conversationId);
  conversationIdRef.current = conversationId;

  const handleToolStarted = useCallback((event: GilbertEvent) => {
    const data = event.data;
    if (data.conversation_id !== conversationIdRef.current) return;

    setToolCalls((prev) => [
      ...prev,
      {
        tool_name: data.tool_name as string,
        tool_call_id: data.tool_call_id as string,
        arguments: data.arguments as Record<string, unknown> | undefined,
        status: "running",
      },
    ]);
  }, []);

  const handleToolCompleted = useCallback((event: GilbertEvent) => {
    const data = event.data;
    if (data.conversation_id !== conversationIdRef.current) return;

    setToolCalls((prev) =>
      prev.map((tc) =>
        tc.tool_call_id === data.tool_call_id
          ? {
              ...tc,
              status: data.is_error ? "error" : "done",
              result_preview: data.result_preview as string | undefined,
            }
          : tc,
      ),
    );
  }, []);

  useEventBus("chat.tool.started", handleToolStarted);
  useEventBus("chat.tool.completed", handleToolCompleted);

  // Reset tool calls when conversation changes
  useEffect(() => {
    setToolCalls([]);
    setExpanded(false);
  }, [conversationId]);

  const runningCount = toolCalls.filter((tc) => tc.status === "running").length;
  const totalCount = toolCalls.length;

  return (
    <div className="rounded-lg border bg-card text-card-foreground">
      <button
        type="button"
        className="flex items-center gap-2 w-full px-3 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <LoaderIcon className="size-3.5 animate-spin shrink-0" />
        <span className="flex-1 text-left">
          {runningCount > 0
            ? `Running ${toolCalls[toolCalls.length - 1]?.tool_name}...`
            : "Thinking..."}
        </span>
        {totalCount > 0 && (
          <span className="text-xs tabular-nums">
            {totalCount} tool{totalCount !== 1 ? "s" : ""}
          </span>
        )}
        <ChevronRightIcon
          className={`size-3.5 shrink-0 transition-transform ${expanded ? "rotate-90" : ""}`}
        />
      </button>

      {expanded && totalCount > 0 && (
        <div className="border-t px-3 py-1.5 space-y-1">
          {toolCalls.map((tc) => (
            <ToolCallRow key={tc.tool_call_id} call={tc} />
          ))}
        </div>
      )}
    </div>
  );
}

function ToolCallRow({ call }: { call: ToolCallState }) {
  const [detailsOpen, setDetailsOpen] = useState(false);

  return (
    <div className="text-xs">
      <button
        type="button"
        className="flex items-center gap-1.5 w-full py-0.5 hover:text-foreground transition-colors text-muted-foreground"
        onClick={() => setDetailsOpen(!detailsOpen)}
      >
        {call.status === "running" && (
          <LoaderIcon className="size-3 animate-spin shrink-0 text-blue-500" />
        )}
        {call.status === "done" && (
          <CheckIcon className="size-3 shrink-0 text-green-500" />
        )}
        {call.status === "error" && (
          <XIcon className="size-3 shrink-0 text-red-500" />
        )}
        <span className="font-mono">{call.tool_name}</span>
        <ChevronRightIcon
          className={`size-3 shrink-0 ml-auto transition-transform ${detailsOpen ? "rotate-90" : ""}`}
        />
      </button>

      {detailsOpen && (
        <div className="ml-4.5 pl-2 border-l border-muted py-1 space-y-1 text-muted-foreground">
          {call.arguments && Object.keys(call.arguments).length > 0 && (
            <div>
              <span className="font-medium">args: </span>
              <span className="font-mono">
                {JSON.stringify(call.arguments, null, 0).slice(0, 200)}
              </span>
            </div>
          )}
          {call.result_preview && (
            <div>
              <span className="font-medium">
                {call.status === "error" ? "error: " : "result: "}
              </span>
              <span className="break-words">{call.result_preview}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
