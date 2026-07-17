"""Notification helpers for HA Routines."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from homeassistant.const import CONF_ACTION
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    ATTR_ROUTINE_ID,
    DOMAIN,
    SERVICE_COMPLETE,
    SERVICE_SKIP_TODAY,
    SERVICE_SNOOZE,
)
from .coordinator import RoutinesCoordinator
from .models import RoutineConfig, RoutineRuntime

_LOGGER = logging.getLogger(__name__)

# * Short action keys; routine id travels in action_data (iOS-friendly)
ACTION_COMPLETE = "HAR_TAGIT"
ACTION_SNOOZE = "HAR_SNOOZE"
ACTION_SKIP = "HAR_SKIP"

_ACTIONS_REGISTERED = False


def _slugify(value: str) -> str:
    """Slugify a device name the same way HA notify services do."""
    cleaned = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return cleaned or "device"


def _resolve_mobile_app_notify_service(
    hass: HomeAssistant, entity_id: str
) -> tuple[str, list[str] | None] | None:
    """Resolve a notify entity to notify.mobile_app_* (required for iOS actions)."""
    # ! Never use notify.<entity_object_id> or notify.send_message; those drop actions on iOS
    local_name = entity_id.partition(".")[2]
    preferred = f"mobile_app_{local_name}"
    if hass.services.has_service("notify", preferred):
        return preferred, None

    registry = er.async_get(hass)
    entity = registry.async_get(entity_id)

    mobile_data = hass.data.get("mobile_app")
    if isinstance(mobile_data, dict) and entity and entity.device_id:
        devices = mobile_data.get("devices") or {}
        notify_svc = mobile_data.get("notify")
        webhook_id: str | None = None
        for cur_webhook_id, device in devices.items():
            if getattr(device, "id", None) == entity.device_id:
                webhook_id = str(cur_webhook_id)
                break
        if webhook_id and notify_svc is not None:
            registered = getattr(notify_svc, "registered_targets", {}) or {}
            for service_name, target_webhook in registered.items():
                if target_webhook == webhook_id and hass.services.has_service(
                    "notify", service_name
                ):
                    return str(service_name), None
            if hass.services.has_service("notify", "mobile_app"):
                return "mobile_app", [webhook_id]

    if entity and entity.device_id:
        device = dr.async_get(hass).async_get(entity.device_id)
        if device is not None:
            for name in (device.name_by_user, device.name):
                if not name:
                    continue
                candidate = f"mobile_app_{_slugify(name)}"
                if hass.services.has_service("notify", candidate):
                    return candidate, None

    notify_services = hass.services.async_services().get("notify", {})
    mobile_services = sorted(
        name for name in notify_services if name.startswith("mobile_app_")
    )
    if len(mobile_services) == 1:
        return mobile_services[0], None

    return None


def _reminder_action_data(routine_id: str) -> dict[str, Any]:
    """Build Companion action payload (iOS + Android)."""
    # * Keep this iOS-clean: no Android-only keys (channel/importance/ttl/priority)
    return {
        "actions": [
            {"action": ACTION_COMPLETE, "title": "Tagit"},
            {"action": ACTION_SNOOZE, "title": "Snooze"},
        ],
        "action_data": {ATTR_ROUTINE_ID: routine_id},
        "tag": f"ha_routines_{routine_id}",
        "push": {
            "sound": {"name": "default", "critical": 0, "volume": 1.0},
        },
    }


async def _async_call_notify(
    hass: HomeAssistant,
    notify_target: str,
    *,
    title: str,
    message: str,
    data: dict[str, Any] | None = None,
) -> bool:
    """Send via notify.mobile_app_* so actionable buttons work on iOS."""
    service_data: dict[str, Any] = {
        "title": title,
        "message": message,
    }
    if data is not None:
        service_data["data"] = data

    if not notify_target.startswith("notify."):
        if "." in notify_target:
            domain, service = notify_target.split(".", 1)
        else:
            domain, service = "notify", notify_target
        if not service.startswith("mobile_app"):
            _LOGGER.error(
                "Notify target %s is not a mobile_app service; actionable buttons need "
                "notify.mobile_app_*",
                notify_target,
            )
            return False
        await hass.services.async_call(domain, service, service_data, blocking=True)
        return True

    resolved = _resolve_mobile_app_notify_service(hass, notify_target)
    if resolved is None:
        _LOGGER.error(
            "Could not resolve %s to notify.mobile_app_*; cannot send actionable notify",
            notify_target,
        )
        return False

    service_name, target = resolved
    if target is not None:
        service_data["target"] = target

    _LOGGER.info(
        "HA Routines notify via notify.%s actions=%s routine=%s",
        service_name,
        bool(data and data.get("actions")),
        (data or {}).get("action_data", {}).get(ATTR_ROUTINE_ID)
        if data
        else None,
    )
    await hass.services.async_call(
        "notify",
        service_name,
        service_data,
        blocking=True,
    )
    return True


async def async_send_routine_notification(
    hass: HomeAssistant,
    coordinator: RoutinesCoordinator,
    routine_id: str,
    config: RoutineConfig,
    runtime: RoutineRuntime,
) -> bool:
    """Send an actionable routine reminder notification."""
    notify_target = (config["reminders"].get("notify_service") or "").strip()
    if not notify_target:
        _LOGGER.debug("No notify target configured for routine %s", routine_id)
        return False

    name = config.get("name") or "Routine"
    description = (config.get("description") or "").strip()
    title = f"💊 {name}"
    if description and description.lower() != name.lower():
        message = f"{description}\n\nHall inne notisen for Tagit eller Snooze."
    else:
        message = f"Dags for {name}!\n\nHall inne notisen for Tagit eller Snooze."

    # * Swedish copy (keep ASCII-safe source editable; normalize here)
    message = (
        message.replace("Hall inne", "Håll inne")
        .replace(" for ", " för ")
        .replace("Dags for", "Dags för")
    )

    try:
        return await _async_call_notify(
            hass,
            notify_target,
            title=title,
            message=message,
            data=_reminder_action_data(routine_id),
        )
    except Exception:
        _LOGGER.exception(
            "Failed to send notification for routine %s via %s",
            routine_id,
            notify_target,
        )
        return False


async def async_send_feedback_notification(
    hass: HomeAssistant,
    config: RoutineConfig,
    *,
    title: str,
    message: str,
    routine_id: str,
) -> None:
    """Replace the reminder notification with a short feedback message."""
    notify_target = (config["reminders"].get("notify_service") or "").strip()
    if not notify_target:
        return
    try:
        await _async_call_notify(
            hass,
            notify_target,
            title=title,
            message=message,
            data={
                "tag": f"ha_routines_{routine_id}",
                "push": {"sound": {"name": "none"}},
            },
        )
    except Exception:
        _LOGGER.exception("Failed to send feedback notification for %s", routine_id)


def _find_coordinator(hass: HomeAssistant) -> RoutinesCoordinator | None:
    """Return the first loaded HA Routines coordinator."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.runtime_data is not None:
            return entry.runtime_data
    return None


def _routine_id_from_event(event: Event) -> str | None:
    """Extract routine id from notification action event payload."""
    data = event.data or {}
    action_data = data.get("action_data")
    if isinstance(action_data, dict):
        routine_id = action_data.get(ATTR_ROUTINE_ID) or action_data.get("routine_id")
        if routine_id:
            return str(routine_id)
    routine_id = data.get(ATTR_ROUTINE_ID) or data.get("routine_id")
    if routine_id:
        return str(routine_id)
    return None


async def async_register_notification_actions(hass: HomeAssistant) -> None:
    """Listen for mobile app notification actions."""
    global _ACTIONS_REGISTERED
    if _ACTIONS_REGISTERED:
        return

    @callback
    def _on_action(event: Event) -> None:
        action = str(event.data.get(CONF_ACTION) or event.data.get("action") or "")
        if action not in (ACTION_COMPLETE, ACTION_SNOOZE, ACTION_SKIP):
            return
        hass.async_create_task(_async_handle_action(hass, action, event))

    hass.bus.async_listen("mobile_app_notification_action", _on_action)
    _ACTIONS_REGISTERED = True


async def _async_handle_action(hass: HomeAssistant, action: str, event: Event) -> None:
    """Apply a notification action to the matching routine."""
    coordinator = _find_coordinator(hass)
    if coordinator is None:
        return

    routine_id = _routine_id_from_event(event)
    if routine_id is None or routine_id not in coordinator.data["routines"]:
        _LOGGER.warning(
            "Notification action %s missing/unknown routine_id in event: %s",
            action,
            event.data,
        )
        return

    config = coordinator.get_routine_config(coordinator.entry, routine_id)
    name = (config or {}).get("name") or "Routine"

    try:
        if action == ACTION_COMPLETE:
            runtime = await coordinator.async_complete(
                routine_id, source="notification"
            )
            if config is not None:
                if runtime.get("completed_today"):
                    feedback = (
                        f"Jag har nu tagit {name}. "
                        "Inga fler paminnelser idag. Bra jobbat!"
                    )
                else:
                    feedback = (
                        f"Jag har nu tagit {name} for den har dosen. "
                        "Nasta dos-paminnelse ar schemalagd."
                    )
                # * Re-apply Swedish chars
                feedback = (
                    feedback.replace("paminnelser", "påminnelser")
                    .replace("for den har", "för den här")
                    .replace("Nasta dos-paminnelse ar", "Nästa dos-påminnelse är")
                )
                await async_send_feedback_notification(
                    hass,
                    config,
                    title="✅ Tagit!",
                    message=feedback,
                    routine_id=routine_id,
                )
        elif action == ACTION_SNOOZE:
            runtime = await coordinator.async_snooze(routine_id)
            minutes = 0
            if runtime.get("snoozed_until"):
                until = datetime.fromisoformat(str(runtime["snoozed_until"]))
                minutes = max(
                    1, int((until - datetime.now(UTC)).total_seconds() // 60)
                )
            if config is not None:
                await async_send_feedback_notification(
                    hass,
                    config,
                    title="😴 Snooze",
                    message=(
                        f"Okej, jag påminner dig om {name} om "
                        f"ca {minutes or 'några'} minuter."
                    ),
                    routine_id=routine_id,
                )
        elif action == ACTION_SKIP:
            await coordinator.async_skip_today(routine_id)
    except ValueError as err:
        _LOGGER.info("Notification action ignored: %s", err)


__all__ = [
    "ACTION_COMPLETE",
    "ACTION_SKIP",
    "ACTION_SNOOZE",
    "SERVICE_COMPLETE",
    "SERVICE_SKIP_TODAY",
    "SERVICE_SNOOZE",
    "async_register_notification_actions",
    "async_send_feedback_notification",
    "async_send_routine_notification",
]
