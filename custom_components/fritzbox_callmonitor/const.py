"""Constants for the AVM Fritz!Box call monitor integration."""

from datetime import timedelta
from enum import StrEnum
from typing import Final

from homeassistant.const import Platform


class FritzState(StrEnum):
    """Fritz!Box call states."""

    RING = "RING"
    CALL = "CALL"
    CONNECT = "CONNECT"
    DISCONNECT = "DISCONNECT"


ATTR_PREFIXES = "prefixes"

FRITZ_ATTR_NAME = "name"
FRITZ_ATTR_SERIAL_NUMBER = "Serial"

UNKNOWN_NAME = "unknown"
SERIAL_NUMBER = "serial_number"
REGEX_NUMBER = r"[^\d\+]"

CONF_PHONEBOOK = "phonebook"
CONF_PHONEBOOK_NAME = "phonebook_name"
CONF_PREFIXES = "prefixes"

DEFAULT_HOST = "169.254.1.1"  # IP valid for all Fritz!Box routers
DEFAULT_PORT = 1012
DEFAULT_USERNAME = "admin"
DEFAULT_PHONEBOOK = 0
DEFAULT_NAME = "Phone"

DOMAIN: Final = "fritzbox_callmonitor"
MANUFACTURER: Final = "FRITZ!"

PLATFORMS = [Platform.SENSOR]


class LookupProvider(StrEnum):
    """Reverse lookup providers.

    Reverse lookup is opt-in: NONE is the default and keeps the integration
    entirely offline apart from the FRITZ!Box itself.
    """

    NONE = "none"
    DASOERTLICHE = "dasoertliche"
    TELLOWS = "tellows"


# Options added by this custom integration on top of the core ones. Every one
# needs a default, because a config entry created by the core integration has
# none of them set.
CONF_HISTORY_DAYS = "history_days"
CONF_HISTORY_LIMIT = "history_limit"
CONF_LOOKUP_PROVIDER = "lookup_provider"
CONF_TELLOWS_API_KEY = "tellows_api_key"

DEFAULT_HISTORY_DAYS = 7
DEFAULT_HISTORY_LIMIT = 20
DEFAULT_LOOKUP_PROVIDER = LookupProvider.NONE

MIN_HISTORY_DAYS = 1
MAX_HISTORY_DAYS = 90
MIN_HISTORY_LIMIT = 1
# Keeps the `calls` attribute well under the recorder's 16 KiB cap on state
# attributes (MAX_STATE_ATTRS_BYTES); ~50 records is roughly 9 KiB.
MAX_HISTORY_LIMIT = 50

ATTR_CALLS = "calls"
ATTR_MISSED_CALLS = "missed_calls"
ATTR_TOTAL_CALLS = "total_calls"

HISTORY_SCAN_INTERVAL = timedelta(minutes=5)
# The box needs a moment to flush a finished call into its call list, so the
# push refresh waits before asking for it.
DISCONNECT_REFRESH_DELAY = 5

SERVICE_GET_CALLS = "get_calls"
SERVICE_LOOKUP_NUMBER = "lookup_number"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_CALL_TYPE = "call_type"
ATTR_DAYS = "days"
ATTR_LIMIT = "limit"
ATTR_NUMBER = "number"
ATTR_FORCE_REFRESH = "force_refresh"
