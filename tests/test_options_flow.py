"""Tests for the options flow."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fritzbox_callmonitor.const import (
    CONF_HISTORY_DAYS,
    CONF_HISTORY_LIMIT,
    CONF_LOOKUP_PROVIDER,
    CONF_PREFIXES,
    CONF_TELLOWS_API_KEY,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_HISTORY_LIMIT,
    DEFAULT_LOOKUP_PROVIDER,
    LookupProvider,
)


async def test_defaults_apply_to_an_entry_from_the_core_integration(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """An entry created by core has none of the new options set.

    That is the whole point of overriding the domain: the existing entry keeps
    working, so the form has to open with sane values rather than blank fields.
    """
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)

    assert result["type"] is FlowResultType.FORM
    defaults = {
        key.schema: key.default()
        for key in result["data_schema"].schema
        if callable(key.default)
    }

    assert defaults[CONF_HISTORY_DAYS] == DEFAULT_HISTORY_DAYS
    assert defaults[CONF_HISTORY_LIMIT] == DEFAULT_HISTORY_LIMIT
    assert defaults[CONF_LOOKUP_PROVIDER] == DEFAULT_LOOKUP_PROVIDER


async def test_lookup_is_off_by_default(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Reverse lookup is opt-in; nothing leaves the network until it is chosen."""
    assert DEFAULT_LOOKUP_PROVIDER is LookupProvider.NONE
    assert setup_integration.runtime_data.lookup.enabled is False


async def test_saving_the_options(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Every field round-trips into the entry options."""
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_PREFIXES: "030, 089",
            CONF_HISTORY_DAYS: 14,
            CONF_HISTORY_LIMIT: 5,
            CONF_LOOKUP_PROVIDER: LookupProvider.TELLOWS.value,
            CONF_TELLOWS_API_KEY: "  secret  ",
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    options = setup_integration.options

    assert options[CONF_PREFIXES] == ["030", "089"]
    assert options[CONF_HISTORY_DAYS] == 14
    assert options[CONF_HISTORY_LIMIT] == 5
    assert options[CONF_LOOKUP_PROVIDER] == LookupProvider.TELLOWS.value
    assert options[CONF_TELLOWS_API_KEY] == "secret"


async def test_saving_options_reloads_the_entry(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_fritz: dict[str, MagicMock],
) -> None:
    """A new window is pointless unless the coordinator picks it up."""
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_HISTORY_DAYS: 21,
            CONF_HISTORY_LIMIT: DEFAULT_HISTORY_LIMIT,
            CONF_LOOKUP_PROVIDER: LookupProvider.NONE.value,
        },
    )
    await hass.async_block_till_done()

    mock_fritz["call"].get_calls.assert_called_with(days=21)


async def test_malformed_prefixes_are_rejected(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Core's prefix validation still applies."""
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_PREFIXES: "  ",
            CONF_HISTORY_DAYS: DEFAULT_HISTORY_DAYS,
            CONF_HISTORY_LIMIT: DEFAULT_HISTORY_LIMIT,
            CONF_LOOKUP_PROVIDER: LookupProvider.NONE.value,
        },
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "malformed_prefixes"}


async def test_an_out_of_range_limit_is_rejected(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The cap is what keeps the attribute under the recorder limit."""
    import pytest
    import voluptuous as vol

    result = await hass.config_entries.options.async_init(setup_integration.entry_id)

    with pytest.raises(vol.Invalid):
        await hass.config_entries.options.async_configure(
            result["flow_id"],
            user_input={
                CONF_HISTORY_DAYS: DEFAULT_HISTORY_DAYS,
                CONF_HISTORY_LIMIT: 9999,
                CONF_LOOKUP_PROVIDER: LookupProvider.NONE.value,
            },
        )
