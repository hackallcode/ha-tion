"""Select platform for the breezer air source (gate)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TionConfigEntry
from .api import TionDevice
from .const import MODE_MANUAL
from .coordinator import TionCoordinator
from .entity import TionEntity

# Air source (gate) positions differ by model:
#  - 4S: 0 = outside, 1 = recirculation (2 positions)
#  - 3S: 0 = inside, 1 = combined, 2 = outside (3 positions)
GATE_4S = {"outside": 0, "recirculation": 1}
GATE_3S = {"inside": 0, "combined": 1, "outside": 2}


def _gate_map(device: TionDevice) -> dict[str, int]:
    return GATE_4S if (device.type or "").startswith("breezer4") else GATE_3S


async def async_setup_entry(
    hass: HomeAssistant, entry: TionConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        TionAirSourceSelect(coordinator, device.guid)
        for device in coordinator.data.devices.values()
        if device.is_breezer
    )


class TionAirSourceSelect(TionEntity, SelectEntity):
    """Air intake source (breezer 'gate')."""

    _attr_translation_key = "air_source"
    _attr_icon = "mdi:air-filter"

    def __init__(self, coordinator: TionCoordinator, guid: str) -> None:
        super().__init__(coordinator, guid)
        self._attr_unique_id = f"{guid}-air_source"
        self._map = _gate_map(self._device)
        self._rev = {v: k for k, v in self._map.items()}
        self._attr_options = list(self._map)

    @property
    def current_option(self) -> str | None:
        device = self._device
        if device is None:
            return None
        return self._rev.get(device.data.get("gate"))

    async def async_select_option(self, option: str) -> None:
        device = self._device
        gate = self._map[option]
        if device.zone.mode != MODE_MANUAL:
            self.coordinator.optimistic_zone_mode(device.zone.guid, MODE_MANUAL)
            await self.coordinator.async_send(
                self.coordinator.client.set_zone_mode(device.zone, mode=MODE_MANUAL)
            )
        self.coordinator.optimistic_device(self._guid, gate=gate)
        await self.coordinator.async_send(
            self.coordinator.client.set_breezer(device, gate=gate)
        )
