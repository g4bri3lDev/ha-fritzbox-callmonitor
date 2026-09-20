"""Tests for the sensors."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from homeassistant.components.recorder.db_schema import MAX_STATE_ATTRS_BYTES
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.fritzbox_callmonitor.const import (
    ATTR_CALLS,
    ATTR_MISSED_CALLS,
    ATTR_TOTAL_CALLS,
    CONF_HISTORY_LIMIT,
    MAX_HISTORY_LIMIT,
)

from . import ENTITY_CALL_HISTORY, ENTITY_CALL_MONITOR
from .fritz import FakeCall


async def test_the_core_sensor_is_untouched(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """Overriding core must not disturb the entity people already have."""
    state = hass.states.get(ENTITY_CALL_MONITOR)

    assert state is not None
    assert state.state == "idle"


async def test_the_core_sensor_keeps_its_unique_id(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The unique id is what preserves the entity id and its history."""
    registry = er.async_get(hass)
    entry = registry.async_get(ENTITY_CALL_MONITOR)

    assert entry is not None
    assert entry.unique_id == "fake_serial_number-0"


async def test_history_state_is_the_newest_call(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """A timestamp state changes once per call, which is the trigger to use."""
    state = hass.states.get(ENTITY_CALL_HISTORY)
    assert state is not None

    # Home Assistant serializes a timestamp state as UTC; the box reported it
    # in its own local time.
    local = dt_util.as_local(dt_util.parse_datetime(state.state))

    assert local.replace(tzinfo=None).isoformat() == "2026-02-03T09:00:00"


async def test_history_attributes_carry_the_list_and_the_counts(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """The attributes are the template contract a drawcustom payload loops over."""
    state = hass.states.get(ENTITY_CALL_HISTORY)
    assert state is not None

    calls = state.attributes[ATTR_CALLS]

    assert state.attributes[ATTR_TOTAL_CALLS] == 3
    assert state.attributes[ATTR_MISSED_CALLS] == 1
    assert [call["id"] for call in calls] == ["3", "2", "1"]
    assert calls[0]["icon"] == "mdi:phone-missed"
    assert calls[1]["icon"] == "mdi:phone-outgoing"


async def test_history_is_unavailable_when_the_call_list_cannot_be_read(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_fritz: dict[str, MagicMock],
) -> None:
    """The history goes unavailable on its own; the call monitor stays up."""
    from fritzconnection.core.exceptions import FritzConnectionException

    mock_fritz["call"].get_calls.side_effect = FritzConnectionException("denied")
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ENTITY_CALL_HISTORY).state == "unavailable"
    assert hass.states.get(ENTITY_CALL_MONITOR).state == "idle"


async def test_history_state_is_unknown_without_calls(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_fritz: dict[str, MagicMock],
) -> None:
    """A box with an empty call list is not an error."""
    mock_fritz["call"].get_calls.return_value = []
    config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_CALL_HISTORY)

    assert state.state == "unknown"
    assert state.attributes[ATTR_CALLS] == []


@pytest.mark.parametrize(
    "calls",
    [[FakeCall(id=str(index), caller=f"+493011122{index:02d}") for index in range(60)]],
)
async def test_the_attribute_stays_under_the_recorder_limit(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_fritz: dict[str, MagicMock],
) -> None:
    """The recorder drops state attributes over 16 KiB, so the cap must hold.

    Uses the documented maximum, which is the worst case the options flow
    allows.
    """
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_HISTORY_LIMIT: MAX_HISTORY_LIMIT}
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    state = hass.states.get(ENTITY_CALL_HISTORY)
    size = len(json.dumps(dict(state.attributes), default=str).encode())

    assert len(state.attributes[ATTR_CALLS]) == MAX_HISTORY_LIMIT
    assert size < MAX_STATE_ATTRS_BYTES


async def test_both_sensors_share_one_device(
    hass: HomeAssistant, setup_integration: MockConfigEntry
) -> None:
    """One FRITZ!Box, one device, two entities."""
    registry = er.async_get(hass)
    monitor = registry.async_get(ENTITY_CALL_MONITOR)
    history = registry.async_get(ENTITY_CALL_HISTORY)

    assert monitor.device_id is not None
    assert monitor.device_id == history.device_id
