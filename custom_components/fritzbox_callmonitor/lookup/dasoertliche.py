"""Reverse lookup against Das Örtliche.

Das Örtliche publishes no API, so this scrapes the public reverse search
("Rückwärtssuche"). That makes it inherently fragile: the markup can change at
any time. Everything here is therefore written to fail soft -- on any error, or
on any result we are not confident about, it returns None and the caller shows
the number instead of a name.
"""

from __future__ import annotations

import asyncio
import html
import logging
import re

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from ..models import NameSource, national_number, normalize_number
from .models import LookupResult

_LOGGER = logging.getLogger(__name__)

URL = "https://www.dasoertliche.de/Controller"
TIMEOUT = aiohttp.ClientTimeout(total=15)
# The site serves a JavaScript notice rather than results to unknown clients.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# A hit is an <a class="hitlnk_name"> whose text is the name, followed within
# the same result block by a phoneblock holding the listed number.
_HIT_NAME = re.compile(
    r'class="hitlnk_name"\s*>(?P<name>.*?)</a>', re.DOTALL | re.IGNORECASE
)
_HIT_PHONE = re.compile(
    r'class="phoneblock"\s*>\s*<span>\s*Tel\.?\s*(?P<phone>[\d\s/+()-]+)</span>',
    re.DOTALL | re.IGNORECASE,
)
_TAGS = re.compile(r"<[^>]+>")
_WHITESPACE = re.compile(r"\s+")


class DasOertlicheProvider:
    """Scrape Das Örtliche's reverse search."""

    domain = "dasoertliche"

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the provider."""
        self._hass = hass
        self._warned = False

    async def async_lookup(self, number: str) -> LookupResult | None:
        """Return the listing for a number, or None."""
        query = national_number(number)
        if not query:
            return None

        try:
            text = await self._async_fetch(query)
        except (TimeoutError, aiohttp.ClientError, asyncio.CancelledError) as err:
            self._warn_once("Das Örtliche request failed: %s", err)
            return None

        if text is None:
            return None

        try:
            name = _extract_name(text, query)
        except Exception:
            self._warn_once("Das Örtliche response could not be parsed")
            return None

        if name is None:
            return None

        return LookupResult(source=NameSource.DASOERTLICHE, name=name)

    async def _async_fetch(self, query: str) -> str | None:
        """Fetch the reverse search page, or None when there is no listing."""
        session = async_get_clientsession(self._hass)
        response = await session.get(
            URL,
            params={"form_name": "search_inv", "ph": query},
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT,
        )
        # The site answers "no listing found" with 410, which is an answer and
        # not a failure -- it must be cached as a miss like any other.
        if response.status == 410:
            return None
        if response.status != 200:
            self._warn_once("Das Örtliche returned HTTP %s", response.status)
            return None
        return await response.text()

    def _warn_once(self, message: str, *args: object) -> None:
        """Warn the first time only, then fall back to debug.

        A provider that has started failing usually keeps failing on every
        refresh; one warning is informative, one per call is noise.
        """
        if self._warned:
            _LOGGER.debug(message, *args)
            return
        self._warned = True
        _LOGGER.warning(message, *args)


def _extract_name(text: str, query: str) -> str | None:
    """Return the name of the hit that actually matches the queried number.

    The search matches loosely and happily returns a page of unrelated
    businesses, so a hit is only accepted when its listed number lines up with
    what was asked for. A single unambiguous hit is accepted as-is; anything
    else without a number match is treated as no result, because showing the
    wrong caller is worse than showing none.
    """
    hits = _parse_hits(text)
    if not hits:
        return None

    matching = {name for name, phone in hits if phone and _numbers_match(phone, query)}
    if len(matching) == 1:
        return matching.pop()
    if matching:
        # Several businesses share the number (a hotline, a shop-in-shop
        # address). No single name is the caller, so report none.
        return None

    if len(hits) == 1 and not hits[0][1]:
        return hits[0][0]

    return None


def _parse_hits(text: str) -> list[tuple[str, str]]:
    """Return (name, listed number) for every result block on the page.

    Each block is delimited by the next name anchor, so a hit without a phone
    block cannot shift the numbers onto the wrong names.
    """
    matches = list(_HIT_NAME.finditer(text))
    hits: list[tuple[str, str]] = []

    for index, match in enumerate(matches):
        name = _clean(match.group("name"))
        if not name:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        phone_match = _HIT_PHONE.search(text, match.end(), end)
        phone = normalize_number(phone_match.group("phone")) if phone_match else ""
        hits.append((name, phone))

    return hits


def _numbers_match(listed: str, query: str) -> bool:
    """Return True when a listed number plausibly is the queried one.

    Listings carry the main number while a call can come from a direct dial-in
    extension, so the listed number being a prefix of the query counts as a
    match. Both are compared on their national part to sidestep +49 / 0049 / 0.
    """
    listed_tail = _national(listed)
    query_tail = _national(query)
    if not listed_tail or not query_tail:
        return False
    return query_tail.startswith(listed_tail) or listed_tail.startswith(query_tail)


def _national(number: str) -> str:
    """Strip country code and trunk prefix so two spellings can be compared."""
    for prefix in ("+49", "0049", "49"):
        if number.startswith(prefix) and len(number) > len(prefix) + 3:
            number = number[len(prefix) :]
            break
    return number.lstrip("0")


def _clean(value: str) -> str:
    """Turn a chunk of markup into plain collapsed text."""
    return _WHITESPACE.sub(" ", html.unescape(_TAGS.sub("", value))).strip()
