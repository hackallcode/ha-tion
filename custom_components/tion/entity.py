"""Base entity for the Tion MagicAir integration."""
from __future__ import annotations

from homeassistant.helpers.device_registry import (
    CONNECTION_NETWORK_MAC,
    DeviceInfo,
    format_mac,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import TionDevice
from .const import DOMAIN, MANUFACTURER
from .coordinator import TionCoordinator


class TionEntity(CoordinatorEntity[TionCoordinator]):
    """Base class: binds an entity to one Tion device and groups them."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TionCoordinator, guid: str) -> None:
        super().__init__(coordinator)
        self._guid = guid

    @property
    def _device(self) -> TionDevice | None:
        return self.coordinator.device(self._guid)

    @property
    def _zone(self):
        device = self._device
        return device.zone if device else None

    @property
    def device_info(self) -> DeviceInfo:
        device = self._device
        return DeviceInfo(
            identifiers={(DOMAIN, self._guid)},
            name=device.name if device else self._guid,
            manufacturer=MANUFACTURER,
            model=device.type if device else None,
            sw_version=device.firmware if device else None,
            hw_version=device.hardware if device else None,
            connections=(
                {(CONNECTION_NETWORK_MAC, format_mac(device.mac))}
                if device and device.mac
                else set()
            ),
        )

    @property
    def available(self) -> bool:
        device = self._device
        return super().available and device is not None and device.valid and device.is_online
