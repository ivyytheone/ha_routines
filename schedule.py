"""Schedule and next-reminder helpers for HA Routines."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .const import (
    SCHEDULE_DAILY,
    SCHEDULE_INTERVAL_DAYS_AFTER_COMPLETION,
    SCHEDULE_INTERVAL_HOURS,
    SCHEDULE_MONTHLY,
    SCHEDULE_WEEKLY,
)
from .models import (
    RoutineConfig,
    RoutineRuntime,
    RoutineState,
    dose_windows,
    normalize_routine_config,
)


def parse_hhmm(value: str) -> time:
    """Parse HH:MM into a time object."""
    hour, minute = value.split(":", 1)
    return time(hour=int(hour), minute=int(minute))


def resolve_timezone(timezone_name: str) -> ZoneInfo:
    """Return ZoneInfo for a timezone name, falling back to UTC."""
    try:
        return ZoneInfo(timezone_name)
    except Exception:
        return ZoneInfo("UTC")


def _allowed_days(config: RoutineConfig) -> set[int]:
    """Return allowed weekday indices for a routine."""
    schedule = config["schedule"]
    if schedule.get("weekdays_only"):
        return {0, 1, 2, 3, 4}
    if schedule.get("weekends_only"):
        return {5, 6}
    days = schedule.get("days_of_week")
    if days:
        return set(days)
    return set(range(7))


def reminder_times(config: RoutineConfig) -> list[str]:
    """Return sorted HH:MM strings across all dose windows (compat helper)."""
    normalized = normalize_routine_config(config)
    schedule = normalized["schedule"]
    schedule_type = schedule.get("schedule_type", SCHEDULE_DAILY)
    schedule_times = list(schedule.get("times") or [])
    reminder_list = list(normalized["reminders"].get("reminder_times") or [])

    if schedule_type == SCHEDULE_INTERVAL_HOURS:
        raw = reminder_list or schedule_times or ["08:00"]
    else:
        raw = schedule_times or reminder_list or ["08:00"]
    return sorted(raw, key=parse_hhmm)


def _reminder_times(config: RoutineConfig) -> list[str]:
    """Internal alias for reminder_times()."""
    return reminder_times(config)


def _completed_dose_indices(runtime: RoutineRuntime) -> set[str]:
    """Return completed dose indices, ignoring legacy HH:MM slot values."""
    return {
        str(slot)
        for slot in list(runtime.get("completed_slots") or [])
        if ":" not in str(slot)
    }


def current_dose_index(config: RoutineConfig, runtime: RoutineRuntime) -> int | None:
    """Return the first incomplete dose index, or None when all doses are done."""
    windows = dose_windows(normalize_routine_config(config))
    completed = _completed_dose_indices(runtime)
    for index in range(len(windows)):
        if str(index) not in completed:
            return index
    return None


def resolve_completion_slot(
    config: RoutineConfig,
    runtime: RoutineRuntime,
    now: datetime | None = None,
    timezone_name: str = "UTC",
) -> str | None:
    """Pick which dose index a completion should close."""
    del now, timezone_name
    index = current_dose_index(config, runtime)
    if index is None:
        return None
    return str(index)


def remaining_slots_today(
    config: RoutineConfig,
    runtime: RoutineRuntime,
) -> list[str]:
    """Return dose indices not yet completed today."""
    windows = dose_windows(normalize_routine_config(config))
    completed = _completed_dose_indices(runtime)
    return [str(index) for index in range(len(windows)) if str(index) not in completed]


def doses_taken_count(runtime: RoutineRuntime) -> int:
    """Count completed dose indices for today."""
    return len(_completed_dose_indices(runtime))


def doses_total_count(config: RoutineConfig) -> int:
    """Return configured doses per day."""
    return max(1, len(dose_windows(normalize_routine_config(config))))


def _combine_local(day: date, time_str: str, tz: ZoneInfo) -> datetime:
    """Combine local date and HH:MM into timezone-aware datetime."""
    return datetime.combine(day, parse_hhmm(time_str), tzinfo=tz)


def _clamp_day_of_month(year: int, month: int, day_of_month: int) -> date:
    """Return a valid date clamped to the last day of the month."""
    for candidate in range(min(day_of_month, 31), 0, -1):
        try:
            return date(year, month, candidate)
        except ValueError:
            continue
    return date(year, month, 1)


def _iter_dose_reminder_candidates(
    config: RoutineConfig,
    runtime: RoutineRuntime,
    day: date,
    today: date,
    tz: ZoneInfo,
) -> list[datetime]:
    """Build candidate reminder datetimes for one calendar day using dose windows."""
    windows = dose_windows(normalize_routine_config(config))
    completed = _completed_dose_indices(runtime)
    candidates: list[datetime] = []
    for index, times in enumerate(windows):
        if day == today and str(index) in completed:
            continue
        for time_str in times:
            candidates.append(_combine_local(day, time_str, tz))
        # * If earlier dose times already passed, later doses can still fire today
    return candidates


def compute_next_reminder_at(
    config: RoutineConfig,
    runtime: RoutineRuntime,
    now: datetime | None = None,
    timezone_name: str = "UTC",
) -> str | None:
    """Compute the next reminder datetime as UTC ISO string."""
    config = normalize_routine_config(config)
    tz = resolve_timezone(timezone_name)
    now_utc = now or datetime.now(UTC)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)
    now_local = now_utc.astimezone(tz)

    state = RoutineState(runtime["state"])
    if state == RoutineState.SKIPPED and runtime.get("skipped_today"):
        schedule_type = config["schedule"].get("schedule_type", SCHEDULE_DAILY)
        if schedule_type != SCHEDULE_INTERVAL_HOURS:
            tomorrow = now_local.date() + timedelta(days=1)
            midnight = datetime.combine(tomorrow, time(0, 0), tzinfo=tz)
            return midnight.astimezone(UTC).isoformat()

    # * Day fully done only when completed_today (all dose slots closed)
    if state == RoutineState.COMPLETED and runtime.get("completed_today"):
        schedule_type = config["schedule"].get("schedule_type", SCHEDULE_DAILY)
        if schedule_type != SCHEDULE_INTERVAL_HOURS:
            tomorrow = now_local.date() + timedelta(days=1)
            midnight = datetime.combine(tomorrow, time(0, 0), tzinfo=tz)
            return midnight.astimezone(UTC).isoformat()

    if state == RoutineState.SNOOZED and runtime.get("snoozed_until"):
        return str(runtime["snoozed_until"])

    schedule_type = config["schedule"].get("schedule_type", SCHEDULE_DAILY)

    if schedule_type == SCHEDULE_INTERVAL_HOURS:
        hours = int(config["schedule"].get("interval_hours") or 4)
        base = now_local
        if runtime.get("last_completed_at"):
            base = datetime.fromisoformat(str(runtime["last_completed_at"])).astimezone(tz)
        candidate = base + timedelta(hours=hours)
        if candidate <= now_local:
            candidate = now_local + timedelta(hours=hours)
        return candidate.astimezone(UTC).isoformat()

    if schedule_type == SCHEDULE_INTERVAL_DAYS_AFTER_COMPLETION:
        days = int(config["schedule"].get("interval_days_after_completion") or 1)
        if runtime.get("last_completed_at"):
            completed = datetime.fromisoformat(
                str(runtime["last_completed_at"])
            ).astimezone(tz)
            day = completed.date() + timedelta(days=days)
        else:
            day = now_local.date()
        times = _reminder_times(config)
        for time_str in times:
            candidate = _combine_local(day, time_str, tz)
            if candidate > now_local:
                return candidate.astimezone(UTC).isoformat()
        next_day = day + timedelta(days=1)
        return _combine_local(next_day, times[0], tz).astimezone(UTC).isoformat()

    allowed = _allowed_days(config)
    today = now_local.date()

    if schedule_type == SCHEDULE_MONTHLY:
        target_dom = int(config["schedule"].get("day_of_month") or 1)
        for month_offset in range(0, 14):
            year = now_local.year + (now_local.month + month_offset - 1) // 12
            month = (now_local.month + month_offset - 1) % 12 + 1
            day = _clamp_day_of_month(year, month, target_dom)
            if day < today:
                continue
            for candidate in _iter_dose_reminder_candidates(
                config, runtime, day, today, tz
            ):
                if candidate > now_local:
                    return candidate.astimezone(UTC).isoformat()
        return None

    # * Daily and weekly: only fire times for the current incomplete dose
    for day_offset in range(0, 15):
        day = today + timedelta(days=day_offset)
        if schedule_type == SCHEDULE_WEEKLY and day.weekday() not in allowed:
            continue
        if schedule_type == SCHEDULE_DAILY and day.weekday() not in allowed:
            continue
        day_runtime = runtime
        if day_offset > 0:
            # * Future days ignore today's completed doses
            day_runtime = {
                **runtime,
                "completed_slots": [],
                "completed_today": False,
            }
        for candidate in _iter_dose_reminder_candidates(
            config, day_runtime, day, today, tz
        ):
            if candidate > now_local:
                return candidate.astimezone(UTC).isoformat()
    return None


def should_reset_day(
    runtime: RoutineRuntime,
    now: datetime | None = None,
    timezone_name: str = "UTC",
) -> bool:
    """Return True when local calendar day changed since the active cycle date."""
    tz = resolve_timezone(timezone_name)
    now_local = (now or datetime.now(UTC)).astimezone(tz)
    today = now_local.date().isoformat()
    cycle_date = runtime.get("cycle_date")
    if cycle_date is None:
        return bool(
            runtime.get("completed_today")
            or runtime.get("skipped_today")
            or runtime.get("completed_slots")
            or RoutineState(runtime["state"])
            in (
                RoutineState.COMPLETED,
                RoutineState.SKIPPED,
                RoutineState.MISSED,
                RoutineState.PARTIAL,
            )
        )
    return str(cycle_date) != today


def apply_streak_on_complete(runtime: RoutineRuntime) -> None:
    """Increment streak counters after a successful completion."""
    runtime["current_streak"] = int(runtime.get("current_streak", 0)) + 1
    runtime["longest_streak"] = max(
        int(runtime.get("longest_streak", 0)),
        int(runtime["current_streak"]),
    )


def apply_streak_on_miss(runtime: RoutineRuntime) -> None:
    """Reset current streak when a routine is missed."""
    runtime["current_streak"] = 0
    runtime["missed_count"] = int(runtime.get("missed_count", 0)) + 1


def trim_history(runtime: RoutineRuntime, limit: int) -> None:
    """Trim history lists to the configured maximum size."""
    max_entries = max(1, limit)
    runtime["completion_history"] = list(runtime.get("completion_history", []))[-max_entries:]
    runtime["missed_history"] = list(runtime.get("missed_history", []))[-max_entries:]
    runtime["skipped_history"] = list(runtime.get("skipped_history", []))[-max_entries:]
