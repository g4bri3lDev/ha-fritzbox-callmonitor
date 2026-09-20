"""Tests for the optional reverse lookup."""

from __future__ import annotations

from pathlib import Path
import time

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.fritzbox_callmonitor.const import LookupProvider
from custom_components.fritzbox_callmonitor.lookup import NumberLookup
from custom_components.fritzbox_callmonitor.lookup.cache import (
    HIT_TTL,
    MISS_TTL,
    CacheEntry,
    LookupCache,
)
from custom_components.fritzbox_callmonitor.lookup.dasoertliche import (
    URL as DASOERTLICHE_URL,
)
from custom_components.fritzbox_callmonitor.lookup.models import LookupResult
from custom_components.fritzbox_callmonitor.lookup.tellows import URL as TELLOWS_URL
from custom_components.fritzbox_callmonitor.models import NameSource

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    """Return the contents of an HTML fixture."""
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def no_request_spacing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove the inter-request delay so tests do not wait for it."""
    monkeypatch.setattr(
        "custom_components.fritzbox_callmonitor.lookup.REQUEST_SPACING", 0
    )


# --- disabled by default ----------------------------------------------------


async def test_disabled_lookup_never_touches_the_network(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The default provider is `none`, and it must be genuinely inert."""
    lookup = NumberLookup(hass)

    assert lookup.enabled is False
    assert lookup.provider_domain is None
    assert await lookup.async_lookup("+4930111222") is None
    assert aioclient_mock.call_count == 0


async def test_tellows_without_a_key_stays_disabled(hass: HomeAssistant) -> None:
    """Selecting tellows but omitting the key must not half-enable it."""
    lookup = NumberLookup(hass, provider=LookupProvider.TELLOWS, tellows_api_key="")

    assert lookup.enabled is False


# --- Das Oertliche ----------------------------------------------------------


async def test_dasoertliche_returns_the_matching_listing(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A single listing whose number matches is used."""
    aioclient_mock.get(DASOERTLICHE_URL, text=fixture("dasoertliche_single_hit.html"))
    lookup = NumberLookup(hass, provider=LookupProvider.DASOERTLICHE)

    result = await lookup.async_lookup("089 1234567")

    assert result is not None
    assert result.name == "Max & Moritz GmbH"
    assert result.source is NameSource.DASOERTLICHE


async def test_dasoertliche_refuses_an_ambiguous_page(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Several businesses on one hotline number: no single name is the caller.

    Reported from a real response, where the search returned nine unrelated
    shops sharing a service number. Showing the first would be wrong.
    """
    aioclient_mock.get(DASOERTLICHE_URL, text=fixture("dasoertliche_hits.html"))
    lookup = NumberLookup(hass, provider=LookupProvider.DASOERTLICHE)

    assert await lookup.async_lookup("022843331120") is None


async def test_dasoertliche_treats_410_as_no_listing(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The site answers "not found" with 410, which is an answer, not an error."""
    aioclient_mock.get(DASOERTLICHE_URL, status=410, text="")
    lookup = NumberLookup(hass, provider=LookupProvider.DASOERTLICHE)

    assert await lookup.async_lookup("+4930111222") is None


async def test_dasoertliche_survives_unexpected_markup(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A scraper's whole job is to fail soft when the page changes."""
    aioclient_mock.get(DASOERTLICHE_URL, text="<html><body>redesigned</body></html>")
    lookup = NumberLookup(hass, provider=LookupProvider.DASOERTLICHE)

    assert await lookup.async_lookup("+4930111222") is None


async def test_dasoertliche_survives_a_server_error(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An outage degrades the name to unknown, it does not raise."""
    aioclient_mock.get(DASOERTLICHE_URL, status=500, text="")
    lookup = NumberLookup(hass, provider=LookupProvider.DASOERTLICHE)

    assert await lookup.async_lookup("+4930111222") is None


# --- tellows ----------------------------------------------------------------


async def test_tellows_returns_name_and_score(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A tellows payload yields both the caller name and the spam score."""
    aioclient_mock.get(
        TELLOWS_URL.format(number="030111222"),
        json={
            "tellows": {
                "score": "8",
                "callername": "Werbe GmbH",
                "callerTypes": "Telemarketer",
            }
        },
    )
    lookup = NumberLookup(
        hass, provider=LookupProvider.TELLOWS, tellows_api_key="secret"
    )

    result = await lookup.async_lookup("+49 30 111222")

    assert result is not None
    assert result.name == "Werbe GmbH"
    assert result.score == 8
    assert result.kind == "Telemarketer"


async def test_tellows_score_without_a_name_is_still_useful(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """A spam score alone is worth keeping; it is what badges a caller."""
    aioclient_mock.get(
        TELLOWS_URL.format(number="030111222"), json={"tellows": {"score": "9"}}
    )
    lookup = NumberLookup(
        hass, provider=LookupProvider.TELLOWS, tellows_api_key="secret"
    )

    result = await lookup.async_lookup("+4930111222")

    assert result is not None
    assert result.name is None
    assert result.score == 9


async def test_tellows_ignores_an_out_of_range_score(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The documented scale is 1-9; anything else is not a score."""
    aioclient_mock.get(
        TELLOWS_URL.format(number="030111222"), json={"tellows": {"score": "42"}}
    )
    lookup = NumberLookup(
        hass, provider=LookupProvider.TELLOWS, tellows_api_key="secret"
    )

    assert await lookup.async_lookup("+4930111222") is None


async def test_tellows_survives_a_non_json_body(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """An HTML error page where JSON was promised must not raise."""
    aioclient_mock.get(TELLOWS_URL.format(number="030111222"), text="<html></html>")
    lookup = NumberLookup(
        hass, provider=LookupProvider.TELLOWS, tellows_api_key="secret"
    )

    assert await lookup.async_lookup("+4930111222") is None


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("+4930111222", "030111222"),
        ("004930111222", "030111222"),
        ("030111222", "030111222"),
        ("030 111-222", "030111222"),
        ("+33123456", "0033123456"),
        ("", ""),
    ],
)
def test_numbers_are_normalized_to_national_dialing(given: str, expected: str) -> None:
    """Both directories are German sites that only accept the dialed form."""
    from custom_components.fritzbox_callmonitor.models import national_number

    assert national_number(given) == expected


async def test_one_number_spelled_two_ways_is_one_cache_entry(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The call list and a service call may spell the same number differently."""
    aioclient_mock.get(DASOERTLICHE_URL, text=fixture("dasoertliche_single_hit.html"))
    lookup = NumberLookup(hass, provider=LookupProvider.DASOERTLICHE)

    await lookup.async_lookup("0891234567")
    await lookup.async_lookup("+49891234567")

    assert aioclient_mock.call_count == 1


async def test_the_shipped_code_carries_no_tellows_credentials() -> None:
    """The vendor's test key is not for permanent use, so it is not shipped."""
    source = (
        Path(__file__).parents[1]
        / "custom_components/fritzbox_callmonitor/lookup/tellows.py"
    ).read_text()

    assert "test123" not in source


# --- caching ----------------------------------------------------------------


async def test_a_hit_is_served_from_cache(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The call list is re-read every few minutes; lookups must not be."""
    aioclient_mock.get(DASOERTLICHE_URL, text=fixture("dasoertliche_single_hit.html"))
    lookup = NumberLookup(hass, provider=LookupProvider.DASOERTLICHE)

    assert await lookup.async_lookup("0891234567") is not None
    assert await lookup.async_lookup("089 123 4567") is not None

    assert aioclient_mock.call_count == 1


async def test_a_miss_is_cached_too(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Without a negative cache an unlisted number is asked about forever."""
    aioclient_mock.get(DASOERTLICHE_URL, status=410, text="")
    lookup = NumberLookup(hass, provider=LookupProvider.DASOERTLICHE)

    assert await lookup.async_lookup("+4930111222") is None
    assert await lookup.async_lookup("+4930111222") is None

    assert aioclient_mock.call_count == 1


async def test_force_refresh_bypasses_the_cache(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """The action offers a way to ask again after a number gets listed."""
    aioclient_mock.get(DASOERTLICHE_URL, text=fixture("dasoertliche_single_hit.html"))
    lookup = NumberLookup(hass, provider=LookupProvider.DASOERTLICHE)

    await lookup.async_lookup("0891234567")
    await lookup.async_lookup("0891234567", force_refresh=True)

    assert aioclient_mock.call_count == 2


def test_cache_entries_expire_on_their_own_schedule() -> None:
    """Misses expire sooner, so a newly listed number is picked up again."""
    now = time.time()
    hit = CacheEntry(timestamp=now, result=LookupResult(NameSource.DASOERTLICHE, "X"))
    miss = CacheEntry(timestamp=now, result=None)

    assert hit.is_fresh(now + HIT_TTL - 1)
    assert not hit.is_fresh(now + HIT_TTL + 1)
    assert miss.is_fresh(now + MISS_TTL - 1)
    assert not miss.is_fresh(now + MISS_TTL + 1)


def test_a_malformed_stored_entry_is_dropped() -> None:
    """A cache file from a future version must not break startup."""
    assert CacheEntry.from_dict({}) is None
    assert CacheEntry.from_dict({"timestamp": "soon"}) is None
    assert CacheEntry.from_dict({"timestamp": 1.0, "result": "nope"}) is None


async def test_the_cache_is_trimmed(hass: HomeAssistant) -> None:
    """An unbounded cache would grow with every spam wave."""
    from custom_components.fritzbox_callmonitor.lookup import cache as cache_module

    cache = LookupCache(hass)
    await cache.async_load()

    for index in range(cache_module.MAX_ENTRIES + 10):
        cache.set(str(index), None)

    assert len(cache._entries) == cache_module.MAX_ENTRIES
    # The oldest writes are the ones dropped.
    assert cache.get("0") is None
    assert cache.get(str(cache_module.MAX_ENTRIES + 9)) is not None
