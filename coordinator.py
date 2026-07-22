"""Data coordinator for HA Routines."""

from __future__ import annotations

import logging
import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    ATTR_ROUTINE_ID,
    DEFAULT_HISTORY_LIMIT,
    DOMAIN,
    EVENT_ROUTINE_COMPLETED,
    EVENT_ROUTINE_REMINDER_SENT,
    EVENT_ROUTINE_SKIPPED,
    EVENT_ROUTINE_SNOOZED,
    SIGNAL_ROUTINES_UPDATE,
    SNOOZE_MAX_MINUTES,
    SNOOZE_MIN_MINUTES,
    SUBENTRY_TYPE_ROUTINE,
)
from .models import (
    HaRoutinesStorage,
    HistoryEntry,
    RoutineConfig,
    RoutineRuntime,
    RoutineState,
    can_transition,
    default_runtime_for_config,
    get_routine_runtime,
    normalize_routine_config,
    utc_now_iso,
)
from .schedule import (
    apply_streak_on_complete,
    apply_streak_on_miss,
    compute_next_reminder_at,
    remaining_slots_today,
    resolve_completion_slot,
    resolve_timezone,
    trim_history,
)
from .storage import async_save_storage

_LOGGER = logging.getLogger(__name__)


class RoutinesCoordinator(DataUpdateCoordinator[HaRoutinesStorage]):
    """Manage HA Routines runtime state and persistence."""

    def __init__(
        self,
        hass: HomeAssistant,
        store: Store[HaRoutinesStorage],
        data: HaRoutinesStorage,
        entry: ConfigEntry | None = None,
    ) -> None:
        """Initialize coordinator."""
        self.store = store
        self.entry = entry
        self.scheduler: Any = None
        # * Callable accepts config_subentry_id= on modern HA AddConfigEntryEntitiesCallback
        self._async_add_sensors: Callable[..., None] | None = None
        self._async_add_binary_sensors: Callable[..., None] | None = None
        self._async_add_buttons: Callable[..., None] | None = None
        self._tracked_routine_ids: set[str] = set()
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=None,
        )
        self.async_set_updated_data(data)

    @property
    def timezone_name(self) -> str:
        """Return Home Assistant timezone name."""
        return self.hass.config.time_zone or "UTC"

    async def _async_update_data(self) -> HaRoutinesStorage:
        """Return current storage snapshot."""
        return self.data

    def get_routine_runtime(self, routine_id: str) -> RoutineRuntime | None:
        """Return runtime state for a routine."""
        return get_routine_runtime(self.data, routine_id)

    def get_routine_config(
        self, entry: ConfigEntry | None, routine_id: str
    ) -> RoutineConfig | None:
        """Return static config from a routine subentry."""
        config_entry = entry or self.entry
        if config_entry is None:
            return None
        subentry = config_entry.subentries.get(routine_id)
        if subentry is None or subentry.subentry_type != SUBENTRY_TYPE_ROUTINE:
            return None
        return normalize_routine_config(cast(RoutineConfig, dict(subentry.data)))

    def ensure_routine_runtime(self, subentry: ConfigSubentry) -> RoutineRuntime:
        """Create or return runtime state for a subentry."""
        routine_id = subentry.subentry_id
        existing = self.get_routine_runtime(routine_id)
        if existing is not None:
            return existing

        runtime = default_runtime_for_config(routine_id)
        tz = resolve_timezone(self.timezone_name)
        runtime["cycle_date"] = datetime.now(tz).date().isoformat()
        config = normalize_routine_config(cast(RoutineConfig, dict(subentry.data)))
        runtime["next_reminder_at"] = compute_next_reminder_at(
            config, runtime, timezone_name=self.timezone_name
        )
        self.data["routines"][routine_id] = runtime
        return runtime

    def _refresh_next_reminder(self, routine_id: str) -> None:
        """Recompute next_reminder_at for a routine."""
        runtime = self.get_routine_runtime(routine_id)
        config = self.get_routine_config(self.entry, routine_id)
        if runtime is None or config is None:
            return
        runtime["next_reminder_at"] = compute_next_reminder_at(
            config, runtime, timezone_name=self.timezone_name
        )

    def _fire_event(self, event_type: str, routine_id: str, **extra: Any) -> None:
        """Fire a Home Assistant bus event for a routine action."""
        data: dict[str, Any] = {ATTR_ROUTINE_ID: routine_id, **extra}
        self.hass.bus.async_fire(event_type, data)

    def _require_runtime(self, routine_id: str) -> RoutineRuntime:
        """Return runtime or raise."""
        runtime = self.get_routine_runtime(routine_id)
        if runtime is None:
            raise ValueError(f"Routine not found: {routine_id}")
        return runtime

    def _require_transition(
        self, runtime: RoutineRuntime, new_state: RoutineState
    ) -> None:
        """Validate state machine transition."""
        current = RoutineState(runtime["state"])
        if not can_transition(current, new_state):
            raise HomeAssistantError(
                f"Cannot go from {current.value} to {new_state.value} for this routine"
            )

    def _history_limit(self, routine_id: str) -> int:
        """Return history limit for a routine."""
        config = self.get_routine_config(self.entry, routine_id)
        if config is None:
            return DEFAULT_HISTORY_LIMIT
        return int(config.get("history_limit", DEFAULT_HISTORY_LIMIT))

    async def async_sync_subentries(self, entry: ConfigEntry) -> None:
        """Align Store runtime records with current subentries."""
        self.entry = entry
        active_ids: set[str] = set()
        for subentry in entry.subentries.values():
            if subentry.subentry_type != SUBENTRY_TYPE_ROUTINE:
                continue
            active_ids.add(subentry.subentry_id)
            self.ensure_routine_runtime(subentry)
            if subentry.subentry_id not in self._tracked_routine_ids:
                self.async_add_routine_entities(subentry)

        removed = [
            routine_id
            for routine_id in list(self.data["routines"])
            if routine_id not in active_ids
        ]
        for routine_id in removed:
            self.data["routines"].pop(routine_id, None)
            self._tracked_routine_ids.discard(routine_id)

        # * Recompute schedules when subentry config changes (reconfigure wizard)
        for routine_id in active_ids:
            self._refresh_next_reminder(routine_id)

        await self.async_persist()
        if self.scheduler is not None:
            await self.scheduler.async_reschedule_all()

    async def async_register_routine_from_subentry(
        self, subentry: ConfigSubentry
    ) -> RoutineRuntime:
        """Register runtime state when a routine subentry is added."""
        runtime = self.ensure_routine_runtime(subentry)
        self.async_add_routine_entities(subentry)
        await self.async_persist()
        if self.scheduler is not None:
            await self.scheduler.async_reschedule_routine(subentry.subentry_id)
        return runtime

    async def async_remove_routine(self, routine_id: str) -> None:
        """Remove runtime state when a routine subentry is deleted."""
        self.data["routines"].pop(routine_id, None)
        self._tracked_routine_ids.discard(routine_id)
        await self.async_persist()
        if self.scheduler is not None:
            self.scheduler.async_cancel_routine(routine_id)

    async def async_complete(
        self, routine_id: str, source: str = "manual"
    ) -> RoutineRuntime:
        """Mark the current dose as done; keep later doses the same day."""
        runtime = self._require_runtime(routine_id)
        current = RoutineState(runtime["state"])
        if current not in (
            RoutineState.PENDING,
            RoutineState.REMINDER_SENT,
            RoutineState.SNOOZED,
            RoutineState.PARTIAL,
            RoutineState.MISSED,
        ):
            raise ValueError(
                f"Cannot complete routine {routine_id} from state {current}"
            )

        config = self.get_routine_config(self.entry, routine_id)
        now_iso = utc_now_iso()
        tz = resolve_timezone(self.timezone_name)
        runtime["cycle_date"] = datetime.now(tz).date().isoformat()
        runtime["last_completed_at"] = now_iso
        runtime["snoozed_until"] = None
        runtime["reminder_count"] = 0
        runtime["skipped_today"] = False

        slots = list(runtime.get("completed_slots") or [])
        if config is not None:
            slot = resolve_completion_slot(
                config, runtime, timezone_name=self.timezone_name
            )
            if slot is not None and slot not in slots:
                slots.append(slot)
        runtime["completed_slots"] = slots

        entry: HistoryEntry = {"completed_at": now_iso, "source": source}
        runtime["completion_history"].append(entry)
        trim_history(runtime, self._history_limit(routine_id))

        more_today = bool(config and remaining_slots_today(config, runtime))
        target = RoutineState.PARTIAL if more_today else RoutineState.COMPLETED
        self._require_transition(runtime, target)
        if more_today:
            # * e.g. took dose 1, still expect dose 2 later today
            runtime["state"] = RoutineState.PARTIAL
            runtime["completed_today"] = False
        else:
            runtime["state"] = RoutineState.COMPLETED
            runtime["completed_today"] = True
            apply_streak_on_complete(runtime)

        self._refresh_next_reminder(routine_id)
        await self.async_persist()
        self._fire_event(
            EVENT_ROUTINE_COMPLETED,
            routine_id,
            source=source,
            completed_today=runtime["completed_today"],
            completed_slots=list(runtime.get("completed_slots") or []),
        )
        if self.scheduler is not None:
            await self.scheduler.async_reschedule_routine(routine_id)
        return runtime

    async def async_snooze(
        self, routine_id: str, minutes: int | None = None
    ) -> RoutineRuntime:
        """Snooze a routine reminder (default: random 4-10 minutes)."""
        runtime = self._require_runtime(routine_id)
        self._require_transition(runtime, RoutineState.SNOOZED)

        if minutes is None:
            snooze_minutes = random.randint(SNOOZE_MIN_MINUTES, SNOOZE_MAX_MINUTES)
        else:
            snooze_minutes = max(1, minutes)
        snooze_until = datetime.now(UTC) + timedelta(minutes=snooze_minutes)
        runtime["state"] = RoutineState.SNOOZED
        runtime["snoozed_until"] = snooze_until.isoformat()
        runtime["next_reminder_at"] = runtime["snoozed_until"]
        await self.async_persist()
        self._fire_event(
            EVENT_ROUTINE_SNOOZED,
            routine_id,
            snoozed_until=runtime["snoozed_until"],
            minutes=snooze_minutes,
        )
        if self.scheduler is not None:
            await self.scheduler.async_reschedule_routine(routine_id)
        return runtime

    async def async_skip_today(self, routine_id: str) -> RoutineRuntime:
        """Skip the routine for the current local day."""
        runtime = self._require_runtime(routine_id)
        self._require_transition(runtime, RoutineState.SKIPPED)

        now_iso = utc_now_iso()
        runtime["state"] = RoutineState.SKIPPED
        runtime["skipped_today"] = True
        runtime["snoozed_until"] = None
        runtime["reminder_count"] = 0
        runtime["skipped_history"].append(now_iso)
        tz = resolve_timezone(self.timezone_name)
        runtime["cycle_date"] = datetime.now(tz).date().isoformat()
        trim_history(runtime, self._history_limit(routine_id))
        self._refresh_next_reminder(routine_id)
        await self.async_persist()
        self._fire_event(EVENT_ROUTINE_SKIPPED, routine_id)
        if self.scheduler is not None:
            await self.scheduler.async_reschedule_routine(routine_id)
        return runtime

    async def async_mark_missed(self, routine_id: str) -> RoutineRuntime:
        """Mark a routine as missed for the current cycle."""
        runtime = self._require_runtime(routine_id)
        self._require_transition(runtime, RoutineState.MISSED)

        now_iso = utc_now_iso()
        runtime["state"] = RoutineState.MISSED
        runtime["snoozed_until"] = None
        runtime["reminder_count"] = 0
        runtime["missed_history"].append(now_iso)
        apply_streak_on_miss(runtime)
        tz = resolve_timezone(self.timezone_name)
        runtime["cycle_date"] = datetime.now(tz).date().isoformat()
        trim_history(runtime, self._history_limit(routine_id))
        self._refresh_next_reminder(routine_id)
        await self.async_persist()
        if self.scheduler is not None:
            await self.scheduler.async_reschedule_routine(routine_id)
        return runtime

    async def async_reset(self, routine_id: str) -> RoutineRuntime:
        """Reset routine runtime to a fresh pending cycle."""
        runtime = self._require_runtime(routine_id)
        runtime["state"] = RoutineState.PENDING
        runtime["completed_today"] = False
        runtime["skipped_today"] = False
        runtime["snoozed_until"] = None
        runtime["reminder_count"] = 0
        runtime["completed_slots"] = []
        tz = resolve_timezone(self.timezone_name)
        runtime["cycle_date"] = datetime.now(tz).date().isoformat()
        self._refresh_next_reminder(routine_id)
        await self.async_persist()
        if self.scheduler is not None:
            await self.scheduler.async_reschedule_routine(routine_id)
        return runtime

    async def async_trigger_reminder(self, routine_id: str) -> RoutineRuntime:
        """Move routine to reminder_sent and bump reminder count."""
        runtime = self._require_runtime(routine_id)
        current = RoutineState(runtime["state"])
        if current == RoutineState.SNOOZED:
            self._require_transition(runtime, RoutineState.REMINDER_SENT)
        elif current in (RoutineState.PENDING, RoutineState.PARTIAL):
            self._require_transition(runtime, RoutineState.REMINDER_SENT)
        elif current == RoutineState.REMINDER_SENT:
            pass
        else:
            raise ValueError(
                f"Cannot trigger reminder from state {current} for {routine_id}"
            )

        runtime["state"] = RoutineState.REMINDER_SENT
        runtime["reminder_count"] = int(runtime.get("reminder_count", 0)) + 1
        runtime["last_reminder_at"] = utc_now_iso()
        runtime["snoozed_until"] = None

        config = self.get_routine_config(self.entry, routine_id)
        if config is not None:
            repeat = int(config["reminders"].get("repeat_interval_minutes") or 15)
            next_at = datetime.now(UTC) + timedelta(minutes=max(1, repeat))
            runtime["next_reminder_at"] = next_at.isoformat()
        else:
            self._refresh_next_reminder(routine_id)

        await self.async_persist()
        self._fire_event(
            EVENT_ROUTINE_REMINDER_SENT,
            routine_id,
            reminder_count=runtime["reminder_count"],
        )
        if self.scheduler is not None:
            await self.scheduler.async_reschedule_routine(routine_id)
        return runtime

    async def async_start_next_cycle(self, routine_id: str) -> RoutineRuntime:
        """Advance COMPLETED/SKIPPED/MISSED into a new PENDING cycle."""
        runtime = self._require_runtime(routine_id)
        self._require_transition(runtime, RoutineState.PENDING)

        runtime["state"] = RoutineState.PENDING
        runtime["completed_today"] = False
        runtime["skipped_today"] = False
        runtime["snoozed_until"] = None
        runtime["reminder_count"] = 0
        runtime["completed_slots"] = []
        tz = resolve_timezone(self.timezone_name)
        runtime["cycle_date"] = datetime.now(tz).date().isoformat()
        self._refresh_next_reminder(routine_id)
        await self.async_persist()
        if self.scheduler is not None:
            await self.scheduler.async_reschedule_routine(routine_id)
        return runtime

    async def async_transition_routine(
        self,
        routine_id: str,
        new_state: RoutineState,
    ) -> RoutineRuntime:
        """Validate and apply a low-level state machine transition."""
        if new_state == RoutineState.COMPLETED:
            return await self.async_complete(routine_id)
        if new_state == RoutineState.SNOOZED:
            return await self.async_snooze(routine_id)
        if new_state == RoutineState.SKIPPED:
            return await self.async_skip_today(routine_id)
        if new_state == RoutineState.MISSED:
            return await self.async_mark_missed(routine_id)
        if new_state == RoutineState.REMINDER_SENT:
            return await self.async_trigger_reminder(routine_id)
        if new_state == RoutineState.PENDING:
            runtime = self._require_runtime(routine_id)
            current = RoutineState(runtime["state"])
            if current in (
                RoutineState.COMPLETED,
                RoutineState.SKIPPED,
                RoutineState.MISSED,
            ):
                return await self.async_start_next_cycle(routine_id)
            return await self.async_reset(routine_id)
        raise ValueError(f"Unsupported transition target: {new_state}")

    async def async_persist(self) -> None:
        """Save data and notify listeners."""
        await async_save_storage(self.store, self.data)
        await self.async_request_refresh()
        self.async_dispatch_update()

    @callback
    def async_dispatch_update(self) -> None:
        """Broadcast update signal to entities."""
        async_dispatcher_send(self.hass, SIGNAL_ROUTINES_UPDATE)
        self.async_update_listeners()

    @callback
    def async_register_sensor_adder(self, async_add_entities: Callable[..., None]) -> None:
        """Store sensor platform callback for dynamic entity creation."""
        self._async_add_sensors = async_add_entities

    @callback
    def async_register_binary_sensor_adder(
        self, async_add_entities: Callable[..., None]
    ) -> None:
        """Store binary_sensor platform callback for dynamic entity creation."""
        self._async_add_binary_sensors = async_add_entities

    @callback
    def async_register_button_adder(self, async_add_entities: Callable[..., None]) -> None:
        """Store button platform callback for dynamic entity creation."""
        self._async_add_buttons = async_add_entities

    def async_track_routine(self, routine_id: str) -> None:
        """Mark routine entities as already registered."""
        self._tracked_routine_ids.add(routine_id)

    @callback
    def async_add_routine_entities(self, subentry: ConfigSubentry) -> None:
        """Register entities when a routine is added after initial setup."""
        # * Late imports avoid circular import with platform modules
        from .binary_sensor import CompletedTodayBinarySensor
        from .button import CompleteButton, SkipTodayButton, SnoozeButton
        from .sensor import DoseProgressSensor, RoutineStatusSensor

        if self.entry is None:
            return
        routine_id = subentry.subentry_id
        if routine_id in self._tracked_routine_ids:
            return
        self._tracked_routine_ids.add(routine_id)

        if self._async_add_sensors:
            self._async_add_sensors(
                [
                    RoutineStatusSensor(self, self.entry, subentry, routine_id),
                    DoseProgressSensor(self, self.entry, subentry, routine_id),
                ],
                config_subentry_id=routine_id,
            )
        if self._async_add_binary_sensors:
            self._async_add_binary_sensors(
                [CompletedTodayBinarySensor(self, self.entry, subentry, routine_id)],
                config_subentry_id=routine_id,
            )
        if self._async_add_buttons:
            self._async_add_buttons(
                [
                    CompleteButton(self, self.entry, subentry, routine_id),
                    SnoozeButton(self, self.entry, subentry, routine_id),
                    SkipTodayButton(self, self.entry, subentry, routine_id),
                ],
                config_subentry_id=routine_id,
            )

    @callback
    def async_shutdown(self) -> None:
        """Cancel background listeners."""
        if self.scheduler is not None:
            self.scheduler.async_shutdown()
            self.scheduler = None
