"""Config flow for the Tion MagicAir integration."""
from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PASSWORD, CONF_SCAN_INTERVAL, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import TionAuthError, TionClient, TionConnectionError
from .const import (
    CONF_AUTH,
    CONF_REFRESH_TOKEN,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(
            CONF_SCAN_INTERVAL, default=int(DEFAULT_SCAN_INTERVAL.total_seconds())
        ): vol.All(int, vol.Range(min=int(MIN_SCAN_INTERVAL.total_seconds()))),
    }
)


class TionConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tion."""

    VERSION = 1

    async def _validate(
        self, username: str, password: str, *, user_initiated: bool = True
    ) -> dict[str, Any]:
        """Log in and return the token fields for the entry, or raise."""
        client = TionClient(async_get_clientsession(self.hass), username, password)
        await client.authenticate(user_initiated=user_initiated)
        return {CONF_AUTH: client.authorization, CONF_REFRESH_TOKEN: client.refresh_token}

    async def _try_validate(
        self, username: str, password: str, errors: dict[str, str]
    ) -> dict[str, Any] | None:
        try:
            return await self._validate(username, password)
        except TionAuthError:
            errors["base"] = "invalid_auth"
        except TionConnectionError:
            errors["base"] = "cannot_connect"
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Unexpected error validating Tion credentials")
            errors["base"] = "unknown"
        return None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
            self._abort_if_unique_id_configured()
            tokens = await self._try_validate(
                user_input[CONF_USERNAME], user_input[CONF_PASSWORD], errors
            )
            if tokens is not None:
                return self.async_create_entry(
                    title=user_input[CONF_USERNAME],
                    data={**user_input, **tokens},
                )
        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """The cloud rejected the stored password."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            tokens = await self._try_validate(
                entry.data[CONF_USERNAME], user_input[CONF_PASSWORD], errors
            )
            if tokens is not None:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_PASSWORD: user_input[CONF_PASSWORD], **tokens},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            description_placeholders={"username": entry.data[CONF_USERNAME]},
            errors=errors,
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Import configuration from configuration.yaml."""
        username = import_data[CONF_USERNAME]
        await self.async_set_unique_id(username.lower())
        self._abort_if_unique_id_configured()

        scan = import_data.get(CONF_SCAN_INTERVAL)
        if isinstance(scan, timedelta):
            scan = int(scan.total_seconds())
        elif scan is None:
            scan = int(DEFAULT_SCAN_INTERVAL.total_seconds())

        try:
            tokens = await self._validate(
                username, import_data[CONF_PASSWORD], user_initiated=False
            )
        except (TionAuthError, TionConnectionError) as err:
            _LOGGER.error("Failed to import Tion YAML config: %s", err)
            return self.async_abort(reason="cannot_connect")

        return self.async_create_entry(
            title=username,
            data={
                CONF_USERNAME: username,
                CONF_PASSWORD: import_data[CONF_PASSWORD],
                CONF_SCAN_INTERVAL: scan,
                **tokens,
            },
        )
