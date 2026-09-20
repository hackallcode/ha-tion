"""DataUpdateCoordinator for the Tion MagicAir integration."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    TionAuthError,
    TionClient,
    TionConnectionError,
    TionDevice,
    TionZone,
)
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class TionData:
    """Snapshot of the location tree, indexed by guid."""

    def __init__(self, devices: list[TionDevice], zones: list[TionZone]) -> None:
        self.devices = {d.guid: d for d in devices}
        self.zones = {z.guid: z for z in zones}


class TionCoordinator(DataUpdateCoordinator[TionData]):
    """Fetch the whole location once per interval and share it with all entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: TionClient,
        scan_interval: timedelta,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=scan_interval,
            config_entry=entry,
        )
        self.client = client

    async def _async_update_data(self) -> TionData:
        try:
            devices, zones = await self.client.get_devices_and_zones()
        except TionAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except TionConnectionError as err:
            raise UpdateFailed(f"Cannot reach Tion cloud: {err}") from err
        return TionData(devices, zones)

    def device(self, guid: str) -> TionDevice | None:
        return self.data.devices.get(guid) if self.data else None

    def zone(self, guid: str) -> TionZone | None:
        return self.data.zones.get(guid) if self.data else None

    def zone_representatives(self) -> list[TionDevice]:
        """One device per zone for zone-level entities (auto mode, target CO2,
        schedule) — the MagicAir station is the controller, so prefer it."""
        reps: dict[str, TionDevice] = {}
        for dev in self.data.devices.values():
            zg = dev.zone.guid
            if zg is None:
                continue
            cur = reps.get(zg)
            if cur is None or (not cur.is_magicair and dev.is_magicair):
                reps[zg] = dev
        return list(reps.values())

    async def async_send(self, coro: Any) -> None:
        """Await a client setter coroutine, then refresh shared state."""
        try:
            await coro
        except (TionAuthError, TionConnectionError) as err:
            _LOGGER.error("Tion command failed: %s", err)
        await self.async_request_refresh()
