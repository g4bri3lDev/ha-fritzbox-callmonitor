"""Optional reverse lookup of numbers the phonebook does not resolve.

Reverse lookup is opt-in and ships disabled. With the default provider
(`none`) `NumberLookup` is inert: it never touches the network, never loads or
writes the cache file, and the call history works exactly as it would without
this package -- names come from the FRITZ!Box phonebook only.

Once enabled, every unknown number is sent to a third party. That is why
lookups are cached (hits and misses alike), serialized with a delay between
them, and never attempted for a number the phonebook already resolved.
"""

from __future__ import annotations

import asyncio
import logging

from homeassistant.core import HomeAssistant

from ..const import LookupProvider
from ..models import NameSource, national_number
from .base import LookupProviderProtocol
from .cache import LookupCache
from .dasoertliche import DasOertlicheProvider
from .models import LookupResult
from .tellows import TellowsProvider

__all__ = ["LookupResult", "NumberLookup"]

_LOGGER = logging.getLogger(__name__)

# Spacing between outbound requests. The call list is small and refreshed in the
# background, so there is no reason to hit a free service in bursts.
REQUEST_SPACING = 1.0


class NumberLookup:
    """Resolve unknown numbers through an optional provider, with caching."""

    def __init__(
        self,
        hass: HomeAssistant,
        provider: LookupProvider = LookupProvider.NONE,
        tellows_api_key: str = "",
    ) -> None:
        """Initialize the lookup."""
        self._hass = hass
        self._provider = _build_provider(hass, provider, tellows_api_key)
        self._cache = LookupCache(hass)
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    @property
    def enabled(self) -> bool:
        """Return True when a provider is configured."""
        return self._provider is not None

    @property
    def provider_domain(self) -> str | None:
        """Return the active provider's domain, or None."""
        return self._provider.domain if self._provider else None

    async def async_lookup(
        self, number: str, *, force_refresh: bool = False
    ) -> LookupResult | None:
        """Look up a number, preferring the cache.

        Returns None both when lookup is disabled and when nothing was found,
        because callers treat the two the same way: show the number.
        """
        if self._provider is None:
            return None

        # Keyed on the national spelling so +4930123 and 030123 are one
        # cache entry rather than two lookups of the same listing.
        key = national_number(number)
        if not key:
            return None

        await self._cache.async_load()

        if not force_refresh and (entry := self._cache.get(key)) is not None:
            return entry.result

        async with self._lock:
            # A second caller may have resolved this number while we waited.
            if not force_refresh and (entry := self._cache.get(key)) is not None:
                return entry.result

            await self._async_space_requests()
            result = await self._provider.async_lookup(key)

        if result is not None and result.is_empty:
            result = None

        # A miss is cached too: that is what stops an unlisted number from
        # being looked up again on every refresh.
        self._cache.set(key, result)

        if result is None:
            _LOGGER.debug("No listing for %s via %s", key, self.provider_domain)

        return result

    async def _async_space_requests(self) -> None:
        """Wait, if needed, to keep requests spaced out."""
        loop = asyncio.get_running_loop()
        elapsed = loop.time() - self._last_request
        if elapsed < REQUEST_SPACING:
            await asyncio.sleep(REQUEST_SPACING - elapsed)
        self._last_request = loop.time()


def _build_provider(
    hass: HomeAssistant, provider: LookupProvider, tellows_api_key: str
) -> LookupProviderProtocol | None:
    """Return the configured provider, or None when lookup is disabled."""
    if provider == LookupProvider.DASOERTLICHE:
        return DasOertlicheProvider(hass)
    if provider == LookupProvider.TELLOWS:
        if not tellows_api_key:
            _LOGGER.warning(
                "Reverse lookup via tellows is selected but no API key is set;"
                " lookup stays disabled"
            )
            return None
        return TellowsProvider(hass, tellows_api_key)
    return None


def source_for(result: LookupResult | None) -> NameSource:
    """Return the name source a result should be attributed to."""
    return result.source if result and result.name else NameSource.UNKNOWN
