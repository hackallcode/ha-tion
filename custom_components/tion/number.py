"""Number platform for Tion setpoints."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import CONCENTRATION_PARTS_PER_MILLION, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TionConfigEntry
from .api import TionDevice
from .const import MODE_MANUAL
from .coordinator import TionCoordinator
from .entity import TionEntity


@dataclass(frozen=True, kw_only=True)
class TionNumberDescription(NumberEntityDescription):
    """Number description with a value getter and a setter."""

    value_fn: Callable[[TionDevice], float | None]
    set_fn: Callable[[TionCoordinator, TionDevice, float], Awaitable[None]]
    zone_level: bool = False


async def _set_target_co2(coord: TionCoordinator, device: TionDevice, value: float) -> None:
    await coord.async_send(coord.client.set_zone_mode(device.zone, target_co2=value))


async def _set_fan_speed(coord: TionCoordinator, device: TionDevice, value: float) -> None:
    # A manual speed implies manual mode + the breezer running.
    if device.zone.mode != MODE_MANUAL:
        await coord.async_send(coord.client.set_zone_mode(device.zone, mode=MODE_MANUAL))
    await coord.async_send(
        coord.client.set_breezer(device, speed=int(value), is_on=True)
    )


async def _set_speed_min(coord: TionCoordinator, device: TionDevice, value: float) -> None:
    await coord.async_send(coord.client.set_breezer(device, speed_min_set=int(value)))


async def _set_speed_max(coord: TionCoordinator, device: TionDevice, value: float) -> None:
    await coord.async_send(coord.client.set_breezer(device, speed_max_set=int(value)))


MAGICAIR_NUMBERS: tuple[TionNumberDescription, ...] = (
    TionNumberDescription(
        key="target_co2",
        translation_key="target_co2",
        device_class=NumberDeviceClass.CO2,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
        native_min_value=500,
        native_max_value=1500,
        native_step=50,
        mode=NumberMode.SLIDER,
        zone_level=True,
        value_fn=lambda d: d.zone.target_co2,
        set_fn=_set_target_co2,
    ),
)

BREEZER_NUMBERS: tuple[TionNumberDescription, ...] = (
    TionNumberDescription(
        key="fan_speed",
        translation_key="fan_speed",
        native_min_value=1,
        native_max_value=6,
        native_step=1,
        mode=NumberMode.SLIDER,
        icon="mdi:fan",
        value_fn=lambda d: d.data.get("speed"),
        set_fn=_set_fan_speed,
    ),
    TionNumberDescription(
        key="speed_min_set",
        translation_key="speed_min_set",
        entity_category=EntityCategory.CONFIG,
        native_min_value=0,
        native_max_value=6,
        native_step=1,
        mode=NumberMode.SLIDER,
        icon="mdi:fan-chevron-down",
        value_fn=lambda d: d.data.get("speed_min_set"),
        set_fn=_set_speed_min,
    ),
    TionNumberDescription(
        key="speed_max_set",
        translation_key="speed_max_set",
        entity_category=EntityCategory.CONFIG,
        native_min_value=1,
        native_max_value=6,
        native_step=1,
        mode=NumberMode.SLIDER,
        icon="mdi:fan-chevron-up",
        value_fn=lambda d: d.data.get("speed_max_set"),
        set_fn=_set_speed_max,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: TionConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[TionNumber] = []
    # Target CO2 is a zone setpoint -> one per zone.
    for device in coordinator.zone_representatives():
        entities.extend(
            TionNumber(coordinator, device.guid, d) for d in MAGICAIR_NUMBERS
        )
    for device in coordinator.data.devices.values():
        if device.is_breezer:
            entities.extend(
                TionNumber(coordinator, device.guid, d) for d in BREEZER_NUMBERS
            )
    async_add_entities(entities)


class TionNumber(TionEntity, NumberEntity):
    """A Tion numeric setpoint."""

    entity_description: TionNumberDescription

    def __init__(
        self, coordinator: TionCoordinator, guid: str, description: TionNumberDescription
    ) -> None:
        super().__init__(coordinator, guid)
        self.entity_description = description
        if description.zone_level:
            self._attr_unique_id = f"{self._zone.guid}-{description.key}"
        else:
            self._attr_unique_id = f"{guid}-{description.key}"

    @property
    def native_value(self) -> float | None:
        device = self._device
        if device is None:
            return None
        return self.entity_description.value_fn(device)

    async def async_set_native_value(self, value: float) -> None:
        await self.entity_description.set_fn(self.coordinator, self._device, value)
