"""Sensor platform for HA Routines."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_COMPLETION_HISTORY,
    ATTR_CURRENT_STREAK,
    ATTR_LAST_COMPLETED,
    ATTR_LONGEST_STREAK,
    ATTR_MISSED_COUNT,
    ATTR_NEXT_REMINDER,
    ATTR_REMINDER_COUNT,
    ATTR_ROUTINE_ID,
    ATTR_TODAY_STATUS,
    SUBENTRY_TYPE_ROUTINE,
)
from .coordinator import RoutinesCoordinator
from .entity import HaRoutinesEntity
from .models import RoutineState
from .schedule import doses_taken_count, doses_total_count

_STATUS_OPTIONS = [
    RoutineState.PENDING.value,
    RoutineState.REMINDER_SENT.value,
    RoutineState.SNOOZED.value,
    RoutineState.PARTIAL.value,
    RoutineState.COMPLETED.value,
    RoutineState.SKIPPED.value,
    RoutineState.MISSED.value,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HA Routines sensor entities."""
    coordinator: RoutinesCoordinator = entry.runtime_data
    coordinator.async_register_sensor_adder(async_add_entities)

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_ROUTINE:
            continue
        coordinator.async_track_routine(subentry_id)
        async_add_entities(
            [
                RoutineStatusSensor(coordinator, entry, subentry, subentry_id),
                DoseProgressSensor(coordinator, entry, subentry, subentry_id),
            ],
            config_subentry_id=subentry_id,
        )


class RoutineStatusSensor(HaRoutinesEntity, SensorEntity):
    """Primary status sensor for a routine."""

    _attr_translation_key = "routine_status"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = _STATUS_OPTIONS

    def __init__(
        self,
        coordinator: RoutinesCoordinator,
        entry: ConfigEntry,
        subentry: Any,
        routine_id: str,
    ) -> None:
        """Initialize status sensor."""
        super().__init__(coordinator, entry, subentry, routine_id, "status")

    @property
    def native_value(self) -> str | None:
        """Return current routine state."""
        runtime = self.routine_runtime
        if runtime is None:
            return None
        return str(runtime["state"])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return dashboard-friendly attributes."""
        runtime = self.routine_runtime
        if runtime is None:
            return {}

        if runtime.get("completed_today"):
            today_status = "completed"
        elif runtime.get("skipped_today"):
            today_status = "skipped"
        else:
            today_status = str(runtime["state"])

        slots = list(runtime.get("completed_slots") or [])
        return {
            ATTR_ROUTINE_ID: self.routine_id,
            ATTR_LAST_COMPLETED: runtime.get("last_completed_at"),
            ATTR_NEXT_REMINDER: runtime.get("next_reminder_at"),
            ATTR_TODAY_STATUS: today_status,
            ATTR_REMINDER_COUNT: runtime.get("reminder_count", 0),
            ATTR_CURRENT_STREAK: runtime.get("current_streak", 0),
            ATTR_LONGEST_STREAK: runtime.get("longest_streak", 0),
            ATTR_MISSED_COUNT: runtime.get("missed_count", 0),
            ATTR_COMPLETION_HISTORY: list(runtime.get("completion_history", [])),
            "snoozed_until": runtime.get("snoozed_until"),
            "completed_slots": slots,
            "skipped_history": list(runtime.get("skipped_history", [])),
            "missed_history": list(runtime.get("missed_history", [])),
        }


class DoseProgressSensor(HaRoutinesEntity, SensorEntity):
    """Shows how many doses are taken today (e.g. 1/2)."""

    _attr_translation_key = "dose_progress"

    def __init__(
        self,
        coordinator: RoutinesCoordinator,
        entry: ConfigEntry,
        subentry: Any,
        routine_id: str,
    ) -> None:
        """Initialize dose progress sensor."""
        super().__init__(coordinator, entry, subentry, routine_id, "dose_progress")

    @property
    def native_value(self) -> str | None:
        """Return doses taken over doses total."""
        runtime = self.routine_runtime
        config = self.routine_config
        if runtime is None or config is None:
            return None
        taken = doses_taken_count(runtime)
        total = doses_total_count(config)
        if runtime.get("completed_today"):
            taken = total
        return f"{taken}/{total}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return dose progress details."""
        runtime = self.routine_runtime
        config = self.routine_config
        if runtime is None or config is None:
            return {}
        taken = doses_taken_count(runtime)
        total = doses_total_count(config)
        if runtime.get("completed_today"):
            taken = total
        if taken <= 0:
            label = "none"
        elif taken >= total:
            label = "all"
        else:
            label = "partial"
        return {
            ATTR_ROUTINE_ID: self.routine_id,
            "doses_taken": taken,
            "doses_total": total,
            "progress_label": label,
        }
