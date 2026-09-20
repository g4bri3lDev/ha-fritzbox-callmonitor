"""Tests for the call history coordinator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
from fritzconnection.core.exceptions import FritzConnectionException
from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.fritzbox_callmonitor.const import (
    CONF_HISTORY_DAYS,
    CONF_HISTORY_LIMIT,
    CONF_LOOKUP_PROVIDER,
    DISCONNECT_REFRESH_DELAY,
    LookupProvider,
)
from custom_components.fritzbox_callmonitor.models import CallType, NameSource

from .conftest import FakeContact


def _coordinator(entry: MockConfigEntry):
    """Return the entry's coordinator."""
    return entry.runtime_data.coordinator


async def test_calls_are_newest_first(setup_integration: MockConfigEntry) -> None:
    """A display shows the most recent call at the top."""
    records = _coordinator(setup_integration).calls

    assert [record.id for record in records] == ["3", "2", "1"]
    assert records[0].type is CallType.MISSED


async def test_missed_calls_are_filtered(setup_integration: MockConfigEntry) -> None:
    """Missed calls are counted separately from the rest."""
    assert [r.id for r in _coordinator(setup_integration).missed_calls] == ["3"]


@pytest.mark.parametrize("contacts", [[FakeContact("Alice", ["+4930111222"], "1")]])
async def test_the_phonebook_wins_over_everything(
    setup_integration: MockConfigEntry,
) -> None:
    """The user's own phonebook is authoritative, and carries the VIP flag."""
    record = _coordinator(setup_integration).calls[0]

    assert record.name == "Alice"
    assert record.name_source is NameSource.PHONEBOOK
    assert record.vip is True


async def test_a_name_from_the_box_is_kept(
    setup_integration: MockConfigEntry,
) -> None:
    """A name the box already resolved needs no further work."""
    record = next(r for r in _coordinator(setup_integration).calls if r.id == "1")

    assert record.name == "Known Contact"
    assert record.name_source is NameSource.FRITZBOX


async def test_unknown_numbers_stay_unknown_without_lookup(
    setup_integration: MockConfigEntry,
) -> None:
    """With lookup off -- the default -- an unknown caller is just a number."""
    record = _coordinator(setup_integration).calls[0]

    assert record.name is None
    assert record.name_source is NameSource.UNKNOWN


@pytest.mark.parametrize("contacts", [[FakeContact("Alice", ["+4930111222"])]])
async def test_a_number_the_phonebook_knows_is_never_looked_up(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_fritz: dict[str, MagicMock],
) -> None:
    """Known contacts must never be sent to a third party."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry,
        options={CONF_LOOKUP_PROVIDER: LookupProvider.DASOERTLICHE.value},
    )

    with patch(
        "custom_components.fritzbox_callmonitor.lookup.NumberLookup.async_lookup",
        return_value=None,
    ) as lookup:
        assert await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    looked_up = {call.args[0] for call in lookup.call_args_list}
    assert "+4930111222" not in looked_up


async def test_the_history_window_and_limit_are_applied(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_fritz: dict[str, MagicMock],
) -> None:
    """Both options reach the box and the trimming."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_HISTORY_DAYS: 30, CONF_HISTORY_LIMIT: 2}
    )

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    mock_fritz["call"].get_calls.assert_called_with(days=30)
    assert len(config_entry.runtime_data.coordinator.calls) == 2


async def test_a_failed_refresh_is_reported(
    setup_integration: MockConfigEntry,
    mock_fritz: dict[str, MagicMock],
) -> None:
    """A box that stops answering marks the data stale rather than crashing.

    Refreshed directly rather than by advancing the clock: waiting on the poll
    schedule also waits on the coordinator's debouncer and an executor job, and
    a loaded CI runner does not guarantee both have finished by the assertion.
    """
    mock_fritz["call"].get_calls.side_effect = FritzConnectionException("nope")

    await _coordinator(setup_integration).async_refresh()

    assert _coordinator(setup_integration).last_update_success is False


async def test_a_finished_call_pushes_a_refresh(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    setup_integration: MockConfigEntry,
) -> None:
    """Hanging up should update the display in seconds, not on the next poll.

    The monitor parses events on its own thread, so this also covers handing
    the refresh over to the event loop safely.
    """
    sensor = _find_call_sensor(hass)

    with patch.object(
        _coordinator(setup_integration), "async_request_refresh"
    ) as refresh:
        await hass.async_add_executor_job(
            sensor._monitor._parse, "01.02.26 13:45:00;DISCONNECT;0;12;"
        )
        await hass.async_block_till_done()

        # Not yet: the box needs a moment to flush the entry into its list, and
        # asking immediately returns the list without it.
        refresh.assert_not_called()

        freezer.tick(DISCONNECT_REFRESH_DELAY + 1)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        refresh.assert_called_once()


async def test_other_call_events_do_not_push_a_refresh(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    setup_integration: MockConfigEntry,
) -> None:
    """Only a finished call adds a call list entry worth re-reading."""
    sensor = _find_call_sensor(hass)

    with patch.object(
        _coordinator(setup_integration), "async_request_refresh"
    ) as refresh:
        await hass.async_add_executor_job(
            sensor._monitor._parse,
            "01.02.26 13:45:00;RING;0;+4930111222;+4989000;SIP0;",
        )
        freezer.tick(DISCONNECT_REFRESH_DELAY + 1)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        refresh.assert_not_called()


async def test_get_calls_can_exceed_the_attribute_limit(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_fritz: dict[str, MagicMock],
) -> None:
    """The action exists precisely to see past `history_limit`."""
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_HISTORY_LIMIT: 1}
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = config_entry.runtime_data.coordinator
    assert len(coordinator.calls) == 1

    records = await coordinator.async_fetch(call_type=0, days=7, limit=None)

    assert len(records) == 3


def _find_call_sensor(hass: HomeAssistant):
    """Return the live call-state sensor entity object."""
    from homeassistant.components.sensor import DOMAIN as SENSOR_DOMAIN
    from homeassistant.helpers.entity_component import EntityComponent

    component: EntityComponent = hass.data[SENSOR_DOMAIN]
    for entity in component.entities:
        if type(entity).__name__ == "FritzBoxCallSensor":
            return entity
    raise AssertionError("call sensor not found")
