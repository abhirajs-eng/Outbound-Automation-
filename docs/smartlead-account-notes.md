# Smartlead account — conventions and house style

Pulled live 2026-08-03 via `scripts/smartlead_dump.py`. Raw export in
`docs/smartlead-export/`. This file is the readable version: how the existing
campaigns are built, so new sequences can match.

## Access

Working. `SMARTLEAD_API_KEY` in the environment authenticates against
`https://server.smartlead.ai/api/v1`.

- Auth is **query param only** (`?api_key=…`). `Authorization: Bearer` and
  `x-api-key` are both rejected with `API key is required.`
- The API **rejects unknown query params** with a 400 (`"_cb" is not allowed`),
  so cache-busters can't be added. Note this: a proxy between here and Smartlead
  caches GETs, and a stale hit is indistinguishable from a live one by status
  code alone. Verify freshness by content, not by HTTP 200.
- Cloudflare 403s urllib's default user-agent (`error code: 1010`). Send an
  ordinary UA — the dumper does.
- `api.smartlead.ai` is not reachable from this environment; use
  `server.smartlead.ai`.

## The three campaigns

`FINAL Qualifiers 1` (3650607), `2` (3650609), `3` (3650610). Created within ~7
seconds of each other on 2026-07-16, all still **DRAFTED**, nothing ever sent.

They are three angles on one motion, not three campaigns:

| | Step 1 hook | Angle |
|---|---|---|
| **1** | "the things you agreed to this week" | Commitments lost during the day |
| **2** | "what you decided three weeks ago" | Decisions/reasoning lost over months |
| **3** | "does ChatGPT know {{company_name}}?" | Your AI can't see what wasn't written down |

Step 3 is shared near-verbatim across all three (the "900 comments" teardown),
with Campaign 1 and 2 running an identical condensed version and Campaign 3 a
longer one. So the variation is concentrated in steps 1–2; the closer is fixed.

## Sequence structure — identical in all three

Three steps, `0 / +3 / +4` days:

| Step | Delay | Subject | Length | Job |
|---|---|---|---|---|
| 1 | day 0 | lowercase, specific | ~5 short paragraphs | Problem → product → proof → CTA |
| 2 | +3 days | **empty** | ~3 paragraphs | One idea, then out |
| 3 | +4 days | lowercase | ~7 paragraphs | Research teardown, longest of the three |

**Step 2's subject is an empty string on purpose** — that makes Smartlead send it
as a reply on the existing thread rather than a new email. Keep this. It's the
single most important structural convention here.

No variants anywhere (`seq_variants: []`, `variant_distribution_type: null`). No
A/B testing configured. No spintax.

## Voice rules, as practised

Consistent enough across nine emails to treat as house style:

- **Lowercase subjects**, no title case, no punctuation. Fragments, not
  sentences: `the things you agreed to this week`.
- **No em-dashes anywhere in nine emails.** Sentences are split with full stops
  instead. Deliberate — match it.
- **Numbered points are spelled out as sentences** — "One. Transcription is
  finished as a business." Never `1.` or bullets. Every body is `<p>` tags only:
  no lists, no bold, no headers.
- **Openers name the reader's situation, never the sender.** No email begins
  with "I'm the founder of…". The product arrives in paragraph 2 or 3.
- **Follow-ups announce their own end**: "one thought and then I will leave it",
  "last one from me". Both steps 2 and 3 do this.
- **Contractions are avoided** — "I will", "it is", "does not", "you are".
  Uniform across all nine.
- **Concrete numbers over adjectives**: "900 comments", "60 meetings for under
  two dollars", "around a hundred of these apps", "first hundred get three
  months free".
- **One CTA, same link every time**
  (`https://forms.gle/u9ceJKnBgDN5FuNE8`), phrased softly on follow-ups: "a spot
  on the early access list is here if it is useful".
- Personalisation is only `{{first_name}}` and `{{company_name}}`. Nothing
  deeper — no custom variables, no lead-level fields.

## Signature

Every one of the nine steps ends with `<p>%signature%</p>`. The signature is not
in the sequence; Smartlead substitutes it per sending mailbox. So the sequence
body is mailbox-agnostic and the signature is configured on the email account.

**This is currently broken — see below.**

## Campaign settings — identical in all three

The house pattern. Match it unless there's a reason not to.

| Setting | Value |
|---|---|
| `scheduler_cron_value.tz` | `America/Los_Angeles` |
| `days` | `[1,2,3,4,5]` — weekdays |
| `startHour` → `endHour` | `09:30` → `11:30` |
| `max_leads_per_day` | `10` |
| `min_time_btwn_emails` | `10` (minutes) |
| `stop_lead_settings` | `REPLY_TO_AN_EMAIL` |
| `follow_up_percentage` | `100` |
| `send_as_plain_text` | `false` |
| `track_settings` | `[]` |
| `unsubscribe_text` | `null` |

## Mailboxes

18 connected, all `warmup_status: ACTIVE`, reputation 99–100%, SMTP and IMAP
both verified, `message_per_day: 15`, and **`total_sent_count: 0`** — warmed but
never used for real sending.

Two domains: `@getaudria.com` (9) and `@audriahq.com` (9).

At 18 mailboxes × 15/day the ceiling is 270/day, while campaigns cap at 10
leads/day. The mailbox pool is sized far beyond current campaign config.

## Four things to fix before anything sends

1. **No mailboxes are attached to any campaign.** All three return zero from
   `campaigns/{id}/email-accounts`. This alone blocks sending, and is likely why
   they're still DRAFTED.
2. **15 of 18 mailboxes have `signature: null`**, yet all nine steps end in
   `%signature%`. Only `charles@`, `savannah@`, and `kelly@` have one, and each
   is a bare first name (`'Charles'`). If a null-signature mailbox sends, that
   token resolves to nothing and leaves a stray empty paragraph — or worse,
   renders literally. Set signatures on every mailbox that will send, or drop
   the token.
3. **`track_settings: []` means open and click tracking are both ON.** Nothing
   is disabled. The pixel and link rewriting both cost deliverability, and at 10
   leads/day there is no volume to spare. This is an unset default, not a
   choice — worth making it one.
4. **`unsubscribe_text: null`** — no unsubscribe footer on any campaign. Decide
   this deliberately before the first send.

## Refreshing

    python3 scripts/smartlead_dump.py --out docs/smartlead-export

Read-only; makes no writes to the account. The export carries no credentials.
