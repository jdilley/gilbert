import { useEffect, useRef } from "react";
import { MessageBubble } from "./MessageBubble";
import type { ChatMessageWithMeta } from "@/types/chat";
import type { UIBlock } from "@/types/ui";
import { UIBlockRenderer } from "@/components/ui/UIBlockRenderer";

interface MessageListProps {
  messages: ChatMessageWithMeta[];
  uiBlocks: UIBlock[];
  isShared: boolean;
  currentUserId?: string;
  onBlockSubmit: (blockId: string, values: Record<string, unknown>) => void;
}

export function MessageList({
  messages,
  uiBlocks,
  isShared,
  currentUserId,
  onBlockSubmit,
}: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, uiBlocks]);

  // Group UI blocks by response_index for interleaving with messages.
  // Track which assistant message index each response_index maps to.
  const visibleBlocks = uiBlocks.filter(
    (block) =>
      (!block.for_user || block.for_user === currentUserId) &&
      block.exclude_user !== currentUserId,
  );

  const blocksByMsgIndex = new Map<number, UIBlock[]>();
  const unanchored: UIBlock[] = [];

  // Build a mapping from message array index to assistant response index
  let assistantCount = 0;
  const assistantIndexToMsgIndex = new Map<number, number>();
  for (let i = 0; i < messages.length; i++) {
    if (messages[i].role === "assistant") {
      assistantIndexToMsgIndex.set(assistantCount, i);
      assistantCount++;
    }
  }

  for (const block of visibleBlocks) {
    if (block.response_index != null) {
      const msgIdx = assistantIndexToMsgIndex.get(block.response_index);
      if (msgIdx != null) {
        const list = blocksByMsgIndex.get(msgIdx) ?? [];
        list.push(block);
        blocksByMsgIndex.set(msgIdx, list);
        continue;
      }
    }
    unanchored.push(block);
  }

  return (
    <div ref={containerRef} className="flex-1 overflow-y-auto overflow-x-hidden overscroll-contain">
      <div className="space-y-4 px-3 py-4 sm:px-4">
        {messages.map((msg, i) => (
          <div key={i}>
            <MessageBubble
              message={msg}
              isShared={isShared}
              currentUserId={currentUserId}
            />
            {blocksByMsgIndex.get(i)?.map((block) => (
              <div key={block.block_id} className="max-w-md mx-auto mt-4">
                <UIBlockRenderer block={block} onSubmit={onBlockSubmit} />
              </div>
            ))}
          </div>
        ))}

        {unanchored.map((block) => (
          <div key={block.block_id} className="max-w-md mx-auto">
            <UIBlockRenderer block={block} onSubmit={onBlockSubmit} />
          </div>
        ))}

        <div ref={bottomRef} />
      </div>
    </div>
  );
}
