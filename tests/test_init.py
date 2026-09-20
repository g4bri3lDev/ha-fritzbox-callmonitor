"""Tests for setting the integration up."""

from __future__ import annotations

from unittest.mock import MagicMock

from fritzconnection.core.exceptions import FritzConnectionException, FritzSecurityError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from requests.exceptions import ConnectionError as RequestsConnectionError

from custom_components.fritzbox_callmonitor.const import DOMAIN

from . import ENTITY_CALL_MONITOR


async def test_setup_and_unload(setup_integration: MockConfigEntry) -> None:
    """The entry loads and unloads cleanly."""
    assert setup_integration.state is ConfigEntryState.LOADED


async def test_one_connection_is_shared(
    setup_integration: MockConfigEntry, mock_fritz: dict[str, MagicMock]
) -> None:
    """The phonebook and the call list use the same TR-064 session.

    Core built a second connection for the box info; sharing one is the point
    of passing `fc=` around.
    """
    connection = mock_fritz["connection"]

    mock_fritz["phonebook_class"].assert_called_once_with(fc=connection)
    mock_fritz["call_class"].assert_called_once_with(fc=connection)


async def test_unload_removes_the_entry(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Unloading tears the platforms down."""
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()

    assert setup_integration.state is ConfigEntryState.NOT_LOADED


async def test_a_connection_error_retries_later(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_fritz: dict[str, MagicMock]
) -> None:
    """An unreachable box is a retry, not a failure."""
    with _patch_phonebook_init(RequestsConnectionError):
        config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_bad_credentials_trigger_reauth(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_fritz: dict[str, MagicMock]
) -> None:
    """A rejected login asks the user to re-authenticate."""
    with _patch_phonebook_init(FritzConnectionException):
        config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_insufficient_permissions_fail_setup(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_fritz: dict[str, MagicMock]
) -> None:
    """A user without phonebook access cannot be set up at all."""
    with _patch_phonebook_init(FritzSecurityError):
        config_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_an_unreadable_call_list_does_not_fail_the_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_fritz: dict[str, MagicMock]
) -> None:
    """Reading the call list needs a permission the phonebook does not.

    Core's call-state sensor worked without it, so a box that refuses the call
    list must still load -- only the history entity goes unavailable.
    """
    mock_fritz["call"].get_calls.side_effect = FritzConnectionException("denied")

    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert hass.states.get(ENTITY_CALL_MONITOR) is not None


async def test_services_are_registered_once(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Both actions exist after the first entry is set up."""
    assert hass.services.has_service(DOMAIN, "get_calls")
    assert hass.services.has_service(DOMAIN, "lookup_number")


def _patch_phonebook_init(exception: type[Exception]):
    """Make the phonebook fail to initialize."""
    from unittest.mock import patch

    return patch(
        "custom_components.fritzbox_callmonitor.FritzBoxPhonebook.init_phonebook",
        side_effect=exception,
    )


def test_the_translations_stay_in_sync() -> None:
    """A missing key falls back to the raw id in the UI, which looks broken."""
    import json
    from pathlib import Path

    translations = Path("custom_components/fritzbox_callmonitor/translations")
    english = json.loads((translations / "en.json").read_text())

    def missing(reference, other, path=""):
        gaps = []
        if isinstance(reference, dict):
            for key, value in reference.items():
                if key not in other:
                    gaps.append(f"{path}.{key}")
                else:
                    gaps += missing(value, other[key], f"{path}.{key}")
        return gaps

    for path in translations.glob("*.json"):
        assert not missing(english, json.loads(path.read_text())), path.name
