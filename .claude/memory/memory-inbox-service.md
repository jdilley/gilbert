# Inbox Service

## Summary
Email inbox service that syncs messages from an email backend into entity storage, publishes events, and exposes AI tools for searching, reading, replying, and composing email.

## Details

### Interface
- **EmailBackend ABC** (`interfaces/email.py`) — sync source and send transport only. Methods: `list_message_ids`, `get_message`, `mark_read`, `send`.
- **Data models**: `EmailAddress` (email + name), `EmailMessage` (message_id, thread_id, subject, sender, to, cc, body_text, body_html, date, in_reply_to, headers).
- The backend is never consulted for reads — all reads come from entity storage.

### Service
- **InboxService** (`core/services/inbox.py`) — capabilities: `email`, `ai_tools`, `ws_handlers`. Requires: `entity_storage`, `scheduler`. Optional: `event_bus`, `knowledge`, `configuration`.
- Polls via scheduler system job (`inbox-poll`). Lists message IDs (up to 500, paginated), walks newest-first, stops at first known message. Only fetches full content for new messages.
- After syncing a message, marks it as read in the remote provider.
- Detects own outbound messages by comparing sender to configured `email_address`.
- No read/unread concept locally — if we have it, it's "read". No `inbox_mark` tool.
- Truncates bodies exceeding `max_body_length`.

### Sync Flow
1. `list_message_ids()` — one cheap API call per page (query: `in:inbox OR in:sent`)
2. Walk IDs newest-first, `exists()` check against entity store, stop at first known
3. For each new ID: `get_message()` → persist → `mark_read()` in backend → publish event
4. On steady-state: typically 0-2 new messages per poll. On fresh store: backfills everything.

### AI Tools
- `inbox_search` — search by sender, subject, limit
- `inbox_read` — full message content by ID
- `inbox_reply` — threaded reply (auto-sets In-Reply-To, References, threadId); supports `attach_documents` param with knowledge store document IDs
- `inbox_send` — compose and send a new email; supports `attach_documents` param with knowledge store document IDs

### Events Published
- `inbox.message.received` — new message persisted (includes `is_inbound` flag)
- `inbox.message.sent` — new outbound email
- `inbox.message.replied` — reply sent in existing thread

### Gmail Backend
- **GmailBackend** (`integrations/gmail.py`) — self-contained backend using google-api-python-client with its own `service_account_json` config param.
- No external GoogleService dependency. Backend builds its own Gmail API client from the service account JSON during `initialize()`.
- Requires domain-wide delegation with `gmail.modify` + `gmail.send` scopes.
- `list_message_ids` paginates internally via `nextPageToken`.
- Threading: Gmail's `threadId` groups conversations. Stored on each message. `in_reply_to` field stores the message's RFC822 `Message-ID` header (used as `In-Reply-To` when replying).

### Configuration
```yaml
inbox:
  enabled: false
  backend: gmail
  email_address: ""     # mailbox to impersonate
  poll_interval: 60     # seconds
  max_body_length: 50000
  settings:
    service_account_json: ""  # inline service account JSON
```

### Design Decisions
- No auto-processing — InboxService only syncs, persists, publishes. Plugins/services subscribe to `inbox.message.received` events.
- No subject filtering or domain gating in core — plugins apply their own filtering.
- No read/unread tracking — presence in the store means it's been synced. Simplifies the model.
- Backend is fully abstracted — Gmail today, IMAP or others can be added by implementing EmailBackend.

### Web UI
- Admin-only inbox browser at `/inbox` (route: `web/routes/inbox.py`, template: `web/templates/inbox.html`)
- Dashboard card with envelope icon, nav link in header (admin only)
- API endpoints: `GET /inbox/api/stats`, `GET /inbox/api/messages`, `GET /inbox/api/messages/{id}`, `GET /inbox/api/threads/{thread_id}`
- Client-side filtering by sender, subject; auto-refresh every 30s; live updates via GilbertEvents WebSocket (debounced)
- Message detail modal with headers, body, and "View Thread" button for multi-message threads
- List view uses `include_body=False` for performance (returns snippets, strips body)
- Stats loaded async via JS (non-blocking page render)
- All JS deferred to `DOMContentLoaded` to avoid race with `GilbertEvents` defined in base.html

### Service Methods
- `search_messages(sender, subject, limit, include_body)` — query entity store
- `get_message(message_id)` — single message from entity store
- `get_thread(thread_id)` — all messages in a thread, date ascending
- `get_stats()` — returns `{total, inbound}` counts
- `reply_to_message(message_id, body_html, body_text, cc, attachments, reply_to, from_name)` — reply via backend, persist outbound. `reply_to` sets the Reply-To header (e.g., route replies to a shared group alias); `from_name` sets a friendly display name on the From header.
- `send_message(to, subject, body_html, body_text, cc, attachments, reply_to, from_name)` — send via backend, persist outbound. Same `reply_to` / `from_name` semantics as above.

### InboxAIChatService (`core/services/inbox_ai_chat.py`)
- Subscribes to `inbox.message.received`, checks sender allowlist, runs AI chat, replies via email
- Capabilities: `email_ai_chat`, `ai_tools`. Requires: `email`, `ai_chat`, `entity_storage`. Optional: `event_bus`, `users`, `knowledge`.
- Thread → conversation mapping persisted in `inbox_ai_chat_threads` collection
- Resolves sender to UserContext via UserService for RBAC
- Strips quoted reply text (Gmail/Outlook/Apple Mail patterns)
- Converts markdown responses to styled HTML via `markdown` library
- Implements ToolProvider with `email_attach` tool so the AI can queue document attachments for the reply
- Injects `[EMAIL CONTEXT]` prefix telling the AI not to use `inbox_send`/`inbox_reply` tools (those create separate emails); the service handles the reply automatically
- Queued attachments are collected after `chat()` and passed to `reply_to_message()`
- Uses `asyncio.Lock` to prevent concurrent message processing from mixing pending attachments
- Config: `inbox_ai_chat.enabled`, `allowed_emails`, `allowed_domains`

### Email Attachments
- `EmailAttachment` dataclass (`interfaces/email.py`): filename, data (bytes), mime_type
- `EmailBackend.send()` accepts `attachments: list[EmailAttachment]`
- Gmail backend encodes as MIME multipart/mixed with multipart/alternative body
- InboxService `reply_to_message()` and `send_message()` pass through attachments
- AI tools accept `attach_documents` array of knowledge store document IDs (e.g., `local:docs/report.pdf`)
- Documents resolved via KnowledgeService backends at send time

### Reply-To and From Display Name
- `EmailBackend.send()` accepts `reply_to: EmailAddress | None` and `from_name: str`
- When `from_name` is set, the Gmail backend formats the From header as `"Name" <email>` via `str(EmailAddress(...))`
- When `reply_to` is set, the Gmail backend adds a `Reply-To` header. Useful for routing customer replies to a shared group alias (e.g. `sales@company.com`) so the whole team sees the thread even though the mailbox sender is a single assistant account.
- These parameters are pass-through only — InboxService does not persist them on the stored outbound record (the stored record still uses `sender_email` = the configured inbox address)

## Related
- [Event System](memory-event-system.md) — events published by inbox
- [Scheduler Service](memory-scheduler-service.md) — polling job
- [Storage Backend](memory-storage-backend.md) — message persistence (SQLite with WAL mode)
- `src/gilbert/interfaces/email.py` — EmailBackend ABC
- `src/gilbert/core/services/inbox.py` — InboxService
- `src/gilbert/integrations/gmail.py` — GmailBackend (self-contained, owns service_account_json)
- `src/gilbert/web/routes/inbox.py` — Web routes (admin only)
- `src/gilbert/web/templates/inbox.html` — Inbox UI template
- `tests/unit/test_inbox_service.py` — InboxService unit tests
- `tests/unit/test_gmail_backend.py` — Gmail backend MIME construction (From, Reply-To, etc.)
