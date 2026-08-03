"""The CrmStore protocol.

Business logic depends on this, never on HubSpot. Roughly 28% of a previous
build turned out to be portable to a different system of record purely because
the enrollment and scoring layers never imported a transport.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, Sequence

from app.domain.models import Company, Contact


@dataclass(frozen=True)
class UpsertResult:
    """Outcome of a batch write.

    `errors` is populated rather than raised: HubSpot batch endpoints report
    per-record failures, and one bad record must not discard the other 99.
    """

    requested: int
    succeeded: int
    #: our identifier -> HubSpot object id
    ids: dict[str, str] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def failed(self) -> int:
        return self.requested - self.succeeded

    @property
    def complete(self) -> bool:
        return self.failed == 0


@dataclass(frozen=True)
class CrmChange:
    """A rep-side edit, as reported by a webhook."""

    event_id: str
    subscription_type: str
    object_id: str
    occurred_at: datetime
    property_name: str | None = None
    property_value: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


class CrmStore(Protocol):
    def ensure_properties(self) -> dict[str, list[str]]:
        """Create any missing custom properties. Returns what was created."""
        ...

    def upsert_contacts(
        self, contacts: Sequence[tuple[Contact, dict[str, Any]]]
    ) -> UpsertResult: ...

    def upsert_companies(self, companies: Sequence[Company]) -> UpsertResult: ...

    def associate_contact_to_company(
        self, contact_id: str, company_id: str
    ) -> bool: ...

    def mark_opted_out(self, emails: Sequence[str]) -> UpsertResult:
        """Mirror our suppressions so reps can see them.

        Postgres stays authoritative -- suppression is enforced in our code,
        globally, before enrollment. This is a display concern.
        """
        ...
