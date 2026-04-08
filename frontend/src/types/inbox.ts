export interface InboxStats {
  total: number;
  unread: number;
}

export interface InboxMessage {
  message_id: string;
  thread_id?: string;
  date: string;
  sender_email: string;
  sender_name: string;
  subject: string;
  snippet: string;
  is_inbound: boolean;
}

export interface MessageDetail extends InboxMessage {
  to: string[];
  cc: string[];
  body_text?: string;
  body_html?: string;
  in_reply_to?: string;
}

export interface PendingReply {
  id: string;
  collection: string;
  lead_id: string;
  customer_email: string;
  subject: string;
  status: string;
  is_initial: boolean;
  send_at: string;
  created_at: string;
  response_text: string;
}
