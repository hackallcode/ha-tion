"""Button platform for Tion actions."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TionConfigEntry
from .api import TionDevice
from .coordinator import TionCoordinator
from .entity import TionEntity


@dataclass(frozen=True, kw_only=True)
class TionButtonDescription(ButtonEntityDescription):
    """Button description with a press handler."""

    press_fn: Callable[[TionCoordinator, TionDevice], Awaitable[None]]
    zone_level: bool = False


async def _apply_schedule(coord: TionCoordinator, device: TionDevice) -> None:
    await coord.async_send(coord.client.apply_schedule(device.zone.guid))


# "Apply schedule settings" — re-syncs the zone to the current scheduled preset
# after a manual change (mirrors the app button shown when the schedule is on but
# the device was changed by hand). Best-effort: pushes the preset onto the
# devices; the cloud is_mode_sync flag may not flip (mobile-app-only).
ZONE_BUTTONS: tuple[TionButtonDescription, ...] = (
    TionButtonDescription(
        key="apply_schedule",
        translation_key="apply_schedule",
        icon="mdi:calendar-sync",
        zone_level=True,
        press_fn=_apply_schedule,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: TionConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[TionButton] = []
    for device in coordinator.zone_representatives():
        entities.extend(TionButton(coordinator, device.guid, d) for d in ZONE_BUTTONS)
    async_add_entities(entities)


class TionButton(TionEntity, ButtonEntity):
    """A momentary Tion action."""

    entity_description: TionButtonDescription

    def __init__(
        self, coordinator: TionCoordinator, guid: str, description: TionButtonDescription
    ) -> None:
        super().__init__(coordinator, guid)
        self.entity_description = description
        if description.zone_level:
            self._attr_unique_id = f"{self._zone.guid}-{description.key}"
        else:
            self._attr_unique_id = f"{guid}-{description.key}"

    async def async_press(self) -> None:
        await self.entity_description.press_fn(self.coordinator, self._device)
