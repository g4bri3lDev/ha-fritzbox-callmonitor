"""Fixtures for the fritzbox_callmonitor tests."""

from __future__ import annotations

from collections.abc import Generator
import queue
from unittest.mock import MagicMock, patch

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fritzbox_callmonitor.const import DOMAIN

from . import MOCK_CONFIG_ENTRY, MOCK_DEVICE_INFO, MOCK_PHONEBOOK_NAME
from .fritz import FakeCall


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load custom_components/ for every test."""


@pytest.fixture
def config_entry() -> MockConfigEntry:
    """Return a config entry in the shape the core integration creates."""
    return MockConfigEntry(
        domain=DOMAIN,
        data=MOCK_CONFIG_ENTRY,
        title=MOCK_PHONEBOOK_NAME,
        unique_id="fake_serial_number-0",
    )


@pytest.fixture
def calls() -> list[FakeCall]:
    """Return a call list covering the types the box reports."""
    return [
        FakeCall(
            id="3",
            type="2",
            caller="+4930111222",
            called_number="+4989000",
            date="03.02.26 09:00",
            duration="0:00",
        ),
        FakeCall(
            id="2",
            type="3",
            called="+4930333444",
            caller_number="+4989000",
            date="02.02.26 18:30",
            duration="0:07",
        ),
        FakeCall(
            id="1",
            type="1",
            caller="+4930555666",
            called_number="+4989000",
            name="Known Contact",
            date="01.02.26 08:15",
            duration="1:03",
        ),
    ]


class FakeContact:
    """A phonebook contact as `FritzPhonebook` exposes it."""

    def __init__(self, name: str, numbers: list[str], category: str = "0") -> None:
        """Build a contact."""
        self.name = name
        self.numbers = numbers
        self.category = category


@pytest.fixture
def contacts() -> list[FakeContact]:
    """Return the phonebook contents.

    Empty by default, so the default call fixture has nothing resolved by the
    phonebook and the other name sources get exercised.
    """
    return []


@pytest.fixture
def phonebook(contacts: list[FakeContact]) -> MagicMock:
    """Return a `FritzPhonebook` stand-in.

    Only the library class is mocked; `FritzBoxPhonebook` stays real, so the
    tests exercise the actual prefix and normalization logic in `get_contact`.
    """
    mock = MagicMock()
    mock.phonebook.contacts = contacts
    mock.phonebook_ids = [0]
    mock.modelname = "FRITZ!Box 7590"
    mock.fc.address = "http://fake_host"
    mock.fc.system_version = "7.57"
    return mock


@pytest.fixture
def fritz_call(calls: list[FakeCall]) -> MagicMock:
    """Return a FritzCall stand-in serving the fixture call list."""
    mock = MagicMock()
    mock.get_calls.return_value = calls
    return mock


@pytest.fixture
def mock_fritz(
    phonebook: MagicMock, fritz_call: MagicMock
) -> Generator[dict[str, MagicMock]]:
    """Patch every fritzconnection entry point the integration uses."""
    connection = MagicMock()
    connection.updatecheck = MOCK_DEVICE_INFO

    with (
        patch(
            "custom_components.fritzbox_callmonitor.FritzConnection",
            return_value=connection,
        ),
        patch(
            "custom_components.fritzbox_callmonitor.base.FritzPhonebook",
            return_value=phonebook,
        ) as phonebook_class,
        patch(
            "custom_components.fritzbox_callmonitor.coordinator.FritzCall",
            return_value=fritz_call,
        ) as call_class,
        patch(
            "custom_components.fritzbox_callmonitor.sensor.FritzMonitor",
        ) as monitor,
        # The event-reading thread blocks on a 10s queue timeout, which would
        # outlive the test. Tests drive `_parse` directly instead.
        patch("custom_components.fritzbox_callmonitor.sensor.Thread"),
    ):
        monitor.return_value.start.return_value = queue.Queue()
        monitor.return_value.is_alive = True

        yield {
            "connection": connection,
            "phonebook": phonebook,
            "phonebook_class": phonebook_class,
            "call": fritz_call,
            "call_class": call_class,
            "monitor": monitor,
        }


@pytest.fixture
async def setup_integration(
    hass: HomeAssistant, config_entry: MockConfigEntry, mock_fritz: dict[str, MagicMock]
) -> MockConfigEntry:
    """Set up the integration with everything mocked."""
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
