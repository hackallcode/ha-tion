"""Constants for the Tion MagicAir integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "tion"

# Config
CONF_AUTH = "auth"  # cached "token_type access_token" stored in the entry
DEFAULT_SCAN_INTERVAL = timedelta(seconds=60)
MIN_SCAN_INTERVAL = timedelta(seconds=10)

# Tion MagicAir cloud API
API_BASE = "https://api2.magicair.tion.ru"
API_TOKEN_URL = f"{API_BASE}/idsrv/oauth2/token"
API_LOCATION_URL = f"{API_BASE}/location"
API_CLIENT_ID = "cd594955-f5ba-4c20-9583-5990bb29f4ef"
API_CLIENT_SECRET = "syRxSrT77P"
TASK_MAX_WAIT = 10  # seconds to wait for a queued command to complete

# Device type markers returned by the API in device["type"]
BREEZER_TYPES = ("breezer", "o2")  # breezer3, breezer4, O2...
MAGICAIR_TYPES = ("co2",)  # co2mb...

# Air source (breezer "gate")
GATE_INSIDE = 0
GATE_COMBINED = 1
GATE_OUTSIDE = 2
GATE_TO_NAME = {GATE_INSIDE: "inside", GATE_COMBINED: "combined", GATE_OUTSIDE: "outside"}
NAME_TO_GATE = {v: k for k, v in GATE_TO_NAME.items()}

# Zone modes
MODE_AUTO = "auto"
MODE_MANUAL = "manual"

MANUFACTURER = "Tion"
