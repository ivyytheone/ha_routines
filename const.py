"""Constants for the HA Routines integration."""

from __future__ import annotations

DOMAIN = "ha_routines"
STORAGE_KEY = "ha_routines_data"
STORAGE_VERSION = 1

SUBENTRY_TYPE_ROUTINE = "routine"

DEFAULT_ICON = "mdi:calendar-check"
DEFAULT_HISTORY_LIMIT = 365
DEFAULT_REMINDER_REPEAT_MINUTES = 15
DEFAULT_MAX_REMINDERS = 3
DEFAULT_REMINDER_TIMES = "08:00"
DEFAULT_SNOOZE_MINUTES = 7
SNOOZE_MIN_MINUTES = 4
SNOOZE_MAX_MINUTES = 10

CONF_NAME = "name"
CONF_ICON = "icon"
CONF_DESCRIPTION = "description"
CONF_SCHEDULE_TYPE = "schedule_type"
CONF_SCHEDULE_TIMES = "schedule_times"
CONF_DOSES_PER_DAY = "doses_per_day"
CONF_DOSE_1_TIMES = "dose_1_times"
CONF_DOSE_2_TIMES = "dose_2_times"
CONF_DOSE_3_TIMES = "dose_3_times"
CONF_DAYS_OF_WEEK = "days_of_week"
CONF_DAY_OF_MONTH = "day_of_month"
CONF_INTERVAL_HOURS = "interval_hours"
CONF_INTERVAL_DAYS_AFTER_COMPLETION = "interval_days_after_completion"
CONF_WEEKDAYS_ONLY = "weekdays_only"
CONF_WEEKENDS_ONLY = "weekends_only"
CONF_REMINDER_TIMES = "reminder_times"
CONF_REMINDER_REPEAT_MINUTES = "reminder_repeat_minutes"
CONF_MAX_REMINDERS = "max_reminders"
CONF_NOTIFICATIONS_ENABLED = "notifications_enabled"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_NOTIFICATION_OPEN_DASHBOARD = "notification_open_dashboard"
CONF_NOTIFICATION_DASHBOARD = "notification_dashboard"
CONF_NOTIFICATION_VIEW_PATH = "notification_view_path"
CONF_NOTIFICATION_CLICK_PATH = "notification_click_path"
CONF_HISTORY_LIMIT = "history_limit"

MAX_DOSES_PER_DAY = 3
DEFAULT_DOSES_PER_DAY = 1

SCHEDULE_DAILY = "daily"
SCHEDULE_WEEKLY = "weekly"
SCHEDULE_MONTHLY = "monthly"
SCHEDULE_INTERVAL_HOURS = "interval_hours"
SCHEDULE_INTERVAL_DAYS_AFTER_COMPLETION = "interval_days_after_completion"

SCHEDULE_TYPES = (
    SCHEDULE_DAILY,
    SCHEDULE_WEEKLY,
    SCHEDULE_MONTHLY,
    SCHEDULE_INTERVAL_HOURS,
    SCHEDULE_INTERVAL_DAYS_AFTER_COMPLETION,
)

PLATFORMS = ["sensor", "binary_sensor", "button"]

SERVICE_COMPLETE = "complete"
SERVICE_SNOOZE = "snooze"
SERVICE_SKIP_TODAY = "skip_today"
SERVICE_RESET = "reset"
SERVICE_TRIGGER_REMINDER = "trigger_reminder"

EVENT_ROUTINE_COMPLETED = "routine_completed"
EVENT_ROUTINE_SKIPPED = "routine_skipped"
EVENT_ROUTINE_SNOOZED = "routine_snoozed"
EVENT_ROUTINE_REMINDER_SENT = "routine_reminder_sent"

SIGNAL_ROUTINES_UPDATE = "ha_routines_update"

ATTR_ROUTINE_ID = "routine_id"
ATTR_LAST_COMPLETED = "last_completed"
ATTR_NEXT_REMINDER = "next_reminder"
ATTR_TODAY_STATUS = "today_status"
ATTR_REMINDER_COUNT = "reminder_count"
ATTR_CURRENT_STREAK = "current_streak"
ATTR_LONGEST_STREAK = "longest_streak"
ATTR_MISSED_COUNT = "missed_count"
ATTR_COMPLETION_HISTORY = "completion_history"
