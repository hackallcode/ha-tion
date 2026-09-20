"""Sensor platform for Tion MagicAir and breezer devices."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    EntityCategory,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from . import TionConfigEntry
from .api import TionDevice
from .coordinator import TionCoordinator
from .entity import TionEntity


def _sanitize(value: StateType) -> StateType:
    """The API returns NaN as the float nan or the string 'NaN'; HA rejects both."""
    if isinstance(value, str) and value.strip().lower() in ("nan", "inf", "-inf"):
        return None
    if isinstance(value, float) and value != value:
        return None
    return value


@dataclass(frozen=True, kw_only=True)
class TionSensorDescription(SensorEntityDescription):
    """Sensor description with a value extractor."""

    value_fn: Callable[[TionDevice], StateType]
    zone_level: bool = False


def _data(key: str, cast=None) -> Callable[[TionDevice], StateType]:
    def _fn(device: TionDevice) -> StateType:
        value = device.data.get(key)
        if value is None or cast is None:
            return value
        try:
            return cast(value)
        except (TypeError, ValueError):
            return None

    return _fn


MAGICAIR_SENSORS: tuple[TionSensorDescription, ...] = (
    TionSensorDescription(
        key="co2",
        translation_key="co2",
        device_class=SensorDeviceClass.CO2,
        native_unit_of_measurement=CONCENTRATION_PARTS_PER_MILLION,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_data("co2"),
    ),
    TionSensorDescription(
        key="temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_data("temperature"),
    ),
    TionSensorDescription(
        key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_data("humidity"),
    ),
    TionSensorDescription(
        key="pm1",
        device_class=SensorDeviceClass.PM1,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_data("pm1"),
    ),
    TionSensorDescription(
        key="pm25",
        device_class=SensorDeviceClass.PM25,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_data("pm25"),
    ),
    TionSensorDescription(
        key="pm10",
        device_class=SensorDeviceClass.PM10,
        native_unit_of_measurement=CONCENTRATION_MICROGRAMS_PER_CUBIC_METER,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_data("pm10"),
    ),
)

BREEZER_SENSORS: tuple[TionSensorDescription, ...] = (
    TionSensorDescription(
        key="t_in",
        translation_key="t_in",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_data("t_in"),
    ),
    TionSensorDescription(
        key="t_out",
        translation_key="t_out",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_data("t_out"),
    ),
    TionSensorDescription(
        key="speed",
        translation_key="speed",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:fan",
        value_fn=lambda d: int(d.data.get("speed") or 0) if d.data.get("is_on") else 0,
    ),
    TionSensorDescription(
        key="filter_days_left",
        translation_key="filter_days_left",
        native_unit_of_measurement=UnitOfTime.DAYS,
        icon="mdi:air-filter",
        value_fn=lambda d: (
            round((d.data.get("filter_time_seconds") or 0) / 86400)
            if d.data.get("filter_time_seconds") is not None
            else None
        ),
    ),
)

# Diagnostic sensors shared by both device types (read from device meta / data).
DIAGNOSTIC_SENSORS: tuple[TionSensorDescription, ...] = (
    TionSensorDescription(
        key="signal_level",
        translation_key="signal_level",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:signal",
        # The station is the RF base (signal_level=0); its real link is Wi-Fi.
        value_fn=lambda d: d.data.get("wi-fi") if d.is_magicair else d.data.get("signal_level"),
    ),
    TionSensorDescription(
        key="firmware",
        translation_key="firmware",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:chip",
        value_fn=lambda d: d.firmware,
    ),
    TionSensorDescription(
        key="mac",
        translation_key="mac",
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:network",
        value_fn=lambda d: d.mac,
    ),
)

# Breezer-only diagnostics.
BREEZER_DIAGNOSTICS: tuple[TionSensorDescription, ...] = (
    TionSensorDescription(
        key="run_hours",
        translation_key="run_hours",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:timer-outline",
        value_fn=lambda d: (
            round((d.data.get("electronic_work_seconds") or 0) / 3600)
            if d.data.get("electronic_work_seconds") is not None
            else None
        ),
    ),
    TionSensorDescription(
        key="heater_power",
        translation_key="heater_power",
        entity_category=EntityCategory.DIAGNOSTIC,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:radiator",
        value_fn=_data("heater_power"),
    ),
    TionSensorDescription(
        key="t_main_board",
        translation_key="t_main_board",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_data("t_main_board"),
    ),
    TionSensorDescription(
        key="t_power_board",
        translation_key="t_power_board",
        entity_category=EntityCategory.DIAGNOSTIC,
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_data("t_power_board"),
    ),
    TionSensorDescription(
        key="turbo_elapsed",
        translation_key="turbo_elapsed",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,  # only some models support turbo
        native_unit_of_measurement=UnitOfTime.SECONDS,
        icon="mdi:fan-plus",
        value_fn=_data("turbo_mode_elapsed_seconds"),
    ),
)


ZONE_SENSORS: tuple[TionSensorDescription, ...] = (
    TionSensorDescription(
        key="current_preset",
        translation_key="current_preset",
        icon="mdi:calendar-clock",
        zone_level=True,
        value_fn=lambda d: d.zone.current_preset_name,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: TionConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[TionSensor] = []

    def _finite(device, desc: TionSensorDescription) -> bool:
        return _sanitize(desc.value_fn(device)) is not None

    def _add(device, desc: TionSensorDescription) -> None:
        # PM only exists on some stations; if this one doesn't report it, skip.
        if desc.key.startswith("pm") and not _finite(device, desc):
            return
        entities.append(TionSensor(coordinator, device.guid, desc))

    for device in coordinator.data.devices.values():
        if device.is_magicair:
            descriptions = (*MAGICAIR_SENSORS, *DIAGNOSTIC_SENSORS)
        elif device.is_breezer:
            descriptions = (*BREEZER_SENSORS, *DIAGNOSTIC_SENSORS, *BREEZER_DIAGNOSTICS)
        else:
            continue
        for desc in descriptions:
            _add(device, desc)
    for device in coordinator.zone_representatives():
        for desc in ZONE_SENSORS:
            _add(device, desc)
    async_add_entities(entities)


class TionSensor(TionEntity, SensorEntity):
    """A single Tion sensor value."""

    entity_description: TionSensorDescription

    def __init__(
        self, coordinator: TionCoordinator, guid: str, description: TionSensorDescription
    ) -> None:
        super().__init__(coordinator, guid)
        self.entity_description = description
        if description.zone_level:
            self._attr_unique_id = f"{self._zone.guid}-{description.key}"
        else:
            self._attr_unique_id = f"{guid}-{description.key}"

    @property
    def native_value(self) -> StateType:
        device = self._device
        if device is None:
            return None
        # The station reports NaN (float or the string "NaN") for sensors it lacks.
        return _sanitize(self.entity_description.value_fn(device))
