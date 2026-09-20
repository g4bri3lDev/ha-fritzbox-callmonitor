"""Persistent cache for reverse lookup results.

Two things make the cache load-bearing rather than an optimization. It keeps
the number of third-party requests near zero -- the call list is re-read every
five minutes and would otherwise be re-looked-up every time -- and it caches
*misses* as well as hits, so an unlisted number is not asked about forever.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from ..models import NameSource
from .models import LookupResult

STORAGE_VERSION = 1
STORAGE_KEY = "fritzbox_callmonitor.lookup_cache"
SAVE_DELAY = 30

HIT_TTL = 90 * 24 * 3600
# Shorter, so a number that gets listed later is picked up within the week.
MISS_TTL = 7 * 24 * 3600
MAX_ENTRIES = 500


@dataclass(frozen=True, slots=True)
class CacheEntry:
    """A cached lookup outcome."""

    timestamp: float
    result: LookupResult | None

    @property
    def is_miss(self) -> bool:
        """Return True when this records that nothing was found."""
        return self.result is None

    def is_fresh(self, now: float) -> bool:
        """Return True when this entry may still be used."""
        ttl = MISS_TTL if self.is_miss else HIT_TTL
        return now - self.timestamp < ttl

    def as_dict(self) -> dict[str, Any]:
        """Return the stored representation."""
        return {
            "timestamp": self.timestamp,
            "result": self.result.as_dict() if self.result else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CacheEntry | None:
        """Rebuild an entry from storage, or None when it is unusable."""
        try:
            timestamp = float(data["timestamp"])
        except KeyError, TypeError, ValueError:
            return None

        raw = data.get("result")
        if raw is None:
            return cls(timestamp=timestamp, result=None)
        if not isinstance(raw, dict):
            return None

        try:
            source = NameSource(raw.get("source", NameSource.UNKNOWN))
        except ValueError:
            source = NameSource.UNKNOWN

        return cls(
            timestamp=timestamp,
            result=LookupResult(
                source=source,
                name=raw.get("name"),
                kind=raw.get("kind"),
                score=raw.get("score"),
            ),
        )


class LookupCache:
    """Store-backed cache of lookup results, keyed by normalized number."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the cache."""
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._entries: dict[str, CacheEntry] = {}
        self._loaded = False

    async def async_load(self) -> None:
        """Load the cache from disk, dropping stale and malformed entries."""
        if self._loaded:
            return
        self._loaded = True

        data = await self._store.async_load()
        if not data:
            return

        now = time.time()
        for number, raw in (data.get("entries") or {}).items():
            if not isinstance(raw, dict):
                continue
            entry = CacheEntry.from_dict(raw)
            if entry is not None and entry.is_fresh(now):
                self._entries[number] = entry

    def get(self, number: str) -> CacheEntry | None:
        """Return a fresh entry for a number, or None."""
        entry = self._entries.get(number)
        if entry is None:
            return None
        if not entry.is_fresh(time.time()):
            del self._entries[number]
            return None
        return entry

    def set(self, number: str, result: LookupResult | None) -> None:
        """Record an outcome and schedule a debounced save."""
        # Re-inserting moves the key to the end, which is what makes the
        # trim below least-recently-written rather than arbitrary.
        self._entries.pop(number, None)
        self._entries[number] = CacheEntry(timestamp=time.time(), result=result)

        while len(self._entries) > MAX_ENTRIES:
            self._entries.pop(next(iter(self._entries)))

        self._store.async_delay_save(self._data, SAVE_DELAY)

    def _data(self) -> dict[str, Any]:
        """Return the payload to persist."""
        return {
            "entries": {
                number: entry.as_dict() for number, entry in self._entries.items()
            }
        }
