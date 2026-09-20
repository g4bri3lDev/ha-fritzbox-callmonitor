"""Coordinator for the FRITZ!Box call list.

The call list lives on the router, which means it survives Home Assistant
restarts and also covers calls that happened while Home Assistant was down --
the reason history is read from the box rather than recorded from the call
monitor socket.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from fritzconnection import FritzConnection
from fritzconnection.core.exceptions import FritzConnectionException, FritzSecurityError
from fritzconnection.lib.fritzcall import FritzCall
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from requests.exceptions import ConnectionError as RequestsConnectionError

from .base import FritzBoxPhonebook
from .const import DOMAIN, HISTORY_SCAN_INTERVAL, UNKNOWN_NAME
from .lookup import NumberLookup
from .models import CallRecord, CallType, NameSource

if TYPE_CHECKING:
    from . import FritzBoxCallMonitorConfigEntry

_LOGGER = logging.getLogger(__name__)


class FritzBoxCallHistoryCoordinator(DataUpdateCoordinator[list[CallRecord]]):
    """Fetch the FRITZ!Box call list and resolve caller names."""

    config_entry: FritzBoxCallMonitorConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: FritzBoxCallMonitorConfigEntry,
        connection: FritzConnection,
        phonebook: FritzBoxPhonebook,
        lookup: NumberLookup,
        history_days: int,
        history_limit: int,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=HISTORY_SCAN_INTERVAL,
        )
        self._connection = connection
        self._phonebook = phonebook
        self._lookup = lookup
        self._history_days = history_days
        self._history_limit = history_limit
        self._fritz_call: FritzCall | None = None

    async def _async_update_data(self) -> list[CallRecord]:
        """Fetch the call list and resolve every caller."""
        try:
            calls = await self.hass.async_add_executor_job(self._fetch_calls)
        except FritzSecurityError as err:
            raise ConfigEntryAuthFailed(
                "Insufficient permissions to read the FRITZ!Box call list"
            ) from err
        except FritzConnectionException as err:
            raise UpdateFailed(f"Error reading the call list: {err}") from err
        except RequestsConnectionError as err:
            raise UpdateFailed(f"Unable to reach the FRITZ!Box: {err}") from err

        return [await self._async_resolve(record) for record in calls]

    def _fetch_calls(self) -> list[CallRecord]:
        """Read and normalize the call list. Runs in the executor."""
        if self._fritz_call is None:
            self._fritz_call = FritzCall(fc=self._connection)

        calls = self._fritz_call.get_calls(days=self._history_days)
        records = [CallRecord.from_call(call) for call in calls]
        records.sort(key=lambda record: record.timestamp, reverse=True)
        return records[: self._history_limit]

    async def _async_resolve(self, record: CallRecord) -> CallRecord:
        """Attach a caller name, from the cheapest source that has one.

        Order is phonebook, then whatever the box itself resolved, then the
        optional reverse lookup. The phonebook is authoritative because it is
        the user's own data, and checking it first is also what keeps unknown
        numbers -- and only unknown numbers -- going out to a third party.
        """
        if not record.number:
            return record

        contact = await self.hass.async_add_executor_job(
            self._phonebook.get_contact, record.number
        )
        if contact.name != UNKNOWN_NAME:
            return record.with_name(contact.name, NameSource.PHONEBOOK, vip=contact.vip)

        if record.name_source == NameSource.FRITZBOX and record.name:
            return record

        result = await self._lookup.async_lookup(record.number)
        if result is None:
            return record

        return record.with_name(result.name, result.source, spam_score=result.score)

    @property
    def calls(self) -> list[CallRecord]:
        """Return the current call list."""
        return self.data or []

    @property
    def missed_calls(self) -> list[CallRecord]:
        """Return only the missed calls of the current call list."""
        return [record for record in self.calls if record.type == CallType.MISSED]

    async def async_fetch(
        self, call_type: int, days: int, limit: int | None
    ) -> list[CallRecord]:
        """Fetch a one-off call list for the `get_calls` action.

        Deliberately bypasses `data`, so an action can ask for a longer window
        than the entity attribute is allowed to carry.
        """
        if self._fritz_call is None:
            self._fritz_call = FritzCall(fc=self._connection)

        def _fetch() -> list[CallRecord]:
            calls = self._fritz_call.get_calls(calltype=call_type, days=days)  # type: ignore[union-attr]
            records = [CallRecord.from_call(call) for call in calls]
            records.sort(key=lambda record: record.timestamp, reverse=True)
            return records if limit is None else records[:limit]

        try:
            records = await self.hass.async_add_executor_job(_fetch)
        except (FritzConnectionException, RequestsConnectionError) as err:
            raise UpdateFailed(f"Error reading the call list: {err}") from err

        return [await self._async_resolve(record) for record in records]
