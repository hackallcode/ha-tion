"""The Tion MagicAir integration."""
from __future__ import annotations

import logging
from datetime import timedelta

import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.const import (
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from .api import TionAuthError, TionClient, TionConnectionError
from .const import CONF_AUTH, DEFAULT_SCAN_INTERVAL, DOMAIN
from .coordinator import TionCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.CLIMATE,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.BUTTON,
]

type TionConfigEntry = ConfigEntry[TionCoordinator]

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Optional(CONF_SCAN_INTERVAL): cv.time_period,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register services and import legacy YAML config into a config entry."""
    from .services import async_setup_services

    async_setup_services(hass)
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data=config[DOMAIN]
            )
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TionConfigEntry) -> bool:
    """Set up Tion from a config entry."""
    session = async_get_clientsession(hass)
    client = TionClient(
        session,
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
        authorization=entry.data.get(CONF_AUTH),
    )
    try:
        await client.authenticate()
    except TionAuthError as err:
        from homeassistant.exceptions import ConfigEntryAuthFailed

        raise ConfigEntryAuthFailed(str(err)) from err
    except TionConnectionError as err:
        from homeassistant.exceptions import ConfigEntryNotReady

        raise ConfigEntryNotReady(str(err)) from err

    # Persist the fresh token so a restart doesn't re-authenticate needlessly.
    if client.authorization != entry.data.get(CONF_AUTH):
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_AUTH: client.authorization}
        )

    scan = entry.data.get(CONF_SCAN_INTERVAL)
    scan_interval = timedelta(seconds=scan) if scan else DEFAULT_SCAN_INTERVAL

    coordinator = TionCoordinator(hass, entry, client, scan_interval)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TionConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
