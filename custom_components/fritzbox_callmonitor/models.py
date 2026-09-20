"""Normalized call records.

`fritzconnection` hands back `Call` objects whose attributes mirror the raw AVM
XML node names (`Id`, `Type`, `Caller`, `CalledNumber`, `Date`, ...) and whose
emptiness rules differ per call type. `CallRecord` flattens that into one shape
that is always fully populated, JSON-safe, and stable enough to be a template
contract -- so a drawcustom payload can loop over it without `default()`
guards everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
import re
from typing import Any

from homeassistant.util import dt as dt_util
import phonenumbers

from .const import DEFAULT_REGION, REGEX_NUMBER


class CallType(StrEnum):
    """Type of a call list entry."""

    INCOMING = "incoming"
    MISSED = "missed"
    OUTGOING = "outgoing"
    REJECTED = "rejected"
    ACTIVE_INCOMING = "active_incoming"
    ACTIVE_OUTGOING = "active_outgoing"
    UNKNOWN = "unknown"


class NameSource(StrEnum):
    """Where a resolved name came from."""

    PHONEBOOK = "phonebook"
    FRITZBOX = "fritzbox"
    DASOERTLICHE = "dasoertliche"
    TELLOWS = "tellows"
    UNKNOWN = "unknown"


# fritzconnection's call type constants, which are the raw AVM values.
CALL_TYPES: dict[int, CallType] = {
    1: CallType.INCOMING,
    2: CallType.MISSED,
    3: CallType.OUTGOING,
    9: CallType.ACTIVE_INCOMING,
    10: CallType.REJECTED,
    11: CallType.ACTIVE_OUTGOING,
}

CALL_ICONS: dict[CallType, str] = {
    CallType.INCOMING: "mdi:phone-incoming",
    CallType.MISSED: "mdi:phone-missed",
    CallType.OUTGOING: "mdi:phone-outgoing",
    CallType.REJECTED: "mdi:phone-cancel",
    CallType.ACTIVE_INCOMING: "mdi:phone-in-talk",
    CallType.ACTIVE_OUTGOING: "mdi:phone-in-talk",
    CallType.UNKNOWN: "mdi:phone",
}

# An outgoing call's counterpart is the number that was dialed; for every other
# type it is the number that called in.
_OUTGOING_TYPES = {CallType.OUTGOING, CallType.ACTIVE_OUTGOING}


@dataclass(frozen=True, slots=True)
class CallRecord:
    """One entry of the FRITZ!Box call list."""

    id: str
    type: CallType
    number: str
    own_number: str
    device: str
    timestamp: datetime
    duration: int
    number_formatted: str = ""
    name: str | None = None
    name_source: NameSource = NameSource.UNKNOWN
    vip: bool = False
    spam_score: int | None = None

    @property
    def icon(self) -> str:
        """Return the MDI icon for this call's type."""
        return CALL_ICONS[self.type]

    def with_name(
        self,
        name: str | None,
        source: NameSource,
        *,
        vip: bool = False,
        spam_score: int | None = None,
    ) -> CallRecord:
        """Return a copy carrying resolved caller details."""
        return replace(
            self,
            name=name,
            name_source=source if name else NameSource.UNKNOWN,
            vip=vip,
            spam_score=spam_score if spam_score is not None else self.spam_score,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the template-facing representation.

        Every key is always present. `icon` is included because it is a
        property of the call type rather than of the layout -- a template
        should not have to re-derive it.
        """
        return {
            "id": self.id,
            "type": str(self.type),
            "number": self.number,
            "number_formatted": self.number_formatted or self.number,
            "own_number": self.own_number,
            "name": self.name,
            "name_source": str(self.name_source),
            "vip": self.vip,
            "spam_score": self.spam_score,
            "device": self.device,
            "timestamp": self.timestamp.isoformat(),
            "duration": self.duration,
            "icon": self.icon,
        }

    @classmethod
    def from_call(cls, call: Any, region: str = DEFAULT_REGION) -> CallRecord:
        """Build a record from a `fritzconnection` `Call`."""
        call_type = CALL_TYPES.get(
            _as_int(getattr(call, "Type", None)), CallType.UNKNOWN
        )
        caller = _as_str(getattr(call, "Caller", None))
        called = _as_str(getattr(call, "Called", None))
        caller_number = _as_str(getattr(call, "CallerNumber", None))
        called_number = _as_str(getattr(call, "CalledNumber", None))

        if call_type in _OUTGOING_TYPES:
            # Outgoing: AVM puts the dialed number in `Called` and the own line
            # that placed the call in `CallerNumber`.
            number, own_number = called, caller_number
        else:
            # Incoming: `Caller` is the other party, `CalledNumber` is the own
            # line that was dialed.
            number, own_number = caller, called_number or called

        return cls(
            id=_as_str(getattr(call, "Id", None)),
            type=call_type,
            number=number,
            own_number=own_number,
            number_formatted=format_national(number, region),
            device=_as_str(getattr(call, "Device", None)),
            timestamp=_as_datetime(call),
            duration=_as_duration(call),
            # The box fills `Name` only from its own phonebooks, so an entry
            # that has one is already resolved and needs no lookup.
            name=_as_str(getattr(call, "Name", None)) or None,
            name_source=(
                NameSource.FRITZBOX
                if _as_str(getattr(call, "Name", None))
                else NameSource.UNKNOWN
            ),
        )


def normalize_number(number: str | None) -> str:
    """Strip formatting from a number, as the core phonebook lookup does."""
    if not number:
        return ""
    return re.sub(REGEX_NUMBER, "", str(number))


def format_national(number: str | None, region: str = DEFAULT_REGION) -> str:
    """Return a number spaced the way it is dialled, e.g. "08704 261".

    German area codes run from two to five digits, so the split cannot be done
    by slicing -- 0173 8706416, 0871 7078927 and 08704 261 all differ. Falls
    back to the raw number for anything unparseable, so the caller always has
    something to show.
    """
    if not number:
        return ""
    try:
        parsed = phonenumbers.parse(number, region)
    except phonenumbers.NumberParseException:
        return number

    if not phonenumbers.is_valid_number(parsed):
        return number

    style = (
        phonenumbers.PhoneNumberFormat.NATIONAL
        if phonenumbers.region_code_for_number(parsed) == region
        else phonenumbers.PhoneNumberFormat.INTERNATIONAL
    )
    return phonenumbers.format_number(parsed, style)


def national_number(number: str | None, country_code: str = "49") -> str:
    """Return a number in German national dialing format.

    Both lookup directories are German sites that expect what you would dial:
    `+4930123456` and `004930123456` are the same listing as `030123456`, but
    only the last spelling is accepted. A number from another country keeps its
    international prefix in `00` form.
    """
    value = normalize_number(number)
    if not value:
        return ""

    if value.startswith(f"+{country_code}"):
        return "0" + value[1 + len(country_code) :]
    if value.startswith(f"00{country_code}"):
        return "0" + value[2 + len(country_code) :]
    if value.startswith("+"):
        return "00" + value[1:]
    return value


def _as_str(value: Any) -> str:
    """Return a stripped string, treating None as empty."""
    return "" if value is None else str(value).strip()


def _as_int(value: Any) -> int:
    """Return an int, treating anything unparseable as 0."""
    try:
        return int(value)
    except TypeError, ValueError:
        return 0


def _as_datetime(call: Any) -> datetime:
    """Return the call's start as a tz-aware local datetime.

    `Call.date` is fritzconnection's converted accessor; it is preferred over
    parsing `Date` ourselves, but it is naive, and AVM reports local time.
    """
    value = getattr(call, "date", None)
    if not isinstance(value, datetime):
        value = _parse_date(_as_str(getattr(call, "Date", None)))
    if value.tzinfo is None:
        return value.replace(tzinfo=dt_util.get_default_time_zone())
    return dt_util.as_local(value)


def _parse_date(value: str) -> datetime:
    """Parse AVM's `dd.mm.yy HH:MM` call list format."""
    try:
        return datetime.strptime(value, "%d.%m.%y %H:%M")
    except ValueError:
        return dt_util.utcnow()


def _as_duration(call: Any) -> int:
    """Return a call duration in seconds.

    `Call.duration` is fritzconnection's converted accessor, but its converters
    hand back the raw string when the value does not parse, so the AVM `HH:MM`
    format (hours may exceed 24 and are not zero padded) is still handled here.
    """
    value = getattr(call, "duration", None)
    if isinstance(value, timedelta):
        return int(value.total_seconds())

    text = _as_str(value) or _as_str(getattr(call, "Duration", None))
    if not text or ":" not in text:
        return 0
    hours, _, minutes = text.partition(":")
    return _as_int(hours) * 3600 + _as_int(minutes) * 60
