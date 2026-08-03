"""Section 6 capacity arithmetic.

    send capacity              = domains x mailboxes x sends_per_mailbox_day
    a 4-step sequence consumes 4 emails per lead
    sustainable enrollments/day = capacity / steps

The reason this is its own module rather than a line in a template: the gap
between a sourcing target and send capacity compounds silently. At 100/day
sourced against 45/day sustainable, the backlog is ~1,650 unmailable leads a
month, and they decay while they wait.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapacityReport:
    configured: bool
    domains: int
    mailboxes_per_domain: int | None
    sends_per_mailbox_day: int | None
    sequence_steps: int
    emails_per_day: int | None
    sustainable_enrollments_per_day: int | None
    sourcing_target: int | None

    @property
    def surplus_per_day(self) -> int | None:
        """Leads sourced per day that cannot be mailed. Negative means slack."""
        if self.sustainable_enrollments_per_day is None or self.sourcing_target is None:
            return None
        return self.sourcing_target - self.sustainable_enrollments_per_day

    @property
    def backlog_per_month(self) -> int | None:
        surplus = self.surplus_per_day
        if surplus is None:
            return None
        return surplus * 22  # working days

    @property
    def status(self) -> str:
        """One of: not_configured, no_target, healthy, oversourcing."""
        if not self.configured:
            return "not_configured"
        if self.sourcing_target is None:
            return "no_target"
        surplus = self.surplus_per_day or 0
        return "oversourcing" if surplus > 0 else "healthy"

    def summary(self) -> str:
        if not self.configured:
            # Never a fabricated number. The dashboard says what is missing.
            return (
                "Send capacity is not configured. Set SENDING_DOMAINS, "
                "MAILBOXES_PER_DOMAIN and SENDS_PER_MAILBOX_DAY in .env "
                "before enabling daily sourcing."
            )
        base = (
            f"{self.domains} domains x {self.mailboxes_per_domain} mailboxes "
            f"x {self.sends_per_mailbox_day}/day = {self.emails_per_day} emails/day "
            f"/ {self.sequence_steps} steps "
            f"= {self.sustainable_enrollments_per_day} new leads/day"
        )
        if self.sourcing_target is None:
            return base + ". No daily sourcing target set."
        if self.status == "oversourcing":
            return (
                base + f". Target is {self.sourcing_target}/day, which builds "
                f"~{self.backlog_per_month} unmailable leads a month. Raise "
                "capacity, lower the target, shorten the sequence, or adopt an "
                "explicit staleness policy."
            )
        return base + f". Target is {self.sourcing_target}/day, within capacity."


def compute(
    *,
    domains: int,
    mailboxes_per_domain: int | None,
    sends_per_mailbox_day: int | None,
    sequence_steps: int,
    sourcing_target: int | None = None,
) -> CapacityReport:
    if sequence_steps <= 0:
        raise ValueError("sequence_steps must be positive")

    configured = bool(
        domains and mailboxes_per_domain is not None and sends_per_mailbox_day is not None
    )
    emails = (
        domains * mailboxes_per_domain * sends_per_mailbox_day if configured else None
    )
    enrollments = emails // sequence_steps if emails is not None else None

    return CapacityReport(
        configured=configured,
        domains=domains,
        mailboxes_per_domain=mailboxes_per_domain,
        sends_per_mailbox_day=sends_per_mailbox_day,
        sequence_steps=sequence_steps,
        emails_per_day=emails,
        sustainable_enrollments_per_day=enrollments,
        sourcing_target=sourcing_target,
    )
