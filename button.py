"""Button platform for HA Routines."""

from __future__ import annotations

from typing import Any

from homeassistant.components.button import ButtonEntity
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
    """Set up HA Routines button entities."""
    coordinator: RoutinesCoordinator = entry.runtime_data
    coordinator.async_register_button_adder(async_add_entities)

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_ROUTINE:
            continue
        async_add_entities(
            [
                CompleteButton(coordinator, entry, subentry, subentry_id),
                SnoozeButton(coordinator, entry, subentry, subentry_id),
                SkipTodayButton(coordinator, entry, subentry, subentry_id),
            ],
            config_subentry_id=subentry_id,
        )


class CompleteButton(HaRoutinesEntity, ButtonEntity):
    """Button to mark a routine completed."""

    _attr_translation_key = "complete"

    def __init__(
        self,
        coordinator: RoutinesCoordinator,
        entry: ConfigEntry,
        subentry: Any,
        routine_id: str,
    ) -> None:
        """Initialize complete button."""
        super().__init__(coordinator, entry, subentry, routine_id, "complete")

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_complete(self.routine_id, source="button")


class SnoozeButton(HaRoutinesEntity, ButtonEntity):
    """Button to snooze a routine reminder."""

    _attr_translation_key = "snooze"

    def __init__(
        self,
        coordinator: RoutinesCoordinator,
        entry: ConfigEntry,
        subentry: Any,
        routine_id: str,
    ) -> None:
        """Initialize snooze button."""
        super().__init__(coordinator, entry, subentry, routine_id, "snooze")

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_snooze(self.routine_id)


class SkipTodayButton(HaRoutinesEntity, ButtonEntity):
    """Button to skip a routine for today."""

    _attr_translation_key = "skip_today"

    def __init__(
        self,
        coordinator: RoutinesCoordinator,
        entry: ConfigEntry,
        subentry: Any,
        routine_id: str,
    ) -> None:
        """Initialize skip-today button."""
        super().__init__(coordinator, entry, subentry, routine_id, "skip_today")

    async def async_press(self) -> None:
        """Handle the button press."""
        await self.coordinator.async_skip_today(self.routine_id)
