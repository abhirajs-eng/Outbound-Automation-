"""ICP configuration loader and evaluator. Pure: no ORM, no network.

The evaluator's contract, which the rest of the system depends on:

    DISQUALIFIED  a hard filter said no, or enrichment came back out of range
    PENDING       nothing said no, but a paid lookup is still outstanding
    QUALIFIED     every criterion that can be checked has been, and passed

Unknown funding stage yields PENDING. It must never yield DISQUALIFIED: stage
costs a credit per company and is resolved at enrollment, so hard-failing on it
makes every freshly sourced lead un-enrollable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from app.domain.models import (
    Contact,
    FundingStage,
    IcpStatus,
    IcpVerdict,
    OfficeSignal,
    Signal,
)

DEFAULT_ICP_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "icp.yaml"

_PUNCT = re.compile(r"[^a-z0-9&]+")


def normalise_title(title: str | None) -> str:
    """Lowercase, collapse punctuation and whitespace.

    'Co‑Founder  &  CEO' and 'co founder & ceo' must compare equal, including
    when the hyphen is a unicode non-breaking one pasted from LinkedIn.
    """
    if not title:
        return ""
    lowered = title.lower().replace("‐", "-").replace("‑", "-")
    lowered = lowered.replace("–", "-").replace("—", "-")
    return _PUNCT.sub(" ", lowered).strip()


def _title_variants(title: str) -> set[str]:
    """Forms a configured title should also match.

    'co-founder' normalises to 'co founder'; both spellings appear in the wild
    and neither should be the only one that counts.
    """
    base = normalise_title(title)
    return {base, base.replace("co founder", "cofounder"),
            base.replace("cofounder", "co founder")}


def registrable_domain(value: str) -> str:
    """Lowercased host with no leading dot, no scheme, no port."""
    host = value.strip().lower()
    host = re.sub(r"^[a-z]+://", "", host)
    host = host.split("/", 1)[0].split("@")[-1].split(":", 1)[0]
    return host.lstrip(".")


def domain_matches(candidate: str, suppressed: str) -> bool:
    """True when `candidate` is `suppressed` or a subdomain of it.

    Blocking acme.com must block jane@careers.acme.com. A plain `endswith`
    would also block notacme.com, so the boundary dot is required.
    """
    candidate = registrable_domain(candidate)
    suppressed = registrable_domain(suppressed)
    if not candidate or not suppressed:
        return False
    return candidate == suppressed or candidate.endswith("." + suppressed)


@dataclass(frozen=True)
class IcpConfig:
    raw: dict[str, Any]

    @classmethod
    def load(cls, path: Path | None = None) -> "IcpConfig":
        data = yaml.safe_load((path or DEFAULT_ICP_PATH).read_text())
        if not isinstance(data, dict):
            raise ValueError("icp.yaml did not parse to a mapping")
        return cls(raw=data)

    # -- hard filters ----------------------------------------------------

    @property
    def exact_titles(self) -> set[str]:
        titles: set[str] = set()
        for title in self.raw["hard"]["titles"]["exact"]:
            titles |= _title_variants(title)
        return titles

    @property
    def partial_titles(self) -> set[str]:
        return {normalise_title(t) for t in self.raw["hard"]["titles"]["partial"]}

    @property
    def ceo_requires_founder_flag(self) -> bool:
        return bool(self.raw["hard"]["titles"]["ceo_requires_founder_flag"])

    @property
    def person_locations(self) -> list[str]:
        return list(self.raw["hard"]["person_locations"])

    @property
    def organization_locations(self) -> list[str]:
        return list(self.raw["hard"]["organization_locations"])

    # -- enrichment ------------------------------------------------------

    @property
    def accepted_stages(self) -> set[FundingStage]:
        return {FundingStage(s) for s in self.raw["enrichment"]["funding_stage"]["accept"]}

    @property
    def rejected_stages(self) -> set[FundingStage]:
        return {FundingStage(s) for s in self.raw["enrichment"]["funding_stage"]["reject"]}

    # -- scoring ---------------------------------------------------------

    @property
    def office_signal_weights(self) -> dict[OfficeSignal, float]:
        weights = self.raw["scored"]["office_signal"]["weights"]
        return {OfficeSignal(k): float(v) for k, v in weights.items()}

    @property
    def founded_year_min(self) -> int | None:
        return self.raw["scored"].get("company_founded_year_min")

    @property
    def signal_weights(self) -> dict[str, dict[str, float]]:
        return {
            name: {
                "weight": float(cfg["weight"]),
                "half_life_days": float(cfg["half_life_days"]),
            }
            for name, cfg in self.raw["signals"].items()
        }

    # -- exclusions ------------------------------------------------------

    @property
    def emailed_within_days(self) -> int:
        return int(self.raw["exclusions"]["emailed_within_days"])

    @property
    def free_mail_domains(self) -> set[str]:
        return {registrable_domain(d) for d in self.raw["exclusions"]["free_mail_domains"]}

    @property
    def competitor_domains(self) -> set[str]:
        return {
            registrable_domain(d)
            for d in (self.raw["exclusions"].get("competitor_domains") or [])
        }

    @property
    def apollo_search(self) -> dict[str, Any]:
        return dict(self.raw["apollo_search"])


# ------------------------------------------------------------------ scoring

def title_score(contact: Contact, config: IcpConfig) -> tuple[float, str]:
    """Score a title 0..100 and say why."""
    normalised = normalise_title(contact.title)
    if not normalised:
        return 0.0, "no title on record"

    if normalised in config.exact_titles:
        return 100.0, f"exact founder title: {contact.title!r}"

    # CEO counts only when the record is independently flagged founder,
    # otherwise every hired CEO in the database qualifies.
    if "ceo" in normalised.split():
        if contact.is_founder_flagged or not config.ceo_requires_founder_flag:
            return 90.0, "CEO with founder flag"
        return 0.0, "CEO but not flagged founder"

    for partial in config.partial_titles:
        if partial and partial in normalised:
            return 60.0, f"partial founder title: {contact.title!r}"

    return 0.0, f"title not in ICP: {contact.title!r}"


def decayed_signal_score(
    signals: list[Signal], config: IcpConfig, *, now: datetime | None = None
) -> tuple[float, list[str]]:
    """Exponential half-life decay, summed across signals.

    Recency dominates by design: at one half-life a signal is worth half its
    weight, and a new-office post scored 100 today is worth ~7 points at 45 days.
    """
    now = now or datetime.now(timezone.utc)
    weights = config.signal_weights
    total = 0.0
    reasons: list[str] = []

    for signal in signals:
        spec = weights.get(signal.signal_type.value)
        if not spec:
            continue
        observed = signal.observed_at
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        age_days = max((now - observed).total_seconds() / 86400.0, 0.0)
        decay = 0.5 ** (age_days / spec["half_life_days"])
        contribution = spec["weight"] * decay
        total += contribution
        reasons.append(
            f"{signal.signal_type.value}: {contribution:.1f} "
            f"({spec['weight']:.0f} decayed over {age_days:.1f}d)"
        )

    return total, reasons


def priority_score(
    contact: Contact,
    config: IcpConfig,
    signals: list[Signal] | None = None,
    *,
    now: datetime | None = None,
) -> float:
    """Blend title fit, office signal and decayed activity signals."""
    title, _ = title_score(contact, config)
    office_weights = config.office_signal_weights
    office = (
        office_weights.get(contact.company.office_signal, 0.0)
        if contact.company
        else office_weights.get(OfficeSignal.UNKNOWN, 0.0)
    )
    signal_total, _ = decayed_signal_score(signals or [], config, now=now)

    return round(0.4 * title + 0.3 * office + 0.3 * min(signal_total, 100.0), 3)


# --------------------------------------------------------------- evaluation

def evaluate(
    contact: Contact,
    config: IcpConfig,
    *,
    signals: list[Signal] | None = None,
    suppressed_emails: set[str] | None = None,
    suppressed_domains: set[str] | None = None,
    now: datetime | None = None,
) -> IcpVerdict:
    now = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    awaiting: list[str] = []

    def disqualify(reason: str) -> IcpVerdict:
        reasons.append(reason)
        return IcpVerdict(IcpStatus.DISQUALIFIED, 0.0, reasons, [])

    if contact.do_not_contact:
        return disqualify("do_not_contact is set")

    # -- hard filters
    fit, why = title_score(contact, config)
    reasons.append(why)
    if fit <= 0:
        return disqualify(why)

    if contact.person_location and not any(
        loc.lower() in contact.person_location.lower()
        for loc in config.person_locations
    ):
        return disqualify(f"person location out of ICP: {contact.person_location!r}")

    company = contact.company
    if company is None:
        # Apollo people search always carries an organization; a record without
        # one cannot be qualified or enriched.
        return disqualify("no company on record")

    if company.organization_location and not any(
        loc.lower() in company.organization_location.lower()
        for loc in config.organization_locations
    ):
        return disqualify(f"company HQ out of ICP: {company.organization_location!r}")

    # -- exclusions
    if company.domain:
        domain = registrable_domain(company.domain)
        if domain in config.free_mail_domains:
            return disqualify(f"free-mail domain: {domain}")
        for competitor in config.competitor_domains:
            if domain_matches(domain, competitor):
                return disqualify(f"competitor domain: {domain}")
        for suppressed in suppressed_domains or set():
            if domain_matches(domain, suppressed):
                return disqualify(f"suppressed domain: {domain}")

    if contact.email and contact.email.lower() in (suppressed_emails or set()):
        return disqualify(f"suppressed email: {contact.email}")

    if contact.last_emailed_at is not None:
        last = contact.last_emailed_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        window = timedelta(days=config.emailed_within_days)
        if now - last < window:
            days = (now - last).days
            return disqualify(
                f"emailed {days}d ago, inside the "
                f"{config.emailed_within_days}d global frequency cap"
            )

    # -- enrichment-dependent
    stage = company.latest_funding_stage
    if stage is None:
        awaiting.append("latest_funding_stage")
        reasons.append("funding stage not enriched (1 credit, resolved at enrollment)")
    elif stage in config.rejected_stages:
        return disqualify(f"funding stage out of ICP: {stage.value}")
    elif stage in config.accepted_stages:
        reasons.append(f"funding stage in ICP: {stage.value}")
    else:
        return disqualify(f"funding stage out of ICP: {stage.value}")

    if contact.email is None:
        awaiting.append("email")

    score = priority_score(contact, config, signals, now=now)
    status = IcpStatus.PENDING if awaiting else IcpStatus.QUALIFIED
    return IcpVerdict(status=status, score=score, reasons=reasons, awaiting=awaiting)
