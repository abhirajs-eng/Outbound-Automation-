---
name: gtm-outbound
description: Run the GTM outbound cycle — source ICP founders from Apollo, qualify and reveal at enrollment, sync to HubSpot, build and launch a Smartlead campaign, and pull stats back. Use when the user asks to run outbound, source leads, build or launch a campaign, sync HubSpot, or check campaign performance, or invokes /gtm-outbound.
---

# GTM outbound cycle

Operationalises the outbound system in this repo. Read `config/icp.yaml` before
sourcing anything — it is the single ICP definition and there is no second copy.
`DECISIONS.md` records every verified API contract and every place a reasonable
assumption turned out wrong; read it before designing around an API.

**This skill is interactive.** MCP connectors require a live session, which is
exactly right here and exactly wrong for a 6am cron. Scheduled jobs use REST
with keys (`app/adapters/`). Never wire an MCP call into the scheduler.

---

## The three numbers that govern every run

Check all three at the start. They change, and the binding one is rarely the
one people expect.

| | Current | Source |
|---|---|---|
| **Send capacity** | 135 leads/day | 18 warmed mailboxes × 30/day ÷ 4 steps |
| **Apollo credits** | ~25–36 leads/day | `apollo_usage_stats_credit_usage_stats` ÷ days left in cycle |
| **Sourcing target** | whichever is lower | — |

**Apollo credits are the binding constraint, by roughly 4×.** Running at send
capacity burns a full monthly credit allowance in about five days. The daily
target is `min(send capacity, credit budget)` — never send capacity alone.

Recompute the credit line every run:

```
credits_left / days_left_in_cycle / ~3 credits per mailable lead
```

~3 credits per mailable lead = 1 email reveal + funding-stage enrichment across
the companies that fail the stage check. It moves with the ICP hit rate; if
observed hit rate drifts, recompute rather than reusing this number.

---

## Routine

### 1. Preflight

- `apollo_usage_stats_credit_usage_stats` → credits left, cycle end date.
- Compute today's target per above. **State it out loud with the arithmetic**
  before sourcing. If the target is below 10/day, say so and stop — that is a
  budget conversation, not a sourcing run.
- Confirm suppressions are current. Suppression is authoritative in Postgres and
  enforced **globally before enrollment**, never per-campaign.

### 2. Source — free, so cast wide

`apollo_mixed_people_api_search` with the filters from `config/icp.yaml`
`apollo_search` and `hard`. **Verified 2026-08-03: this call costs 0 credits**
(checked by bracketing a search with credit reads).

Set both `person_locations` **and** `organization_locations`. Setting only the
organization one returns employees worldwide, and you pay for that later when
you enrich them.

**What comes back** — verified live, not from docs:

```
id, first_name, last_name, title, linkedin_url, last_refreshed_at,
organization: { id, name, domain }
```

**No email. No location. No employee count. No funding stage.** Do not plan to
filter locally on fields the response does not contain.

**Facet rotation is mandatory, not an optimisation.** The standard ICP filter
set returns `total_entries: 49,416` against a hard 50,000 display cap
(100/page × 500 pages) — it is at 99% of the ceiling on day one. Rotate a facet
(keyword tag, employee range, founded year band) per run and track position in
`source_cursors`. Without rotation you re-read the same first pages forever.

Persist every result immediately, marked **stage-unknown**. Costs nothing.

### 3. Score and rank

Score with `app/domain/icp.py` — title fit, office signal, decayed activity
signals. Rank descending. Everything downstream costs money and works top-down,
so ordering *is* the budget allocation.

### 4. Qualify — 1 credit per company

Only for leads about to be mailed, highest priority first, in batches of 10
(`apollo_organizations_bulk_enrich`, max 10 domains/call).

**Before calling, say this to the user verbatim — do not paraphrase, and state
the real counts:**

> This will enrich [N] companies and consume up to [N] credits (1 credit per
> match, no charge for unmatched). Do you want to proceed?

Then apply `config/icp.yaml` `enrichment.funding_stage`:
- Seed / Series A / Series B → qualified
- Series C and later → disqualified
- **Still unknown → pending, never a hard fail.** A previous build hard-failed
  on unknown stage and every sourced lead became un-enrollable.

### 5. Reveal emails — at enrollment only, never earlier

`apollo_people_bulk_match` (max 10/call), passing the `id` from search.

Emails bought months before use bounce more, and bounces burn sending domains.
This is the single rule most worth holding: if bounce rate ever spikes, the
first thing to check is whether something started revealing early.

Last names may be masked on some plans. That does not block enrichment — pass
the `id` and carry on.

### 6. Push to HubSpot

Contacts batch-upsert on `apollo_person_id`; companies are matched by domain.
Five custom properties, no more — the Free tier caps at ~10 and a sixth is a
decision, not a convenience.

- **Never write `lifecyclestage`.** It is reserved with HubSpot's own vocabulary.
  Ours is `seed_lifecycle_stage`.
- **Omit unknown values; never send empty strings.** An empty string overwrites
  a correction a rep made by hand.
- Field ownership: HubSpot wins for rep edits (owner, pipeline stage, notes);
  we win for computed fields (`priority_score`, `seed_lifecycle_stage`,
  `latest_funding_stage`, `office_signal`).
- Mirror suppressions to HubSpot's opt-out so reps can see them. Postgres stays
  authoritative — enrollment never consults HubSpot for suppression.

### 7. Build the Smartlead campaign

Base `https://server.smartlead.ai/api/v1`, auth via `?api_key=` **query param**.

```
POST   /campaigns/create                {name}
POST   /campaigns/{id}/sequences        FULL REPLACE, not a merge
POST   /campaigns/{id}/email-accounts   {email_account_ids: [int]}
POST   /campaigns/{id}/leads            {lead_list: [...], settings: {}}
POST   /campaigns/{id}/schedule         {timezone, days_of_the_week, ...}
PATCH  /campaigns/{id}/status           {status: START|PAUSED|STOPPED}
```

- `/sequences` is a **full replace**. Send every step, or you silently delete
  the ones you left out.
- Use **in-campaign step variants** for A/B tests — same audience, same
  mailboxes, same weeks. Cross-campaign comparisons are confounded and not worth
  running.
- **Unresolved:** the per-step variants array appears as both `seq_variants` and
  `variants` in the docs. Send `seq_variants`, log the response, and **confirm
  with one live call before the first launch.** The wrong field name gives you a
  campaign with no copy.
- **Never retry a mutating call through a timeout.** Duplicate campaigns and
  double sends are worse than a failed request.

### 8. Approval gate — a human launches, always

Create the campaign **paused**. Present for review:

- the rendered emails for **5 real leads from the segment** (real merge values,
  not placeholders)
- recipient count, mailboxes, daily volume
- the capacity and credit arithmetic from step 1

A campaign cannot go active without a recorded approver and launch timestamp —
that is a database CHECK constraint, not a convention, and it will reject the
write. CAN-SPAM compliance is a trigger: no unsubscribe or no physical address
means activation raises, not warns.

### 9. Pull stats back

```
GET /campaigns/{id}/statistics
GET /campaigns/{id}/analytics-by-date     MAX 30-DAY SPAN — chunk requests
GET /campaigns/{id}/leads/{lead_id}/message-history
```

Metric definitions, all **per lead, not per email** — a lead who gets 4 emails
and replies once is 1 reply / 1 delivered lead:

```
delivered      = sent - bounced
reply_rate     = replied_leads / delivered_leads
positive_rate  = positive_replies / delivered_leads
```

- **Exclude bounced leads from the denominator.** They were never reachable.
- **A variant filter must narrow the LEAD scope, not just the event scope.**
  Replies attach to leads, not events. Filtering only events credits every
  variant with every other variant's replies, silently corrupting the exact
  number winner detection reads.
- **Open rate is not available for decisions.** Apple MPP and corporate scanners
  auto-open it. It is absent from the metrics object deliberately.

---

## Winner detection — the part that is easy to get wrong

At ~30 leads/day, copy tests take months. Say so with a number rather than
"not enough data yet".

- Detecting **2% → 3%** positive-reply at 80% power needs **3,825 delivered per
  variant** (verified by computation, not quoted). At 30/day split two ways that
  is well over a year.
- A "200 delivered, 8 positive" floor can only detect **4% → 11.5%**. Nothing in
  cold email copy does that.
- At n=200, 8 vs 16 conversions gives **P(B>A) = 0.952** — it *clears* a 0.95
  Bayesian threshold on noise alone. **The minimum-sample gate is not redundant
  with the statistics; it is the only thing stopping that false winner.**

So: require a frequentist test **and** a Bayesian one **and** the sample gate to
agree. Report credible intervals, never bare point estimates. **Kill losers
fast, crown winners slowly** — a variant with 0 conversions in 400 delivered is
confidently bad within days, and futility detection is where nearly all the
value is at this volume. Never route 100% to the incumbent; hold ~30% for a
challenger.

---

## Hard boundaries

- **Never spend credits without the verbatim confirmation** in step 4, with real
  counts. Never exceed 200 credits in a run without a fresh explicit approval —
  and if an estimate turns out 20× low, stop and re-confirm rather than
  proceeding on stale approval.
- **Never launch a campaign.** Create paused, present for review, let a human
  press go. `AUTO_LAUNCH_CAMPAIGNS` defaults to no.
- **Never send an email from this skill.** Sending happens in Smartlead, after a
  human launch.
- **Never fabricate.** No mock leads, no seeded stats, no placeholder numbers. If
  a source is not wired up, say which phase it arrives in. Distinguish "not
  evaluated" from "evaluated to zero" — a column of zeros reads as a measurement.
- **Never reveal emails outside enrollment.**
- **Never write `lifecyclestage`.**
- **Never bypass suppression, the 90-day frequency cap, or the approval gate** by
  writing directly to the database.
- **Do not build a LinkedIn scraper.** There is no official API for searching
  public LinkedIn posts; every route is a scraper or a reseller of one, and
  routing through a third-party actor moves the mechanics, not the breach. The
  signal provider is manual — chosen deliberately, recorded in `DECISIONS.md` §5.

## Stopping fast

If anything looks wrong mid-run: **pause at Smartlead first.** Stopping the
scheduler does not stop in-flight sends — Smartlead holds the queue. Full
procedure in `RUNBOOK.md`.
