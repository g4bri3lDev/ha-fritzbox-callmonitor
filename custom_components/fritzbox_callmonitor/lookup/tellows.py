"""Reverse lookup and spam scoring against the tellows API.

Unlike the directory scrapers this is a documented API, but it needs a key that
the user buys from tellows. Their published test credentials are deliberately
not shipped here: the vendor states they are not intended for permanent use.
"""

from __future__ import annotations

import asyncio
import logging

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..models import NameSource, national_number
from .models import LookupResult

_LOGGER = logging.getLogger(__name__)

URL = "https://www.tellows.de/basic/num/{number}"
TIMEOUT = aiohttp.ClientTimeout(total=15)
PARTNER = "tellowskey"


class TellowsProvider:
    """Query tellows for a caller name and spam score."""

    domain = "tellows"

    def __init__(self, hass: HomeAssistant, api_key: str) -> None:
        """Initialize the provider."""
        self._hass = hass
        self._api_key = api_key
        self._warned = False

    async def async_lookup(self, number: str) -> LookupResult | None:
        """Return what tellows knows about a number, or None."""
        query = national_number(number)
        if not query or not self._api_key:
            return None

        try:
            payload = await self._async_fetch(query)
        except (TimeoutError, aiohttp.ClientError, asyncio.CancelledError) as err:
            self._warn_once("tellows request failed: %s", err)
            return None

        if payload is None:
            return None

        result = _parse(payload)
        if result is None or result.is_empty:
            return None
        return result

    async def _async_fetch(self, query: str) -> dict | None:
        """Fetch the JSON payload for a number."""
        session = async_get_clientsession(self._hass)
        response = await session.get(
            URL.format(number=query),
            params={"json": "1", "partner": PARTNER, "apikey": self._api_key},
            timeout=TIMEOUT,
        )
        if response.status == 404:
            return None
        if response.status != 200:
            self._warn_once("tellows returned HTTP %s", response.status)
            return None
        try:
            # tellows answers with text/html despite the JSON body.
            return await response.json(content_type=None)
        except (aiohttp.ClientError, ValueError) as err:
            self._warn_once("tellows response was not JSON: %s", err)
            return None

    def _warn_once(self, message: str, *args: object) -> None:
        """Warn the first time only, then fall back to debug."""
        if self._warned:
            _LOGGER.debug(message, *args)
            return
        self._warned = True
        _LOGGER.warning(message, *args)


def _parse(payload: dict) -> LookupResult | None:
    """Turn a tellows payload into a LookupResult."""
    if not isinstance(payload, dict):
        return None

    data = payload.get("tellows")
    if not isinstance(data, dict):
        return None

    name = _first_caller_name(data)
    return LookupResult(
        source=NameSource.TELLOWS,
        name=name,
        kind=_text(data.get("callerTypes")) or _text(data.get("callertype")),
        score=_score(data.get("score")),
    )


def _first_caller_name(data: dict) -> str | None:
    """Return the caller name, which tellows nests differently per number."""
    for key in ("callername", "name"):
        if name := _text(data.get(key)):
            return name

    names = data.get("callerNames")
    if isinstance(names, dict):
        names = names.get("caller")
    if isinstance(names, str):
        return _text(names)
    if isinstance(names, list):
        for entry in names:
            if isinstance(entry, str) and (name := _text(entry)):
                return name
            if isinstance(entry, dict) and (name := _text(entry.get("name"))):
                return name
    return None


def _text(value: object) -> str | None:
    """Return a non-empty stripped string, or None."""
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _score(value: object) -> int | None:
    """Return the tellows score (1-9), or None when absent."""
    try:
        score = int(value)  # type: ignore[arg-type]
    except TypeError, ValueError:
        return None
    return score if 1 <= score <= 9 else None
