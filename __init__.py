"""The HA Routines integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, PLATFORMS
from .coordinator import RoutinesCoordinator
from .notification import async_register_notification_actions
from .scheduler import RoutineScheduler
from .services import async_register_services, async_unregister_services
from .storage import async_load_storage

type HaRoutinesConfigEntry = ConfigEntry[RoutinesCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: HaRoutinesConfigEntry) -> bool:
    """Set up HA Routines from a config entry."""
    store, data = await async_load_storage(hass)
    coordinator = RoutinesCoordinator(hass, store, data, entry)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await coordinator.async_sync_subentries(entry)

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="HA Routines",
        manufacturer="HA Routines",
        model="Hub",
    )

    scheduler = RoutineScheduler(hass, coordinator)
    coordinator.scheduler = scheduler
    await scheduler.async_start()

    await async_register_services(hass)
    await async_register_notification_actions(hass)

    # ! Listener must be async; HA awaits it as a coroutine
    entry.async_on_unload(entry.add_update_listener(_async_entry_updated))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Sync runtime storage when subentries are added, updated, or removed."""
    if entry.state != ConfigEntryState.LOADED:
        return
    if entry.domain != DOMAIN:
        return

    typed_entry: HaRoutinesConfigEntry = entry
    await typed_entry.runtime_data.async_sync_subentries(typed_entry)


async def async_unload_entry(hass: HomeAssistant, entry: HaRoutinesConfigEntry) -> bool:
    """Unload a config entry."""
    coordinator = entry.runtime_data
    coordinator.async_shutdown()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await async_unregister_services(hass)
    return unload_ok
