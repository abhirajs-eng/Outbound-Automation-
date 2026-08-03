"""HubSpot private-app adapter.

Verified facts this is built on (spec §2, re-verify at first live call):

- Private apps work on all tiers **including Free**. Token from
  Settings -> Integrations -> Private Apps, shown once.
- Required scopes: `crm.objects.{contacts,companies}.{read,write}` and
  `crm.schemas.{contacts,companies}.{read,write}`. The **schemas** scopes are
  what allow creating custom properties programmatically and are easy to miss --
  without them property creation fails at runtime, not at auth.
- Rate limits Free/Starter: **100 requests / 10 seconds**, 250,000/day.
- Batch endpoints take **100 records per call**.
- **Custom objects are Enterprise-only** and are not used.
- Webhooks are supported in private apps, but **subscriptions must be configured
  in the UI** -- they cannot be created or edited by API.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from app.adapters.crm import UpsertResult
from app.adapters.http import (
    HttpTransport,
    HttpxTransport,
    RateLimiter,
    call_with_policy,
)
from app.domain.hubspot_mapping import (
    ALL_PROPERTIES,
    BATCH_SIZE,
    build_upsert_inputs,
    chunked,
    company_to_properties,
    contact_to_properties,
)
from app.domain.models import Company, Contact

logger = logging.getLogger(__name__)

BASE_URL = "https://api.hubapi.com"

REQUIRED_SCOPES = (
    "crm.objects.contacts.read",
    "crm.objects.contacts.write",
    "crm.objects.companies.read",
    "crm.objects.companies.write",
    "crm.schemas.contacts.read",
    "crm.schemas.contacts.write",
    "crm.schemas.companies.read",
    "crm.schemas.companies.write",
)


class HubSpotError(Exception):
    pass


class HubSpotCrmStore:
    """CrmStore implementation. Sync, because it runs from cron jobs."""

    def __init__(
        self,
        token: str,
        *,
        transport: HttpTransport | None = None,
        limiter: RateLimiter | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        if not token:
            raise HubSpotError("a private app token is required")
        self._token = token
        self._transport = transport or HttpxTransport()
        # Deliberately under the documented 100/10s so a second process sharing
        # the portal does not push the pair over the limit.
        self._limiter = limiter or RateLimiter(max_calls=90, per_seconds=10.0)
        self._base_url = base_url.rstrip("/")

    # ------------------------------------------------------------- internals

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _call(
        self, method: str, path: str, *, mutating: bool, json: Any | None = None,
        params: dict[str, Any] | None = None,
    ):
        return call_with_policy(
            self._transport,
            method,
            f"{self._base_url}{path}",
            mutating=mutating,
            headers=self._headers(),
            json=json,
            params=params,
            limiter=self._limiter,
        )

    # ------------------------------------------------------------ properties

    def list_property_names(self, object_type: str) -> set[str]:
        response = self._call("GET", f"/crm/v3/properties/{object_type}",
                              mutating=False)
        if not response.ok:
            raise HubSpotError(
                f"could not list {object_type} properties "
                f"({response.status}): {_explain(response)}"
            )
        results = (response.body or {}).get("results", [])
        return {item.get("name") for item in results if item.get("name")}

    def ensure_properties(self) -> dict[str, list[str]]:
        """Create the five custom properties, skipping any that already exist.

        Idempotent: safe to run on every deploy.
        """
        created: dict[str, list[str]] = {}

        for object_type, definitions in ALL_PROPERTIES.items():
            existing = self.list_property_names(object_type)
            made: list[str] = []

            for definition in definitions:
                if definition.name in existing:
                    logger.info(
                        "property %s.%s already exists", object_type, definition.name
                    )
                    continue

                response = self._call(
                    "POST",
                    f"/crm/v3/properties/{object_type}",
                    mutating=True,
                    json=definition.to_payload(),
                )
                if response.ok:
                    made.append(definition.name)
                    logger.info("created property %s.%s", object_type, definition.name)
                    continue

                if response.status == 409:
                    # Created concurrently by another deploy. Not an error.
                    logger.info(
                        "property %s.%s already existed (409)",
                        object_type, definition.name,
                    )
                    continue
                if response.status == 403:
                    raise HubSpotError(
                        f"403 creating {object_type}.{definition.name}. The token "
                        f"is probably missing crm.schemas.{object_type}.write -- "
                        "that scope is what allows creating custom properties, "
                        "and it is separate from crm.objects.*.write."
                    )
                raise HubSpotError(
                    f"could not create {object_type}.{definition.name} "
                    f"({response.status}): {_explain(response)}"
                )

            created[object_type] = made

        return created

    # --------------------------------------------------------------- records

    def upsert_contacts(
        self, contacts: Sequence[tuple[Contact, dict[str, Any]]]
    ) -> UpsertResult:
        """Batch upsert keyed on apollo_person_id.

        `contacts` is (Contact, extras) where extras may carry priority_score
        and seed_lifecycle_stage -- both live in Postgres, not on the dataclass.
        """
        records = []
        skipped: list[dict[str, Any]] = []

        for contact, extras in contacts:
            if not contact.apollo_person_id:
                # Without the dedup key an upsert would create a duplicate on
                # every run. Report it rather than writing one.
                skipped.append(
                    {
                        "reason": "missing apollo_person_id",
                        "email": contact.email,
                        "name": f"{contact.first_name or ''} {contact.last_name or ''}".strip(),
                    }
                )
                continue
            records.append(
                (
                    contact.apollo_person_id,
                    contact_to_properties(
                        contact,
                        priority_score=extras.get("priority_score"),
                        seed_lifecycle_stage=extras.get("seed_lifecycle_stage"),
                    ),
                )
            )

        result = self._batch_upsert(
            "contacts", records, id_property="apollo_person_id"
        )
        return UpsertResult(
            requested=len(contacts),
            succeeded=result.succeeded,
            ids=result.ids,
            errors=result.errors + skipped,
        )

    def upsert_companies(self, companies: Sequence[Company]) -> UpsertResult:
        """Upsert companies keyed on domain.

        HubSpot's `domain` is not a hasUniqueValue property, so batch upsert by
        idProperty is not available. Companies are low-volume relative to
        contacts, so this reads then writes rather than spending one of our five
        custom property slots on a company dedup key.
        """
        with_domain = [c for c in companies if c.domain]
        skipped = [
            {"reason": "missing domain", "name": c.name}
            for c in companies
            if not c.domain
        ]

        ids: dict[str, str] = {}
        errors: list[dict[str, Any]] = list(skipped)
        succeeded = 0

        for company in with_domain:
            domain = company.domain.lower()
            try:
                existing_id = self.find_company_by_domain(domain)
                properties = company_to_properties(company)

                if existing_id:
                    response = self._call(
                        "PATCH",
                        f"/crm/v3/objects/companies/{existing_id}",
                        mutating=True,
                        json={"properties": properties},
                    )
                else:
                    response = self._call(
                        "POST",
                        "/crm/v3/objects/companies",
                        mutating=True,
                        json={"properties": properties},
                    )

                if response.ok:
                    ids[domain] = str((response.body or {}).get("id", existing_id or ""))
                    succeeded += 1
                else:
                    errors.append(
                        {
                            "domain": domain,
                            "status": response.status,
                            "message": _explain(response),
                        }
                    )
            except Exception as exc:  # noqa: BLE001 - one company must not stop the batch
                errors.append({"domain": domain, "message": str(exc)})

        return UpsertResult(
            requested=len(companies), succeeded=succeeded, ids=ids, errors=errors
        )

    def find_company_by_domain(self, domain: str) -> str | None:
        response = self._call(
            "POST",
            "/crm/v3/objects/companies/search",
            mutating=False,
            json={
                "filterGroups": [
                    {
                        "filters": [
                            {
                                "propertyName": "domain",
                                "operator": "EQ",
                                "value": domain.lower(),
                            }
                        ]
                    }
                ],
                "limit": 1,
                "properties": ["domain"],
            },
        )
        if not response.ok:
            raise HubSpotError(
                f"company search failed ({response.status}): {_explain(response)}"
            )
        results = (response.body or {}).get("results", [])
        return str(results[0]["id"]) if results else None

    def _batch_upsert(
        self, object_type: str, records: list[tuple[str, dict]], *, id_property: str
    ) -> UpsertResult:
        ids: dict[str, str] = {}
        errors: list[dict[str, Any]] = []
        succeeded = 0

        for batch in chunked(records, BATCH_SIZE):
            inputs = build_upsert_inputs(batch, id_property=id_property)
            response = self._call(
                "POST",
                f"/crm/v3/objects/{object_type}/batch/upsert",
                mutating=True,
                json={"inputs": inputs},
            )

            if response.ok or response.status == 207:
                body = response.body or {}
                for item in body.get("results", []):
                    key = (item.get("properties") or {}).get(id_property)
                    if key:
                        ids[key] = str(item.get("id"))
                    succeeded += 1
                # 207 means some records failed; HubSpot lists them separately.
                for failure in body.get("errors", []) or []:
                    errors.append(
                        {"status": response.status, "message": str(failure)}
                    )
            else:
                errors.append(
                    {
                        "status": response.status,
                        "message": _explain(response),
                        "batch_size": len(batch),
                    }
                )

        return UpsertResult(
            requested=len(records), succeeded=succeeded, ids=ids, errors=errors
        )

    def associate_contact_to_company(self, contact_id: str, company_id: str) -> bool:
        response = self._call(
            "PUT",
            f"/crm/v4/objects/contacts/{contact_id}/associations/default/companies/{company_id}",
            mutating=True,
        )
        return response.ok

    def mark_opted_out(self, emails: Sequence[str]) -> UpsertResult:
        """Mirror suppressions into HubSpot's opt-out so reps can see them.

        Postgres remains authoritative. This is display only -- enrollment never
        consults HubSpot for suppression.
        """
        addresses = [e.strip().lower() for e in emails if e and e.strip()]
        succeeded = 0
        errors: list[dict[str, Any]] = []

        for batch in chunked(addresses, BATCH_SIZE):
            for address in batch:
                response = self._call(
                    "POST",
                    "/communication-preferences/v3/unsubscribe",
                    mutating=True,
                    json={"emailAddress": address, "subscriptionId": None},
                )
                if response.ok:
                    succeeded += 1
                else:
                    errors.append(
                        {
                            "email": address,
                            "status": response.status,
                            "message": _explain(response),
                        }
                    )

        return UpsertResult(
            requested=len(addresses), succeeded=succeeded, errors=errors
        )

    # ------------------------------------------------------------ diagnostics

    def check_access(self) -> dict[str, Any]:
        """Confirm the token works and report which properties already exist."""
        report: dict[str, Any] = {"ok": True, "objects": {}}
        for object_type in ALL_PROPERTIES:
            try:
                names = self.list_property_names(object_type)
                expected = {d.name for d in ALL_PROPERTIES[object_type]}
                report["objects"][object_type] = {
                    "readable": True,
                    "custom_properties_present": sorted(expected & names),
                    "custom_properties_missing": sorted(expected - names),
                }
            except HubSpotError as exc:
                report["ok"] = False
                report["objects"][object_type] = {
                    "readable": False, "error": str(exc)
                }
        return report


def _explain(response) -> str:
    body = response.body
    if isinstance(body, dict):
        return str(body.get("message") or body)
    return str(body)[:500]
