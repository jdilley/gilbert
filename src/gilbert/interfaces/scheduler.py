"""Scheduler interface — recurring and one-shot timed tasks."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable


class JobState(StrEnum):
    """Lifecycle state of a scheduled job."""

    PENDING = "pending"
    RUNNING = "running"
    IDLE = "idle"
    DONE = "done"
    FAILED = "failed"


class ScheduleType(StrEnum):
    """How a job is scheduled."""

    INTERVAL = "interval"
    DAILY = "daily"
    HOURLY = "hourly"
    ONCE = "once"


@dataclass
class Schedule:
    """Describes when and how often a job runs."""

    type: ScheduleType
    interval_seconds: float = 0
    hour: int = 0
    minute: int = 0

    @classmethod
    def every(cls, seconds: float) -> Schedule:
        """Run every N seconds."""
        return cls(type=ScheduleType.INTERVAL, interval_seconds=seconds)

    @classmethod
    def daily_at(cls, hour: int, minute: int = 0) -> Schedule:
        """Run daily at a specific time."""
        return cls(type=ScheduleType.DAILY, hour=hour, minute=minute)

    @classmethod
    def hourly_at(cls, minute: int = 0) -> Schedule:
        """Run hourly at a specific minute."""
        return cls(type=ScheduleType.HOURLY, minute=minute)

    @classmethod
    def once_after(cls, seconds: float) -> Schedule:
        """Run once after a delay."""
        return cls(type=ScheduleType.ONCE, interval_seconds=seconds)


@dataclass
class JobInfo:
    """Runtime info about a scheduled job."""

    name: str
    schedule: Schedule
    state: JobState = JobState.PENDING
    system: bool = False
    owner: str = ""  # user_id of creator (empty for system jobs)
    enabled: bool = True
    run_count: int = 0
    last_run: str = ""
    last_duration_seconds: float = 0.0
    last_error: str = ""


# Callback type for scheduled jobs
JobCallback = Callable[[], Awaitable[Any]]


@runtime_checkable
class SchedulerProvider(Protocol):
    """Protocol for scheduling and managing timed jobs.

    Services resolve this via ``get_capability("scheduler")`` to register
    jobs without depending on the concrete SchedulerService.
    """

    def add_job(
        self,
        name: str,
        schedule: Schedule,
        callback: JobCallback,
        system: bool = False,
        enabled: bool = True,
        owner: str = "",
    ) -> JobInfo:
        """Register a job. System jobs are not user-editable."""
        ...

    def remove_job(self, name: str, requester_id: str = "") -> None:
        """Remove a job."""
        ...

    def enable_job(self, name: str) -> None:
        """Enable a disabled job."""
        ...

    def disable_job(self, name: str) -> None:
        """Disable a running job."""
        ...

    def list_jobs(self, include_system: bool = True) -> list[JobInfo]:
        """List all registered jobs."""
        ...

    def get_job(self, name: str) -> JobInfo | None:
        """Get info about a specific job."""
        ...

    async def run_now(self, name: str) -> None:
        """Execute a job immediately, outside its schedule."""
        ...
