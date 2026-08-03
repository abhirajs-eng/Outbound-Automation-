"""HubSpot mapping. Pure — no token, no network."""

from __future__ import annotations

import pytest

from app.domain.hubspot_mapping import (
    ALL_PROPERTIES,
    BATCH_SIZE,
    CONTACT_PROPERTIES,
    COMPANY_PROPERTIES,
    ReservedPropertyError,
    build_upsert_inputs,
    chunked,
    company_to_properties,
    contact_to_properties,
)
from app.domain.models import Company, Contact, FundingStage, OfficeSignal


# ------------------------------------------------- the five-property budget

def test_exactly_five_custom_properties_are_defined():
    """Free tier caps custom properties at ~10. Adding a sixth is a decision.

    Everything else the enrollment layer needs lives in Postgres.
    """
    total = sum(len(defs) for defs in ALL_PROPERTIES.values())
    assert total == 5, [d.name for defs in ALL_PROPERTIES.values() for d in defs]


def test_the_five_are_the_ones_specified():
    assert {d.name for d in CONTACT_PROPERTIES} == {
        "apollo_person_id", "priority_score", "seed_lifecycle_stage",
    }
    assert {d.name for d in COMPANY_PROPERTIES} == {
        "latest_funding_stage", "office_signal",
    }


def test_apollo_person_id_is_unique_so_it_can_key_a_batch_upsert():
    """HubSpot rejects an idProperty that is not marked hasUniqueValue."""
    definition = next(d for d in CONTACT_PROPERTIES if d.name == "apollo_person_id")
    assert definition.has_unique_value is True
    assert definition.to_payload()["hasUniqueValue"] is True


def test_only_the_dedup_key_is_unique():
    others = [
        d for defs in ALL_PROPERTIES.values() for d in defs
        if d.name != "apollo_person_id"
    ]
    assert all(d.has_unique_value is False for d in others)


def test_enumeration_options_cover_the_full_vocabulary():
    stage = next(d for d in COMPANY_PROPERTIES if d.name == "latest_funding_stage")
    assert {o["value"] for o in stage.to_payload()["options"]} == {
        s.value for s in FundingStage
    }
    signal = next(d for d in COMPANY_PROPERTIES if d.name == "office_signal")
    assert {o["value"] for o in signal.to_payload()["options"]} == {
        s.value for s in OfficeSignal
    }


# ------------------------------------------- the reserved-property guard

def test_writing_lifecyclestage_raises():
    """`lifecyclestage` is reserved and has HubSpot's own vocabulary.

    Overwriting it corrupts a rep-facing field. Ours is seed_lifecycle_stage.
    """
    with pytest.raises(ReservedPropertyError) as excinfo:
        build_upsert_inputs(
            [("p1", {"lifecyclestage": "enrolled"})], id_property="apollo_person_id"
        )
    assert "seed_lifecycle_stage" in str(excinfo.value)


def test_our_stage_property_is_allowed():
    inputs = build_upsert_inputs(
        [("p1", {"seed_lifecycle_stage": "enrolled"})],
        id_property="apollo_person_id",
    )
    assert inputs[0]["properties"]["seed_lifecycle_stage"] == "enrolled"


# --------------------------------------------------------------- mapping

def _contact(**kwargs) -> Contact:
    defaults = dict(
        apollo_person_id="p1", first_name="Jane", last_name="Doe",
        title="Co-Founder & CEO",
        company=Company(name="Acme", domain="Acme.com"),
    )
    defaults.update(kwargs)
    return Contact(**defaults)


def test_contact_maps_to_hubspot_field_names():
    properties = contact_to_properties(
        _contact(email="jane@acme.com"),
        priority_score=87.5,
        seed_lifecycle_stage="sourced",
    )
    assert properties["firstname"] == "Jane"
    assert properties["lastname"] == "Doe"
    assert properties["jobtitle"] == "Co-Founder & CEO"
    assert properties["email"] == "jane@acme.com"
    assert properties["apollo_person_id"] == "p1"
    assert properties["priority_score"] == 87.5
    assert properties["seed_lifecycle_stage"] == "sourced"


def test_unrevealed_contact_carries_no_email_key_at_all():
    """Not an empty string: an empty value overwrites a rep's manual correction."""
    properties = contact_to_properties(_contact(email=None))
    assert "email" not in properties


def test_unenriched_company_carries_no_funding_stage_key():
    """None means 'not enriched'. Sending '' asserts we looked and found none."""
    properties = company_to_properties(Company(name="Acme", domain="acme.com"))
    assert "latest_funding_stage" not in properties


def test_enriched_company_sends_the_stage_value():
    properties = company_to_properties(
        Company(name="Acme", domain="acme.com",
                latest_funding_stage=FundingStage.SERIES_A)
    )
    assert properties["latest_funding_stage"] == "series_a"


def test_company_domain_is_lowercased():
    assert company_to_properties(
        Company(name="Acme", domain="Acme.COM")
    )["domain"] == "acme.com"


def test_office_signal_defaults_to_unknown_and_is_still_sent():
    """'unknown' is a real value, distinct from 'not evaluated'."""
    properties = company_to_properties(Company(name="Acme", domain="acme.com"))
    assert properties["office_signal"] == "unknown"


# --------------------------------------------------------------- batching

def test_batches_are_capped_at_the_hubspot_limit():
    batches = list(chunked(list(range(250)), BATCH_SIZE))
    assert [len(b) for b in batches] == [100, 100, 50]


def test_empty_input_produces_no_batches():
    assert list(chunked([], BATCH_SIZE)) == []


def test_exact_multiple_does_not_emit_a_trailing_empty_batch():
    assert [len(b) for b in chunked(list(range(200)), BATCH_SIZE)] == [100, 100]


def test_zero_batch_size_is_rejected():
    with pytest.raises(ValueError):
        list(chunked([1, 2, 3], 0))


def test_upsert_inputs_are_keyed_on_the_id_property():
    inputs = build_upsert_inputs(
        [("p1", {"firstname": "Jane"}), ("p2", {"firstname": "Ann"})],
        id_property="apollo_person_id",
    )
    assert [i["id"] for i in inputs] == ["p1", "p2"]
    assert all(i["idProperty"] == "apollo_person_id" for i in inputs)


def test_upsert_without_a_key_is_rejected():
    """An empty key would create a fresh duplicate on every run."""
    with pytest.raises(ValueError):
        build_upsert_inputs([("", {"firstname": "Jane"})],
                            id_property="apollo_person_id")
