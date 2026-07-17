"""Service registration for HA Routines."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from .const import (
    ATTR_ROUTINE_ID,
    DEFAULT_SNOOZE_MINUTES,
    DOMAIN,
    SERVICE_COMPLETE,
    SERVICE_RESET,
    SERVICE_SKIP_TODAY,
    SERVICE_SNOOZE,
    SERVICE_TRIGGER_REMINDER,
)
from .coordinator import RoutinesCoordinator
from .notification import async_send_routine_notification

_LOGGER = logging.getLogger(__name__)

_SERVICES_REGISTERED = False

SERVICE_ROUTINE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ROUTINE_ID): cv.string,
    }
)

SERVICE_SNOOZE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ROUTINE_ID): cv.string,
        vol.Optional("minutes", default=DEFAULT_SNOOZE_MINUTES): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=1440)
        ),
    }
)


def _get_coordinator(hass: HomeAssistant) -> RoutinesCoordinator:
    """Return the first loaded coordinator or raise."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.runtime_data is not None:
            return entry.runtime_data
    raise ValueError("HA Routines is not loaded")


def _resolve_routine_id(hass: HomeAssistant, raw: str) -> str:
    """Resolve routine_id from raw id or entity_id."""
    if raw in _get_coordinator(hass).data["routines"]:
        return raw

    registry = er.async_get(hass)
    entity = registry.async_get(raw)
    if entity and entity.unique_id and entity.platform == DOMAIN:
        # * unique_id format: {routine_id}_{key}
        parts = entity.unique_id.rsplit("_", 1)
        if len(parts) == 2:
            candidate = parts[0]
            if candidate in _get_coordinator(hass).data["routines"]:
                return candidate
            # * UUID routine ids contain underscores; strip known suffixes
            for suffix in (
                "_status",
                "_completed_today",
                "_complete",
                "_snooze",
                "_skip_today",
            ):
                if entity.unique_id.endswith(suffix):
                    routine_id = entity.unique_id[: -len(suffix)]
                    if routine_id in _get_coordinator(hass).data["routines"]:
                        return routine_id

    # * Also accept entity_id that embeds routine id in object_id
    for routine_id in _get_coordinator(hass).data["routines"]:
        if routine_id in raw:
            return routine_id

    raise ValueError(f"Unknown routine_id: {raw}")


async def async_register_services(hass: HomeAssistant) -> None:
    """Register HA Routines services."""
    global _SERVICES_REGISTERED
    if _SERVICES_REGISTERED:
        return

    async def _complete(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        routine_id = _resolve_routine_id(hass, call.data[ATTR_ROUTINE_ID])
        await coordinator.async_complete(routine_id, source="service")

    async def _snooze(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        routine_id = _resolve_routine_id(hass, call.data[ATTR_ROUTINE_ID])
        await coordinator.async_snooze(routine_id, call.data.get("minutes"))

    async def _skip_today(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        routine_id = _resolve_routine_id(hass, call.data[ATTR_ROUTINE_ID])
        await coordinator.async_skip_today(routine_id)

    async def _reset(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        routine_id = _resolve_routine_id(hass, call.data[ATTR_ROUTINE_ID])
        await coordinator.async_reset(routine_id)

    async def _trigger_reminder(call: ServiceCall) -> None:
        coordinator = _get_coordinator(hass)
        routine_id = _resolve_routine_id(hass, call.data[ATTR_ROUTINE_ID])
        config = coordinator.get_routine_config(coordinator.entry, routine_id)
        runtime = coordinator.get_routine_runtime(routine_id)
        if config is None or runtime is None:
            return

        should_notify = bool(
            config["reminders"].get("notifications_enabled", True)
        ) and bool((config["reminders"].get("notify_service") or "").strip())
        if should_notify:
            sent = await async_send_routine_notification(
                hass, coordinator, routine_id, config, runtime
            )
            if not sent:
                return

        await coordinator.async_trigger_reminder(routine_id)

    hass.services.async_register(
        DOMAIN, SERVICE_COMPLETE, _complete, schema=SERVICE_ROUTINE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SNOOZE, _snooze, schema=SERVICE_SNOOZE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SKIP_TODAY, _skip_today, schema=SERVICE_ROUTINE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RESET, _reset, schema=SERVICE_ROUTINE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_TRIGGER_REMINDER,
        _trigger_reminder,
        schema=SERVICE_ROUTINE_SCHEMA,
    )
    _SERVICES_REGISTERED = True
    hass.data.setdefault(DOMAIN, {})


async def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister HA Routines services when the last entry is removed."""
    global _SERVICES_REGISTERED
    entries = hass.config_entries.async_entries(DOMAIN)
    if entries:
        return

    for service in (
        SERVICE_COMPLETE,
        SERVICE_SNOOZE,
        SERVICE_SKIP_TODAY,
        SERVICE_RESET,
        SERVICE_TRIGGER_REMINDER,
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)

    _SERVICES_REGISTERED = False
    hass.data.pop(DOMAIN, None)
