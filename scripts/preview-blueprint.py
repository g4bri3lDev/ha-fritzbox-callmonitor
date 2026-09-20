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
import ast
import asyncio
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
import sys

from jinja2 import Environment
from odl_renderer import generate_image
from PIL import Image
import yaml

# The 4.1" tag is a BWRY panel: four inks, no grey. Anything else in the
# payload has to be dithered to these, which is what makes a 1px "ltgray"
# hairline disappear on the hardware while looking perfect in the PNG.
#
# These are the *measured* ink colours for the panel, from py-opendisplay's
# DISPLAY_PALETTE_MAP (panel 0x0037, ColorScheme.BWRY) -- not idealised sRGB.
# The difference matters: e-paper white is a light grey and the red is a dark
# maroon, so red on black manages only 1.45:1 while yellow manages 5.57:1.
# Simulating with pure (255, 0, 0) hides that.
# Quantising has to happen against the *idealised* colours, because that is
# how a hue finds the right ink: pure red is Euclidean-nearer the yellow ink
# than the red one, so measuring distances against measured values turns every
# red row yellow. Map to the ink afterwards instead.
IDEAL = [(255, 255, 255), (0, 0, 0), (255, 0, 0), (255, 255, 0)]

# The measured ink colours for this panel, from py-opendisplay's
# DISPLAY_PALETTE_MAP (panel 0x0037, ColorScheme.BWRY). E-paper white is a
# light grey and the red is a dark maroon, which is the whole point of
# previewing with them: red reaches only 1.45:1 against black, yellow 5.57:1.
MEASURED = {
    (255, 255, 255): (173, 178, 174),
    (0, 0, 0): (10, 7, 14),
    (255, 0, 0): (85, 24, 14),
    (255, 255, 0): (172, 128, 0),
}
PAPER_WHITE = MEASURED[(255, 255, 255)]

REPO = Path(__file__).resolve().parents[1]
BLUEPRINT = REPO / "blueprints/automation/fritzbox_callmonitor/call_list_400x300.yaml"

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


def _timestamp_custom(
    value: float, fmt: str = "%Y-%m-%dT%H:%M:%S", local: bool = True
) -> str:
    """Home Assistant's `timestamp_custom`."""
    return datetime.fromtimestamp(value, TZ if local else UTC).strftime(fmt)


def _to_panel(image: Image.Image) -> Image.Image:
    """Approximate what the panel can actually show.

    `drawcustom` dithers with error diffusion before sending, so a colour that
    is not one of the four inks becomes a pattern of dots. This is not the
    exact quantiser the firmware uses, but it is close enough to reveal the
    failure it is here to catch: fine detail in a dithered colour.
    """
    palette = Image.new("P", (1, 1))
    flat = [c for rgb in IDEAL for c in rgb] + [0, 0, 0] * (256 - len(IDEAL))
    palette.putpalette(flat)
    quantised = (
        image.convert("RGB")
        .quantize(palette=palette, dither=Image.Dither.FLOYDSTEINBERG)
        .convert("RGB")
    )
    # Now swap each idealised colour for the ink that actually prints it.
    inked = quantised.copy()
    inked.putdata([MEASURED.get(px, px) for px in quantised.getdata()])
    return inked


def _report_hairlines(image: Image.Image, panel: Image.Image) -> None:
    """Warn about rows that are a solid line before dithering but not after."""
    # Both sides must be RGB, or the comparison against white is meaningless
    # and every pixel counts as drawn.
    image = image.convert("RGB")
    panel = panel.convert("RGB")
    width, height = image.size
    for y in range(height):
        drawn = [x for x in range(width) if image.getpixel((x, y)) != (255, 255, 255)]
        if len(drawn) < width // 3:
            continue
        survived = sum(1 for x in drawn if panel.getpixel((x, y)) != PAPER_WHITE)
        ratio = survived / len(drawn)
        if ratio < 0.9:
            print(  # noqa: T201
                f"  warning: the line at y={y} loses {100 - int(ratio * 100)}% of"
                " its pixels on a BWRY panel -- use a solid ink, not a grey",
                file=sys.stderr,
            )


async def main() -> int:
    """Render the blueprint's payload and save it."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--empty", action="store_true", help="render the no-calls state"
    )
    parser.add_argument(
        "--panel",
        action="store_true",
        help="also save a BWRY-dithered simulation of what the tag shows",
    )
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    blueprint = yaml.load(BLUEPRINT.read_text(), Loader=_Loader)
    payload = blueprint["actions"][0]["data"]["payload"]

    environment = Environment(autoescape=False)
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

    # Parse it exactly as Home Assistant does. A templated service field is
    # rendered to a string and then passed through ast.literal_eval; if that
    # fails it stays a string, and `opendisplay.drawcustom` rejects it with
    # "expected list at 'payload'". literal_eval is *Python* syntax, so the
    # payload must say True/False/None, never JSON's true/false/null -- which
    # is why this does not simply use json.loads: JSON would accept a payload
    # that Home Assistant then refuses.
    try:
        elements = ast.literal_eval(rendered)
    except (ValueError, SyntaxError, MemoryError) as err:
        print(f"Home Assistant could not parse this payload: {err}", file=sys.stderr)  # noqa: T201
        print(
            "hint: use Python literals (True/False/None), not true/false/null",
            file=sys.stderr,
        )
        for number, line in enumerate(rendered.splitlines(), 1):
            print(f"{number:3} {line}", file=sys.stderr)  # noqa: T201
        return 1

    if not isinstance(elements, list):
        print(  # noqa: T201
            f"payload parsed as {type(elements).__name__}, but drawcustom requires a list",
            file=sys.stderr,
        )
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

    # Always check, even without --panel: the whole point is that the RGB
    # render looks fine while the hardware does not.
    panel = _to_panel(image)
    _report_hairlines(image, panel)
    if args.panel:
        panel_out = out.with_name(out.stem + "-panel" + out.suffix)
        panel.save(panel_out)
        print(f"panel simulation -> {panel_out}")  # noqa: T201

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
