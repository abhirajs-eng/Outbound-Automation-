# Handoff: create three Smartlead campaigns from the HubSpot leads

Paste this whole file into a new session. It assumes no prior context.

---

## The task

A batch of leads was pulled from Apollo and added to HubSpot. Split that batch
into three equal parts and load each part into its own Smartlead campaign,
using the three message arms already written in this repo.

- 25 emails per mailbox per day (**already configured** — do not redo)
- Same sequences as the three existing campaigns
- Equal split across the three arms
- Campaigns must be left **DRAFTED**. Never start a campaign.

Repo: `abhirajs-eng/Outbound-Automation-`, branch
`claude/smartleads-connection-bt3v6w`.

---

## Step 1 — get the leads out of HubSpot

**Read this before querying — one specific mistake already cost a session.**

HubSpot's `search_crm_objects` is backed by a search index that lags recent
writes. A bulk import that landed minutes earlier returns **nothing**, and it
looks exactly like an empty portal. That happened here: a search reported 2
contacts (both HubSpot's stock demo records, `bh@hubspot.com` and
`emailmaria@hubspot.com`) and the conclusion "the leads aren't there" was
reported to the user, who correctly pushed back twice.

So:

- Use **`get_crm_objects`** (the list endpoint, reads records directly), not
  `search_crm_objects`, to confirm what is actually in the portal.
- Only trust a search result that is *non-empty*. An empty one proves nothing.
- Portal is `246941336`, user `kenny.m@audria.tech`. If the leads are not in
  that portal, ask which portal — do not assume they don't exist.
- The `LEAD` object reads as `REQUIRES_ACCOUNT_MODIFICATION` and cannot be
  queried. Leads attach to contacts, so query CONTACT.
- The HubSpot connector was flapping (`enabledInChat` toggling false) all of
  the previous session. If its tools are missing, ask the user to enable
  HubSpot in the chat's connector settings, or to export CSV instead.

Pull at minimum: `email`, `firstname`, `lastname`, `company`, `website`,
`city`. Save as CSV or JSON anywhere in the repo.

**A CSV export from the HubSpot UI works just as well** and avoids the
connector entirely. If the connector is being difficult, ask for that.

---

## Step 2 — create the campaigns

One command. It handles parsing, dedupe, the three-way split, campaign
creation, mailbox attachment and lead upload.

```bash
python3 scripts/smartlead_launch_batch.py --leads <your-file.csv> --suffix "Aug batch"
```

Add `--dry-run` first to see the split without writing anything. Recommended.

`--leads-per-day N` sets how many new leads enter **each** campaign per day
(default 25, so 75/day across the three). See the ramp note below before
raising it.

The script maps common Apollo/HubSpot column names automatically (`Email`,
`First Name`, `Company`, …), drops rows with no email and duplicate emails, and
**splits round-robin rather than into contiguous thirds** — exports arrive
sorted, so chunking would hand one arm all the best leads and make the three
arms incomparable. Do not change this to a chunked split.

It refuses to run if any pool mailbox is missing a signature, because the email
bodies end in `%signature%`.

---

## Step 3 — verify against the live account

Do not trust the script's exit code. Confirm by reading the account back:

```bash
for cid in <the three new ids>; do
  curl -sS "https://server.smartlead.ai/api/v1/campaigns/$cid?api_key=$SMARTLEAD_API_KEY"
  curl -sS "https://server.smartlead.ai/api/v1/campaigns/$cid/leads?api_key=$SMARTLEAD_API_KEY&limit=100"
  curl -sS "https://server.smartlead.ai/api/v1/campaigns/$cid/email-accounts?api_key=$SMARTLEAD_API_KEY"
done
```

Check: `status` is `DRAFTED`, lead counts match the split, 16 mailboxes
attached, 3 sequence steps each, `track_settings` disables open and click
tracking.

---

## Smartlead API — what you need to know

`SMARTLEAD_API_KEY` is already in the environment. Base URL
`https://server.smartlead.ai/api/v1`.

- Auth is **query param only** (`?api_key=…`). `Authorization: Bearer` and
  `x-api-key` are rejected with `API key is required.`
- Cloudflare 403s urllib's default user-agent (`error code: 1010`). Send an
  ordinary UA — the repo scripts already do.
- Unknown query params are rejected with a 400, so **cache-busters cannot be
  added**. A proxy between here and Smartlead caches GETs, and a stale hit is
  indistinguishable from a live one by status code. **Verify freshness by
  content, not by HTTP 200.** A previous session reported "the plan renewed and
  it works" on the strength of a cached response that was byte-identical to one
  taken before the renewal.
- Sequence delays are `delay_in_days` **on write**, `delayInDays` on read.
- `offset`/`limit` are rejected on `campaigns/{id}`, `/sequences` and
  `/email-accounts`; `/leads` requires `limit` ≤ 100.
- `track_settings` normalises on save: post `DONT_TRACK_EMAIL_OPEN` /
  `DONT_TRACK_LINK_CLICK`, read back `DONT_EMAIL_OPEN` / `DONT_LINK_CLICK`.
- `api.smartlead.ai` is unreachable from this environment. Use
  `server.smartlead.ai`.

---

## Current account state

### Live campaigns (leave alone — these are a separate 33-lead batch)

| ID | Name | Spec |
|---|---|---|
| 3754206 | Follow-Through Story | `docs/sequences/sequence-1.json` |
| 3754247 | The Memory Story | `docs/sequences/sequence-2.json` |
| 3754252 | The AI Org Story | `docs/sequences/sequence-3.json` |

All DRAFTED, 11 leads each, never sent. Three older `FINAL Qualifiers`
campaigns were deleted on 2026-08-03; their copy, settings and leads are
preserved in `docs/smartlead-export/`.

### Mailboxes — already configured, do not redo

18 connected. **16 in the sending pool at 25/day = 400/day ceiling.** All 16
have a signature set (bare first name, matching house convention), so
`%signature%` resolves.

Held back until warmup is further along, left at 15/day and out of every
campaign: `harsh@audriahq.com`, `sneha@getaudria.com`.

| ID | Mailbox | ID | Mailbox |
|---|---|---|---|
| 21579577 | robert@audriahq.com | 21432017 | sophia@getaudria.com |
| 21579562 | jessica@audriahq.com | 21432004 | janice@getaudria.com |
| 21579547 | emily@audriahq.com | 21431981 | ansh@getaudria.com |
| 21579538 | david@audriahq.com | 21431944 | abhiraj@getaudria.com |
| 21566147 | sarah@audriahq.com | 21431896 | pranay@getaudria.com |
| 21566139 | michael@audriahq.com | 21404118 | charles@getaudria.com |
| 21566136 | jennifer@audriahq.com | 21404108 | savannah@getaudria.com |
| 21563852 | jamie@audriahq.com | 21404008 | kelly@getaudria.com |

Every mailbox has `total_sent_count: 0`. **These have never sent a real
email.** Warmup reputation is 99–100%.

---

## The three message arms

Identical structure, three angles on one motion. Copy lives in
`docs/sequences/*.json`; do not rewrite it.

| Arm | Step 1 subject | Angle |
|---|---|---|
| Follow-Through Story | the things you agreed to this week | Commitments lost during the day |
| The Memory Story | what you decided three weeks ago | Decisions lost over months |
| The AI Org Story | does ChatGPT know {{company_name}}? | Your AI can't see what wasn't written down |

Three steps at **day 0 / +3 / +7**:

- **Step 1** carries **no link** and asks for a reply. Deliberate: these
  mailboxes have never sent, and a link in a first cold email from a
  zero-history mailbox is the riskiest shape available. Do not add one.
- **Step 2 has an empty subject.** This makes Smartlead thread it as a genuine
  reply under step 1. Do not put literal `re: …` text there — that opens a new
  thread that only looks like a reply.
- **Steps 2 and 3** carry exactly one App Store link, embedded in words already
  in the sentence (`try it today`, `free during early access`), never as a
  trailing branded anchor.

### House style, if any copy needs editing

Lowercase fragment subjects. **No em-dashes** — sentences split with full stops
instead. Numbered points spelled out ("One. Transcription is finished as a
business."), never `1.` or bullets. `<p>` tags only, no bold, no lists.
Contractions avoided ("I will", "it is", "does not"). Straight apostrophes, not
curly. Openers name the reader's situation; the product arrives in paragraph
2–3. Concrete numbers over adjectives. Personalisation is only
`{{first_name}}` and `{{company_name}}`.

Campaign settings: `America/Los_Angeles`, weekdays, 09:30–11:30, 10 min between
emails, stop on reply, follow-ups 100%, open and click tracking **disabled**
(click tracking rewrites links through a Smartlead domain, which would stop the
App Store link resolving to apple.com).

---

## Open items

1. **Email 3 has no short variant.** All arms send the long version to
   everyone. The user has said three times it should be "long/short
   pre-assigned half and half" but has not supplied the short copy. If they
   send it, add as a second `seq_variant` at 50/50 on each campaign.
2. **`%signature%` has never been confirmed to resolve at send time.** The user
   saw it render literally in the editor, which is expected there. Before any
   campaign starts, send a test to the seeded test address in each campaign
   (`abhiraj.s@audria.tech`, `+test2@`, `+test3@`) and confirm the sign-off
   shows a name and not the raw token. If it does not resolve, hardcode the
   sender's first name in the bodies.
3. **`jamie@audriahq.com` has display name "Adam Cooper"**, so its signature is
   `Adam`. Address and name disagree. Cosmetic, but a recipient may notice.
4. **Ramp before full volume.** The 400/day ceiling is capacity, not a target.
   Every mailbox has zero send history; opening at full volume risks two warmed
   domains. Suggest ~75/day for several days, then step up. The
   `--leads-per-day` default of 25 per campaign does this.

---

## Scripts in this repo

| Script | Purpose |
|---|---|
| `scripts/smartlead_launch_batch.py` | Split a lead file three ways and create the campaigns. **Use this.** |
| `scripts/smartlead_create_campaign.py` | Create/configure one campaign from a spec. `--sequences-only` revises copy without touching leads or settings; `--campaign-id` resumes a partial failure. |
| `scripts/smartlead_dump.py` | Read-only export of every campaign's settings, sequences and mailboxes. |

Background and full findings: `docs/smartlead-account-notes.md`.

---

## Ground rules

- Campaigns stay **DRAFTED**. Starting one sends real email to real founders.
- Verify writes by reading the account back, not by trusting exit codes.
- Do not delete anything without backing it up to the repo first and confirming
  the data exists elsewhere.
- Do not reduce the requested scope silently. If something is blocked, finish
  everything else and say plainly what was left undone.
