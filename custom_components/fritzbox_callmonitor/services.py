"""Actions for the fritzbox_callmonitor integration.

Both return response data rather than firing events: they exist for scripts and
templates that want more than the history sensor's attribute can carry, or that
want to resolve a single number on demand.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .const import (
    ATTR_CALL_TYPE,
    ATTR_CONFIG_ENTRY_ID,
    ATTR_DAYS,
    ATTR_FORCE_REFRESH,
    ATTR_LIMIT,
    ATTR_NUMBER,
    DEFAULT_HISTORY_DAYS,
    DOMAIN,
    MAX_HISTORY_DAYS,
    MIN_HISTORY_DAYS,
    SERVICE_GET_CALLS,
    SERVICE_LOOKUP_NUMBER,
)

if TYPE_CHECKING:
    from . import FritzBoxCallMonitorConfigEntry

# The AVM call type filter, by the names used in CallRecord.
CALL_TYPE_FILTERS: dict[str, int] = {
    "all": 0,
    "incoming": 1,
    "missed": 2,
    "outgoing": 3,
    "rejected": 10,
}

GET_CALLS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional(ATTR_CALL_TYPE, default="all"): vol.In(CALL_TYPE_FILTERS),
        vol.Optional(ATTR_DAYS, default=DEFAULT_HISTORY_DAYS): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_HISTORY_DAYS, max=MAX_HISTORY_DAYS)
        ),
        vol.Optional(ATTR_LIMIT): vol.All(vol.Coerce(int), vol.Range(min=1)),
    }
)

LOOKUP_NUMBER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(ATTR_NUMBER): cv.string,
        vol.Optional(ATTR_FORCE_REFRESH, default=False): cv.boolean,
    }
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the actions once, no matter how many entries exist."""
    if hass.services.has_service(DOMAIN, SERVICE_GET_CALLS):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_CALLS,
        _async_get_calls,
        schema=GET_CALLS_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_LOOKUP_NUMBER,
        _async_lookup_number,
        schema=LOOKUP_NUMBER_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )


async def _async_get_calls(call: ServiceCall) -> ServiceResponse:
    """Return the call list for a window, bypassing the attribute cap."""
    entry = _get_entry(call)
    records = await entry.runtime_data.coordinator.async_fetch(
        call_type=CALL_TYPE_FILTERS[call.data[ATTR_CALL_TYPE]],
        days=call.data[ATTR_DAYS],
        limit=call.data.get(ATTR_LIMIT),
    )
    return {"calls": [record.as_dict() for record in records]}


async def _async_lookup_number(call: ServiceCall) -> ServiceResponse:
    """Look up a single number on demand."""
    entry = _get_entry(call)
    lookup = entry.runtime_data.lookup

    if not lookup.enabled:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="lookup_disabled",
        )

    result = await lookup.async_lookup(
        call.data[ATTR_NUMBER], force_refresh=call.data[ATTR_FORCE_REFRESH]
    )
    if result is None:
        return {"name": None, "kind": None, "score": None, "source": "unknown"}
    return dict(result.as_dict())


def _get_entry(call: ServiceCall) -> FritzBoxCallMonitorConfigEntry:
    """Return the loaded config entry named by the call."""
    entry_id: str = call.data[ATTR_CONFIG_ENTRY_ID]
    entry: Any = call.hass.config_entries.async_get_entry(entry_id)

    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_found",
            translation_placeholders={"target": entry_id},
        )
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
            translation_placeholders={"target": entry.title},
        )
    return entry
