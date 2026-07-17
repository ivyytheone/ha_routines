"""Config flow for HA Routines."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowContext,
    SubentryFlowResult,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .const import (
    CONF_DAY_OF_MONTH,
    CONF_DAYS_OF_WEEK,
    CONF_DESCRIPTION,
    CONF_HISTORY_LIMIT,
    CONF_ICON,
    CONF_INTERVAL_DAYS_AFTER_COMPLETION,
    CONF_INTERVAL_HOURS,
    CONF_MAX_REMINDERS,
    CONF_NAME,
    CONF_NOTIFICATIONS_ENABLED,
    CONF_NOTIFY_SERVICE,
    CONF_REMINDER_REPEAT_MINUTES,
    CONF_REMINDER_TIMES,
    CONF_SCHEDULE_TIMES,
    CONF_SCHEDULE_TYPE,
    CONF_WEEKDAYS_ONLY,
    CONF_WEEKENDS_ONLY,
    DEFAULT_HISTORY_LIMIT,
    DEFAULT_ICON,
    DEFAULT_MAX_REMINDERS,
    DEFAULT_REMINDER_REPEAT_MINUTES,
    DEFAULT_REMINDER_TIMES,
    DOMAIN,
    SCHEDULE_DAILY,
    SCHEDULE_TYPES,
    SCHEDULE_WEEKLY,
    SUBENTRY_TYPE_ROUTINE,
)
from .models import routine_config_from_flow_data, slugify


def _notify_entity_selector(hass: HomeAssistant) -> selector.EntitySelector:
    """Entity picker for Companion notify targets (falls back to any notify entity)."""
    registry = er.async_get(hass)
    has_mobile_app = any(
        entry.domain == "notify" and entry.platform == "mobile_app"
        for entry in registry.entities.values()
    )
    if has_mobile_app:
        # * Actionable Tagit/Snooze buttons require the Companion app
        return selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain="notify",
                integration="mobile_app",
                multiple=False,
            )
        )
    return selector.EntitySelector(
        selector.EntitySelectorConfig(domain="notify", multiple=False)
    )


def _parse_days_of_week(raw: str) -> list[int]:
    """Parse comma-separated weekday indices."""
    days: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        day = int(part)
        if 0 <= day <= 6:
            days.append(day)
    return days or list(range(7))


def _join_times(times: list[Any] | None, fallback: str = DEFAULT_REMINDER_TIMES) -> str:
    """Join HH:MM list into comma-separated wizard text."""
    if not times:
        return fallback
    return ", ".join(str(item) for item in times)


def _flow_data_from_routine_config(config: dict[str, Any]) -> dict[str, Any]:
    """Flatten stored RoutineConfig into wizard form fields."""
    schedule = dict(config.get("schedule") or {})
    reminders = dict(config.get("reminders") or {})
    times = list(schedule.get("times") or reminders.get("reminder_times") or ["08:00"])
    days = list(schedule.get("days_of_week") or list(range(7)))
    notify = reminders.get("notify_service")
    return {
        CONF_NAME: str(config.get("name") or ""),
        CONF_ICON: str(config.get("icon") or DEFAULT_ICON),
        CONF_DESCRIPTION: str(config.get("description") or ""),
        CONF_SCHEDULE_TYPE: str(schedule.get("schedule_type") or SCHEDULE_DAILY),
        CONF_SCHEDULE_TIMES: _join_times(times),
        CONF_DAYS_OF_WEEK: ",".join(str(day) for day in days),
        CONF_DAY_OF_MONTH: int(schedule.get("day_of_month") or 1),
        CONF_INTERVAL_HOURS: int(schedule.get("interval_hours") or 4),
        CONF_INTERVAL_DAYS_AFTER_COMPLETION: int(
            schedule.get("interval_days_after_completion") or 1
        ),
        CONF_WEEKDAYS_ONLY: bool(schedule.get("weekdays_only", False)),
        CONF_WEEKENDS_ONLY: bool(schedule.get("weekends_only", False)),
        CONF_REMINDER_TIMES: _join_times(
            list(reminders.get("reminder_times") or times), _join_times(times)
        ),
        CONF_REMINDER_REPEAT_MINUTES: int(
            reminders.get("repeat_interval_minutes") or DEFAULT_REMINDER_REPEAT_MINUTES
        ),
        CONF_MAX_REMINDERS: int(reminders.get("max_reminders") or DEFAULT_MAX_REMINDERS),
        CONF_NOTIFICATIONS_ENABLED: bool(
            reminders.get("notifications_enabled", True)
        ),
        CONF_NOTIFY_SERVICE: str(notify) if notify else None,
        CONF_HISTORY_LIMIT: int(config.get("history_limit") or DEFAULT_HISTORY_LIMIT),
    }


def _normalize_wizard_data(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize wizard fields before building RoutineConfig."""
    normalized = dict(data)
    if CONF_DAYS_OF_WEEK in normalized and isinstance(normalized[CONF_DAYS_OF_WEEK], str):
        normalized[CONF_DAYS_OF_WEEK] = _parse_days_of_week(normalized[CONF_DAYS_OF_WEEK])
    if not normalized.get(CONF_NOTIFY_SERVICE):
        normalized[CONF_NOTIFY_SERVICE] = None
    if normalized.get(CONF_DESCRIPTION) == "":
        normalized[CONF_DESCRIPTION] = None
    return normalized


def _basic_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Step 1 schema with optional defaults."""
    return vol.Schema(
        {
            vol.Required(
                CONF_NAME, default=str(defaults.get(CONF_NAME, ""))
            ): str,
            vol.Optional(
                CONF_ICON, default=str(defaults.get(CONF_ICON, DEFAULT_ICON))
            ): str,
            vol.Optional(
                CONF_DESCRIPTION,
                default=str(defaults.get(CONF_DESCRIPTION, "")),
            ): str,
        }
    )


def _schedule_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Step 2 schema with optional defaults."""
    return vol.Schema(
        {
            vol.Required(
                CONF_SCHEDULE_TYPE,
                default=str(defaults.get(CONF_SCHEDULE_TYPE, SCHEDULE_DAILY)),
            ): vol.In(SCHEDULE_TYPES),
            vol.Optional(
                CONF_SCHEDULE_TIMES,
                default=str(defaults.get(CONF_SCHEDULE_TIMES, DEFAULT_REMINDER_TIMES)),
            ): str,
            vol.Optional(
                CONF_DAYS_OF_WEEK,
                default=str(defaults.get(CONF_DAYS_OF_WEEK, "0,1,2,3,4,5,6")),
            ): str,
            vol.Optional(
                CONF_DAY_OF_MONTH,
                default=int(defaults.get(CONF_DAY_OF_MONTH, 1)),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=31)),
            vol.Optional(
                CONF_INTERVAL_HOURS,
                default=int(defaults.get(CONF_INTERVAL_HOURS, 4)),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=168)),
            vol.Optional(
                CONF_INTERVAL_DAYS_AFTER_COMPLETION,
                default=int(defaults.get(CONF_INTERVAL_DAYS_AFTER_COMPLETION, 1)),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=365)),
            vol.Optional(
                CONF_WEEKDAYS_ONLY,
                default=bool(defaults.get(CONF_WEEKDAYS_ONLY, False)),
            ): bool,
            vol.Optional(
                CONF_WEEKENDS_ONLY,
                default=bool(defaults.get(CONF_WEEKENDS_ONLY, False)),
            ): bool,
        }
    )


def _reminders_schema(
    hass: HomeAssistant, defaults: dict[str, Any]
) -> vol.Schema:
    """Step 3 schema with optional defaults."""
    schedule_default = str(
        defaults.get(CONF_SCHEDULE_TIMES)
        or defaults.get(CONF_REMINDER_TIMES)
        or DEFAULT_REMINDER_TIMES
    )
    schema: dict[Any, Any] = {
        vol.Optional(
            CONF_REMINDER_TIMES,
            default=str(defaults.get(CONF_REMINDER_TIMES, schedule_default)),
        ): str,
        vol.Optional(
            CONF_REMINDER_REPEAT_MINUTES,
            default=int(
                defaults.get(
                    CONF_REMINDER_REPEAT_MINUTES, DEFAULT_REMINDER_REPEAT_MINUTES
                )
            ),
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=1440)),
        vol.Optional(
            CONF_MAX_REMINDERS,
            default=int(defaults.get(CONF_MAX_REMINDERS, DEFAULT_MAX_REMINDERS)),
        ): vol.All(vol.Coerce(int), vol.Range(min=0, max=50)),
        vol.Optional(
            CONF_NOTIFICATIONS_ENABLED,
            default=bool(defaults.get(CONF_NOTIFICATIONS_ENABLED, True)),
        ): bool,
        vol.Optional(
            CONF_HISTORY_LIMIT,
            default=int(defaults.get(CONF_HISTORY_LIMIT, DEFAULT_HISTORY_LIMIT)),
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=5000)),
    }
    notify_default = defaults.get(CONF_NOTIFY_SERVICE)
    if notify_default:
        schema[
            vol.Optional(CONF_NOTIFY_SERVICE, default=str(notify_default))
        ] = _notify_entity_selector(hass)
    else:
        schema[vol.Optional(CONF_NOTIFY_SERVICE)] = _notify_entity_selector(hass)
    return vol.Schema(schema)


class HaRoutinesConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore[call-arg,misc]
    """Handle hub config flow for HA Routines."""

    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: config_entries.ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return subentry types supported by this integration."""
        return {SUBENTRY_TYPE_ROUTINE: RoutineSubentryFlowHandler}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the HA Routines hub entry."""
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title="HA Routines", data={})

        return self.async_show_form(step_id="user")

    async def async_on_create_entry(self, result: ConfigFlowResult) -> ConfigFlowResult:
        """Offer to add the first routine after hub setup."""
        entry = result["result"]
        await self.hass.config_entries.subentries.async_init(
            (entry.entry_id, SUBENTRY_TYPE_ROUTINE),
            context=SubentryFlowContext(source=SOURCE_USER),
        )
        return result


class RoutineSubentryFlowHandler(ConfigSubentryFlow):
    """Three-step wizard for adding or editing a routine."""

    def __init__(self) -> None:
        """Initialize wizard storage."""
        self._wizard_data: dict[str, Any] = {}
        self._is_reconfigure = False

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 1: routine name, icon, and description."""
        if user_input is not None:
            self._wizard_data.update(user_input)
            return await self.async_step_schedule()

        return self.async_show_form(
            step_id="user",
            data_schema=_basic_schema(self._wizard_data),
            description_placeholders={
                "name": str(self._wizard_data.get(CONF_NAME, "")),
            },
        )

    async def async_step_schedule(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 2: schedule configuration."""
        errors: dict[str, str] = {}

        if user_input is not None:
            schedule_type = user_input.get(CONF_SCHEDULE_TYPE, SCHEDULE_DAILY)
            if user_input.get(CONF_WEEKDAYS_ONLY) and user_input.get(CONF_WEEKENDS_ONLY):
                errors["base"] = "weekdays_weekends_conflict"
            elif schedule_type == SCHEDULE_WEEKLY and not user_input.get(
                CONF_DAYS_OF_WEEK
            ):
                errors["base"] = "days_required"
            else:
                self._wizard_data.update(user_input)
                return await self.async_step_reminders()

        return self.async_show_form(
            step_id="schedule",
            data_schema=_schedule_schema(self._wizard_data),
            errors=errors,
            description_placeholders={
                "name": str(self._wizard_data.get(CONF_NAME, "")),
            },
        )

    async def async_step_reminders(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 3: reminder settings and finish."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._wizard_data.update(user_input)
            flow_data = _normalize_wizard_data(self._wizard_data)
            config = routine_config_from_flow_data(flow_data)
            unique_id = slugify(config["name"])
            parent = self._get_entry()

            if self._is_reconfigure:
                subentry = self._get_reconfigure_subentry()
                conflict = any(
                    other.unique_id == unique_id
                    and other.subentry_id != subentry.subentry_id
                    for other in parent.subentries.values()
                )
                if conflict:
                    errors["base"] = "already_configured"
                else:
                    return self.async_update_and_abort(
                        parent,
                        subentry,
                        title=config["name"],
                        data=config,
                        unique_id=unique_id,
                    )

            # * Create path: ConfigSubentryFlow has no async_set_unique_id
            if any(
                subentry.unique_id == unique_id
                for subentry in parent.subentries.values()
            ):
                errors["base"] = "already_configured"
            else:
                return self.async_create_entry(
                    title=config["name"],
                    data=config,
                    unique_id=unique_id,
                )

        return self.async_show_form(
            step_id="reminders",
            data_schema=_reminders_schema(self.hass, self._wizard_data),
            errors=errors,
            description_placeholders={
                "name": str(self._wizard_data.get(CONF_NAME, "")),
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Re-run the full wizard with current routine values prefilled."""
        subentry = self._get_reconfigure_subentry()
        self._is_reconfigure = True
        self._wizard_data = _flow_data_from_routine_config(dict(subentry.data))
        return await self.async_step_user()
