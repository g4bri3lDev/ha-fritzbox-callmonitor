"""Tests for the actions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
import voluptuous as vol

from custom_components.fritzbox_callmonitor.const import (
    CONF_LOOKUP_PROVIDER,
    DOMAIN,
    SERVICE_GET_CALLS,
    SERVICE_LOOKUP_NUMBER,
    LookupProvider,
)
from custom_components.fritzbox_callmonitor.lookup.dasoertliche import (
    URL as DASOERTLICHE_URL,
)

from .test_lookup import fixture


async def test_get_calls_returns_the_list(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The action answers with response data rather than firing an event."""
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_CALLS,
        {"config_entry_id": setup_integration.entry_id},
        blocking=True,
        return_response=True,
    )

    assert [call["id"] for call in response["calls"]] == ["3", "2", "1"]


async def test_get_calls_passes_the_type_filter_to_the_box(
    hass: HomeAssistant,
    setup_integration: MockConfigEntry,
    mock_fritz: dict[str, MagicMock],
) -> None:
    """Filtering happens on the box, not after the fact."""
    await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_CALLS,
        {
            "config_entry_id": setup_integration.entry_id,
            "call_type": "missed",
            "days": 30,
        },
        blocking=True,
        return_response=True,
    )

    mock_fritz["call"].get_calls.assert_called_with(calltype=2, days=30)


async def test_get_calls_honours_the_limit(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A caller can ask for fewer entries."""
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_CALLS,
        {"config_entry_id": setup_integration.entry_id, "limit": 1},
        blocking=True,
        return_response=True,
    )

    assert len(response["calls"]) == 1


async def test_get_calls_rejects_an_unknown_entry(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A typo in the entry id is a validation error, not a traceback."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_CALLS,
            {"config_entry_id": "does-not-exist"},
            blocking=True,
            return_response=True,
        )


async def test_get_calls_rejects_a_window_beyond_the_maximum(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The schema bounds the window the box is asked for."""
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_CALLS,
            {"config_entry_id": setup_integration.entry_id, "days": 999},
            blocking=True,
            return_response=True,
        )


async def test_lookup_number_explains_that_lookup_is_off(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Lookup is opt-in, so the default answer is a pointer to the option."""
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_LOOKUP_NUMBER,
            {
                "config_entry_id": setup_integration.entry_id,
                "number": "+4930111222",
            },
            blocking=True,
            return_response=True,
        )


async def test_lookup_number_resolves_when_enabled(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_fritz: dict[str, MagicMock],
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """With a provider configured the action returns what it found."""
    aioclient_mock.get(DASOERTLICHE_URL, text=fixture("dasoertliche_single_hit.html"))
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={CONF_LOOKUP_PROVIDER: LookupProvider.DASOERTLICHE.value},
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    with patch("custom_components.fritzbox_callmonitor.lookup.REQUEST_SPACING", 0):
        response = await hass.services.async_call(
            DOMAIN,
            SERVICE_LOOKUP_NUMBER,
            {"config_entry_id": config_entry.entry_id, "number": "089 1234567"},
            blocking=True,
            return_response=True,
        )

    assert response["name"] == "Max & Moritz GmbH"
    assert response["source"] == "dasoertliche"


async def test_lookup_number_reports_nothing_found(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_fritz: dict[str, MagicMock],
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """A miss is a complete answer, with every key present."""
    aioclient_mock.get(DASOERTLICHE_URL, status=410, text="")
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={CONF_LOOKUP_PROVIDER: LookupProvider.DASOERTLICHE.value},
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    with patch("custom_components.fritzbox_callmonitor.lookup.REQUEST_SPACING", 0):
        response = await hass.services.async_call(
            DOMAIN,
            SERVICE_LOOKUP_NUMBER,
            {"config_entry_id": config_entry.entry_id, "number": "+4930111222"},
            blocking=True,
            return_response=True,
        )

    assert response == {"name": None, "kind": None, "score": None, "source": "unknown"}
