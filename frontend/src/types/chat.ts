import type { UIBlock } from "./ui";

export type FileAttachment =
  | {
      kind: "image";
      name?: string;
      media_type: string;
      data: string;
    }
  | {
      kind: "document";
      name: string;
      media_type: string;
      data: string;
    }
  | {
      kind: "text";
      name: string;
      media_type: string;
      text: string;
    };

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  author_id?: string;
  author_name?: string;
  attachments?: FileAttachment[];
}

export interface ConversationSummary {
  conversation_id: string;
  title: string;
  preview: string;
  updated_at: string;
  message_count: number;
  shared: boolean;
  member_count?: number;
  members?: ConversationMember[];
  visibility?: "public" | "invite";
  is_member?: boolean;
  is_invited?: boolean;
}

export interface ConversationMember {
  user_id: string;
  display_name: string;
  role?: "owner" | "member";
}

export interface ConversationDetail {
  conversation_id: string;
  title: string;
  messages: ChatMessageWithMeta[];
  ui_blocks: UIBlock[];
  updated_at: string;
  shared: boolean;
  members?: ConversationMember[];
  invites?: { user_id: string; display_name: string }[];
  owner_id?: string;
}

export interface ToolUsageEntry {
  tool_name: string;
  is_error: boolean;
  arguments?: Record<string, unknown>;
  result?: string;
}

export interface ChatResponse {
  response: string;
  conversation_id: string;
  ui_blocks: UIBlock[];
  tool_usage?: ToolUsageEntry[];
}

export interface ChatMessageWithMeta extends ChatMessage {
  tool_usage?: ToolUsageEntry[];
}
