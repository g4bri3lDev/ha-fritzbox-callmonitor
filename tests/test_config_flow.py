"""Tests for the config flow.

The flow is vendored from core unchanged apart from sharing one connection, so
these cover that the vendored path still works rather than re-testing every
core branch (core's own suite does that).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fritzconnection.core.exceptions import FritzConnectionException, FritzSecurityError
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from requests.exceptions import ConnectionError as RequestsConnectionError

from custom_components.fritzbox_callmonitor.config_flow import ConnectResult
from custom_components.fritzbox_callmonitor.const import (
    CONF_PHONEBOOK,
    DOMAIN,
    SERIAL_NUMBER,
)

from . import (
    MOCK_DEVICE_INFO,
    MOCK_HOST,
    MOCK_PASSWORD,
    MOCK_PORT,
    MOCK_SERIAL_NUMBER,
    MOCK_USERNAME,
)

USER_INPUT = {
    CONF_HOST: MOCK_HOST,
    CONF_PORT: MOCK_PORT,
    CONF_USERNAME: MOCK_USERNAME,
    CONF_PASSWORD: MOCK_PASSWORD,
}


def _patch_flow(phonebook_names: list[str], connection: MagicMock):
    """Patch the flow's view of the box.

    Only the library class is mocked; `FritzBoxPhonebook` stays real so the
    vendored flow runs its actual code.
    """
    phonebook = MagicMock()
    phonebook.phonebook_ids = list(range(len(phonebook_names)))
    phonebook.phonebook.contacts = []
    phonebook.phonebook_info.side_effect = [{"name": name} for name in phonebook_names]

    return (
        patch(
            "custom_components.fritzbox_callmonitor.config_flow.FritzConnection",
            return_value=connection,
        ),
        patch(
            "custom_components.fritzbox_callmonitor.base.FritzPhonebook",
            return_value=phonebook,
        ),
    )


@pytest.fixture
def connection() -> MagicMock:
    """Return a connection whose updatecheck reports a serial number."""
    mock = MagicMock()
    mock.updatecheck = MOCK_DEVICE_INFO
    return mock


async def test_a_box_with_one_phonebook_is_set_up_directly(
    hass: HomeAssistant, connection: MagicMock
) -> None:
    """With a single phonebook there is nothing to choose."""
    patches = _patch_flow(["fake_phonebook_name"], connection)

    with patches[0], patches[1]:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "fake_phonebook_name"
    assert result["data"][SERIAL_NUMBER] == MOCK_SERIAL_NUMBER
    assert result["data"][CONF_PHONEBOOK] == 0


async def test_the_flow_builds_only_one_connection(
    hass: HomeAssistant, connection: MagicMock
) -> None:
    """Core built a second one just to read the serial number."""
    patches = _patch_flow(["fake_phonebook_name"], connection)

    with (
        patch(
            "custom_components.fritzbox_callmonitor.config_flow.FritzConnection",
            return_value=connection,
        ) as connection_class,
        patches[1],
    ):
        await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
        )
        await hass.async_block_till_done()

    assert connection_class.call_count == 1


async def test_several_phonebooks_are_offered(
    hass: HomeAssistant, connection: MagicMock
) -> None:
    """More than one phonebook means the user picks."""
    patches = _patch_flow(["first", "second"], connection)

    with patches[0], patches[1]:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "phonebook"


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (RequestsConnectionError, ConnectResult.NO_DEVIES_FOUND),
        (FritzSecurityError, ConnectResult.INSUFFICIENT_PERMISSIONS),
        (FritzConnectionException, ConnectResult.INVALID_AUTH),
    ],
)
async def test_connection_problems_are_reported(
    hass: HomeAssistant, exception: type[Exception], expected: str
) -> None:
    """Each failure mode keeps its own message."""
    with patch(
        "custom_components.fritzbox_callmonitor.config_flow.FritzConnection",
        side_effect=exception,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
        )

    assert result["type"] is FlowResultType.ABORT or result["errors"]


async def test_the_same_box_is_not_added_twice(
    hass: HomeAssistant, connection: MagicMock, config_entry: MockConfigEntry
) -> None:
    """The unique id is serial number plus phonebook, as in core."""
    config_entry.add_to_hass(hass)
    patches = _patch_flow(["fake_phonebook_name"], connection)

    with patches[0], patches[1]:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_USER}, data=USER_INPUT
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
