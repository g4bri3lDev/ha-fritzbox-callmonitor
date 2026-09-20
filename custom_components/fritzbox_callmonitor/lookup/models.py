"""Result type shared by all reverse lookup providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import NameSource


@dataclass(frozen=True, slots=True)
class LookupResult:
    """What a provider managed to find out about a number."""

    source: NameSource
    name: str | None = None
    kind: str | None = None
    score: int | None = None

    @property
    def is_empty(self) -> bool:
        """Return True when the provider found nothing worth caching as a hit."""
        return self.name is None and self.score is None

    def as_dict(self) -> dict[str, Any]:
        """Return the service-response representation."""
        return {
            "name": self.name,
            "kind": self.kind,
            "score": self.score,
            "source": str(self.source),
        }
