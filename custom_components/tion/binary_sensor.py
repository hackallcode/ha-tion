"""Binary sensor platform for Tion devices."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TionConfigEntry
from .api import TionDevice
from .coordinator import TionCoordinator
from .entity import TionEntity


@dataclass(frozen=True, kw_only=True)
class TionBinaryDescription(BinarySensorEntityDescription):
    """Binary sensor description with a value extractor."""

    value_fn: Callable[[TionDevice], bool | None]
    always_available: bool = False
    zone_level: bool = False


ONLINE = TionBinaryDescription(
    key="online",
    translation_key="online",
    device_class=BinarySensorDeviceClass.CONNECTIVITY,
    entity_category=EntityCategory.DIAGNOSTIC,
    value_fn=lambda d: d.is_online,
    always_available=True,
)
FILTER = TionBinaryDescription(
    key="filter_need_replace",
    translation_key="filter_need_replace",
    device_class=BinarySensorDeviceClass.PROBLEM,
    value_fn=lambda d: bool(d.data.get("filter_need_replace")),
)
TURBO = TionBinaryDescription(
    key="turbo",
    translation_key="turbo",
    device_class=BinarySensorDeviceClass.RUNNING,
    entity_category=EntityCategory.DIAGNOSTIC,
    entity_registry_enabled_default=False,  # only some models support turbo
    value_fn=lambda d: bool(d.data.get("turbo_mode_is_active")),
)
# is_active (enabled) is surfaced by the schedule switch; this indicator shows
# whether the device currently follows the schedule (goes False after a manual
# change → the "Apply schedule" button re-syncs it).
SCHEDULE = TionBinaryDescription(
    key="schedule_running",
    translation_key="schedule_running",
    # No device_class on purpose: "synced" reads as on/off, not running/not-running.
    icon="mdi:calendar-clock",
    zone_level=True,
    value_fn=lambda d: d.zone.schedule_is_running,
)


async def async_setup_entry(
    hass: HomeAssistant, entry: TionConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[TionBinarySensor] = []
    for device in coordinator.data.devices.values():
        if device.is_breezer:
            for desc in (ONLINE, FILTER, TURBO):
                entities.append(TionBinarySensor(coordinator, device.guid, desc))
        elif device.is_magicair:
            entities.append(TionBinarySensor(coordinator, device.guid, ONLINE))
    for device in coordinator.zone_representatives():
        entities.append(TionBinarySensor(coordinator, device.guid, SCHEDULE))
    async_add_entities(entities)


class TionBinarySensor(TionEntity, BinarySensorEntity):
    """A Tion boolean status."""

    entity_description: TionBinaryDescription

    def __init__(
        self, coordinator: TionCoordinator, guid: str, description: TionBinaryDescription
    ) -> None:
        super().__init__(coordinator, guid)
        self.entity_description = description
        if description.zone_level:
            self._attr_unique_id = f"{self._zone.guid}-{description.key}"
        else:
            self._attr_unique_id = f"{guid}-{description.key}"

    @property
    def available(self) -> bool:
        if self.entity_description.always_available:
            # Report connectivity even while the device itself is offline.
            return self.coordinator.last_update_success and self._device is not None
        return super().available

    @property
    def is_on(self) -> bool | None:
        device = self._device
        if device is None:
            return None
        return self.entity_description.value_fn(device)
