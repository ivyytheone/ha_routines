"""Base entity for HA Routines."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import RoutinesCoordinator
from .models import RoutineConfig, RoutineRuntime


class HaRoutinesEntity(CoordinatorEntity[RoutinesCoordinator], Entity):
    """Base class for HA Routines entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: RoutinesCoordinator,
        entry: ConfigEntry,
        subentry: ConfigSubentry,
        routine_id: str,
        key: str,
    ) -> None:
        """Initialize routine entity."""
        super().__init__(coordinator)
        self._config_entry = entry
        self._subentry = subentry
        self._routine_id = routine_id
        self._attr_unique_id = f"{routine_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, routine_id)},
            name=str(subentry.data.get("name", "Routine")),
            manufacturer="HA Routines",
            model="Routine",
            via_device=(DOMAIN, entry.entry_id),
        )
        # * Entity icons come from icons.json (state-aware); do not force one icon on all entities

    @property
    def routine_id(self) -> str:
        """Return routine subentry id."""
        return self._routine_id

    @property
    def routine_config(self) -> RoutineConfig | None:
        """Return static routine configuration."""
        return self.coordinator.get_routine_config(self._config_entry, self._routine_id)

    @property
    def routine_runtime(self) -> RoutineRuntime | None:
        """Return mutable routine runtime state."""
        return self.coordinator.get_routine_runtime(self._routine_id)

    @property
    def available(self) -> bool:
        """Return True when runtime data exists for this routine."""
        return self.routine_runtime is not None
