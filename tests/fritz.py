"""Stand-ins for the parts of fritzconnection the integration talks to.

These mirror the real library's shapes rather than its behavior: `Call`
attributes are the raw AVM XML node names with the lowercase converted
accessors on top, which is exactly the awkwardness `CallRecord` exists to
absorb, so the tests have to reproduce it faithfully.
"""

from __future__ import annotations

from datetime import datetime, timedelta


class FakeCall:
    """A `fritzconnection.lib.fritzcall.Call` look-alike."""

    def __init__(
        self,
        *,
        id: str = "1",
        type: str = "1",
        caller: str | None = None,
        called: str | None = None,
        caller_number: str | None = None,
        called_number: str | None = None,
        name: str | None = None,
        device: str = "Fon 1",
        date: str = "01.02.26 13:45",
        duration: str = "0:05",
    ) -> None:
        """Build a call entry."""
        self.Id = id
        self.Type = type
        self.Caller = caller
        self.Called = called
        self.CallerNumber = caller_number
        self.CalledNumber = called_number
        self.Name = name
        self.Device = device
        self.Port = "10"
        self.Date = date
        self.Duration = duration
        self.Count = None
        self.Path = None

    @property
    def id(self) -> int | str:
        """Return the id as int, as the library's converter does."""
        return _convert(self.Id, int)

    @property
    def type(self) -> int | str:
        """Return the type as int, as the library's converter does."""
        return _convert(self.Type, int)

    @property
    def date(self) -> datetime | str:
        """Return the date as datetime, as the library's converter does."""
        return _convert(self.Date, _to_datetime)

    @property
    def duration(self) -> timedelta | str:
        """Return the duration as timedelta, as the library's converter does."""
        return _convert(self.Duration, _to_timedelta)


def _convert(value, converter):
    """Convert, falling back to the raw value -- the library swallows errors."""
    if not value:
        return value
    try:
        return converter(value)
    except TypeError, ValueError:
        return value


def _to_datetime(value: str) -> datetime:
    """Parse AVM's call list date format."""
    return datetime.strptime(value, "%d.%m.%y %H:%M")


def _to_timedelta(value: str) -> timedelta:
    """Parse AVM's `HH:MM` duration format."""
    hours, minutes = (int(part) for part in value.split(":", 1))
    return timedelta(hours=hours, minutes=minutes)
