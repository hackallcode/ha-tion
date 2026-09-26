"""DataUpdateCoordinator for the Tion MagicAir integration."""
from __future__ import annotations

import logging
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later
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

# Optimistic values are kept "sticky" for this long: every poll within the
# window re-applies them over the freshly fetched (eventually-consistent) cloud
# data, so a command shown instantly never flickers back to the old value while
# the Tion cloud catches up. After the window a poll shows the confirmed state.
PENDING_TTL = 20
# Force one reconcile right after the window, so the confirmed state appears
# promptly instead of waiting for the next scheduled poll.
RECONCILE_DELAY = PENDING_TTL + 1


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
        self._reconcile_unsub = None
        # sticky optimistic state (see PENDING_TTL)
        self._pending_dev: dict[str, dict[str, Any]] = {}
        self._pending_zone: dict[str, dict[str, Any]] = {}
        self._pending_until = 0.0

    async def _async_update_data(self) -> TionData:
        try:
            devices, zones = await self.client.get_devices_and_zones()
        except TionAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except TionConnectionError as err:
            raise UpdateFailed(f"Cannot reach Tion cloud: {err}") from err
        data = TionData(devices, zones)
        self._apply_pending(data)
        return data

    def _apply_pending(self, data: "TionData") -> None:
        """Overlay still-valid optimistic values on freshly fetched data so the
        UI doesn't flicker back while the cloud is catching up."""
        if monotonic() >= self._pending_until:
            self._pending_dev.clear()
            self._pending_zone.clear()
            return
        for guid, fields in self._pending_dev.items():
            dev = data.devices.get(guid)
            if dev is not None:
                dev._raw.setdefault("data", {}).update(fields)
        for zg, p in self._pending_zone.items():
            z = data.zones.get(zg)
            if z is None:
                continue
            if "mode" in p:
                z._raw.setdefault("mode", {})["current"] = p["mode"]
            if "co2" in p:
                z._raw.setdefault("mode", {}).setdefault("auto_set", {})["co2"] = p["co2"]
            if "schedule" in p:
                z._raw.setdefault("schedule", {}).update(p["schedule"])

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

    # -- optimistic updates: reflect a command in the UI immediately ----------

    def _touch_pending(self) -> None:
        self._pending_until = monotonic() + PENDING_TTL

    def optimistic_device(self, guid: str, **fields: Any) -> None:
        """Patch a device's cached data and notify entities at once, so the UI
        shows the change without waiting for the cloud round-trip. The value is
        kept sticky for PENDING_TTL so a lagging poll doesn't revert it."""
        dev = self.device(guid)
        if dev is not None:
            dev._raw.setdefault("data", {}).update(fields)
            self._pending_dev.setdefault(guid, {}).update(fields)
            self._touch_pending()
            self.async_update_listeners()

    def optimistic_zone_mode(self, zone_guid: str, mode: str) -> None:
        z = self.zone(zone_guid)
        if z is not None:
            z._raw.setdefault("mode", {})["current"] = mode
            self._pending_zone.setdefault(zone_guid, {})["mode"] = mode
            self._touch_pending()
            self.async_update_listeners()

    def optimistic_zone_co2(self, zone_guid: str, co2: float) -> None:
        z = self.zone(zone_guid)
        if z is not None:
            z._raw.setdefault("mode", {}).setdefault("auto_set", {})["co2"] = co2
            self._pending_zone.setdefault(zone_guid, {})["co2"] = co2
            self._touch_pending()
            self.async_update_listeners()

    def optimistic_zone_schedule(self, zone_guid: str, **fields: Any) -> None:
        z = self.zone(zone_guid)
        if z is not None:
            z._raw.setdefault("schedule", {}).update(fields)
            self._pending_zone.setdefault(zone_guid, {}).setdefault("schedule", {}).update(fields)
            self._touch_pending()
            self.async_update_listeners()

    def _schedule_reconcile(self) -> None:
        """Re-read /location once, a few seconds out, after the cloud settles."""
        if self._reconcile_unsub is not None:
            self._reconcile_unsub()

        async def _run(_now) -> None:
            self._reconcile_unsub = None
            await self.async_request_refresh()

        self._reconcile_unsub = async_call_later(self.hass, RECONCILE_DELAY, _run)

    async def async_send(self, coro: Any) -> None:
        """Await a client setter coroutine. On success, reconcile with the cloud
        after a delay (keeping any optimistic update visible meanwhile); on
        failure, refresh immediately to revert the optimistic update."""
        try:
            await coro
        except (TionAuthError, TionConnectionError) as err:
            _LOGGER.error("Tion command failed: %s", err)
            await self.async_request_refresh()
            return
        self._schedule_reconcile()
