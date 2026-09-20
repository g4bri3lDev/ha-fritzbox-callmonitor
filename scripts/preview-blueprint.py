#!/usr/bin/env python3
"""Render a drawcustom blueprint's payload to a PNG, without Home Assistant.

The payload is a Jinja template producing a JSON array, so it can be rendered
offline against sample data -- which is how the shipped layout was checked for
overlapping text rather than by flashing a tag repeatedly.

    uv run --with jinja2 --with odl-renderer python scripts/preview-blueprint.py
    uv run --with jinja2 --with odl-renderer python scripts/preview-blueprint.py --empty

The Home Assistant template helpers used by the blueprint (`now`, `timedelta`,
`as_timestamp`, `timestamp_custom`) are reimplemented here so the harness
renders exactly the text the blueprint ships, not a convenient variant of it.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta, timezone
import json
from pathlib import Path
import sys

import yaml
from jinja2 import Environment
from odl_renderer import generate_image

REPO = Path(__file__).resolve().parents[1]
BLUEPRINT = (
    REPO / "blueprints/automation/fritzbox_callmonitor/call_list_400x300.yaml"
)

TZ = timezone(timedelta(hours=1))
NOW = datetime(2026, 2, 3, 19, 12, tzinfo=TZ)


def _record(**overrides: object) -> dict:
    """Return a call record in the shape `CallRecord.as_dict` produces."""
    record = {
        "id": "1",
        "type": "incoming",
        "number": "",
        "own_number": "+4989000",
        "name": None,
        "name_source": "unknown",
        "vip": False,
        "spam_score": None,
        "device": "Fon 1",
        "timestamp": NOW.isoformat(),
        "duration": 0,
        "icon": "mdi:phone-incoming",
    }
    record.update(overrides)
    return record


# One of each case the layout has to survive: an unknown number, a long VIP
# name, a spam-scored caller, an outgoing call, a withheld caller and a name
# long enough to be truncated.
SAMPLE = [
    _record(
        id="9",
        type="missed",
        number="+4930555123456",
        icon="mdi:phone-missed",
        timestamp=(NOW - timedelta(minutes=18)).isoformat(),
    ),
    _record(
        id="8",
        number="+498912345",
        name="Dr. Weber Zahnarztpraxis",
        name_source="phonebook",
        vip=True,
        duration=372,
        timestamp=(NOW - timedelta(hours=3)).isoformat(),
    ),
    _record(
        id="7",
        type="missed",
        number="+4932221099887",
        name="Gewinnspiel Service",
        name_source="tellows",
        spam_score=8,
        icon="mdi:phone-missed",
        timestamp=(NOW - timedelta(hours=5)).isoformat(),
    ),
    _record(
        id="6",
        type="outgoing",
        number="+4915112345678",
        name="Mama",
        name_source="phonebook",
        icon="mdi:phone-outgoing",
        duration=1845,
        timestamp=(NOW - timedelta(days=1)).isoformat(),
    ),
    # A withheld caller, exactly as a real FRITZ!Box reports one: no number at
    # all, and the box's own placeholder in the name field.
    _record(
        id="5b",
        type="missed",
        number="",
        name="Unbekannt",
        name_source="fritzbox",
        icon="mdi:phone-missed",
        timestamp=(NOW - timedelta(days=1, hours=4)).isoformat(),
    ),
    _record(
        id="5",
        number="+498998765",
        name="Hausverwaltung Meier GmbH",
        name_source="dasoertliche",
        duration=95,
        timestamp=(NOW - timedelta(days=2)).isoformat(),
    ),
]


class _Loader(yaml.SafeLoader):
    """Home Assistant's `!input` is not standard YAML."""


_Loader.add_constructor("!input", lambda loader, node: None)


def _as_timestamp(value: str) -> float:
    """Home Assistant's `as_timestamp`."""
    return datetime.fromisoformat(value).timestamp()


def _timestamp_custom(value: float, fmt: str = "%Y-%m-%dT%H:%M:%S", local: bool = True) -> str:
    """Home Assistant's `timestamp_custom`."""
    return datetime.fromtimestamp(value, TZ if local else UTC).strftime(fmt)


async def main() -> int:
    """Render the blueprint's payload and save it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--empty", action="store_true", help="render the no-calls state")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    blueprint = yaml.load(BLUEPRINT.read_text(), Loader=_Loader)
    payload = blueprint["actions"][0]["data"]["payload"]

    environment = Environment(autoescape=False)  # noqa: S701 - rendering JSON, not HTML
    environment.filters["timestamp_custom"] = _timestamp_custom
    environment.globals |= {
        "as_timestamp": _as_timestamp,
        "now": lambda: NOW,
        "timedelta": timedelta,
    }

    calls = [] if args.empty else SAMPLE
    rendered = environment.from_string(payload).render(
        calls=calls,
        missed=sum(1 for call in calls if call["type"] == "missed"),
    )

    try:
        elements = json.loads(rendered)
    except json.JSONDecodeError as err:
        print(f"payload is not valid JSON: {err}", file=sys.stderr)  # noqa: T201
        for number, line in enumerate(rendered.splitlines(), 1):
            print(f"{number:3} {line}", file=sys.stderr)  # noqa: T201
        return 1

    image = await generate_image(
        width=400,
        height=300,
        elements=elements,
        background="white",
        accent_color="red",
    )

    default = "call-list-400x300-empty.png" if args.empty else "call-list-400x300.png"
    out = args.out or REPO / "docs/images" / default
    image.save(out)
    print(f"{len(elements)} elements -> {out}")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
