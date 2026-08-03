"""Plain dataclasses shared by scoring, statistics, parsing and API clients.

Nothing in app/domain imports SQLAlchemy. Business logic that depends on a
transport or an ORM cannot be tested without one, and cannot be moved when the
system of record changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class FundingStage(str, Enum):
    PRE_SEED = "pre_seed"
    SEED = "seed"
    SERIES_A = "series_a"
    SERIES_B = "series_b"
    SERIES_C = "series_c"
    SERIES_D_PLUS = "series_d_plus"
    PUBLIC = "public"
    ACQUIRED = "acquired"
    BOOTSTRAPPED = "bootstrapped"
    OTHER = "other"


class OfficeSignal(str, Enum):
    CONFIRMED_IN_OFFICE = "confirmed_in_office"
    LIKELY_IN_OFFICE = "likely_in_office"
    LIKELY_REMOTE = "likely_remote"
    UNKNOWN = "unknown"


class IcpStatus(str, Enum):
    #: Not yet evaluated, or evaluated and waiting on paid enrichment.
    PENDING = "pending"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"


class SignalType(str, Enum):
    NEW_OFFICE = "new_office"
    VENDOR_COMPLAINT = "vendor_complaint"
    RETURN_TO_OFFICE = "return_to_office"
    FUNDING_ANNOUNCEMENT = "funding_announcement"
    HIRING_ONSITE = "hiring_onsite"
    CITY_EXPANSION = "city_expansion"
    TEAM_GROWTH = "team_growth"


@dataclass(frozen=True)
class Company:
    name: str
    apollo_org_id: str | None = None
    domain: str | None = None
    founded_year: int | None = None
    #: None means not enriched. It does not mean "no funding".
    latest_funding_stage: FundingStage | None = None
    office_signal: OfficeSignal = OfficeSignal.UNKNOWN
    office_signal_evidence: list[dict] = field(default_factory=list)
    organization_location: str | None = None


@dataclass(frozen=True)
class Contact:
    apollo_person_id: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    linkedin_url: str | None = None
    person_location: str | None = None
    #: Absent until revealed at enrollment; search never returns it.
    email: str | None = None
    is_founder_flagged: bool = False
    company: Company | None = None
    last_emailed_at: datetime | None = None
    do_not_contact: bool = False


@dataclass(frozen=True)
class Signal:
    signal_type: SignalType
    observed_at: datetime
    provider: str
    url: str | None = None
    excerpt: str | None = None


@dataclass(frozen=True)
class IcpVerdict:
    """Result of evaluating a contact against config/icp.yaml.

    `status` is PENDING when the only thing standing between the lead and a
    verdict is a credit-costing enrichment call. That is the normal state for a
    freshly sourced lead, not an error.
    """

    status: IcpStatus
    score: float
    reasons: list[str] = field(default_factory=list)
    #: Set when status is PENDING: what would have to be fetched to decide.
    awaiting: list[str] = field(default_factory=list)

    @property
    def enrollable_after_enrichment(self) -> bool:
        return self.status is not IcpStatus.DISQUALIFIED
