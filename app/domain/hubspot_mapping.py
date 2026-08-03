"""HubSpot property definitions and record mapping. Pure: no HTTP, no ORM.

Constraints this module encodes, all of them load-bearing:

- **Free tier caps custom properties at ~10.** Exactly five are defined here and
  adding a sixth is a decision, not a convenience. Everything else the
  enrollment layer needs (icp_reasons, office_signal_evidence, last_emailed_at,
  do_not_contact) stays in Postgres, where it is queryable at volume.
- **`lifecyclestage` is reserved** and has its own HubSpot vocabulary
  (subscriber, lead, MQL, SQL, opportunity, customer, evangelist). Ours is
  `seed_lifecycle_stage`. Writing to the reserved one raises here rather than
  quietly corrupting a rep-facing field.
- **Custom objects are Enterprise-only.** Standard Contacts and Companies plus
  these properties work on Free.
- **Batch endpoints take 100 records per call.**
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Iterator, Sequence

from app.domain.models import Company, Contact, FundingStage, OfficeSignal

#: HubSpot's documented batch size. Not a tuning knob.
BATCH_SIZE = 100

#: Reserved HubSpot properties we must never write. `lifecyclestage` is the one
#: that actually gets attempted; the others are here so the guard is a rule
#: rather than a special case.
RESERVED_PROPERTIES = frozenset(
    {"lifecyclestage", "hs_lead_status", "hubspot_owner_id", "createdate"}
)


class ReservedPropertyError(ValueError):
    """Raised when a mapping would write a HubSpot-reserved property."""


@dataclass(frozen=True)
class PropertyDefinition:
    name: str
    label: str
    type: str
    field_type: str
    group_name: str
    description: str
    options: tuple[str, ...] = ()
    #: Required for use as a batch-upsert idProperty. HubSpot rejects an
    #: idProperty that is not marked unique, and the error is not obvious.
    has_unique_value: bool = False

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": self.name,
            "label": self.label,
            "type": self.type,
            "fieldType": self.field_type,
            "groupName": self.group_name,
            "description": self.description,
        }
        if self.has_unique_value:
            payload["hasUniqueValue"] = True
        if self.options:
            payload["options"] = [
                {"label": _humanise(value), "value": value, "displayOrder": index}
                for index, value in enumerate(self.options)
            ]
        return payload


def _humanise(value: str) -> str:
    return value.replace("_", " ").title()


CONTACT_PROPERTIES: tuple[PropertyDefinition, ...] = (
    PropertyDefinition(
        name="apollo_person_id",
        label="Apollo Person ID",
        type="string",
        field_type="text",
        group_name="contactinformation",
        description=(
            "Dedup key. HubSpot's native key is email, which is absent for every "
            "lead we have not paid to reveal."
        ),
        has_unique_value=True,
    ),
    PropertyDefinition(
        name="priority_score",
        label="Priority Score",
        type="number",
        field_type="number",
        group_name="contactinformation",
        description="Blended title fit, office signal and decayed activity signals.",
    ),
    PropertyDefinition(
        name="seed_lifecycle_stage",
        label="Outbound Stage",
        type="enumeration",
        field_type="select",
        group_name="contactinformation",
        description=(
            "Our outbound stage. Deliberately separate from the reserved "
            "lifecyclestage property, which has its own vocabulary."
        ),
        options=(
            "sourced", "qualified", "enrolled", "engaged",
            "replied", "meeting", "disqualified",
        ),
    ),
)

COMPANY_PROPERTIES: tuple[PropertyDefinition, ...] = (
    PropertyDefinition(
        name="latest_funding_stage",
        label="Latest Funding Stage",
        type="enumeration",
        field_type="select",
        group_name="companyinformation",
        description=(
            "The ICP criterion. Only obtainable from Apollo's bulk_enrich "
            "endpoint, at 1 credit per matched company. Empty means not "
            "enriched, not 'no funding'."
        ),
        options=tuple(stage.value for stage in FundingStage),
    ),
    PropertyDefinition(
        name="office_signal",
        label="Office Signal",
        type="enumeration",
        field_type="select",
        group_name="companyinformation",
        description=(
            "Whether the team works from a physical office. Apollo cannot query "
            "this. Evidence is stored in Postgres so the value stays auditable."
        ),
        options=tuple(signal.value for signal in OfficeSignal),
    ),
)

ALL_PROPERTIES = {
    "contacts": CONTACT_PROPERTIES,
    "companies": COMPANY_PROPERTIES,
}


def _guard_reserved(properties: dict[str, Any]) -> dict[str, Any]:
    clashes = RESERVED_PROPERTIES & properties.keys()
    if clashes:
        raise ReservedPropertyError(
            f"refusing to write HubSpot-reserved properties: {sorted(clashes)}. "
            "Use seed_lifecycle_stage for our own stage vocabulary."
        )
    return properties


def contact_to_properties(
    contact: Contact,
    *,
    priority_score: float | None = None,
    seed_lifecycle_stage: str | None = None,
) -> dict[str, Any]:
    """Map a Contact to HubSpot properties, omitting anything unknown.

    Absent keys are omitted rather than sent as empty strings: an empty string
    overwrites a value a rep may have corrected by hand.
    """
    properties: dict[str, Any] = {}

    if contact.apollo_person_id:
        properties["apollo_person_id"] = contact.apollo_person_id
    if contact.first_name:
        properties["firstname"] = contact.first_name
    if contact.last_name:
        properties["lastname"] = contact.last_name
    if contact.title:
        properties["jobtitle"] = contact.title
    if contact.linkedin_url:
        properties["hs_linkedin_url"] = contact.linkedin_url
    # Only present once revealed at enrollment. Search never returns it.
    if contact.email:
        properties["email"] = contact.email
    if contact.company and contact.company.name:
        properties["company"] = contact.company.name
    if priority_score is not None:
        properties["priority_score"] = round(float(priority_score), 3)
    if seed_lifecycle_stage:
        properties["seed_lifecycle_stage"] = seed_lifecycle_stage

    return _guard_reserved(properties)


def company_to_properties(company: Company) -> dict[str, Any]:
    properties: dict[str, Any] = {}

    if company.name:
        properties["name"] = company.name
    if company.domain:
        properties["domain"] = company.domain.lower()
    if company.founded_year:
        properties["founded_year"] = company.founded_year
    # None means not enriched. Sending "" would assert we looked and found none.
    if company.latest_funding_stage is not None:
        properties["latest_funding_stage"] = company.latest_funding_stage.value
    if company.office_signal is not None:
        properties["office_signal"] = company.office_signal.value

    return _guard_reserved(properties)


def chunked(items: Sequence[Any], size: int = BATCH_SIZE) -> Iterator[list[Any]]:
    """Split into HubSpot-sized batches.

    A 100-lead/day pipeline against a 100 req/10s limit uses well under 0.1% of
    the daily allowance -- provided records go through the batch endpoints
    rather than one call each.
    """
    if size <= 0:
        raise ValueError("batch size must be positive")
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def build_upsert_inputs(
    records: Iterable[tuple[str, dict[str, Any]]], *, id_property: str
) -> list[dict[str, Any]]:
    """Build batch-upsert inputs keyed on a unique property.

    HubSpot matches on `idProperty`, which must be a property created with
    hasUniqueValue. For contacts that is apollo_person_id -- email is absent for
    every lead we have not paid to reveal, so it cannot be the key.
    """
    inputs = []
    for identifier, properties in records:
        if not identifier:
            raise ValueError(f"empty {id_property}; cannot upsert without a key")
        inputs.append(
            {
                "idProperty": id_property,
                "id": identifier,
                "properties": _guard_reserved(properties),
            }
        )
    return inputs
