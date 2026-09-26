"""Climate platform for the Tion breezer."""
from __future__ import annotations

from homeassistant.components.climate import (
    FAN_AUTO,
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TionConfigEntry
from .coordinator import TionCoordinator
from .entity import TionEntity

FAN_SPEEDS = ["1", "2", "3", "4", "5", "6"]


async def async_setup_entry(
    hass: HomeAssistant, entry: TionConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        TionClimate(coordinator, device.guid)
        for device in coordinator.data.devices.values()
        if device.is_breezer
    )


class TionClimate(TionEntity, ClimateEntity):
    """A Tion breezer as a climate entity."""

    _attr_name = None  # use the device name
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1
    _attr_fan_modes = [FAN_AUTO, *FAN_SPEEDS]

    def __init__(self, coordinator: TionCoordinator, guid: str) -> None:
        super().__init__(coordinator, guid)
        self._attr_unique_id = guid

    @property
    def _d(self) -> dict:
        device = self._device
        return device.data if device else {}

    @property
    def _heater_installed(self) -> bool:
        device = self._device
        if not device:
            return False
        return bool(self._d.get("heater_type")) or "4S" in (device.name or "")

    @property
    def hvac_modes(self) -> list[HVACMode]:
        modes = [HVACMode.OFF, HVACMode.FAN_ONLY]
        if self._heater_installed:
            modes.append(HVACMode.HEAT)
        return modes

    @property
    def hvac_mode(self) -> HVACMode:
        if not self._d.get("is_on"):
            return HVACMode.OFF
        if self._d.get("heater_mode") == "heat":
            return HVACMode.HEAT
        return HVACMode.FAN_ONLY

    @property
    def supported_features(self) -> ClimateEntityFeature:
        features = (
            ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        if self._heater_installed:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE
        return features

    @property
    def current_temperature(self) -> float | None:
        return self._d.get("t_out")

    @property
    def target_temperature(self) -> float | None:
        return self._d.get("t_set")

    @property
    def min_temp(self) -> float:
        device = self._device
        return device.t_min if device and device.t_min is not None else 0

    @property
    def max_temp(self) -> float:
        device = self._device
        return device.t_max if device and device.t_max is not None else 30

    @property
    def fan_mode(self) -> str | None:
        device = self._device
        if device and device.zone.mode == "auto":
            return FAN_AUTO
        if not self._d.get("is_on"):
            return None
        return str(int(self._d.get("speed") or 0))

    async def async_set_temperature(self, **kwargs) -> None:
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            self.coordinator.optimistic_device(self._guid, t_set=int(temp))
            await self.coordinator.async_send(
                self.coordinator.client.set_breezer(self._device, t_set=int(temp))
            )

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        device = self._device
        if fan_mode == FAN_AUTO:
            self.coordinator.optimistic_zone_mode(device.zone.guid, "auto")
            await self.coordinator.async_send(
                self.coordinator.client.set_zone_mode(device.zone, mode="auto")
            )
            return
        if device.zone.mode == "auto":
            self.coordinator.optimistic_zone_mode(device.zone.guid, "manual")
            await self.coordinator.async_send(
                self.coordinator.client.set_zone_mode(device.zone, mode="manual")
            )
        self.coordinator.optimistic_device(self._guid, speed=int(fan_mode), is_on=True)
        await self.coordinator.async_send(
            self.coordinator.client.set_breezer(self._device, speed=int(fan_mode), is_on=True)
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        device = self._device
        if hvac_mode == HVACMode.OFF:
            if device.zone.mode == "auto":
                self.coordinator.optimistic_zone_mode(device.zone.guid, "manual")
                await self.coordinator.async_send(
                    self.coordinator.client.set_zone_mode(device.zone, mode="manual")
                )
            self.coordinator.optimistic_device(self._guid, is_on=False, speed=0)
            await self.coordinator.async_send(
                self.coordinator.client.set_breezer(self._device, speed=0, is_on=False)
            )
            return
        speed = int(self._d.get("speed") or 0) or 1
        self.coordinator.optimistic_device(
            self._guid, is_on=True, speed=speed,
            heater_mode="heat" if hvac_mode == HVACMode.HEAT else "maintenance",
        )
        await self.coordinator.async_send(
            self.coordinator.client.set_breezer(
                self._device,
                heater_enabled=hvac_mode == HVACMode.HEAT,
                speed=speed,
                is_on=True,
            )
        )

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.FAN_ONLY)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
