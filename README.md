# Outbound Automation — Audria

Two systems, one repo:

| | What it does | Where |
|---|---|---|
| **[GTM outbound](#gtm-outbound)** | Sources ICP founders from Apollo, syncs them to HubSpot, sends sequences through Smartlead, measures what works | `app/`, `migrations/`, `config/` |
| **[X/Twitter growth](#xtwitter-growth)** | Daily research and a paste-ready comment queue; a human does all posting | `docs/`, `daily/` |

They share one ICP definition (`config/icp.yaml`) and nothing else.

## Running either one

```
/gtm-outbound     source, qualify, sync, build a campaign, pull stats
/audria-daily     research ICP founders, build the X execution queue
```

`/gtm-outbound` drives the cycle interactively through the Apollo and HubSpot
MCP connectors. **Scheduled jobs use REST with keys instead** — MCP needs a live
session and is the wrong transport for a 6am cron.

---

# GTM outbound

**Build status: Phases 1–2 complete** (foundation, HubSpot integration).
Sourcing, sequences, sending, stats, signals and the performance loop are not
wired up yet. Screens for them state which phase they arrive in rather than
showing zeros — a column of zeros reads as a measurement, and nothing has been
measured.

Phase 2's round-trip checkpoint is **unverified**: it needs a private app token,
which is not configured. `GET /hubspot/status` reports exactly which properties
exist and which are missing once one is.

## Architecture

**HubSpot owns people. Postgres owns analytics and orchestration.**

This split is forced, not preferred. The metric layer runs queries like "distinct
leads with a reply event, grouped by variant, excluding mid-flight sequences."
No CRM API serves that at volume — you would paginate thousands of records
through a rate-limited endpoint on every dashboard load.

| HubSpot (system of record, human-facing) | Postgres (analytics + orchestration) |
|---|---|
| Contacts — identity, title, email, LinkedIn | `email_events` (high volume) |
| Companies — name, domain, funding stage, office signal | `replies`, `reply_classifications` |
| Native pipeline stage, owner, notes | `campaigns`, `campaign_leads` |
| Reply activity on the timeline | `sequences` + versions, `signals`, `experiments` |
| | `suppressions` (**authoritative**), `job_runs`, `mailboxes` |

Suppression is authoritative in Postgres because it must be enforced in our code,
globally, before enrollment. It is *mirrored* to HubSpot's native opt-out so reps
can see it.

## How sourcing actually works

Apollo's free people search returns no email, no funding stage and no location.
Both of the fields that decide whether a lead is worth mailing cost credits and
are only obtainable one record at a time. So:

1. **People search (free)** with tight filters → persist immediately, marked
   stage-unknown. Costs nothing.
2. **Enrich for funding stage (1 credit/company)** only at enrollment, on the
   leads about to be mailed, highest priority first.
3. **Reveal email (1+ credits/person)** only at enrollment. Emails bought months
   before use bounce more, and bounces burn sending domains.

Unknown funding stage is **pending qualification, not a hard fail**. A previous
build hard-failed on it and every sourced lead became un-enrollable.

Budget accordingly: at a 25–40% hit rate, 100 stage-verified ICP leads costs
roughly 250–350 credits, not the ~10 a naive plan assumes.

## Setup

```bash
cp .env.example .env      # then fill it in — see below
docker compose up
```

Postgres is published on **5433** so a native install can coexist. Migrations run
in a one-shot `migrate` service that `app` and `scheduler` both depend on, so
they cannot race each other on boot.

- API: http://localhost:8000 — `/health`, `/capacity`, `/jobs`
- Scheduler: its own process, so scaling the web tier does not multiply cron jobs

## Environment variables

Full list with commentary in `.env.example`. The ones that block work when absent:

| Variable | Blocks | Note |
|---|---|---|
| `DATABASE_URL` | everything | |
| `PHYSICAL_ADDRESS` | sequence activation | CAN-SPAM. **Not guessable — do not invent one.** Enforced by a database trigger, not just a warning. |
| `SENDING_DOMAINS`, `MAILBOXES_PER_DOMAIN`, `SENDS_PER_MAILBOX_DAY` | capacity reporting | Until set, `/capacity` reports `not_configured` rather than a made-up number |
| `HUBSPOT_PRIVATE_APP_TOKEN` | Phase 2 | Scopes must include `crm.schemas.*` — those are what allow creating custom properties by API, and they are easy to miss |
| `APOLLO_API_KEY` | Phase 3 | |
| `SMARTLEAD_API_KEY` | Phase 5 | |
| `APIFY_ACTOR_ID` | the Apify signal provider | Required when `SIGNAL_PROVIDER=apify`. A token alone must never self-enable scraping. |

## Capacity arithmetic

```
send capacity               = mailboxes × sends_per_mailbox_day
a 4-step sequence consumes 4 emails per lead
sustainable enrollments/day = capacity ÷ steps
```

**Current configuration: 2 domains, 18 warmed mailboxes.** At 30 sends/mailbox/day
that is 540 emails/day ÷ 4 steps = **135 sustainable enrollments/day**.

Set `TOTAL_MAILBOXES` rather than `MAILBOXES_PER_DOMAIN` when mailboxes are not
split evenly across domains.

### But send capacity is not the binding constraint

Measured 2026-08-03: **2,135 Apollo lead credits, 24 days left in the cycle.** At
~3 credits per mailable lead (one email reveal, plus stage enrichment across the
companies that fail the check), that is **~30 leads/day** — and sourcing at the
full 135/day would burn the entire monthly allowance in about **five days**.

| Credits/lead | Leads left this cycle | Sustainable/day | Runway at 135/day |
|---|---|---|---|
| 2.5 | 854 | 36 | 6.3 days |
| 3.0 | 712 | 30 | 5.3 days |
| 3.5 | 610 | 25 | 4.5 days |

**The daily target is `min(send capacity, credit budget)` ≈ 30/day.** This
inverts the spec's §6 concern — mailing capacity exceeds sourcing budget by more
than 4×, so mailboxes sit idle rather than leads piling up. Resolving it is a
budget decision: raise the Apollo plan or accept ~30/day. Shortening the sequence
raises send capacity but does not touch the credit line, so it does not help.

## Running jobs

```bash
docker compose run --rm migrate python -m tools.migrate status
docker compose run --rm migrate python -m tools.migrate up
docker compose run --rm migrate python -m tools.migrate down --steps 1
```

Jobs are registered in `app/jobs/registry.py`. Jobs from later phases appear
there marked `enabled=False` with the phase they arrive in, so `/jobs` names what
is not running yet instead of showing an empty schedule.

Scheduled jobs use **REST with keys, never MCP** — MCP requires a live agent
session and is the wrong transport for a 6am cron.

## HubSpot setup

1. Settings → Integrations → **Private Apps** → create one. Works on **all
   tiers including Free**. The token is shown **once**.
2. Grant all eight scopes:
   ```
   crm.objects.contacts.read    crm.objects.contacts.write
   crm.objects.companies.read   crm.objects.companies.write
   crm.schemas.contacts.read    crm.schemas.contacts.write
   crm.schemas.companies.read   crm.schemas.companies.write
   ```
   The **`crm.schemas.*`** ones are what allow creating custom properties by
   API. They are easy to miss, and without them property creation fails at
   runtime with a 403 — the adapter catches that and names the missing scope.
3. Put the token in `.env` as `HUBSPOT_PRIVATE_APP_TOKEN`, then:
   ```bash
   curl -s localhost:8000/hubspot/status | python -m json.tool
   docker compose exec scheduler python -c "from app.jobs.registry import run_job; \
     from app.db import build_engine; from app.config import get_settings; \
     print(run_job('provision_hubspot_properties', build_engine(get_settings().database_url)))"
   ```
4. **Webhooks must be configured in the HubSpot UI** — private apps cannot
   create or edit subscriptions by API. Point them at
   `POST /webhooks/hubspot` and set `HUBSPOT_WEBHOOK_SECRET`. Without the
   secret the endpoint returns 401 rather than accepting unsigned requests.

### The five custom properties

Free tier caps custom properties at ~10, so exactly five are used. A sixth is a
decision, not a convenience.

| Object | Property | Why |
|---|---|---|
| Contact | `apollo_person_id` | Dedup key, created `hasUniqueValue` so it can key a batch upsert. HubSpot's native key is email, absent for every unrevealed lead. |
| Contact | `priority_score` | What reps sort by |
| Contact | `seed_lifecycle_stage` | Ours. `lifecyclestage` is reserved by HubSpot with its own vocabulary — writing it raises. |
| Company | `latest_funding_stage` | The ICP criterion |
| Company | `office_signal` | The criterion Apollo cannot filter on |

Everything else (`icp_reasons`, `office_signal_evidence`, `last_emailed_at`,
`do_not_contact`) stays in Postgres. The enrollment layer needs it; HubSpot does
not.

**Custom objects are Enterprise-only and are not used.**

### Field ownership

- **HubSpot wins** for rep edits: owner, native pipeline stage, notes,
  corrections to name/title/email.
- **We win** for computed fields: `priority_score`, `seed_lifecycle_stage`,
  `latest_funding_stage`, `office_signal`.
- Unknown values are **omitted** rather than sent as empty strings — an empty
  string overwrites a correction a rep made by hand.

## Adding an ICP filter

Everything lives in `config/icp.yaml`. There is no second copy in Python.

The three sections are not interchangeable:

- **`hard`** — queryable in Apollo people search. A wrong value disqualifies.
- **`enrichment`** — costs credits, resolved at enrollment. Unknown is *pending*,
  never a fail. **Do not move `funding_stage` into `hard`.**
- **`scored`** — Apollo cannot query it. Contributes to priority, never filters.
  `office_signal` lives here: it is also how you find out whether the criterion
  predicts conversion at all, by slicing reply rates on it.

To add a title, add it to `hard.titles.exact`. Note that `Co-Founder & CEO` and
`Cofounder & CEO` are listed explicitly — without them the most common founder
self-description only matches the partial rule, scores 60, and ranks *below* a
bare "Founder" at 100. There is a test for exactly that.

After editing, run the ICP tests. They are pure — no database needed.

## Tests

```bash
pytest tests/                        # all
pytest tests/test_icp.py             # pure logic, no database
```

Tests run against **real Postgres, never SQLite** — the schema depends on JSONB,
partial unique indexes, CHECK constraints and triggers, none of which SQLite
enforces. A green SQLite suite would be actively misleading.

```bash
docker compose up -d db
createdb -h localhost -p 5433 -U outbound outbound_test
```

Coverage is deliberately concentrated on what rots silently: dedup keys, ICP
logic, metric math against hand-computed values, and winner statistics against
closed-form results.

> **Note:** PyPI is blocked in the environment this was built in, so `pytest`
> itself has never been run here. The schema was verified by applying the
> migrations to a live Postgres 16 and exercising all 20 constraint cases with
> `psql`; the domain logic was verified by running all 52 assertions directly.
> Both passed in full. See `DECISIONS.md` for exactly what was and was not run.

## Documentation

- **`RUNBOOK.md`** — what each alert means, what to do when Apollo returns
  nothing, when bounce rate spikes, and **how to stop everything fast**. Read
  the stop procedure before you need it: stopping the scheduler does not stop
  in-flight sends.
- **`DECISIONS.md`** — every API contract verified with dates, every place the
  spec turned out wrong, every assumption still outstanding.

---

# X/Twitter growth

Operating system for Audria's X/Twitter growth motion: Claude handles research,
qualification, and writing; a human handles all posting, commenting, following,
and DMing.

## Why it's split this way

X's automation rules prohibit non-API scripting of the site, full stop —
regardless of who wrote the content or how well-paced it is. So every action that
touches x.com directly (posting, commenting, following, DMing) stays manual,
always. Own-account *scheduling* is the one exception, and only through an
official-API tool (Typefully/Buffer), never through this repo or a browser agent.
See `docs/audria-x-growth-operating-doc.md` §8 for the full reasoning — it is
deliberate and shouldn't need relitigating each session.

**No automation in this repo ever posts, comments, follows, or DMs on X.** It
only produces text for a human to review and paste.

## Layout

```
docs/
  audria-x-growth-operating-doc.md   the operating doc — source of truth, paste-portable
daily/
  YYYY-MM-DD.md                      one file per day: execution queue + appendix + own-account drafts
.claude/skills/audria-daily/
  SKILL.md                           runs the daily routine on demand (/audria-daily)
```

## Running the daily routine

In a Claude Code session with this repo open:

```
/audria-daily
```

This reads the operating doc, does live research (funding sources, office-signal
queries, handle resolution), and writes `daily/<today>.md` with:
- an ordered, paste-ready execution queue (max 5 entries)
- a research appendix (sources, confidence, exclusions)
- 2–3 own-account draft posts per the content pillars in §7

A human then reviews `daily/<today>.md`, approves/edits/cuts, and executes
manually — pasting comments, and queuing approved own-account posts in Typefully.

### Voice calibration

Own-account drafts are generic until real writing samples are supplied (§7:
"voice calibration is a prerequisite"). Drop 5–10 samples of your unedited
writing (old tweets, Slack messages, emails) into `docs/voice-samples/` and
future runs will use them; until then, drafts are flagged as generic in the
daily file.

## Automation

A scheduled job can run `/audria-daily` each morning and leave the output as a
Gmail draft for review — see the session notes for setup status. It never touches
x.com; it only prepares the file/draft for a human to act on.
