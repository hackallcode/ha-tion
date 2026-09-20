"""Switch platform for Tion controls (device- and zone-level)."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TionConfigEntry
from .api import TionDevice
from .const import MODE_AUTO, MODE_MANUAL
from .coordinator import TionCoordinator
from .entity import TionEntity


@dataclass(frozen=True, kw_only=True)
class TionSwitchDescription(SwitchEntityDescription):
    """Switch description with a state getter and a setter."""

    value_fn: Callable[[TionDevice], bool]
    set_fn: Callable[[TionCoordinator, TionDevice, bool], Awaitable[None]]
    zone_level: bool = False


async def _set_power(coord: TionCoordinator, device: TionDevice, on: bool) -> None:
    # In auto the station drives the breezer; take manual control to power on/off.
    if device.zone.mode != MODE_MANUAL:
        await coord.async_send(
            coord.client.set_zone_mode(device.zone, mode=MODE_MANUAL)
        )
    await coord.async_send(
        coord.client.set_breezer(device, speed=1 if on else 0, is_on=on)
    )


async def _set_heater(coord: TionCoordinator, device: TionDevice, on: bool) -> None:
    # Turning heat on implies the breezer runs; turning it off just disables the heater.
    if on:
        await coord.async_send(
            coord.client.set_breezer(device, heater_enabled=True, is_on=True)
        )
    else:
        await coord.async_send(coord.client.set_breezer(device, heater_enabled=False))


async def _set_backlight(coord: TionCoordinator, device: TionDevice, on: bool) -> None:
    await coord.async_send(coord.client.set_device_backlight(device, 1 if on else 0))


async def _set_sound(coord: TionCoordinator, device: TionDevice, on: bool) -> None:
    await coord.async_send(coord.client.set_sound(device, on))


async def _set_auto(coord: TionCoordinator, device: TionDevice, on: bool) -> None:
    await coord.async_send(
        coord.client.set_zone_mode(device.zone, mode=MODE_AUTO if on else MODE_MANUAL)
    )


async def _set_schedule(coord: TionCoordinator, device: TionDevice, on: bool) -> None:
    await coord.async_send(coord.client.set_schedule_active(device.zone.guid, on))


ZONE_SWITCHES: tuple[TionSwitchDescription, ...] = (
    TionSwitchDescription(
        key="auto_mode",
        translation_key="auto_mode",
        icon="mdi:auto-mode",
        zone_level=True,
        value_fn=lambda d: d.zone.mode == MODE_AUTO,
        set_fn=_set_auto,
    ),
    # Enable/disable schedule (api.set_schedule_active → POST .../schedule?on=...).
    # Both directions work. Re-syncing after a manual change is the "Apply
    # schedule" button (button.py). Requires an existing schedule in the zone.
    TionSwitchDescription(
        key="schedule",
        translation_key="schedule",
        icon="mdi:calendar-clock",
        zone_level=True,
        value_fn=lambda d: bool(d.zone.schedule_is_active),
        set_fn=_set_schedule,
    ),
)

BREEZER_SWITCHES: tuple[TionSwitchDescription, ...] = (
    TionSwitchDescription(
        key="power",
        translation_key="power",
        device_class=SwitchDeviceClass.SWITCH,
        icon="mdi:power",
        value_fn=lambda d: bool(d.data.get("is_on")),
        set_fn=_set_power,
    ),
    TionSwitchDescription(
        key="heater",
        translation_key="heater",
        device_class=SwitchDeviceClass.SWITCH,
        icon="mdi:radiator",
        value_fn=lambda d: d.data.get("heater_mode") == "heat",
        set_fn=_set_heater,
    ),
    TionSwitchDescription(
        key="backlight",
        translation_key="backlight",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:led-on",
        value_fn=lambda d: bool(d.data.get("backlight")),
        set_fn=_set_backlight,
    ),
    TionSwitchDescription(
        key="sound",
        translation_key="sound",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:volume-high",
        value_fn=lambda d: bool(d.data.get("sound_is_on")),
        set_fn=_set_sound,
    ),
)

MAGICAIR_SWITCHES: tuple[TionSwitchDescription, ...] = (
    TionSwitchDescription(
        key="backlight",
        translation_key="backlight",
        entity_category=EntityCategory.CONFIG,
        icon="mdi:led-on",
        value_fn=lambda d: bool(d.data.get("backlight")),
        set_fn=_set_backlight,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: TionConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[TionSwitch] = []
    for device in coordinator.zone_representatives():
        entities.extend(TionSwitch(coordinator, device.guid, d) for d in ZONE_SWITCHES)
    for device in coordinator.data.devices.values():
        descs = (
            BREEZER_SWITCHES
            if device.is_breezer
            else MAGICAIR_SWITCHES
            if device.is_magicair
            else ()
        )
        entities.extend(TionSwitch(coordinator, device.guid, d) for d in descs)
    async_add_entities(entities)


class TionSwitch(TionEntity, SwitchEntity):
    """A Tion on/off control."""

    entity_description: TionSwitchDescription

    def __init__(
        self, coordinator: TionCoordinator, guid: str, description: TionSwitchDescription
    ) -> None:
        super().__init__(coordinator, guid)
        self.entity_description = description
        if description.zone_level:
            self._attr_unique_id = f"{self._zone.guid}-{description.key}"
        else:
            self._attr_unique_id = f"{guid}-{description.key}"

    @property
    def is_on(self) -> bool | None:
        device = self._device
        if device is None:
            return None
        return self.entity_description.value_fn(device)

    async def async_turn_on(self, **kwargs) -> None:
        await self.entity_description.set_fn(self.coordinator, self._device, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self.entity_description.set_fn(self.coordinator, self._device, False)
