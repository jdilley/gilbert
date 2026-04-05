# Scheduler Service

## Summary
Manages recurring and one-shot timed tasks. Supports system jobs (registered by services) and user jobs (timers/alarms set via AI chat). All periodic work in Gilbert must go through this service.

## Details

### Interface
- `src/gilbert/interfaces/scheduler.py` — `Schedule` (every/daily/hourly/once factories), `JobInfo` (with owner field), `JobState`, `JobCallback`

### Service
- `src/gilbert/core/services/scheduler.py` — `SchedulerService`
- Always registered (core service, not optional)
- Capabilities: `scheduler`, `ai_tools`
- System jobs: registered by other services, cannot be removed — only paused/resumed by admins
- User jobs: created/cancelled via AI tools, publish events when fired
- Timer ownership: user jobs track owner, non-admins can only cancel their own

### Job Lifecycle
- States: pending → running → idle (recurring) or done/failed (one-shot)
- Each job runs in its own asyncio task via `_run_job_loop()`
- `_next_delay()` calculates sleep time based on schedule type
- Jobs can be enabled/disabled, run immediately via `run_now()`

### AI Tools
- `list_timers` (everyone) — list all jobs (system + user)
- `set_timer` (user) — one-shot timer, fires `timer.fired` event, tracks owner
- `set_alarm` (user) — recurring alarm, fires `alarm.fired` event, tracks owner
- `cancel_timer` (user) — remove own timer; admins can cancel any; system timers cannot be cancelled
- `pause_timer` (admin) — disable a timer/alarm (system or user)
- `resume_timer` (admin) — re-enable a paused timer/alarm

### Services Using the Scheduler
- `PresenceService` → `presence-poll` (every 30s)
- `DoorbellService` → `doorbell-poll` (every 5s)
- `KnowledgeService` → `knowledge-sync` (every 300s)

## Related
- `tests/unit/test_scheduler_service.py` — 18 tests
