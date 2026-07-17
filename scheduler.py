"""Async scheduler for HA Routines."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time

from .models import RoutineState
from .notification import async_send_routine_notification
from .schedule import should_reset_day

if TYPE_CHECKING:
    from .coordinator import RoutinesCoordinator

_LOGGER = logging.getLogger(__name__)


class RoutineScheduler:
    """Schedule reminders and state ticks for all routines."""

    def __init__(self, hass: HomeAssistant, coordinator: RoutinesCoordinator) -> None:
        """Initialize scheduler."""
        self.hass = hass
        self.coordinator = coordinator
        self._started = False
        self._unsubs: dict[str, Callable[[], None]] = {}

    async def async_start(self) -> None:
        """Start background scheduling and reconcile after restart."""
        self._started = True
        await self.async_reconcile_all()
        await self.async_reschedule_all()

    def async_shutdown(self) -> None:
        """Stop background scheduling."""
        self._started = False
        for unsub in list(self._unsubs.values()):
            unsub()
        self._unsubs.clear()

    def async_cancel_routine(self, routine_id: str) -> None:
        """Cancel scheduled callback for one routine."""
        unsub = self._unsubs.pop(routine_id, None)
        if unsub is not None:
            unsub()

    async def async_reschedule_all(self) -> None:
        """Reschedule every known routine."""
        if not self._started:
            return
        for routine_id in list(self.coordinator.data["routines"]):
            await self.async_reschedule_routine(routine_id)

    async def async_reconcile_all(self) -> None:
        """Reconcile missed reminders and day roll-overs after restart."""
        now = datetime.now(UTC)
        for routine_id, runtime in list(self.coordinator.data["routines"].items()):
            if should_reset_day(
                runtime, now=now, timezone_name=self.coordinator.timezone_name
            ):
                state = RoutineState(runtime["state"])
                if state in (
                    RoutineState.COMPLETED,
                    RoutineState.SKIPPED,
                    RoutineState.MISSED,
                ):
                    await self.coordinator.async_start_next_cycle(routine_id)
                elif runtime.get("completed_today") or runtime.get("skipped_today"):
                    await self.coordinator.async_reset(routine_id)
                continue

            state = RoutineState(runtime["state"])
            next_at = runtime.get("next_reminder_at")
            if not next_at:
                self.coordinator._refresh_next_reminder(routine_id)
                continue

            due = datetime.fromisoformat(next_at)
            if due.tzinfo is None:
                due = due.replace(tzinfo=UTC)
            if due > now:
                continue

            # * Past-due after restart: fire reminder or mark missed
            if state in (RoutineState.PENDING, RoutineState.SNOOZED, RoutineState.REMINDER_SENT):
                await self._async_handle_due(routine_id, now=now)

        await self.coordinator.async_persist()

    async def async_reschedule_routine(self, routine_id: str) -> None:
        """Schedule the next point-in-time callback for a routine."""
        self.async_cancel_routine(routine_id)
        if not self._started:
            return

        runtime = self.coordinator.get_routine_runtime(routine_id)
        if runtime is None:
            return

        next_at = runtime.get("next_reminder_at")
        if not next_at:
            self.coordinator._refresh_next_reminder(routine_id)
            runtime = self.coordinator.get_routine_runtime(routine_id)
            next_at = runtime.get("next_reminder_at") if runtime else None
        if not next_at:
            return

        when = datetime.fromisoformat(next_at)
        if when.tzinfo is None:
            when = when.replace(tzinfo=UTC)
        now = datetime.now(UTC)
        if when <= now:
            when = now + timedelta(seconds=1)

        @callback
        def _fire(_now: datetime) -> None:
            self.hass.async_create_task(self._async_on_timer(routine_id))

        self._unsubs[routine_id] = async_track_point_in_utc_time(self.hass, _fire, when)
        _LOGGER.debug("Scheduled routine %s at %s", routine_id, when.isoformat())

    async def _async_on_timer(self, routine_id: str) -> None:
        """Handle a scheduled timer firing."""
        self._unsubs.pop(routine_id, None)
        await self._async_handle_due(routine_id)
        await self.async_reschedule_routine(routine_id)

    async def _async_handle_due(
        self, routine_id: str, now: datetime | None = None
    ) -> None:
        """Process a due reminder, snooze expiry, day roll-over, or miss."""
        runtime = self.coordinator.get_routine_runtime(routine_id)
        config = self.coordinator.get_routine_config(self.coordinator.entry, routine_id)
        if runtime is None or config is None:
            return

        reference = now or datetime.now(UTC)
        if should_reset_day(
            runtime, now=reference, timezone_name=self.coordinator.timezone_name
        ):
            state = RoutineState(runtime["state"])
            if state in (
                RoutineState.COMPLETED,
                RoutineState.SKIPPED,
                RoutineState.MISSED,
            ):
                await self.coordinator.async_start_next_cycle(routine_id)
            else:
                await self.coordinator.async_reset(routine_id)
            return

        state = RoutineState(runtime["state"])
        if state in (RoutineState.COMPLETED, RoutineState.SKIPPED):
            return

        if state == RoutineState.MISSED:
            await self.coordinator.async_start_next_cycle(routine_id)
            return

        max_reminders = int(config["reminders"].get("max_reminders") or 0)
        reminder_count = int(runtime.get("reminder_count", 0))

        if state == RoutineState.REMINDER_SENT and max_reminders > 0:
            if reminder_count >= max_reminders:
                await self.coordinator.async_mark_missed(routine_id)
                return

        if state in (
            RoutineState.PENDING,
            RoutineState.SNOOZED,
            RoutineState.REMINDER_SENT,
        ):
            if max_reminders > 0 and reminder_count >= max_reminders:
                await self.coordinator.async_mark_missed(routine_id)
                return

            # * Send first; only mark reminder_sent when notify succeeds (or is disabled)
            should_notify = bool(
                config["reminders"].get("notifications_enabled", True)
            ) and bool((config["reminders"].get("notify_service") or "").strip())
            if should_notify:
                runtime_before = self.coordinator.get_routine_runtime(routine_id)
                if runtime_before is None:
                    return
                sent = await async_send_routine_notification(
                    self.hass,
                    self.coordinator,
                    routine_id,
                    config,
                    runtime_before,
                )
                if not sent:
                    # ! Keep pending and retry in 60s instead of lying with reminder_sent
                    runtime_before["next_reminder_at"] = (
                        datetime.now(UTC) + timedelta(seconds=60)
                    ).isoformat()
                    await self.coordinator.async_persist()
                    await self.async_reschedule_routine(routine_id)
                    return

            await self.coordinator.async_trigger_reminder(routine_id)
