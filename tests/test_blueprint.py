"""Tests for the shipped display blueprint.

The blueprint's payload is a template that has to survive Home Assistant's own
rendering, which is stricter than it looks: a templated service field is
rendered to a string and then passed through `ast.literal_eval`. If that fails
the field stays a string, and `opendisplay.drawcustom` -- whose schema is
`vol.Required("payload"): list` -- rejects the call with "expected list at
'payload'". Validating the payload as JSON is not enough, because JSON accepts
`true`/`false`/`null` while `literal_eval` does not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
import pytest
import yaml

from custom_components.fritzbox_callmonitor.const import ATTR_CALLS
from custom_components.fritzbox_callmonitor.models import CallRecord

from .fritz import FakeCall

BLUEPRINT = (
    Path(__file__).parents[1]
    / "blueprints/automation/fritzbox_callmonitor/call_list_400x300.yaml"
)


class _Loader(yaml.SafeLoader):
    """Home Assistant's `!input` tag is not standard YAML."""


_Loader.add_constructor("!input", lambda loader, node: None)


@pytest.fixture
def blueprint() -> dict[str, Any]:
    """Return the parsed blueprint."""
    return yaml.load(BLUEPRINT.read_text(), Loader=_Loader)


@pytest.fixture
def payload(blueprint: dict[str, Any]) -> str:
    """Return the drawcustom payload template."""
    return blueprint["actions"][0]["data"]["payload"]


def _render(hass: HomeAssistant, payload: str, calls: list[dict]) -> Any:
    """Render the payload the way Home Assistant renders service data."""
    return Template(payload, hass).async_render(
        {"calls": calls, "missed": sum(1 for c in calls if c["type"] == "missed")}
    )


def test_the_blueprint_is_valid_yaml(blueprint: dict[str, Any]) -> None:
    """A broken block scalar silently swallows the template."""
    inputs = blueprint["blueprint"]["input"]

    assert blueprint["blueprint"]["domain"] == "automation"
    assert {"call_history", "displays"} <= set(inputs)


def test_every_optional_input_has_a_default(blueprint: dict[str, Any]) -> None:
    """Only the sensor and the displays may be required of the user.

    Anything else must work unconfigured, or importing the blueprint turns into
    a questionnaire.
    """
    inputs = blueprint["blueprint"]["input"]
    optional = set(inputs) - {"call_history", "displays"}

    missing = [name for name in optional if "default" not in inputs[name]]

    assert not missing, f"optional inputs without a default: {missing}"


def test_the_font_defaults_to_a_bundled_one(blueprint: dict[str, Any]) -> None:
    """A default of anything else would be broken on every fresh install.

    Only ppb.ttf and rbm.ttf ship with the renderer; the repository
    deliberately contains no font files of its own.
    """
    assert blueprint["blueprint"]["input"]["font"]["default"] in ("ppb.ttf", "rbm.ttf")


def test_the_repository_ships_no_font_files() -> None:
    """A font is the user's licence to hold, not ours to redistribute."""
    repo = Path(__file__).parents[1]
    fonts = [
        path
        for pattern in ("**/*.ttf", "**/*.otf", "**/*.woff", "**/*.woff2")
        for path in repo.glob(pattern)
        if ".venv" not in path.parts and ".git" not in path.parts
    ]

    assert not fonts, f"font files in the repository: {fonts}"


async def test_the_payload_renders_to_a_list(hass: HomeAssistant, payload: str) -> None:
    """Drawcustom's schema is `vol.Required("payload"): list`.

    Rendering to a *string* is the failure mode this guards: Home Assistant
    only turns it into a list if `ast.literal_eval` accepts it.
    """
    records = [
        CallRecord.from_call(FakeCall(type="2", caller="+4930111222")).as_dict(),
        CallRecord.from_call(
            FakeCall(type="3", called="+4930333444", caller_number="+4989000")
        ).as_dict(),
    ]

    result = _render(hass, payload, records)

    assert isinstance(result, list), (
        "payload rendered to a string; Home Assistant will reject it with "
        "\"expected list at 'payload'\". Use Python literals (True/False/None), "
        "not JSON's true/false/null."
    )
    assert all(isinstance(element, dict) for element in result)
    assert all("type" in element for element in result)


async def test_the_payload_uses_no_json_only_literals(payload: str) -> None:
    """`true`, `false` and `null` are what break `literal_eval`."""
    offenders = [
        literal for literal in ("true", "false", "null") if f": {literal}" in payload
    ]

    assert not offenders, f"JSON literals in payload: {offenders}"


async def test_the_payload_survives_an_empty_call_list(
    hass: HomeAssistant, payload: str
) -> None:
    """A box with no recent calls must still render the empty state."""
    result = _render(hass, payload, [])

    assert isinstance(result, list)
    assert result


async def test_the_payload_survives_a_withheld_caller(
    hass: HomeAssistant, payload: str
) -> None:
    """A withheld caller has no number at all, which a real box does send."""
    record = CallRecord.from_call(
        FakeCall(type="2", caller="", name="Unbekannt")
    ).as_dict()
    assert record["number"] == ""

    result = _render(hass, payload, [record])

    assert isinstance(result, list)
    assert not any(element.get("value") == "" for element in result), (
        "a blank text element is drawn for the missing number"
    )


async def test_the_payload_reads_the_attribute_this_integration_publishes(
    payload: str,
) -> None:
    """The blueprint and the sensor have to agree on the attribute name."""
    assert (
        f"'{ATTR_CALLS}'" in payload
        or f'"{ATTR_CALLS}"' in payload
        or ("calls[" in payload)
    )
