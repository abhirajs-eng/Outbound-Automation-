# Runbook

Operational procedures for the GTM outbound system. For the X/Twitter growth
routine see `docs/audria-x-growth-operating-doc.md` — different system, same repo.

---

## Stop everything, fast

**Read this first, before you need it.**

> **Stopping the scheduler does not stop in-flight sends.** Smartlead holds the
> campaign and its schedule. Killing our scheduler stops us *enrolling* and
> *syncing*; it does not stop a single email that Smartlead has already queued.
> **Pause at the provider first, always.**

Order matters:

1. **Pause at Smartlead.** Log into the Smartlead dashboard and set every
   running campaign to PAUSED. This is the only action that stops mail leaving.
   By API: `PATCH /campaigns/{id}/status {"status": "PAUSED"}`.
2. **Then stop our scheduler:** `docker compose stop scheduler`.
3. **Then mark it locally** so nothing re-enrolls when the scheduler restarts:
   set the campaign `status` to `paused` with a `paused_reason`.
4. Leave the app and database running — you will want them to diagnose.

If step 1 fails (Smartlead down, credentials rejected): **say so loudly, do not
proceed quietly.** Escalate to a human immediately and disable the mailboxes at
the mailbox provider if the campaign is actively harmful. A failed provider
pause that gets logged and forgotten is how a bad campaign runs all weekend.

Nothing auto-resumes. Ever. Resuming is a human action.

---

## Alerts

### `bounce_rate > 3%` — circuit breaker, auto-pause

**Meaning:** sending domain reputation is actively being damaged. Bounces are
the fastest way to burn a domain.

**Automatic:** the campaign is paused locally, then at the provider. If the
provider call fails the alert escalates rather than silently retrying.

**Do:**
1. Confirm the pause actually landed at Smartlead. Do not trust the local state.
2. Look at *which* leads bounced — cut by sending domain, mailbox, and lead
   sourcing date. A spike concentrated in one mailbox is a mailbox problem; a
   spike concentrated in leads revealed months ago is a stale-email problem.
3. Every hard bounce must already be in `suppressions`. Verify the count matches.
4. Do not resume until the cause is identified. Bounce rate does not recover on
   its own.

**Most likely cause:** emails revealed long before use. This is exactly why
reveal happens at enrollment — if bounces spike, check whether something started
revealing early.

### `spam_complaint_rate > 0.5%` — circuit breaker, auto-pause

**Meaning:** more serious than bounces. Complaints affect every domain you send
from, and recovery takes weeks.

**Do:** pause everything, not just the offending campaign. Read the actual copy
being sent. Check the unsubscribe link works — a broken unsubscribe converts
opt-outs into complaints. Do not resume without a copy change.

### Apollo returns nothing

**Not automatically an incident.** Work through in order:

1. **Is a facet exhausted?** Each filter set caps at 50,000 records (100/page ×
   500 pages). Check `source_cursors` for `pages_exhausted = true`. If the
   active facet is exhausted, rotation is the fix, not a retry.
2. **Are the filters too tight?** Tight filters are correct — they are what keeps
   celebrities, nonprofits and VC funds out. Loosen deliberately and one facet at
   a time, not by removing several at once.
3. **Is the API up?** Check `job_runs` for the error text.
4. **Credit ceiling hit?** `APOLLO_CREDIT_CEILING_PER_RUN` (default 200) aborts a
   run rather than overspending. This looks like "returned nothing" in a summary
   but appears clearly in `job_runs.error`. Raising it is a deliberate act, and
   above 200 credits it needs a human decision.

**Do not** respond to an empty search by widening filters automatically. Silent
widening is how the lead list fills with people nobody wants to email.

### A signal provider breaks

**Manual provider:** cannot break — it is a human pasting a URL and text. If the
form errors, that is an app bug.

**X API:** check the bearer token and the current pricing tier. Recent-search is
a paid feature and access changes.

**Apify:** check `APIFY_ACTOR_ID` is still set and the actor still exists. **The
provider refuses to load without an explicitly configured actor id** — a token
alone must never be enough to turn scraping on. If the actor vanished, that is a
decision point for a human, not something to swap around.

**In all cases:** signals are a prioritisation input, not a gate. A broken signal
provider degrades ordering; it does not stop outbound. Do not treat it as urgent.

### Job failing repeatedly

```sql
SELECT job_name, status, started_at, error
FROM job_runs
WHERE status = 'failed'
ORDER BY started_at DESC
LIMIT 20;
```

`skipped_locked` is **not** a failure — it means another runner held the advisory
lock. Frequent skips mean a job is running longer than its interval.

### Campaign will not activate

Two gates, both deliberate, both database-level:

- `campaigns_approval_gate` — no approver or no launch timestamp. Someone tried
  to activate without going through the review screen.
- `CAN-SPAM: sequence_version N lacks unsubscribe and/or physical address` — the
  copy is missing a working unsubscribe or the postal address. **Check
  `PHYSICAL_ADDRESS` is set in `.env`.** It has no default by design.

Neither is a bug. Do not work around either by writing directly to the database.

---

## Routine operations

### Run a job by hand

```bash
docker compose exec scheduler python -c \
  "from app.jobs.registry import run_job; from app.db import build_engine; \
   from app.config import get_settings; \
   print(run_job('heartbeat', build_engine(get_settings().database_url)))"
```

Advisory locking means this is safe while the scheduler is running — it returns
`skipped_locked` rather than double-running.

### Migrations

```bash
docker compose run --rm migrate python -m tools.migrate status
docker compose run --rm migrate python -m tools.migrate up
docker compose run --rm migrate python -m tools.migrate down --steps 1
```

The whole run holds an advisory lock, so two containers booting together cannot
interleave.

### Check capacity against the sourcing target

```bash
curl -s localhost:8000/capacity | python -m json.tool
```

`"status": "oversourcing"` means the daily target exceeds what can be mailed.
The backlog does not sit still — leads decay while they wait. Fix by raising
capacity, lowering the target, shortening the sequence, or adopting an explicit
staleness policy. Not by ignoring it.

`"status": "not_configured"` means the mailbox numbers are not in `.env` yet.
That is a real state, not an error — no number is invented to fill it.

### Health

```bash
curl -s localhost:8000/health | python -m json.tool
```

Returns 503 only when the database is unreachable. Missing credentials and a
missing physical address show as `false` in the response without failing the
check — they block specific work, not the service.

---

## Things that are true and easy to forget

- **Suppression is enforced globally, in our code, before enrollment.** Never
  per-campaign, never only at the provider. HubSpot's opt-out is a *mirror* for
  reps to see, not the authority.
- **Domain suppression covers subdomains.** Blocking `acme.com` blocks
  `jane@careers.acme.com`, and deliberately does not block `notacme.com`.
- **The 90-day frequency cap is checked twice** — at enrollment *and* before each
  step. A sequence spans weeks; a lead can become ineligible mid-flight.
- **Open rate is not available for decisions.** Apple MPP and corporate scanners
  auto-open. It is absent from the metrics object entirely.
- **Meetings booked is a guardrail, not a decision metric.** It needs roughly 4×
  the sample of positive-reply rate.
- **Never route 100% of traffic to the incumbent.** Hold ~30% for a challenger.
- **Kill losers fast, crown winners slowly.** A variant with 0 conversions in 400
  delivered is confidently bad within days. A variant that looks 2× better at
  n=200 is not a winner — that clears a 0.95 Bayesian threshold on noise alone.
