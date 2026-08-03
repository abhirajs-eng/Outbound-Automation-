# Smartlead account — observed conventions

Captured 2026-08-03 from a single successful `GET /api/v1/campaigns` call before
the account's plan lapsed. **Facts observed from the account only** — no inferred
best practices. Sequence bodies and signatures are not in here because the
endpoints that serve them were already returning `Plan expired!` (see below).

## Access status

The `SMARTLEAD_API_KEY` in the environment is **valid** — it returned real
account data once. Every call after that returns `HTTP 401 {"message":"Plan
expired!"}`, including a verbatim repeat of the call that succeeded. This is a
billing state, not an auth problem.

Verified while probing:

- Auth is **query param only** (`?api_key=…`). `Authorization: Bearer` and
  `x-api-key` headers both return `API key is required.`
- Base host is `server.smartlead.ai`. `api.smartlead.ai` is not reachable from
  this environment (proxy returns 403 on CONNECT).
- Cloudflare fronts the API and 403s any request with urllib's default
  user-agent (`error code: 1010`). Send an ordinary UA.

Blocked endpoints (all `401 Plan expired!`): `campaigns`, `campaigns/{id}`,
`campaigns/{id}/sequences`, `campaigns/{id}/email-accounts`,
`campaigns/{id}/statistics`, `email-accounts`, `client/`.

## Campaigns

Three campaigns, all created within ~7 seconds of each other on 2026-07-16,
all still `DRAFTED` — nothing has ever sent.

| ID | Name | Status |
|---|---|---|
| 3650607 | FINAL Qualifiers 1 | DRAFTED |
| 3650609 | FINAL Qualifiers 2 | DRAFTED |
| 3650610 | FINAL Qualifiers 3 | DRAFTED |

The near-identical timestamps and the `Qualifiers 1/2/3` naming suggest three
parallel variants of one motion rather than three independent campaigns.
Unconfirmed until the sequences are readable.

## Settings — identical across all three

This is the house pattern; a new campaign should match it unless there's a
reason to diverge.

| Setting | Value | Reading |
|---|---|---|
| `scheduler_cron_value.tz` | `America/Los_Angeles` | |
| `scheduler_cron_value.days` | `[1,2,3,4,5]` | Weekdays only |
| `startHour` / `endHour` | `09:30` → `11:30` | A 2-hour morning window |
| `max_leads_per_day` | `10` | Deliberately low volume |
| `min_time_btwn_emails` | `10` | Minutes — ~12 sends/hr ceiling |
| `stop_lead_settings` | `REPLY_TO_AN_EMAIL` | Stops the sequence on any reply |
| `follow_up_percentage` | `100` | All leads get follow-ups |
| `send_as_plain_text` | `false` | HTML send |
| `enable_ai_esp_matching` | `false` | |
| `track_settings` | `[]` | **Open and click tracking both on** |
| `unsubscribe_text` | `null` | No unsubscribe footer set |
| `client_id` / `parent_campaign_id` | `null` | Not whitelabelled, not a subcampaign |

Two notes on that table, since both are load-bearing and neither is settled:

- `track_settings: []` means nothing is disabled — open and click tracking are
  **on**. Open tracking injects a pixel and click tracking rewrites links, both
  of which cost deliverability. The empty array is a default, so this reads as
  never-configured rather than chosen.
- The 10 leads/day cap and reply-stop pair cleanly with the volume argument in
  `daily/2026-07-28.md` ("40 emails/day, 2% reply → 12/day hand-checked, 19%").
  Consistent with the stated thesis.

## Not yet known

Everything about the actual writing. Sequence step count and delays, subject
lines, body copy, spintax, variant/A-B structure, personalisation variables,
signature block and whether it's per-sequence or per-mailbox, sending mailboxes,
domains, and warmup health.

## Refreshing this file

    export SMARTLEAD_API_KEY=…
    python3 scripts/smartlead_dump.py --out docs/smartlead-export

Dumps settings + sequences + mailboxes per campaign. Read-only. Currently exits
non-zero on the expired plan; it will run clean once the subscription renews.
