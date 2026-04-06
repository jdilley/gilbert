# Inbox Service

## Summary
Email inbox service that syncs messages from an email backend into entity storage, publishes events, and exposes AI tools for searching, reading, replying, and composing email.

## Details

### Interface
- **EmailBackend ABC** (`interfaces/email.py`) — sync source and send transport only. Methods: `list_message_ids`, `get_message`, `mark_read`, `send`.
- **Data models**: `EmailAddress` (email + name), `EmailMessage` (message_id, thread_id, subject, sender, to, cc, body_text, body_html, date, in_reply_to, headers).
- The backend is never consulted for reads — all reads come from entity storage.

### Service
- **InboxService** (`core/services/inbox.py`) — capabilities: `email`, `ai_tools`. Requires: `entity_storage`, `scheduler`. Optional: `event_bus`, `google_api`.
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
- `inbox_reply` — threaded reply (auto-sets In-Reply-To, References, threadId)
- `inbox_send` — compose and send a new email

### Events Published
- `inbox.message.received` — new message persisted (includes `is_inbound` flag)
- `inbox.message.sent` — new outbound email
- `inbox.message.replied` — reply sent in existing thread

### Gmail Backend
- **GmailBackend** (`integrations/gmail.py`) — uses google-api-python-client via GoogleService.
- Requires a Google account profile with `gmail.modify` + `gmail.send` scopes and domain-wide delegation.
- `set_service()` called by InboxService after GoogleService builds the API client.
- `list_message_ids` paginates internally via `nextPageToken`.
- Threading: Gmail's `threadId` groups conversations. Stored on each message. `in_reply_to` field stores the message's RFC822 `Message-ID` header (used as `In-Reply-To` when replying).

### Configuration
```yaml
inbox:
  enabled: false
  backend: gmail
  credential: ""        # google.accounts key name
  email_address: ""     # mailbox to impersonate
  poll_interval: 60     # seconds
  max_body_length: 50000
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
- `reply_to_message(message_id, body_html, body_text)` — reply via backend, persist outbound
- `send_message(to, subject, body_html, body_text, cc)` — send via backend, persist outbound

## Related
- [Event System](memory-event-system.md) — events published by inbox
- [Scheduler Service](memory-scheduler-service.md) — polling job
- [Storage Backend](memory-storage-backend.md) — message persistence (SQLite with WAL mode)
- `src/gilbert/interfaces/email.py` — EmailBackend ABC
- `src/gilbert/core/services/inbox.py` — InboxService
- `src/gilbert/integrations/gmail.py` — GmailBackend
- `src/gilbert/web/routes/inbox.py` — Web routes (admin only)
- `src/gilbert/web/templates/inbox.html` — Inbox UI template
- `tests/unit/test_inbox_service.py` — 23 unit tests
