"""Diagnostics for the fritzbox_callmonitor integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import FritzBoxCallMonitorConfigEntry
from .const import CONF_TELLOWS_API_KEY

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME, CONF_TELLOWS_API_KEY}
# Call records are phone numbers and the names behind them -- the most personal
# data this integration touches. Diagnostics report their shape, never them.
CALL_KEYS_TO_REDACT = {"number", "own_number", "name", "id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: FritzBoxCallMonitorConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    data = config_entry.runtime_data
    coordinator = data.coordinator

    return {
        "entry": {
            "data": async_redact_data(dict(config_entry.data), TO_REDACT),
            "options": async_redact_data(dict(config_entry.options), TO_REDACT),
        },
        "lookup": {
            "enabled": data.lookup.enabled,
            "provider": data.lookup.provider_domain,
        },
        "history": {
            "last_update_success": coordinator.last_update_success,
            "total_calls": len(coordinator.calls),
            "missed_calls": len(coordinator.missed_calls),
            "calls": [
                async_redact_data(record.as_dict(), CALL_KEYS_TO_REDACT)
                for record in coordinator.calls
            ],
        },
    }
