"""ICP logic. Pure, so no database needed."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.icp import (
    IcpConfig,
    decayed_signal_score,
    domain_matches,
    evaluate,
    normalise_title,
    priority_score,
    title_score,
)
from app.domain.models import (
    Company,
    Contact,
    FundingStage,
    IcpStatus,
    OfficeSignal,
    Signal,
    SignalType,
)

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def config() -> IcpConfig:
    return IcpConfig.load()


def us_company(**kwargs) -> Company:
    defaults = dict(
        name="Acme",
        domain="acme.com",
        organization_location="San Francisco, California, United States",
        latest_funding_stage=FundingStage.SEED,
    )
    defaults.update(kwargs)
    return Company(**defaults)


def founder(**kwargs) -> Contact:
    defaults = dict(
        apollo_person_id="p1",
        title="Co-Founder & CEO",
        person_location="San Francisco, California, United States",
        company=us_company(),
    )
    defaults.update(kwargs)
    return Contact(**defaults)


# ------------------------------------------------------------------- titles

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Co-Founder & CEO", "co founder & ceo"),
        ("Co‑Founder & CEO", "co founder & ceo"),   # unicode non-breaking hyphen
        ("  CO FOUNDER  &  CEO ", "co founder & ceo"),
        ("Cofounder/CEO", "cofounder ceo"),
    ],
)
def test_normalise_title_collapses_punctuation_and_unicode(raw, expected):
    assert normalise_title(raw) == expected


@pytest.mark.parametrize(
    "title",
    ["Founder", "Co-Founder", "Cofounder", "Co Founder", "Founding Partner",
     "Founder & CEO", "Co-Founder & CEO", "Cofounder & CEO"],
)
def test_configured_founder_titles_score_exact(title, config):
    score, why = title_score(founder(title=title), config)
    assert score == 100.0, why


def test_cofounder_ceo_outranks_bare_founder(config):
    """The regression this exists for.

    'Co-Founder & CEO' is the most common self-description. If it only matches
    the partial rule it scores 60 and ranks below a bare 'Founder' at 100 --
    the highest-intent title sorted to the bottom of the queue.
    """
    combined, _ = title_score(founder(title="Co-Founder & CEO"), config)
    bare, _ = title_score(founder(title="Founder"), config)
    assert combined >= bare == 100.0


def test_ceo_without_founder_flag_is_rejected(config):
    score, why = title_score(founder(title="CEO", is_founder_flagged=False), config)
    assert score == 0.0
    assert "not flagged founder" in why


def test_ceo_with_founder_flag_is_accepted(config):
    score, _ = title_score(founder(title="CEO", is_founder_flagged=True), config)
    assert score == 90.0


def test_unrelated_title_scores_zero(config):
    assert title_score(founder(title="VP of Engineering"), config)[0] == 0.0


# ------------------------------------------------- deferred qualification

def test_unknown_funding_stage_is_pending_not_disqualified(config):
    """The bug that made a previous build's entire lead list un-enrollable.

    Funding stage costs a credit per company and is resolved at enrollment. A
    freshly sourced lead has no stage, and that must not be a hard fail.
    """
    verdict = evaluate(founder(company=us_company(latest_funding_stage=None)),
                       config, now=NOW)
    assert verdict.status is IcpStatus.PENDING
    assert "latest_funding_stage" in verdict.awaiting
    assert verdict.enrollable_after_enrichment


def test_missing_email_is_pending_not_disqualified(config):
    verdict = evaluate(founder(email=None), config, now=NOW)
    assert verdict.status is IcpStatus.PENDING
    assert "email" in verdict.awaiting


def test_fully_known_lead_qualifies(config):
    verdict = evaluate(founder(email="jane@acme.com"), config, now=NOW)
    assert verdict.status is IcpStatus.QUALIFIED
    assert verdict.awaiting == []


@pytest.mark.parametrize(
    "stage", [FundingStage.SERIES_C, FundingStage.SERIES_D_PLUS, FundingStage.PUBLIC],
)
def test_late_stage_is_disqualified_once_known(stage, config):
    verdict = evaluate(founder(company=us_company(latest_funding_stage=stage)),
                       config, now=NOW)
    assert verdict.status is IcpStatus.DISQUALIFIED


# ----------------------------------------------------------- hard filters

def test_non_us_person_is_disqualified(config):
    verdict = evaluate(founder(person_location="Berlin, Germany"), config, now=NOW)
    assert verdict.status is IcpStatus.DISQUALIFIED


def test_non_us_company_hq_is_disqualified(config):
    company = us_company(organization_location="London, United Kingdom")
    verdict = evaluate(founder(company=company), config, now=NOW)
    assert verdict.status is IcpStatus.DISQUALIFIED


def test_free_mail_domain_is_disqualified(config):
    verdict = evaluate(founder(company=us_company(domain="gmail.com")), config, now=NOW)
    assert verdict.status is IcpStatus.DISQUALIFIED


def test_do_not_contact_is_disqualified(config):
    verdict = evaluate(founder(do_not_contact=True), config, now=NOW)
    assert verdict.status is IcpStatus.DISQUALIFIED


# ------------------------------------------------------ frequency cap (90d)

def test_emailed_inside_the_window_is_disqualified(config):
    contact = founder(last_emailed_at=NOW - timedelta(days=30))
    verdict = evaluate(contact, config, now=NOW)
    assert verdict.status is IcpStatus.DISQUALIFIED
    assert "frequency cap" in " ".join(verdict.reasons)


def test_emailed_outside_the_window_is_allowed(config):
    contact = founder(last_emailed_at=NOW - timedelta(days=91), email="j@acme.com")
    assert evaluate(contact, config, now=NOW).status is IcpStatus.QUALIFIED


def test_frequency_cap_boundary_is_exclusive_at_exactly_90_days(config):
    """At exactly 90 days the lead is out of the window and mailable."""
    contact = founder(last_emailed_at=NOW - timedelta(days=90), email="j@acme.com")
    assert evaluate(contact, config, now=NOW).status is IcpStatus.QUALIFIED


# ------------------------------------------------------- domain suppression

@pytest.mark.parametrize(
    "candidate,suppressed,expected",
    [
        ("acme.com", "acme.com", True),
        ("careers.acme.com", "acme.com", True),          # subdomains are covered
        ("mail.careers.acme.com", "acme.com", True),
        ("notacme.com", "acme.com", False),              # the endswith trap
        ("acme.com.evil.com", "acme.com", False),
        ("ACME.COM", "acme.com", True),
        ("https://careers.acme.com/jobs", "acme.com", True),
        ("jane@careers.acme.com", "acme.com", True),
    ],
)
def test_domain_matching_covers_subdomains_without_overreaching(
    candidate, suppressed, expected
):
    assert domain_matches(candidate, suppressed) is expected


def test_suppressed_domain_blocks_the_contact(config):
    verdict = evaluate(
        founder(company=us_company(domain="careers.acme.com")),
        config,
        suppressed_domains={"acme.com"},
        now=NOW,
    )
    assert verdict.status is IcpStatus.DISQUALIFIED


# --------------------------------------------------------- signal decay

def test_signal_decays_by_half_at_one_half_life(config):
    """new_office: weight 100, half-life 14d."""
    fresh, _ = decayed_signal_score(
        [Signal(SignalType.NEW_OFFICE, NOW, "manual")], config, now=NOW
    )
    aged, _ = decayed_signal_score(
        [Signal(SignalType.NEW_OFFICE, NOW - timedelta(days=14), "manual")],
        config, now=NOW,
    )
    assert fresh == pytest.approx(100.0)
    assert aged == pytest.approx(50.0)


def test_new_office_signal_is_cold_by_45_days(config):
    """Recency dominates: white-hot for 7 days, cold by 45."""
    hot, _ = decayed_signal_score(
        [Signal(SignalType.NEW_OFFICE, NOW - timedelta(days=7), "manual")],
        config, now=NOW,
    )
    cold, _ = decayed_signal_score(
        [Signal(SignalType.NEW_OFFICE, NOW - timedelta(days=45), "manual")],
        config, now=NOW,
    )
    assert hot == pytest.approx(70.7, abs=0.5)
    assert cold < 12.0


def test_signals_accumulate(config):
    score, reasons = decayed_signal_score(
        [
            Signal(SignalType.NEW_OFFICE, NOW, "manual"),
            Signal(SignalType.TEAM_GROWTH, NOW, "manual"),
        ],
        config, now=NOW,
    )
    assert score == pytest.approx(145.0)
    assert len(reasons) == 2


# ------------------------------------------------------------- prioritising

def test_in_office_company_outranks_remote_one(config):
    """office_signal never filters, but it must move the ordering."""
    in_office = founder(company=us_company(
        office_signal=OfficeSignal.CONFIRMED_IN_OFFICE,
        office_signal_evidence=[{"url": "https://example.com/post"}],
    ))
    remote = founder(company=us_company(office_signal=OfficeSignal.LIKELY_REMOTE))
    assert priority_score(in_office, config) > priority_score(remote, config)


def test_fresh_signal_outranks_stale_one(config):
    contact = founder()
    fresh = priority_score(
        contact, config, [Signal(SignalType.NEW_OFFICE, NOW, "manual")], now=NOW
    )
    stale = priority_score(
        contact, config,
        [Signal(SignalType.NEW_OFFICE, NOW - timedelta(days=60), "manual")], now=NOW,
    )
    assert fresh > stale
