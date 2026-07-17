"""Binary sensor platform for HA Routines."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import SUBENTRY_TYPE_ROUTINE
from .coordinator import RoutinesCoordinator
from .entity import HaRoutinesEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HA Routines binary sensor entities."""
    coordinator: RoutinesCoordinator = entry.runtime_data
    coordinator.async_register_binary_sensor_adder(async_add_entities)

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_ROUTINE:
            continue
        async_add_entities(
            [
                CompletedTodayBinarySensor(
                    coordinator, entry, subentry, subentry_id
                )
            ],
            config_subentry_id=subentry_id,
        )


class CompletedTodayBinarySensor(HaRoutinesEntity, BinarySensorEntity):
    """Binary sensor indicating whether the routine was completed today."""

    _attr_translation_key = "completed_today"

    def __init__(
        self,
        coordinator: RoutinesCoordinator,
        entry: ConfigEntry,
        subentry: Any,
        routine_id: str,
    ) -> None:
        """Initialize completed-today binary sensor."""
        super().__init__(coordinator, entry, subentry, routine_id, "completed_today")

    @property
    def is_on(self) -> bool:
        """Return True when completed today."""
        runtime = self.routine_runtime
        if runtime is None:
            return False
        return bool(runtime.get("completed_today"))
