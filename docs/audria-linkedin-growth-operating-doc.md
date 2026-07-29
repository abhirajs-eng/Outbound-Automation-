# Audria — LinkedIn Growth Operating Doc

**Portable brief.** Paste into any Claude session to run the daily routine. v1 — 2026-07-29.

---

## 1. Context

**Product:** Audria — early access. Meeting memory: commitments made, decisions taken, context that evaporates between conversations.

**ICP:** Seed to Series B founders, US-based, with a physical US office, working out of that office (not remote-first). Same ICP as the X motion — LinkedIn is a second channel into the same list, not a different audience.

**Product wedges** — the angles worth building outreach and conversation around:
- Commitments: the things you agreed to and didn't write down
- Decisions: what was decided weeks ago and why, when nobody can reconstruct it
- Context: what AI tools do and don't know about your company

---

## 2. Division of labor

| Claude does | Human does |
|---|---|
| Discovery and qualification of ICP founders | Approves everything |
| Monitoring company/funding/hiring signals | Sends connection requests, comments, messages |
| Writing **final, paste-ready** connection notes and follow-ups | Pastes and clicks, in LinkedIn's own UI |
| Sequencing follow-ups against accept/reply state | Logs who accepted / replied |
| Building the ordered daily queue | ~10–15 min execution |

The human's job is execution, not authorship or judgment. Everything requiring reading, thinking, or writing happens before the human opens LinkedIn.

---

## 3. Daily routine

### Claude — delivered before the human's execution window

1. Pull new US funding announcements (seed / Series A / Series B) from §4 sources.
2. Filter: US HQ with a real street address, headcount roughly under 50, stage confirmed.
3. Run office-signal queries (§4) to establish in-office status.
4. Resolve founders to LinkedIn profile URLs.
5. Check accept/reply state on anyone already in sequence (per the human's log) and draft the next message due.
6. Output the **execution queue** (§5) — ordered, paste-ready, no decisions left open.

### Human — ~10–15 min execution + ~10 min review

1. **Review** (10 min): approve, edit, or cut. Anything not approved is dropped, not deferred.
2. **Execute** (10–15 min): work the queue top to bottom — send connection requests with the given note, paste follow-ups to people who accepted, comment where flagged. Open profile → paste → send → next.
3. **Log**: record who accepted and who replied, and when. This log is the only input Claude has for §7 sequencing — without it, follow-ups can't be scheduled correctly.

There is no official-API equivalent to Typefully for LinkedIn *connecting or messaging others* — see §8. If the human also wants their own LinkedIn posts scheduled, official-API tools (Buffer, Hootsuite, Taplio) can handle that the same way Typefully handles X; that's a separate, optional track from the outbound queue below.

---

## 4. Discovery sources

**Funding / stage** (same sources as the X motion):
- vcnewsdaily.com — daily, includes city and stage
- techstartups.com funding roundups
- news.crunchbase.com
- YC company directory (batch = reliable stage proxy)
- Apollo.io or Crunchbase for verification (**always verify — never trust a single source**)

**In-office signal — the hardest criterion, and the most valuable:**
- **Job listings are the strongest source**, same as the X doc — company career pages, Ashby/Wellfound/BuiltIn listings that state office policy explicitly.
- LinkedIn **company page** employee count (often visible in a search snippet without logging in) is a useful headcount cross-check.
- Company blog posts announcing office openings or relocations.

**LinkedIn profile resolution:**
- Resolve profile URLs via **indexed third-party sources** — Crunchbase person pages, company "team" pages, startupintros.com-style directories, press coverage that links a founder's profile — the same way the X doc resolves handles via startupintros.com rather than searching X directly.
- **Do not log into LinkedIn to search for people.** LinkedIn's own search requires an authenticated session, and scripted/automated querying of it is exactly the kind of scraping its terms prohibit (see §8). A profile URL surfaced by an external search engine or an indexed directory page is fine to use — it's public information found the normal way, not extracted by automating LinkedIn itself.
- If a candidate's profile can't be resolved via an external source, drop them rather than guess or attempt a LinkedIn-side search.

---

## 5. Execution queue format

The queue is an **ordered action list** with three parts, not a research dump. Every row must be executable without further thought.

```
## NEW CONNECTS

### 1. Firstname Lastname — Company (Stage, City)
PROFILE: <link>
CONNECTION NOTE (paste as-is, ≤300 characters):
<final note text, references the specific trigger — funding, office move, hiring signal>
WHY: <one line>
---

## FOLLOW-UPS DUE

### Firstname Lastname — Company (connected 2026-07-22, no reply)
MESSAGE (paste as-is):
<final follow-up text>
STEP: 2 of 3
---

## OPTIONAL ENGAGEMENT (comment before connecting, high-value targets only)

### Firstname Lastname — Company
POST: <link, only if the post content was independently verified — see note below>
COMMENT (paste as-is):
<final comment text>
---
```

Rules for the queue:
- Ordered by priority within each section. If the human runs out of time, they stop partway, having done the highest-value ones.
- Note/message text is **final**. No brackets, no "[insert observation]", no options to choose between.
- Maximum 5 new connects per day. Research 10, queue the best 5.
- **On comments specifically:** unlike the X motion, Claude generally cannot read the live text of a specific LinkedIn post (most require a logged-in session and aren't search-indexed in full). Only include a COMMENT entry when the post's actual content was verified through an independent, fetchable source (e.g., the post was quoted in press coverage, or the founder cross-posted the same text elsewhere public). Otherwise, give the human a PROFILE + WHY + suggested angle and let them draft the comment live after reading the real post — do not invent comment text against an unread post.

**Research metadata** (stage source, headcount, in-office evidence, confidence) goes in a separate appendix, not inline. Keep the execution list clean.

Flag anything past Series B for exclusion.

---

## 6. Connection note & sequencing guidance

### The connection note (Step 1, sent with the request)

- Reference a specific, real trigger — the funding round, a job listing, an office-opening post. Generic notes ("Would love to connect!") get ignored and are invisible to a busy founder.
- 300-character LinkedIn limit. Every note must fit without truncation — check length before it goes in the queue.
- No Audria mention in the connection note. It's a professional-context intro, not a pitch.

### The sequence (only after acceptance — never message someone who hasn't accepted)

1. **Step 1 — the connection note** (above), sent with the request.
2. **Step 2 — first follow-up**, ~5–7 days after acceptance if no reply. Something specific and useful — a genuine observation about their work or company. A light, non-pushy Audria mention is reasonable here; LinkedIn is a professional-intent surface and a tasteful one-line mention reads differently than it would on X.
3. **Step 3 — breakup message**, ~14 days after acceptance if still no reply. Short, no pressure, leaves the door open. No further messages after this without a reply.

Anyone who replies at any step exits the scripted sequence — respond to what they actually said, don't keep firing scripted steps at an active conversation.

### Volume

LinkedIn enforces its own connection-request rate limits platform-side, and they've tightened over the years — don't test the ceiling. **3–5 new connection requests/day** keeps this well under any published limit and matches the X motion's cadence, which is also the right pace for the human to write real, specific notes rather than filler.

### The quality test

> Would this note or message be useful/interesting to this specific person, or could it be pasted to anyone in the queue unchanged?

If it's interchangeable across candidates, it's not ready to send.

---

## 7. Own-account content (optional, secondary track)

LinkedIn content is a lighter-weight complement to outbound here, not the main motion — target 2–3 posts/week, not daily.

| Pillar | Material |
|---|---|
| Business & Finance | Outbound/GTM mechanics with real numbers — pricing, fundraising, hiring, early sales lessons |
| Technology | AI tooling that works vs. demo-ware, building on LLMs, honest agent-landscape takes |
| Founder life | Specific, concrete moments — not generic "lessons learned" listicles |

**Hard rules**, same as the X motion: no generic startup-advice content, specific beats abstract, no Audria mention for the first several weeks and roughly 5% product thereafter. Voice calibration from `docs/voice-samples/` is a prerequisite — same samples used for the X motion apply here.

---

## 8. Scope: why connecting and messaging stay manual

This doc deliberately excludes agent-driven connecting, messaging, following, or commenting on linkedin.com. The reasoning, stated plainly so it doesn't need relitigating:

**The issue is the method, not the content.** LinkedIn's User Agreement and Professional Community Policies broadly prohibit automated use of the platform — scraping profile data, and using bots, scripts, or unauthorized tools to connect, message, or otherwise act on the site — and treat it as grounds for restriction or permanent suspension. This applies regardless of who wrote the content, who approved it, or how well it's paced. As with the X motion, the rule addresses *how* the action reaches the platform, not who authored it or how good the judgment behind it was.

**There is no self-serve official-API path for connecting or messaging others.** LinkedIn's Marketing API and Talent Solutions API are partner-gated and built for advertising/recruiting use cases, not generic outbound automation — there's no equivalent to Typefully/Buffer for sending connection requests or DMs on a founder's behalf. (Own-content *scheduling* is the exception, same shape as the X motion: Buffer/Hootsuite/Taplio connect via LinkedIn's official API and can handle that piece if wanted — see §3.)

**The commercial and personal-risk reason, which matters more than the rule:** a LinkedIn account is most founders' primary professional identity, more so than an X account for many people. Getting it restricted isn't just a lost channel — it can mean losing access to real business relationships built over years. And Audria is a trust product sold to founders in a small, well-connected market; being identified as running a connection bot undermines the exact thing the product is about.

**Where the line sits:** a person asking an agent to send one connection request while they're present and reviewing it is that person using a tool. A standing daily routine of agent-sent connections or messages is a system operating on linkedin.com. This doc sits on the manual side, and the design goal is to make that side cost ~10–15 minutes rather than an hour.

---

## 9. Handoff prompt

> I'm running the Audria LinkedIn growth routine. Read the attached operating doc. Today's job: build the execution queue per §4 and §5 — new connects (max 5), follow-ups due per my accept/reply log, and any qualifying optional-engagement comments — plus draft any due Step 2/3 follow-ups. My accept/reply log and writing samples are attached. Research metadata in an appendix, not inline.
