"""Provider protocol for reverse number lookup."""

from __future__ import annotations

from typing import Protocol

from .models import LookupResult


class LookupProviderProtocol(Protocol):
    """A reverse lookup backend.

    Implementations must **fail soft**: any network, parsing or format problem
    returns None rather than raising, so that a provider going bad degrades a
    caller name to "unknown" instead of failing the coordinator refresh.
    """

    domain: str

    async def async_lookup(self, number: str) -> LookupResult | None:
        """Look up a number, or return None when nothing was found."""
