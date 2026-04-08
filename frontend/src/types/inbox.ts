export interface InboxStats {
  total: number;
  unread: number;
}

export interface InboxMessage {
  _id: string;
  date: string;
  from: string;
  to?: string;
  cc?: string;
  subject: string;
  snippet: string;
  inbound: boolean;
  thread_id?: string;
}

export interface MessageDetail extends InboxMessage {
  body_text?: string;
  body_html?: string;
}

export interface PendingReply {
  _id: string;
  status: string;
  scheduled_time: string;
  recipient: string;
  subject: string;
  preview: string;
  collection: string;
}
