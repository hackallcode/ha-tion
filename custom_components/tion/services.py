"""Services for managing Tion presets and schedules."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import DOMAIN

ATTR_DEVICE_ID = "device_id"
ATTR_PRESET = "preset"
ATTR_SCHEDULE = "schedule"
ATTR_GUID = "guid"

_DEVICE = {vol.Required(ATTR_DEVICE_ID): cv.string}
GET_SCHEMA = vol.Schema(_DEVICE)
SET_PRESET_SCHEMA = vol.Schema({**_DEVICE, vol.Required(ATTR_PRESET): dict})
SET_SCHEDULE_SCHEMA = vol.Schema({**_DEVICE, vol.Required(ATTR_SCHEDULE): dict})
DELETE_SCHEMA = vol.Schema({**_DEVICE, vol.Required(ATTR_GUID): cv.string})


def _resolve(hass: HomeAssistant, device_id: str):
    """Resolve a HA device_id to (coordinator, zone_guid)."""
    device = dr.async_get(hass).async_get(device_id)
    if device is None:
        raise HomeAssistantError(f"Unknown device {device_id}")
    guid = next((i[1] for i in device.identifiers if i[0] == DOMAIN), None)
    entry = next(
        (hass.config_entries.async_get_entry(e) for e in device.config_entries), None
    )
    if guid is None or entry is None or entry.runtime_data is None:
        raise HomeAssistantError(f"{device_id} is not a Tion device")
    coordinator = entry.runtime_data
    tion_device = coordinator.device(guid)
    if tion_device is None:
        raise HomeAssistantError(f"Tion device {guid} not found")
    return coordinator, tion_device.zone.guid


def async_setup_services(hass: HomeAssistant) -> None:
    """Register the Tion CRUD services (idempotent)."""

    async def get_presets(call: ServiceCall) -> ServiceResponse:
        coordinator, zone = _resolve(hass, call.data[ATTR_DEVICE_ID])
        return {"presets": await coordinator.client.get_presets(zone)}

    async def set_preset(call: ServiceCall) -> ServiceResponse:
        coordinator, zone = _resolve(hass, call.data[ATTR_DEVICE_ID])
        result = await coordinator.client.save_preset(zone, call.data[ATTR_PRESET])
        await coordinator.async_request_refresh()
        return {"result": result}

    async def delete_preset(call: ServiceCall) -> ServiceResponse:
        coordinator, zone = _resolve(hass, call.data[ATTR_DEVICE_ID])
        result = await coordinator.client.delete_preset(zone, call.data[ATTR_GUID])
        await coordinator.async_request_refresh()
        return {"result": result}

    async def get_schedule(call: ServiceCall) -> ServiceResponse:
        coordinator, zone = _resolve(hass, call.data[ATTR_DEVICE_ID])
        return {"schedule": await coordinator.client.get_schedule(zone)}

    async def set_schedule(call: ServiceCall) -> ServiceResponse:
        coordinator, zone = _resolve(hass, call.data[ATTR_DEVICE_ID])
        result = await coordinator.client.save_schedule(zone, call.data[ATTR_SCHEDULE])
        await coordinator.async_request_refresh()
        return {"result": result}

    async def delete_schedule(call: ServiceCall) -> ServiceResponse:
        coordinator, zone = _resolve(hass, call.data[ATTR_DEVICE_ID])
        result = await coordinator.client.delete_schedule(zone, call.data[ATTR_GUID])
        await coordinator.async_request_refresh()
        return {"result": result}

    reg = hass.services.async_register
    resp = SupportsResponse.ONLY
    reg(DOMAIN, "get_presets", get_presets, GET_SCHEMA, supports_response=resp)
    reg(DOMAIN, "set_preset", set_preset, SET_PRESET_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    reg(DOMAIN, "delete_preset", delete_preset, DELETE_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    reg(DOMAIN, "get_schedule", get_schedule, GET_SCHEMA, supports_response=resp)
    reg(DOMAIN, "set_schedule", set_schedule, SET_SCHEDULE_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
    reg(DOMAIN, "delete_schedule", delete_schedule, DELETE_SCHEMA, supports_response=SupportsResponse.OPTIONAL)
