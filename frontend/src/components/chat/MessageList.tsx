import { useEffect, useRef } from "react";
import { TurnBubble } from "./TurnBubble";
import type { ChatTurn } from "@/types/chat";
import type { UIBlock } from "@/types/ui";
import { UIBlockRenderer } from "@/components/ui/UIBlockRenderer";

interface MessageListProps {
  turns: ChatTurn[];
  uiBlocks: UIBlock[];
  isShared: boolean;
  currentUserId?: string;
  onBlockSubmit: (blockId: string, values: Record<string, unknown>) => void;
}

export function MessageList({
  turns,
  uiBlocks,
  isShared,
  currentUserId,
  onBlockSubmit,
}: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, uiBlocks]);

  // UI blocks are anchored by ``response_index`` which the backend
  // sets to the 0-based turn index (== count of user messages minus
  // one at the time the block was produced). Since we render one
  // ``TurnBubble`` per turn, response_index maps 1:1 onto the turn
  // array index — no extra bookkeeping required.
  const visibleBlocks = uiBlocks.filter(
    (block) =>
      (!block.for_user || block.for_user === currentUserId) &&
      block.exclude_user !== currentUserId,
  );

  const blocksByTurnIndex = new Map<number, UIBlock[]>();
  const unanchored: UIBlock[] = [];

  for (const block of visibleBlocks) {
    if (
      block.response_index != null &&
      block.response_index >= 0 &&
      block.response_index < turns.length
    ) {
      const turnIdx = block.response_index;
      const list = blocksByTurnIndex.get(turnIdx) ?? [];
      list.push(block);
      blocksByTurnIndex.set(turnIdx, list);
      continue;
    }
    unanchored.push(block);
  }

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto overflow-x-hidden overscroll-contain"
    >
      <div className="space-y-6 px-3 py-4 sm:px-4">
        {turns.map((turn, i) => (
          <div key={i}>
            <TurnBubble
              turn={turn}
              isShared={isShared}
              currentUserId={currentUserId}
            />
            {blocksByTurnIndex.get(i)?.map((block) => (
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
