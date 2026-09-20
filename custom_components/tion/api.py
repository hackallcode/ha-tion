"""Async client and models for the Tion MagicAir cloud API."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import (
    API_CLIENT_ID,
    API_CLIENT_SECRET,
    API_LOCATION_URL,
    API_TOKEN_URL,
    API_BASE,
    BREEZER_TYPES,
    MAGICAIR_TYPES,
    MODE_AUTO,
    MODE_MANUAL,
    TASK_MAX_WAIT,
)

_LOGGER = logging.getLogger(__name__)

# Merge breezer changes arriving within this window into one /mode call.
COALESCE_DELAY = 0.3


class TionError(Exception):
    """Base Tion error."""


class TionAuthError(TionError):
    """Raised when authentication fails (bad credentials)."""


class TionConnectionError(TionError):
    """Raised when the cloud cannot be reached or returns an error."""


def _matches(device_type: str | None, markers: tuple[str, ...]) -> bool:
    # Prefix match: "co2mb" must be a MagicAir, not a breezer (it contains "o2").
    dt = (device_type or "").lower()
    return any(dt.startswith(m) for m in markers)


class TionZone:
    """A zone (room) as returned by the cloud. Wraps the raw dict."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self._raw = raw

    @property
    def guid(self) -> str | None:
        return self._raw.get("guid")

    @property
    def name(self) -> str | None:
        return self._raw.get("name")

    @property
    def mode(self) -> str | None:
        """Current zone mode: 'auto' or 'manual'."""
        return (self._raw.get("mode") or {}).get("current")

    @property
    def target_co2(self) -> float | None:
        return ((self._raw.get("mode") or {}).get("auto_set") or {}).get("co2")

    @property
    def schedule(self) -> dict[str, Any]:
        return self._raw.get("schedule") or {}

    @property
    def schedule_is_active(self) -> bool | None:
        """Whether a schedule is configured for the zone."""
        return self.schedule.get("is_active")

    @property
    def schedule_is_running(self) -> bool | None:
        """Whether the schedule currently drives the zone (the on/off state)."""
        return self.schedule.get("is_mode_sync")

    @property
    def current_preset_name(self) -> str | None:
        return (self.schedule.get("current_preset") or {}).get("name")


class TionDevice:
    """A device (breezer or MagicAir station). Wraps the raw dict."""

    def __init__(self, raw: dict[str, Any], zone: TionZone) -> None:
        self._raw = raw
        self.zone = zone

    @property
    def guid(self) -> str | None:
        return self._raw.get("guid")

    @property
    def name(self) -> str | None:
        return self._raw.get("name")

    @property
    def type(self) -> str | None:
        return self._raw.get("type")

    @property
    def mac(self) -> str | None:
        return self._raw.get("mac")

    @property
    def firmware(self) -> str | None:
        return self._raw.get("firmware")

    @property
    def hardware(self) -> str | None:
        return self._raw.get("hardware")

    @property
    def is_online(self) -> bool:
        return bool(self._raw.get("is_online"))

    @property
    def t_max(self) -> float | None:
        return self._raw.get("t_max")

    @property
    def t_min(self) -> float | None:
        return self._raw.get("t_min")

    @property
    def max_speed(self) -> int | None:
        return self._raw.get("max_speed")

    @property
    def data(self) -> dict[str, Any]:
        return self._raw.get("data") or {}

    @property
    def valid(self) -> bool:
        return self.guid is not None and bool(self.data.get("data_valid", True))

    @property
    def is_breezer(self) -> bool:
        return _matches(self.type, BREEZER_TYPES)

    @property
    def is_magicair(self) -> bool:
        return _matches(self.type, MAGICAIR_TYPES)


class TionClient:
    """Async client for the Tion MagicAir cloud."""

    def __init__(
        self,
        session: ClientSession,
        email: str,
        password: str,
        authorization: str | None = None,
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self.authorization = authorization
        # Every breezer /mode POST sends the FULL state, so near-simultaneous
        # commands must not clobber each other. We coalesce overrides that arrive
        # within a short window into ONE /mode call; a lock serializes writes.
        self._write_lock = asyncio.Lock()
        self._pending: dict[str, dict[str, Any]] = {}

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Authorization": self.authorization or "",
            "Content-Type": "application/json",
            "Origin": "https://magicair.tion.ru",
            "Referer": "https://magicair.tion.ru/dashboard/overview",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0) HomeAssistant Tion",
        }

    async def authenticate(self) -> str:
        """Get a fresh OAuth token. Returns the authorization header value."""
        data = {
            "username": self._email,
            "password": self._password,
            "client_id": API_CLIENT_ID,
            "client_secret": API_CLIENT_SECRET,
            "grant_type": "password",
        }
        try:
            async with self._session.post(API_TOKEN_URL, data=data, timeout=15) as resp:
                if resp.status == 200:
                    js = await resp.json()
                    self.authorization = f"{js['token_type']} {js['access_token']}"
                    return self.authorization
                if resp.status in (400, 401):
                    raise TionAuthError("Invalid Tion credentials")
                raise TionConnectionError(f"Token request failed: HTTP {resp.status}")
        except ClientError as err:
            raise TionConnectionError(f"Token request error: {err}") from err
        except asyncio.TimeoutError as err:
            raise TionConnectionError("Token request timed out") from err

    async def _request(
        self, method: str, url: str, *, json: dict | None = None, _retry: bool = True
    ) -> Any:
        """Perform an authorized request, re-authenticating once on 401."""
        if not self.authorization:
            await self.authenticate()
        if method != "GET":
            _LOGGER.debug("Tion -> %s %s json=%s", method, url, json)
        try:
            async with self._session.request(
                method, url, json=json, headers=self._headers, timeout=15
            ) as resp:
                if resp.status == 401 and _retry:
                    await self.authenticate()
                    return await self._request(method, url, json=json, _retry=False)
                if resp.status not in (200, 201, 204):
                    raise TionConnectionError(f"{method} {url} -> HTTP {resp.status}")
                if resp.status == 204:
                    return None
                try:
                    body = await resp.json(content_type=None)
                except (ValueError, TypeError):
                    body = None
                if method != "GET":
                    _LOGGER.debug("Tion <- %s %s status=%s body=%s",
                                  method, url, resp.status, body)
                return body
        except ClientError as err:
            raise TionConnectionError(f"{method} {url} error: {err}") from err
        except asyncio.TimeoutError as err:
            raise TionConnectionError(f"{method} {url} timed out") from err

    async def get_devices_and_zones(self) -> tuple[list[TionDevice], list[TionZone]]:
        """Fetch the whole location tree in one call."""
        locations = await self._request("GET", API_LOCATION_URL)
        devices: list[TionDevice] = []
        zones: list[TionZone] = []
        for location in locations or []:
            for raw_zone in location.get("zones", []):
                zone = TionZone(raw_zone)
                zones.append(zone)
                for raw_device in raw_zone.get("devices", []):
                    devices.append(TionDevice(raw_device, zone))
        return devices, zones

    async def _wait_for_task(self, js: dict[str, Any]) -> bool:
        """Poll a queued command until completed."""
        if js.get("status") != "queued":
            _LOGGER.warning("Tion command not queued: %s", js)
            return False
        task_id = js.get("task_id")
        if not task_id:
            return False
        url = f"{API_BASE}/task/{task_id}"
        delay = 0.5
        for _ in range(int(TASK_MAX_WAIT / delay)):
            result = await self._request("GET", url)
            if result.get("status") == "completed":
                return True
            await asyncio.sleep(delay)
        _LOGGER.warning("Tion task %s did not complete in %ss", task_id, TASK_MAX_WAIT)
        return False

    # -- setters -------------------------------------------------------------

    async def _fresh_device(self, guid: str) -> TionDevice | None:
        devices, _ = await self.get_devices_and_zones()
        return next((d for d in devices if d.guid == guid), None)

    async def _fresh_zone(self, guid: str) -> TionZone | None:
        _, zones = await self.get_devices_and_zones()
        return next((z for z in zones if z.guid == guid), None)

    async def set_zone_mode(
        self, zone: TionZone, *, mode: str | None = None, target_co2: float | None = None
    ) -> bool:
        """Set zone auto/manual mode and/or target CO2."""
        _LOGGER.debug("set_zone_mode zone=%s mode=%s target_co2=%s (was %s)",
                      zone.guid, mode, target_co2, zone.mode)
        async with self._write_lock:
            fresh = await self._fresh_zone(zone.guid) or zone
            new_mode = mode or fresh.mode or MODE_MANUAL
            co2 = target_co2 if target_co2 is not None else fresh.target_co2
            payload = {
                "mode": new_mode if new_mode in (MODE_AUTO, MODE_MANUAL) else MODE_MANUAL,
                "co2": int(co2) if co2 is not None else 900,
            }
            js = await self._request(
                "POST", f"{API_BASE}/zone/{zone.guid}/mode", json=payload
            )
            return await self._wait_for_task(js)

    async def set_breezer(self, device: TionDevice, **overrides: Any) -> bool:
        """Queue a breezer change. Overrides arriving within COALESCE_DELAY are
        merged into ONE /mode call, built from freshly re-read state — so e.g.
        a fan-speed change and an hvac-mode change fired together both apply."""
        guid = device.guid
        _LOGGER.debug("set_breezer queue guid=%s overrides=%s (zone_mode=%s)",
                      guid, overrides, device.zone.mode)
        self._pending.setdefault(guid, {}).update(overrides)
        await asyncio.sleep(COALESCE_DELAY)
        async with self._write_lock:
            pending = self._pending.pop(guid, None)
            if not pending:
                _LOGGER.debug("set_breezer guid=%s already flushed by a concurrent call", guid)
                return True  # a concurrent call already flushed our overrides
            fresh = await self._fresh_device(guid) or device
            _LOGGER.debug("set_breezer flush guid=%s merged=%s", guid, pending)
            return await self._set_breezer_locked(fresh, pending)

    async def _set_breezer_locked(self, device: TionDevice, overrides: dict) -> bool:
        d = device.data
        speed = overrides.get("speed", d.get("speed") or 0)
        speed = int(round(speed))
        heater_enabled = overrides.get("heater_enabled")
        if heater_enabled is None:
            heater_enabled = bool(d.get("heater_enabled") or d.get("heater_mode") == "heat")
        # is_on MUST come from the real device state when not explicitly set, NOT
        # inferred from speed: an "off" command sends speed>=1 (the API needs it),
        # so a later partial command (e.g. a temperature change) that inferred
        # is_on from speed>0 would resurrect a breezer the user just turned off.
        is_on = overrides.get("is_on")
        if is_on is None:
            is_on = bool(d.get("is_on"))
        payload: dict[str, Any] = {
            "is_on": bool(is_on),
            "heater_enabled": bool(heater_enabled),
            "heater_mode": "heat" if heater_enabled else "maintenance",
            "t_set": int(round(overrides.get("t_set", d.get("t_set") or 10))),
            "speed": speed if speed > 0 else 1,
            "speed_min_set": int(round(overrides.get("speed_min_set", d.get("speed_min_set") or 0))),
            "speed_max_set": int(round(overrides.get("speed_max_set", d.get("speed_max_set") or 6))),
        }
        # gate rides along in the full /mode payload (backlight/sound are separate).
        gate = overrides.get("gate", d.get("gate"))
        if gate is not None:
            payload["gate"] = int(gate)
        js = await self._request(
            "POST", f"{API_BASE}/device/{device.guid}/mode", json=payload
        )
        return await self._wait_for_task(js)

    async def reset_filter(self, device: TionDevice) -> bool:
        """Reset the filter life timer (POST /device/{guid}/settings)."""
        async with self._write_lock:
            js = await self._request(
                "POST",
                f"{API_BASE}/device/{device.guid}/settings",
                json={"reset_filter_timer": True},
            )
            return await self._wait_for_task(js)

    async def set_device_backlight(self, device: TionDevice, backlight: int) -> bool:
        """Backlight toggle for any device (POST /device/{guid}/settings)."""
        async with self._write_lock:
            js = await self._request(
                "POST",
                f"{API_BASE}/device/{device.guid}/settings",
                json={"backlight": int(backlight)},
            )
            return await self._wait_for_task(js)

    async def set_sound(self, device: TionDevice, on: bool) -> bool:
        """Breezer beeper toggle (POST /device/{guid}/settings, field 'sound')."""
        async with self._write_lock:
            js = await self._request(
                "POST",
                f"{API_BASE}/device/{device.guid}/settings",
                json={"sound": bool(on)},
            )
            return await self._wait_for_task(js)

    # -- presets & schedule (per zone) --------------------------------------

    async def get_presets(self, zone_guid: str) -> list:
        return await self._request("GET", f"{API_BASE}/preset/{zone_guid}") or []

    async def save_preset(self, zone_guid: str, preset: dict) -> Any:
        """Create (no guid) or edit (guid → ?presetId= query, verified) a preset."""
        guid = preset.get("guid")
        if guid:
            url = f"{API_BASE}/preset/{zone_guid}?presetId={guid}"
            return await self._request("PUT", url, json=preset)
        return await self._request("POST", f"{API_BASE}/preset/{zone_guid}", json=preset)

    async def delete_preset(self, zone_guid: str, preset_guid: str) -> Any:
        # Mobile-API form (from app capture): DELETE /preset/{zone}?presetId={guid}.
        # Presets are capped at 5 per zone.
        # DANGER: on this cloud a delete can also wipe the zone's OTHER presets
        # and the schedule (observed twice). Snapshot first and restore whatever
        # the delete took beyond the requested preset.
        presets_before, sched_before = await self._snapshot_presets_schedule(zone_guid)
        target = next(
            (p.get("name") for p in presets_before if p.get("guid") == preset_guid), None
        )
        result = await self._request(
            "DELETE", f"{API_BASE}/preset/{zone_guid}?presetId={preset_guid}"
        )
        await self._reconcile_zone(
            zone_guid, presets_before, sched_before,
            deleted_names={target} if target else set(),
        )
        return result

    async def get_schedule(self, zone_guid: str) -> list:
        return await self._request("GET", f"{API_BASE}/schedule/{zone_guid}") or []

    async def save_schedule(self, zone_guid: str, schedule: dict) -> Any:
        """Create (no guid → POST) or edit (guid → PUT ?scheduleId=) a schedule.
        NOTE: editing (re-applying) does NOT enable it and in fact clears
        is_mode_sync; enabling is mobile-app-only (see set_schedule_active)."""
        body = {
            "active_days": schedule["active_days"],
            "timings": [
                {"preset_id": t["preset_id"], "starts_at": t["starts_at"]}
                for t in schedule["timings"]
            ],
        }
        guid = schedule.get("guid")
        if guid:
            url = f"{API_BASE}/schedule/{zone_guid}?scheduleId={guid}"
            return await self._request("PUT", url, json=body)
        return await self._request("POST", f"{API_BASE}/schedule/{zone_guid}", json=body)

    async def delete_schedule(self, zone_guid: str, schedule_guid: str) -> Any:
        # Bundle-confirmed: DELETE /schedule/{zone}?scheduleid={guid} (query
        # param, NOT body — the body form returned 500).
        # DANGER: deleting a schedule also wipes the zone's presets on this cloud
        # (observed). Snapshot the presets and restore any that get wiped; the
        # schedule itself is meant to go, so it is not restored.
        presets_before, _ = await self._snapshot_presets_schedule(zone_guid)
        result = await self._request(
            "DELETE", f"{API_BASE}/schedule/{zone_guid}?scheduleid={schedule_guid}"
        )
        await self._reconcile_zone(zone_guid, presets_before, None)
        return result

    async def _snapshot_presets_schedule(self, zone_guid: str):
        """Capture the zone's presets (full) and schedule (timings keyed by preset
        NAME, so they survive preset-guid churn) for restore after a delete."""
        presets = await self.get_presets(zone_guid)
        schedule = await self.get_schedule(zone_guid)
        id2name = {p.get("guid"): p.get("name") for p in presets}
        sched = None
        if schedule:
            s = schedule[0]
            sched = {
                "active_days": s.get("active_days"),
                "timings": [
                    {"name": id2name.get(t.get("preset_id")), "starts_at": t.get("starts_at")}
                    for t in s.get("timings", [])
                ],
            }
        return presets, sched

    async def _reconcile_zone(
        self, zone_guid: str, presets_before: list, sched_before: dict | None,
        deleted_names: set | None = None,
    ) -> None:
        """Undo cascade damage from a delete: recreate presets/schedule wiped as a
        side effect, keeping intentionally-deleted names gone. Recreated presets
        get fresh guids, so the schedule is re-pointed by name."""
        deleted_names = deleted_names or set()
        have = {p.get("name") for p in await self.get_presets(zone_guid)}
        for p in presets_before:
            name = p.get("name")
            if name in deleted_names or name in have:
                continue
            _LOGGER.warning(
                "Recreating preset %r wiped by a Tion delete side effect", name
            )
            body = {k: p[k] for k in ("name", "icon", "climate_settings", "devices") if k in p}
            await self.save_preset(zone_guid, body)

        if sched_before is None:
            return
        n2g = {p.get("name"): p.get("guid") for p in await self.get_presets(zone_guid)}
        timings = [
            {"preset_id": n2g[t["name"]], "starts_at": t["starts_at"]}
            for t in sched_before.get("timings", [])
            if t.get("name") in n2g
        ]
        if not timings:
            return
        cur = await self.get_schedule(zone_guid)
        if not cur:
            _LOGGER.warning("Recreating schedule wiped by a Tion delete side effect")
            await self.save_schedule(
                zone_guid, {"active_days": sched_before["active_days"], "timings": timings}
            )
            return
        cur_ids = set(n2g.values())
        if any(t.get("preset_id") not in cur_ids for t in cur[0].get("timings", [])):
            # schedule survived but references recreated (new-guid) presets → re-point
            await self.save_schedule(
                zone_guid,
                {"guid": cur[0]["guid"], "active_days": sched_before["active_days"],
                 "timings": timings},
            )

    async def set_schedule_active(self, zone_guid: str, active: bool) -> bool:
        """Enable/disable schedule operation. Mobile-API form (verified live on
        api2): POST /zone/{guid}/schedule?on=true|false (the on/off state is a
        QUERY param, not a body field), task 'toggleCalendar'. No-op if already
        in the requested state. Requires an existing schedule in the zone."""
        async with self._write_lock:
            zone = await self._fresh_zone(zone_guid)
            if zone is not None and bool(zone.schedule_is_active) == active:
                return True
            js = await self._request(
                "POST",
                f"{API_BASE}/zone/{zone_guid}/schedule?on={'true' if active else 'false'}",
                json={},
            )
            return await self._wait_for_task(js)

    async def apply_schedule(self, zone_guid: str) -> bool:
        """Re-sync the zone to its current scheduled preset ('apply schedule
        settings' in the app). Mobile-API form (verified live on api2): POST
        /zone/{guid}/schedule/preset with an empty body, task 'activatePreset'.
        Sets is_mode_sync back to true and applies the scheduled preset."""
        js = await self._request(
            "POST", f"{API_BASE}/zone/{zone_guid}/schedule/preset", json={}
        )
        return await self._wait_for_task(js)
