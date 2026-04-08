import type { ConversationMember } from "@/types/chat";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";

interface MemberPanelProps {
  members: ConversationMember[];
  ownerId?: string;
  currentUserId?: string;
  onKick: (userId: string) => void;
}

export function MemberPanelContent({
  members,
  ownerId,
  currentUserId,
  onKick,
}: MemberPanelProps) {
  const isOwner = currentUserId === ownerId;

  return (
    <div className="p-3">
      <h3 className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground mb-3 px-1">
        Members ({members.length})
      </h3>
      <div className="space-y-1">
        {members.map((m) => (
          <div
            key={m.user_id}
            className="group flex items-center gap-2.5 rounded-lg px-2 py-1.5"
          >
            <Avatar className="size-6">
              <AvatarFallback className="text-[10px]">
                {m.display_name.charAt(0).toUpperCase()}
              </AvatarFallback>
            </Avatar>
            <span className="flex-1 truncate text-sm">{m.display_name}</span>
            {m.user_id === ownerId && (
              <Badge variant="secondary" className="text-[10px] px-1">
                Owner
              </Badge>
            )}
            {isOwner && m.user_id !== currentUserId && (
              <Button
                variant="ghost"
                size="xs"
                className="hidden text-destructive group-hover:inline-flex"
                onClick={() => onKick(m.user_id)}
              >
                Kick
              </Button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
