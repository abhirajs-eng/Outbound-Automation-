---
name: linkedin-daily
description: Run the daily Audria LinkedIn growth routine — research ICP founders, build the paste-ready connection/follow-up queue, and flag any due sequence steps. Use when the user asks to run the LinkedIn growth routine, build today's LinkedIn queue, or invokes /linkedin-daily.
---

# Audria LinkedIn daily growth routine

Read `docs/audria-linkedin-growth-operating-doc.md` in full before doing anything else — it is the source of truth for ICP, sourcing, queue format, note/sequencing guidance, and content pillars. This skill just operationalizes its §3/§9 handoff.

## Steps

1. **Research (§4).** Using live web search/fetch, pull recent US seed/Series A/Series B funding announcements from the sources in §4. Cross-verify every candidate against at least two sources — never trust one. Run office-signal queries (job listings are the strongest signal) to confirm in-office status. Resolve founders to LinkedIn profile URLs via external indexed sources only — never by searching or browsing linkedin.com directly (§4).
2. **Never fabricate.** Every name, company, link, and profile URL in the output must come from an actual fetched source. If you can't verify a candidate, drop it rather than guess. If fewer than 5 solid new-connect candidates survive verification, ship fewer — say so in the appendix, don't pad.
3. **Filter.** US HQ with a real street address, headcount roughly under 50, stage confirmed, Series B or earlier (flag and exclude anything past Series B).
4. **Check the sequence log.** If the user has supplied an accept/reply log (who accepted, when, who replied), identify anyone due for Step 2 (~5–7 days post-accept, no reply) or Step 3 (~14 days, no reply) per §6, and draft that message. Never draft a follow-up for someone who hasn't accepted, and never draft a scripted step for someone who already replied.
5. **Build the queue (§5).** Research ~10 new-connect candidates, queue the best 5 max, in priority order, plus any due follow-ups from step 4. Connection notes must be final, ≤300 characters, no brackets or placeholders, and reference a specific real trigger. Only include an OPTIONAL ENGAGEMENT comment entry when the underlying post's actual text was independently verified through a fetchable source — never invent comment text against a post you couldn't read (§5).
6. **Draft own-account content (§7), if requested.** 2–3 posts/week across the pillar mix. Check `docs/voice-samples/` for writing samples — if present, calibrate voice from them; if absent, write in a plain, specific, non-generic founder voice and label the section "GENERIC VOICE — add samples to docs/voice-samples/ to calibrate." No Audria mentions this early.
7. **Write the output** to `daily-linkedin/<YYYY-MM-DD>.md` (today's date) with sections in this order: New Connects, Follow-Ups Due, Optional Engagement, Own-Account Drafts (if requested), Research Appendix (metadata only — sources, headcount evidence, confidence, exclusions — kept out of the queue itself).

## Hard boundaries

- Never open, script, or automate linkedin.com itself — no connecting, messaging, following, or commenting via browser or API, and no automated searching/browsing of LinkedIn to resolve profiles. This skill only produces text a human pastes manually, using profile URLs found via external sources. See operating doc §8.
- Never invent a LinkedIn profile URL or a post's content. If it can't be verified via an independent source, drop the candidate or the comment entry rather than guess.
- Don't queue anything into Buffer/Hootsuite/Taplio or any other LinkedIn tool — that's the human's step, and only applies to the human's own posts, never to connecting/messaging others.
- If you can't reach 5 verified new-connect candidates, deliver what's verified and say plainly what's missing rather than filling gaps with invented detail.
