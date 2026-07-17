"""Persistent storage for HA Routines."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import STORAGE_KEY, STORAGE_VERSION
from .models import HaRoutinesStorage, migrate_storage


async def async_load_storage(
    hass: HomeAssistant,
) -> tuple[Store[HaRoutinesStorage], HaRoutinesStorage]:
    """Load HA Routines data from disk."""
    store: Store[HaRoutinesStorage] = Store(
        hass,
        STORAGE_VERSION,
        STORAGE_KEY,
    )
    raw: dict[str, Any] | None = await store.async_load()
    data = migrate_storage(raw or {})
    if raw is None:
        await store.async_save(data)
    return store, data


async def async_save_storage(store: Store[HaRoutinesStorage], data: HaRoutinesStorage) -> None:
    """Persist HA Routines data."""
    await store.async_save(data)
