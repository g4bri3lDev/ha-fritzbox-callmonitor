"""Tests for diagnostics."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator


async def test_diagnostics_redact_the_credentials(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_integration: MockConfigEntry,
) -> None:
    """A diagnostics download must not carry the box password."""
    result = await get_diagnostics_for_config_entry(
        hass, hass_client, setup_integration
    )

    assert result["entry"]["data"]["password"] == "**REDACTED**"
    assert result["entry"]["data"]["username"] == "**REDACTED**"


async def test_diagnostics_redact_who_called(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_integration: MockConfigEntry,
) -> None:
    """Call records are the most personal data here: report shape, not content."""
    result = await get_diagnostics_for_config_entry(
        hass, hass_client, setup_integration
    )

    call = result["history"]["calls"][0]

    assert call["number"] == "**REDACTED**"
    assert call["own_number"] == "**REDACTED**"
    # The shape still has to be visible for a bug report to be useful.
    assert call["type"] == "missed"
    assert call["duration"] == 0


async def test_diagnostics_report_the_lookup_setting(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    setup_integration: MockConfigEntry,
) -> None:
    """Whether lookup is on is the first thing to check in a report."""
    result = await get_diagnostics_for_config_entry(
        hass, hass_client, setup_integration
    )

    assert result["lookup"] == {"enabled": False, "provider": None}
