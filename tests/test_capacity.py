"""Section 6 arithmetic, against the worked example in the spec."""

from __future__ import annotations

import pytest

from app.domain.capacity import compute


def test_worked_example_from_the_spec():
    """2 domains x 3 mailboxes x 30/day = 180 emails/day / 4 steps = 45 leads/day."""
    report = compute(
        domains=2, mailboxes_per_domain=3, sends_per_mailbox_day=30, sequence_steps=4
    )
    assert report.emails_per_day == 180
    assert report.sustainable_enrollments_per_day == 45


def test_a_100_per_day_target_against_45_capacity_is_flagged():
    report = compute(
        domains=2, mailboxes_per_domain=3, sends_per_mailbox_day=30,
        sequence_steps=4, sourcing_target=100,
    )
    assert report.status == "oversourcing"
    assert report.surplus_per_day == 55
    assert report.backlog_per_month == 1210   # 55 x 22 working days
    assert "unmailable" in report.summary()


def test_a_target_within_capacity_is_healthy():
    report = compute(
        domains=2, mailboxes_per_domain=3, sends_per_mailbox_day=30,
        sequence_steps=4, sourcing_target=40,
    )
    assert report.status == "healthy"
    assert report.surplus_per_day == -5


def test_shortening_the_sequence_raises_sustainable_enrollments():
    four = compute(domains=2, mailboxes_per_domain=3, sends_per_mailbox_day=30,
                   sequence_steps=4)
    three = compute(domains=2, mailboxes_per_domain=3, sends_per_mailbox_day=30,
                    sequence_steps=3)
    assert three.sustainable_enrollments_per_day == 60
    assert three.sustainable_enrollments_per_day > four.sustainable_enrollments_per_day


def test_unconfigured_capacity_reports_nothing_rather_than_zero():
    """A zero here would read as a measurement. It has to read as 'unknown'."""
    report = compute(
        domains=0, mailboxes_per_domain=None, sends_per_mailbox_day=None,
        sequence_steps=4,
    )
    assert report.configured is False
    assert report.status == "not_configured"
    assert report.emails_per_day is None
    assert report.sustainable_enrollments_per_day is None
    assert report.surplus_per_day is None
    assert "not configured" in report.summary()


def test_partial_capacity_config_is_still_unconfigured():
    report = compute(
        domains=2, mailboxes_per_domain=3, sends_per_mailbox_day=None, sequence_steps=4
    )
    assert report.configured is False
    assert report.emails_per_day is None


def test_zero_steps_is_rejected():
    with pytest.raises(ValueError):
        compute(domains=2, mailboxes_per_domain=3, sends_per_mailbox_day=30,
                sequence_steps=0)
