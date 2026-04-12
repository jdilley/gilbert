import { useState, useRef, useCallback, useEffect, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { SendHorizontalIcon } from "lucide-react";
import { useWsApi } from "@/hooks/useWsApi";
import { useWebSocket } from "@/hooks/useWebSocket";
import type { SlashCommand, SlashParameter } from "@/types/slash";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

/** Parse ``/command ...`` into {command, restAfterCommand} or null. */
function matchSlash(input: string): { command: string; rest: string } | null {
  const m = /^\/([a-zA-Z][a-zA-Z0-9_\-]*)(?:(\s)([\s\S]*))?$/.exec(input);
  if (!m) return null;
  return { command: m[1], rest: m[3] ?? "" };
}

/** Count shell-style tokens, respecting (simple) quotes, to pick current param. */
function countCompletedTokens(rest: string): number {
  let count = 0;
  let inToken = false;
  let quote: '"' | "'" | null = null;
  for (let i = 0; i < rest.length; i++) {
    const ch = rest[i];
    if (quote) {
      if (ch === quote) quote = null;
      continue;
    }
    if (ch === '"' || ch === "'") {
      quote = ch;
      if (!inToken) {
        inToken = true;
      }
      continue;
    }
    if (ch === " " || ch === "\t") {
      if (inToken) {
        count += 1;
        inToken = false;
      }
      continue;
    }
    inToken = true;
  }
  // If the text ends mid-token (no trailing space), that token is in-progress
  // and counts as the "current" parameter index, not a completed one.
  return count;
}

export function ChatInput({
  onSend,
  disabled = false,
  placeholder = "Type a message...",
}: ChatInputProps) {
  const [message, setMessage] = useState("");
  const [suggestionIndex, setSuggestionIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { connected } = useWebSocket();
  const api = useWsApi();

  const { data: allCommands = [] } = useQuery({
    queryKey: ["slash-commands"],
    queryFn: api.listSlashCommands,
    enabled: connected,
    staleTime: 60_000,
  });

  // Re-focus when enabled (after sending completes)
  useEffect(() => {
    if (!disabled) {
      textareaRef.current?.focus();
    }
  }, [disabled]);

  const slashMatch = useMemo(() => matchSlash(message), [message]);

  // Pickable commands list: shown while the user is still typing the
  // command name (before the first space). Filters by prefix.
  const suggestions = useMemo(() => {
    if (!slashMatch) return [];
    // Only show dropdown while we're still inside the command name token
    // (i.e., user hasn't typed a space yet).
    if (message.includes(" ")) return [];
    const prefix = slashMatch.command.toLowerCase();
    return allCommands.filter((c) =>
      c.command.toLowerCase().startsWith(prefix),
    );
  }, [slashMatch, message, allCommands]);

  // Active command (once the user has picked one and typed past the name).
  const activeCommand = useMemo<SlashCommand | null>(() => {
    if (!slashMatch) return null;
    return (
      allCommands.find((c) => c.command === slashMatch.command) ?? null
    );
  }, [slashMatch, allCommands]);

  // Which parameter is currently being entered, for the help strip.
  const activeParamIndex = useMemo(() => {
    if (!activeCommand || !slashMatch) return -1;
    const tokens = countCompletedTokens(slashMatch.rest);
    const visibleParams = activeCommand.parameters.filter(
      (p) => !p.name.startsWith("_"),
    );
    return Math.min(tokens, Math.max(0, visibleParams.length - 1));
  }, [activeCommand, slashMatch]);

  // Clamp the suggestion index whenever the list changes
  useEffect(() => {
    if (suggestionIndex >= suggestions.length) {
      setSuggestionIndex(0);
    }
  }, [suggestions.length, suggestionIndex]);

  const handleSend = useCallback(() => {
    const trimmed = message.trim();
    if (!trimmed) return;
    onSend(trimmed);
    setMessage("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.focus();
    }
  }, [message, onSend]);

  function completeSuggestion(cmd: SlashCommand) {
    const next = `/${cmd.command} `;
    setMessage(next);
    setSuggestionIndex(0);
    // Resize next tick
    requestAnimationFrame(() => {
      if (textareaRef.current) {
        textareaRef.current.style.height = "auto";
        textareaRef.current.style.height =
          Math.min(textareaRef.current.scrollHeight, 150) + "px";
        textareaRef.current.focus();
      }
    });
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    const pickerOpen = suggestions.length > 0;

    if (pickerOpen) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSuggestionIndex((i) => (i + 1) % suggestions.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSuggestionIndex(
          (i) => (i - 1 + suggestions.length) % suggestions.length,
        );
        return;
      }
      if (e.key === "Tab" || (e.key === "Enter" && !e.shiftKey)) {
        e.preventDefault();
        completeSuggestion(suggestions[suggestionIndex]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        // Clear only the leading slash so the picker closes but the
        // user doesn't lose whatever else they were typing.
        setMessage(message.replace(/^\//, ""));
        return;
      }
    }

    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (!disabled) handleSend();
    }
  }

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setMessage(e.target.value);
    const el = e.target;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 150) + "px";
  }

  // Unknown slash command warning strip (only when user has typed past the
  // command name AND the command isn't in the available list).
  const unknownCommand = useMemo(() => {
    if (!slashMatch) return false;
    if (!message.includes(" ")) return false; // still picking
    if (allCommands.length === 0) return false; // not loaded yet
    return !allCommands.some((c) => c.command === slashMatch.command);
  }, [slashMatch, message, allCommands]);

  return (
    <div className="shrink-0 border-t bg-background p-3 sm:p-4">
      <div className="relative mx-auto max-w-3xl">
        {/* Autocomplete popover (commands picker) */}
        {suggestions.length > 0 && (
          <div className="absolute bottom-full left-0 right-0 mb-2 max-h-72 overflow-y-auto rounded-md border bg-popover shadow-lg">
            {suggestions.map((cmd, idx) => (
              <button
                key={cmd.command}
                type="button"
                className={`flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left text-sm ${
                  idx === suggestionIndex
                    ? "bg-accent text-foreground"
                    : "text-foreground/90 hover:bg-accent/60"
                }`}
                onMouseEnter={() => setSuggestionIndex(idx)}
                onClick={() => completeSuggestion(cmd)}
              >
                <div className="flex w-full items-center gap-2">
                  <span className="font-mono font-medium">/{cmd.command}</span>
                  <span className="truncate text-xs text-muted-foreground">
                    {cmd.provider}
                  </span>
                </div>
                <div className="line-clamp-2 text-xs text-muted-foreground">
                  {cmd.help || cmd.description}
                </div>
              </button>
            ))}
          </div>
        )}

        {/* Parameter help strip (once a command is selected) */}
        {activeCommand && suggestions.length === 0 && (
          <SlashHelp command={activeCommand} activeIndex={activeParamIndex} />
        )}

        {/* Unknown command warning */}
        {unknownCommand && (
          <div className="mb-2 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-1.5 text-xs text-destructive">
            Unknown slash command. Press <kbd>/</kbd> to see the list.
          </div>
        )}

        <div className="flex items-end gap-2">
          <Textarea
            ref={textareaRef}
            value={message}
            onChange={handleInput}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            rows={1}
            className="min-h-[40px] max-h-[150px] resize-none text-base sm:text-sm"
          />
          <Button
            onClick={handleSend}
            disabled={disabled || !message.trim()}
            size="icon"
            className="shrink-0"
          >
            <SendHorizontalIcon className="size-4" />
            <span className="sr-only">Send</span>
          </Button>
        </div>
      </div>
    </div>
  );
}

/** Inline usage strip shown while the user is filling in a command's args. */
function SlashHelp({
  command,
  activeIndex,
}: {
  command: SlashCommand;
  activeIndex: number;
}) {
  const visibleParams = command.parameters.filter(
    (p) => !p.name.startsWith("_"),
  );
  const currentParam: SlashParameter | undefined = visibleParams[activeIndex];

  return (
    <div className="mb-2 space-y-1 rounded-md border bg-muted/30 px-3 py-2 text-xs">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-mono font-medium">/{command.command}</span>
        {visibleParams.map((p, i) => {
          const active = i === activeIndex;
          const label = p.required ? `<${p.name}>` : `[${p.name}]`;
          return (
            <span
              key={p.name}
              className={`font-mono ${
                active
                  ? "text-foreground font-semibold underline decoration-dotted underline-offset-4"
                  : "text-muted-foreground"
              }`}
            >
              {label}
            </span>
          );
        })}
      </div>
      {currentParam ? (
        <div className="text-muted-foreground">
          <span className="font-mono text-foreground">{currentParam.name}</span>
          <span className="mx-1">·</span>
          <span>{currentParam.type}</span>
          {currentParam.required && (
            <span className="ml-1 text-destructive">(required)</span>
          )}
          {currentParam.description && (
            <>
              <span className="mx-1">—</span>
              <span>{currentParam.description}</span>
            </>
          )}
          {currentParam.enum && currentParam.enum.length > 0 && (
            <div>
              Options:{" "}
              {currentParam.enum.map((v) => (
                <span
                  key={v}
                  className="mr-1 rounded bg-muted px-1 font-mono"
                >
                  {v}
                </span>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="text-muted-foreground italic">
          {command.help || command.description}
        </div>
      )}
    </div>
  );
}
