# Decisions, verified contracts, and places the spec was wrong

Every entry records what was checked, when, and against what. Where a claim has
not been verified against a live API it says so explicitly — an unverified
assumption recorded as fact is how the previous build lost an architecture.

---

## Verification status by source

| Claim | Status | Date | How |
|---|---|---|---|
| §1.3 sample size: 2%→3% needs ~3,825/variant | **Confirmed** | 2026-08-03 | Computed, this repo |
| §1.3 Bayesian: 8-vs-16 on n=200 clears 0.95 | **Confirmed** | 2026-08-03 | Computed, this repo |
| §1.3 "200 delivered / 8 positive" floor detects ~4%→11.5% | **Confirmed** | 2026-08-03 | Computed, this repo |
| §6 capacity worked example (2×3×30 ÷ 4 = 45) | **Confirmed** | 2026-08-03 | `tests/test_capacity.py` |
| Postgres schema behaviour (all constraints) | **Confirmed** | 2026-08-03 | Live Postgres 16.13 |
| §1.1 Apollo endpoint costs and response fields | **Inherited, unverified here** | spec: 2026-07-30/31 | Not re-checked — no key configured |
| §1.6 Smartlead contract | **Inherited, unverified here** | spec: 2026-07-30/31 | Not re-checked — no key configured |
| §2 HubSpot facts (tiers, scopes, limits) | **Inherited, unverified here** | spec: 2026-08-03 | Not re-checked — no token configured |
| HubSpot adapter behaviour (batching, 403 handling, partial failure) | **Confirmed against a fake transport** | 2026-08-03 | `verify_client` — contract shape assumed, error handling proven |
| Webhook dedup on repeated delivery | **Confirmed** | 2026-08-03 | Live Postgres 16.13 |

The inherited rows are treated as true for design purposes and **re-verified at
the start of the phase that first depends on them** (Phase 2 HubSpot, Phase 3
Apollo, Phase 5 Smartlead). Where docs and live behaviour disagree, live wins
and the discrepancy is recorded here with a date.

---

## Statistical claims — checked, not taken on faith

Computed with a closed-form two-proportion z sample size and the exact
beta-binomial `P(B>A)` series, both in plain Python.

**2% → 3% positive-reply rate, α=0.05 two-sided, 80% power: n = 3,825.1 per
variant.** The spec's ~3,825 is exact. At ~45 enrollments/day split two ways
this is ~170 days per conclusive test, which is why futility detection carries
nearly all the value at this volume.

**A "200 delivered, 8 positive" floor detects 4% → 11.5% (n=198/arm).** It does
not detect anything smaller. Nothing in cold email copy produces a 187%
relative lift, so that floor is not a real gate.

**At n=200, 8 vs 16 conversions gives P(B>A) = 0.9516** with Beta(1,1) priors.
This *clears* a 0.95 Bayesian threshold. The statistics alone would crown that
winner. **The minimum-sample gate is therefore not redundant with the
statistical test** — it is the only thing that stops this. Encoded as
`experiments.min_delivered_per_variant`, default 400.

---

## Where this build departs from the spec

### 1. Open rate: absent rather than raising

**Spec (§1.4):** "make the accessor raise, don't just document it."

**Built:** open rate is not a field on the metrics dataclass or its dict form at
all. A separately named diagnostic function computes it and is never called by
decision code.

**Why:** a property that raises is a landmine for anything that iterates or
serialises all metrics — dashboard rendering, CSV export, a debug repr. The
guarantee wanted is "no decision path can read this," and absence delivers that
without making unrelated code crash. Recorded because it is a deliberate
deviation, not an oversight. Arrives in Phase 6.

### 2. The repo was not empty

The spec assumes an empty repo. This one already holds the Audria X/Twitter
growth system (`docs/`, `daily/`, `.claude/skills/audria-daily/`). Those are
untouched; the outbound system was added alongside in `app/`, `migrations/`,
`config/`, `tests/`, `tools/`.

This turned out to be useful rather than awkward: `docs/audria-x-growth-operating-doc.md`
§1 already defines the ICP (Seed–Series B, US-based, physical US office, working
from it) and it matches spec §4. `config/icp.yaml` is now the single definition
both systems read, rather than a second copy that drifts.

### 3. Capacity is expressed as a mailbox count, not domains × per-domain

**Spec (§6):** `domains × mailboxes × sends_per_mailbox_day`.

**Actual configuration (confirmed with the operator, 2026-08-03):** 2 sending
domains, **18 mailboxes total**. That is 9 and 9 only if nobody has ever moved
one, and the product form silently encodes that assumption.

**Built:** `TOTAL_MAILBOXES` takes precedence over `MAILBOXES_PER_DOMAIN`. The
product form still works and the spec's worked example still yields 45/day.
From Phase 5 the count will come from Smartlead's `GET /email-accounts` rather
than from `.env` at all — a real count beats a configured one.

**What this changes strategically:** at 30 sends/mailbox/day, 18 mailboxes give
540 emails/day ÷ 4 steps = **135 sustainable enrollments/day**. The spec's worry
— a 100/day sourcing target against 45/day capacity building ~1,650 unmailable
leads a month — **does not apply here.** 100/day is comfortably within capacity
(35/day of slack).

The binding constraint moves elsewhere: 18 mailboxes at 135 leads/day needs
roughly **340–470 Apollo credits/day** for stage enrichment and email reveal at
a 25–40% hit rate. Sourcing volume is an Apollo spend question, not a send
capacity question. Recorded here so the daily target is set against the right
number.

**Warm-up caveat, not yet resolved:** if these 18 mailboxes are new, 30/day each
from day one will burn them. Cold mailboxes want ~10/day ramping over 3–4 weeks,
which is 45 leads/day initially — back at the spec's figure. `mailboxes.status`
carries a `warming` value and `warmup_started_at` for this; whether the ramp is
needed is a question for the operator before Phase 5.

### 4. Section 0 was left unfilled

Sourced from the existing operating doc (real, not guessed):

- `COMPANY_NAME` = Audria
- `WHAT_WE_SELL` = meeting memory — commitments, decisions, context
- `TIMEZONE` = Asia/Kolkata ops, America/New_York sending
- ICP = Seed–Series B US founders with a physical US office

**Not guessed, left blocking:** `PHYSICAL_ADDRESS`, `SENDING_DOMAINS`,
`MAILBOXES_PER_DOMAIN`, `SENDS_PER_MAILBOX_DAY`, `HUBSPOT_PORTAL_ID`,
`DRIVE_SEQUENCE_FOLDER`. `/capacity` reports `not_configured` rather than a
fabricated number, and `Settings.require_physical_address()` raises.

---

### 5. Signal provider: manual only

**Chosen by the operator, 2026-08-03.** There is no official API for searching
public LinkedIn posts; every route is a scraper or a reseller of one, and
routing via a third-party actor moves the mechanics of the ToS breach, not the
breach. Manual paste-in works from day one, costs nothing, and carries no risk.

The `SignalProvider` interface still defines `x_api` and `apify` so either can
be added later without rework. The Apify provider **refuses to load without an
explicitly configured `APIFY_ACTOR_ID`** — verified: `load_settings()` raises
when `SIGNAL_PROVIDER=apify` and no actor id is set. A token alone can never
self-enable scraping.

This is also consistent with the reasoning already recorded in
`docs/audria-x-growth-operating-doc.md` §8: Audria is a trust product sold to
founders in a small, well-connected market, and the commercial cost of being
identified as running a scraper exceeds the value of the signals.

### 6. Companies are upserted by search-then-write, not batch upsert

**Constraint:** HubSpot's batch upsert matches on an `idProperty`, which must be
a property created with `hasUniqueValue: true`. HubSpot's native `domain` is not
one. So batch upsert by domain is not available.

**Options considered:** spend one of the five free-tier custom property slots on
a company dedup key, or read-then-write per company.

**Built:** read-then-write. `find_company_by_domain` searches, then PATCHes an
existing id or POSTs a new record. Companies are low-volume relative to contacts
— at 135 leads/day most share companies already seen — and the property budget
is worth more than the requests. A failure on one company is recorded and the
rest of the batch continues.

Contacts *do* use batch upsert, keyed on `apollo_person_id` with
`hasUniqueValue: true`. That is exactly why the property exists: HubSpot's native
key is email, which is absent for every lead we have not paid to reveal.

### 7. The retry policy distinguishes "unknown" from "rejected"

**Spec (§8):** "Mutating calls are never retried."

**Built, more precisely:**

| Situation | Mutating | Read |
|---|---|---|
| Timeout / connection error | **never retried** | retried |
| Explicit `429` | **retried** | retried |
| `5xx` | **not retried** | retried |
| `4xx` other than 429 | not retried | not retried |

**Why the refinement:** a timeout means the request may have landed — that is
the case the spec's rule protects, and it is preserved exactly. A `429` is the
server stating it did *not* process the request, which is a different fact.
Treating them identically means either double sends (if you retry both) or
failing on ordinary rate limiting (if you retry neither). `5xx` stays
un-retried for mutations because a 500 can follow a partial write.

Verified with a fake transport: a timeout on a mutating call is attempted
exactly once; a 429 on a mutating call is retried and succeeds.

### 8. Unsigned webhooks are refused, including when no secret is set

The receiver is an internet-reachable write path into the CRM mirror. When
`HUBSPOT_WEBHOOK_SECRET` is unset it returns 401 with an explanation rather than
accepting unsigned requests. "Accept everything in dev" is how an
unauthenticated write endpoint reaches production.

Signature verification is HubSpot v3: `HMAC-SHA256(secret, METHOD + URI + raw
body + timestamp)`, base64, compared with `hmac.compare_digest`. Requests
outside a five-minute window are rejected in **both** directions — a future
timestamp is refused too, since otherwise a captured signature has an unbounded
lifetime.

The raw request body is signed, not re-serialised JSON. Re-serialising changes
key order and whitespace, and the signature stops matching for reasons that look
like a HubSpot bug.

**Verified live against Postgres:** a repeated delivery of the same
`hubspot_event_id` stores nothing and leaves the row count at 1. Dedup is
`ON CONFLICT DO NOTHING` on a unique index, not lookup-then-insert — two
concurrent retries would both pass a lookup.

### 9. Field ownership between HubSpot and the pipeline

A documented rule, not a race:

- **HubSpot wins** for anything a rep edits by hand: owner, native pipeline
  stage, notes, and corrections to name/title/email.
- **We win** for anything the pipeline computes: `priority_score`,
  `seed_lifecycle_stage`, `latest_funding_stage`, `office_signal`.
- A rep edit to a pipeline-owned field is **recorded and surfaced**, not silently
  applied and not silently overwritten.

Enforced in mapping by omitting unknown values rather than sending empty
strings — an empty string overwrites a correction a rep made by hand.

`lifecyclestage` is reserved by HubSpot with its own vocabulary (subscriber,
lead, MQL, SQL, opportunity, customer, evangelist). Writing it raises
`ReservedPropertyError` naming `seed_lifecycle_stage` as the alternative, rather
than corrupting a rep-facing field.

---

## Schema decisions

**Funding stage is nullable and NULL means "not enriched."** It does not mean
"no funding." The ICP evaluator returns `PENDING` for it. There is a test whose
entire job is to fail if someone later makes unknown stage a hard filter —
that change made every sourced lead in a previous build un-enrollable.

**The approval gate is a CHECK constraint**
(`campaigns_approval_gate`): `status <> 'active' OR (approved_by IS NOT NULL AND
approved_at IS NOT NULL AND launched_at IS NOT NULL)`. Verified live: an INSERT
of an active campaign without an approver is rejected by Postgres.

**CAN-SPAM is a trigger, not a CHECK.** A CHECK constraint cannot reference
another table, and compliance lives on `sequence_versions`. The trigger raises
on any attempt to move a campaign to `approved` or `active` with non-compliant
copy. Verified live: the INSERT fails with a `CAN-SPAM:` message. Drafting
non-compliant copy is still allowed — the gate is on activation, not authoring.

**`variant_label` is denormalised onto `campaign_leads`.** This is the §1.4 bug
made structurally hard to reproduce: a variant filter must narrow the **lead**
scope, because replies attach to leads and not to events. Filtering only events
credits every variant with every other variant's replies. With the label on the
lead row, the natural query is the correct one.

**`office_signal` requires evidence** (`companies_office_signal_needs_evidence`):
any value other than `unknown` needs a non-empty evidence array. An office
signal with no evidence behind it is not auditable and will quietly become
folklore.

**`mailboxes.daily_cap` is capped at 50** in the schema. Cold mailboxes die
above roughly that, and a limit that lives only in a config comment gets raised
by whoever is in a hurry.

**Partial unique indexes throughout**, because `apollo_person_id`, `email`, and
`hubspot_contact_id` are all genuinely absent on some rows and NULL must not
collide with NULL. Email and domain uniqueness are on `lower(...)` — verified
live that `Jane@Acme.com` and `jane@acme.com` collide.

**Advisory locks, not a locks table.** An advisory lock dies with its
connection. A row left by a crashed 3am job blocks every later run until a human
notices. `lock_key()` uses `zlib.crc32`, not `hash()` — Python's `hash` is
salted per process, so the same job name would produce a different key in each
container.

---

## Interface decisions

**Job bodies receive their engine through `JobContext`.** §1.8's trap: a
framework whose `execute_job(engine=…)` governs only locking and bookkeeping,
while the job body reaches for a global session, writes to a different database
than it reports. There is deliberately no module-level engine or session in
`app/db.py`, so a job body cannot reach one. The heartbeat job reads through
`ctx.session()` specifically so this regression surfaces immediately.

**Mutating calls are never retried.** `with_retries(mutating=True)` disables
retries entirely rather than reducing them. A timeout tells you nothing about
whether the write landed, and a duplicate campaign or double send is worse than
a failed request. Backoff uses full jitter — without it, every client that
failed together retries together.

**`app/domain/` imports no ORM and no HTTP client.** Scoring, statistics,
sequence parsing and API clients all operate on plain dataclasses. Enforced by
the fact that the domain tests run with no database at all.

---

## Environment limitations found during this build

**PyPI is blocked by this session's egress policy** (403 from `pypi.org` and
`files.pythonhosted.org`, both direct and through the agent proxy). Consequence:
`fastapi`, `sqlalchemy`, `psycopg`, `apscheduler`, `scipy` and `pytest` could
not be installed, so **`pytest` was never executed in this environment.**

What was verified instead, and how:

- **Migrations and every schema constraint** — against a live local
  Postgres 16.13, applying the `.sql` files with `psql` directly. Up, down, and
  up again all clean; 21 tables created, zero objects left behind on reverse.
  All 20 constraint cases behaved correctly.
- **All pure domain logic** — 52 assertions covering ICP evaluation, title
  normalisation, the 90-day cap, subdomain suppression, signal decay, capacity
  arithmetic and dedup keys, run directly against the modules (`pyyaml` is
  present in the system Python). All 52 pass.

The `pytest` suite in `tests/` is written and mirrors those assertions exactly,
but **its first real run will be on a machine with PyPI access.** Treat the
Phase 1 checkpoint as verified for the schema and the domain logic, and as
*unrun* for `tests/test_schema.py` and `tests/test_migrations.py` as pytest
files — their content was executed as SQL and as plain Python respectively.

`docker compose build` was likewise not executed here, for the same reason: the
image build installs from PyPI.
