"""Data models, state machine, and helpers for HA Routines."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypedDict

from .const import (
    DEFAULT_HISTORY_LIMIT,
    DEFAULT_ICON,
    DEFAULT_MAX_REMINDERS,
    DEFAULT_REMINDER_REPEAT_MINUTES,
    DEFAULT_REMINDER_TIMES,
    SCHEDULE_DAILY,
    SCHEDULE_INTERVAL_HOURS,
    STORAGE_VERSION,
)


class RoutineState(StrEnum):
    """Lifecycle states for a routine occurrence."""

    PENDING = "pending"
    REMINDER_SENT = "reminder_sent"
    SNOOZED = "snoozed"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    MISSED = "missed"


class ScheduleType(StrEnum):
    """Supported schedule modes."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    INTERVAL_HOURS = "interval_hours"
    INTERVAL_DAYS_AFTER_COMPLETION = "interval_days_after_completion"


# * Valid state transitions for the routine occurrence state machine
VALID_TRANSITIONS: dict[RoutineState, frozenset[RoutineState]] = {
    RoutineState.PENDING: frozenset(
        {
            RoutineState.REMINDER_SENT,
            # * Dashboard snooze before the reminder fires ("remind me later")
            RoutineState.SNOOZED,
            RoutineState.COMPLETED,
            RoutineState.SKIPPED,
            RoutineState.MISSED,
        }
    ),
    RoutineState.REMINDER_SENT: frozenset(
        {
            RoutineState.COMPLETED,
            RoutineState.SNOOZED,
            RoutineState.SKIPPED,
            RoutineState.MISSED,
            # * Multi-dose days: completing 08:00 returns to pending for 12:00
            RoutineState.PENDING,
        }
    ),
    RoutineState.SNOOZED: frozenset(
        {
            RoutineState.REMINDER_SENT,
            # * Pressing snooze again extends the delay
            RoutineState.SNOOZED,
            RoutineState.COMPLETED,
            RoutineState.SKIPPED,
            RoutineState.PENDING,
        }
    ),
    RoutineState.COMPLETED: frozenset({RoutineState.PENDING}),
    RoutineState.SKIPPED: frozenset({RoutineState.PENDING}),
    RoutineState.MISSED: frozenset({RoutineState.PENDING}),
}


class ScheduleConfig(TypedDict, total=False):
    """Schedule definition stored on the subentry."""

    schedule_type: str
    times: list[str]
    days_of_week: list[int]
    day_of_month: int
    interval_hours: int
    interval_days_after_completion: int
    weekdays_only: bool
    weekends_only: bool


class ReminderConfig(TypedDict, total=False):
    """Reminder and notification settings stored on the subentry."""

    reminder_times: list[str]
    repeat_interval_minutes: int
    max_reminders: int
    notifications_enabled: bool
    notify_service: str | None


class RoutineConfig(TypedDict):
    """Full routine configuration persisted in subentry.data."""

    name: str
    icon: str
    description: str | None
    schedule: ScheduleConfig
    reminders: ReminderConfig
    history_limit: int


class HistoryEntry(TypedDict):
    """Single completion record."""

    completed_at: str
    source: str


class RoutineRuntime(TypedDict):
    """Mutable runtime state for a routine, stored in HA Store."""

    routine_id: str
    state: str
    last_completed_at: str | None
    next_reminder_at: str | None
    reminder_count: int
    current_streak: int
    longest_streak: int
    missed_count: int
    snoozed_until: str | None
    completion_history: list[HistoryEntry]
    missed_history: list[str]
    skipped_history: list[str]
    completed_today: bool
    skipped_today: bool
    cycle_date: str | None
    last_reminder_at: str | None
    completed_slots: list[str]


class HaRoutinesStorage(TypedDict):
    """Root storage document."""

    version: int
    routines: dict[str, RoutineRuntime]


def can_transition(from_state: RoutineState, to_state: RoutineState) -> bool:
    """Return True when the state machine allows the transition."""
    return to_state in VALID_TRANSITIONS.get(from_state, frozenset())


def utc_now_iso() -> str:
    """Return current UTC time as ISO string."""
    return datetime.now(UTC).isoformat()


def new_id() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


def slugify(value: str) -> str:
    """Convert a display name to a stable slug."""
    slug = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return slug or "routine"


def parse_time_list(raw: str) -> list[str]:
    """Parse comma-separated HH:MM times."""
    times: list[str] = []
    for part in raw.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        hour, minute = candidate.split(":", 1)
        times.append(f"{int(hour):02d}:{int(minute):02d}")
    return times or parse_time_list(DEFAULT_REMINDER_TIMES)


def default_schedule_config(schedule_type: str = SCHEDULE_DAILY) -> ScheduleConfig:
    """Return default schedule config for a schedule type."""
    config: ScheduleConfig = {
        "schedule_type": schedule_type,
        "times": parse_time_list(DEFAULT_REMINDER_TIMES),
        "days_of_week": [0, 1, 2, 3, 4, 5, 6],
        "weekdays_only": False,
        "weekends_only": False,
    }
    if schedule_type == ScheduleType.MONTHLY:
        config["day_of_month"] = 1
    if schedule_type == ScheduleType.INTERVAL_HOURS:
        config["interval_hours"] = 4
    if schedule_type == ScheduleType.INTERVAL_DAYS_AFTER_COMPLETION:
        config["interval_days_after_completion"] = 1
    return config


def default_reminder_config() -> ReminderConfig:
    """Return default reminder settings."""
    return {
        "reminder_times": parse_time_list(DEFAULT_REMINDER_TIMES),
        "repeat_interval_minutes": DEFAULT_REMINDER_REPEAT_MINUTES,
        "max_reminders": DEFAULT_MAX_REMINDERS,
        "notifications_enabled": True,
        "notify_service": None,
    }


def default_runtime_for_config(routine_id: str) -> RoutineRuntime:
    """Create initial runtime state for a new routine."""
    return {
        "routine_id": routine_id,
        "state": RoutineState.PENDING,
        "last_completed_at": None,
        "next_reminder_at": None,
        "reminder_count": 0,
        "current_streak": 0,
        "longest_streak": 0,
        "missed_count": 0,
        "snoozed_until": None,
        "completion_history": [],
        "missed_history": [],
        "skipped_history": [],
        "completed_today": False,
        "skipped_today": False,
        "cycle_date": None,
        "last_reminder_at": None,
        "completed_slots": [],
    }


def default_storage() -> HaRoutinesStorage:
    """Return empty storage document."""
    return {
        "version": STORAGE_VERSION,
        "routines": {},
    }


def routine_config_from_flow_data(flow_data: dict[str, Any]) -> RoutineConfig:
    """Build a RoutineConfig from wizard step data."""
    schedule_type = str(flow_data.get("schedule_type", SCHEDULE_DAILY))
    schedule = default_schedule_config(schedule_type)

    if times := flow_data.get("schedule_times"):
        schedule["times"] = parse_time_list(str(times))
    if days := flow_data.get("days_of_week"):
        schedule["days_of_week"] = [int(day) for day in days]
    if day_of_month := flow_data.get("day_of_month"):
        schedule["day_of_month"] = int(day_of_month)
    if interval_hours := flow_data.get("interval_hours"):
        schedule["interval_hours"] = int(interval_hours)
    if interval_days := flow_data.get("interval_days_after_completion"):
        schedule["interval_days_after_completion"] = int(interval_days)
    if flow_data.get("weekdays_only"):
        schedule["weekdays_only"] = True
        schedule["days_of_week"] = [0, 1, 2, 3, 4]
    if flow_data.get("weekends_only"):
        schedule["weekends_only"] = True
        schedule["days_of_week"] = [5, 6]

    reminders = default_reminder_config()
    if reminder_times := flow_data.get("reminder_times"):
        reminders["reminder_times"] = parse_time_list(str(reminder_times))
    if repeat_minutes := flow_data.get("reminder_repeat_minutes"):
        reminders["repeat_interval_minutes"] = int(repeat_minutes)
    if max_reminders := flow_data.get("max_reminders"):
        reminders["max_reminders"] = int(max_reminders)
    reminders["notifications_enabled"] = bool(flow_data.get("notifications_enabled", True))
    if notify_service := flow_data.get("notify_service"):
        reminders["notify_service"] = str(notify_service)

    # * Day-based fire times come from the schedule step; keep reminder_times aligned
    if schedule_type != SCHEDULE_INTERVAL_HOURS and schedule.get("times"):
        reminders["reminder_times"] = list(schedule["times"])

    description_value = flow_data.get("description")
    description = str(description_value).strip() if description_value else None

    return {
        "name": str(flow_data["name"]).strip(),
        "icon": str(flow_data.get("icon") or DEFAULT_ICON),
        "description": description,
        "schedule": schedule,
        "reminders": reminders,
        "history_limit": int(flow_data.get("history_limit", DEFAULT_HISTORY_LIMIT)),
    }


def migrate_storage(data: dict[str, Any]) -> HaRoutinesStorage:
    """Migrate legacy or partial storage to the current schema."""
    if not data:
        return default_storage()

    routines_raw = data.get("routines", {})
    routines: dict[str, RoutineRuntime] = {}
    if isinstance(routines_raw, dict):
        for routine_id, runtime in routines_raw.items():
            if isinstance(runtime, dict):
                routines[str(routine_id)] = _normalize_runtime(str(routine_id), runtime)

    return {
        "version": int(data.get("version", STORAGE_VERSION)),
        "routines": routines,
    }


def _normalize_runtime(routine_id: str, runtime: dict[str, Any]) -> RoutineRuntime:
    """Ensure a runtime dict has all required keys."""
    state_value = str(runtime.get("state", RoutineState.PENDING))
    try:
        state = RoutineState(state_value)
    except ValueError:
        state = RoutineState.PENDING

    normalized: RoutineRuntime = {
        "routine_id": str(runtime.get("routine_id", routine_id)),
        "state": state,
        "last_completed_at": runtime.get("last_completed_at"),
        "next_reminder_at": runtime.get("next_reminder_at"),
        "reminder_count": int(runtime.get("reminder_count", 0)),
        "current_streak": int(runtime.get("current_streak", 0)),
        "longest_streak": int(runtime.get("longest_streak", 0)),
        "missed_count": int(runtime.get("missed_count", 0)),
        "snoozed_until": runtime.get("snoozed_until"),
        "completion_history": list(runtime.get("completion_history", [])),
        "missed_history": list(runtime.get("missed_history", [])),
        "skipped_history": list(runtime.get("skipped_history", [])),
        "completed_today": bool(runtime.get("completed_today", False)),
        "skipped_today": bool(runtime.get("skipped_today", False)),
        "cycle_date": runtime.get("cycle_date"),
        "last_reminder_at": runtime.get("last_reminder_at"),
        "completed_slots": [
            str(slot) for slot in list(runtime.get("completed_slots") or [])
        ],
    }
    return normalized


def get_routine_runtime(storage: HaRoutinesStorage, routine_id: str) -> RoutineRuntime | None:
    """Return runtime state for a routine id."""
    return storage["routines"].get(routine_id)
