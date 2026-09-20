"""Tests for the normalized call record."""

from __future__ import annotations

from datetime import UTC, datetime

from homeassistant.core import HomeAssistant
import pytest

from custom_components.fritzbox_callmonitor.models import (
    CallRecord,
    CallType,
    NameSource,
)

from .fritz import FakeCall


@pytest.mark.parametrize(
    ("raw_type", "expected"),
    [
        ("1", CallType.INCOMING),
        ("2", CallType.MISSED),
        ("3", CallType.OUTGOING),
        ("9", CallType.ACTIVE_INCOMING),
        ("10", CallType.REJECTED),
        ("11", CallType.ACTIVE_OUTGOING),
        ("99", CallType.UNKNOWN),
        (None, CallType.UNKNOWN),
    ],
)
def test_every_avm_call_type_maps(raw_type: str | None, expected: CallType) -> None:
    """Each AVM type value becomes a named type, unknown ones included."""
    record = CallRecord.from_call(FakeCall(type=raw_type))

    assert record.type is expected
    assert record.icon.startswith("mdi:")


def test_incoming_call_takes_caller_as_counterpart() -> None:
    """On an incoming call the other party is `Caller`."""
    record = CallRecord.from_call(
        FakeCall(type="1", caller="+4930111222", called_number="+4989000")
    )

    assert record.number == "+4930111222"
    assert record.own_number == "+4989000"


def test_outgoing_call_takes_called_as_counterpart() -> None:
    """On an outgoing call AVM swaps the fields around."""
    record = CallRecord.from_call(
        FakeCall(type="3", called="+4930333444", caller_number="+4989000")
    )

    assert record.number == "+4930333444"
    assert record.own_number == "+4989000"


def test_name_from_the_box_is_attributed_to_the_box() -> None:
    """A name the box filled in comes from its own phonebook."""
    record = CallRecord.from_call(FakeCall(name="Known Contact"))

    assert record.name == "Known Contact"
    assert record.name_source is NameSource.FRITZBOX


def test_missing_name_is_none_rather_than_empty() -> None:
    """An unresolved call has no name at all, not an empty string."""
    record = CallRecord.from_call(FakeCall(name=""))

    assert record.name is None
    assert record.name_source is NameSource.UNKNOWN


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        ("0:05", 300),
        ("1:03", 3780),
        # AVM does not cap the hours at 24 and does not zero pad them.
        ("30:00", 108000),
        ("", 0),
        ("nonsense", 0),
    ],
)
def test_duration_becomes_seconds(duration: str, expected: int) -> None:
    """Durations are reported in seconds whatever AVM sends."""
    assert CallRecord.from_call(FakeCall(duration=duration)).duration == expected


async def test_timestamp_is_timezone_aware(hass: HomeAssistant) -> None:
    """AVM reports local time; the record carries the zone explicitly."""
    record = CallRecord.from_call(FakeCall(date="01.02.26 13:45"))

    assert record.timestamp.tzinfo is not None
    assert record.timestamp.replace(tzinfo=None) == datetime(2026, 2, 1, 13, 45)


async def test_unparseable_date_does_not_raise(hass: HomeAssistant) -> None:
    """A date the box mangles must not take down the whole refresh."""
    record = CallRecord.from_call(FakeCall(date="not a date"))

    assert record.timestamp.tzinfo is not None


def test_as_dict_always_carries_every_key() -> None:
    """Templates loop over these without `default()`, so nothing may be absent."""
    record = CallRecord.from_call(FakeCall())

    assert set(record.as_dict()) == {
        "id",
        "type",
        "number",
        "number_formatted",
        "own_number",
        "name",
        "name_source",
        "vip",
        "spam_score",
        "device",
        "timestamp",
        "duration",
        "icon",
    }


def test_as_dict_is_json_safe() -> None:
    """The dict lands in a state attribute, so it must be plain JSON types."""
    import json

    record = CallRecord.from_call(FakeCall()).with_name(
        "Someone", NameSource.DASOERTLICHE, spam_score=7
    )

    restored = json.loads(json.dumps(record.as_dict()))

    assert restored["name"] == "Someone"
    assert restored["name_source"] == "dasoertliche"
    assert restored["spam_score"] == 7
    assert datetime.fromisoformat(restored["timestamp"]).tzinfo is not None


def test_with_name_ignores_a_source_without_a_name() -> None:
    """Claiming a source while having no name would mislabel the record."""
    record = CallRecord.from_call(FakeCall()).with_name(None, NameSource.DASOERTLICHE)

    assert record.name is None
    assert record.name_source is NameSource.UNKNOWN


def test_utc_timestamps_are_converted_to_local(hass: HomeAssistant) -> None:
    """A tz-aware value from the library is normalized, not passed through."""

    class AwareCall(FakeCall):
        @property
        def date(self) -> datetime:
            return datetime(2026, 2, 1, 12, 0, tzinfo=UTC)

    record = CallRecord.from_call(AwareCall())

    assert record.timestamp.tzinfo is not None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # German area codes run from two to five digits, so the split cannot be
        # done by slicing. All of these came off a real FRITZ!Box.
        ("08704261", "08704 261"),
        ("01738706416", "0173 8706416"),
        ("08717078927", "0871 7078927"),
        ("087173308", "0871 73308"),
        ("+4930111222", "030 111222"),
        ("0049891234567", "089 1234567"),
    ],
)
def test_numbers_are_split_into_area_code_and_subscriber(
    raw: str, expected: str
) -> None:
    """The formatted number is what the display shows."""
    from custom_components.fritzbox_callmonitor.models import format_national

    assert format_national(raw) == expected


def test_a_foreign_number_keeps_its_country_code() -> None:
    """A Swiss caller must not be rendered as though it were German."""
    from custom_components.fritzbox_callmonitor.models import format_national

    assert format_national("+41446681800") == "+41 44 668 18 00"


@pytest.mark.parametrize("raw", ["", "12345", "not a number", "+99999999999999"])
def test_an_unformattable_number_is_returned_unchanged(raw: str) -> None:
    """Formatting is cosmetic; it must never lose or mangle the number."""
    from custom_components.fritzbox_callmonitor.models import format_national

    assert format_national(raw) == raw


def test_the_record_always_offers_something_to_display() -> None:
    """`number_formatted` falls back to the raw number, never to empty."""
    record = CallRecord.from_call(FakeCall(type="1", caller="12345"))

    assert record.as_dict()["number_formatted"] == "12345"
