---
name: audria-daily
description: Run the daily Audria X/Twitter growth routine — research ICP founders, build the paste-ready execution queue, and draft 2-3 own-account posts. Use when the user asks to run the Audria daily routine, build today's queue, or invokes /audria-daily.
---

# Audria daily growth routine

Read `docs/audria-x-growth-operating-doc.md` in full before doing anything else — it is the source of truth for ICP, sourcing, queue format, comment guidance, and content pillars. This skill just operationalizes its §3/§9 handoff.

## Steps

1. **Research (§4).** Using live web search/fetch, pull recent US seed/Series A/Series B funding announcements from the sources in §4. Cross-verify every candidate against at least two sources — never trust one. Run office-signal queries (job listings are the strongest signal) to confirm in-office status. Resolve founders to X handles last, per §4's note that x.com isn't search-indexed.
2. **Never fabricate.** Every name, company, link, and handle in the output must come from an actual fetched source. If you can't verify a candidate, drop it rather than guess. If fewer than 5 solid candidates survive verification, ship fewer — say so in the appendix, don't pad.
3. **Filter.** US HQ with a real street address, headcount roughly under 50, stage confirmed, Series B or earlier (flag and exclude anything past Series B).
4. **Build the queue (§5).** Research ~10 candidates, queue the best 5 max, in priority order. Comment text must be final — no brackets, no placeholders — and structurally distinct entry to entry. Apply the §6 quality test to every comment ("useful to a stranger independent of the poster?") and the §6 post-type ranking (skip funding announcements and pure hiring posts).
5. **Draft own-account content (§7).** 2–3 posts across the pillar mix (Business/Finance ~35%, Technology ~35%, Travel ~15%, Personal ~15%). Check `docs/voice-samples/` for writing samples — if present, calibrate voice from them; if absent, write in a plain, specific, non-generic founder voice and label the section "GENERIC VOICE — add samples to docs/voice-samples/ to calibrate." No Audria mentions this early.
6. **Write the output** to `daily/<YYYY-MM-DD>.md` (today's date) with three sections in this order: Execution Queue, Own-Account Drafts, Research Appendix (metadata only — sources, headcount evidence, confidence, exclusions — kept out of the queue itself).

## Hard boundaries

- Never open, script, or automate x.com itself — no posting, commenting, following, or DMing via browser or API. This skill only produces text a human pastes manually. See operating doc §8.
- Don't queue anything into Typefully or any other posting tool — that's the human's step.
- If you can't reach 5 verified queue candidates or 2 own-account drafts, deliver what's verified and say plainly what's missing rather than filling gaps with invented detail.
