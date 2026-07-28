# Audria — X/Twitter Growth Operating Doc

**Portable brief.** Paste into any Claude session to run the daily routine. v3 — 2026-07-28.

---

## 1. Context

**Product:** Audria — early access. Meeting memory: commitments made, decisions taken, context that evaporates between conversations.

**ICP:** Seed to Series B founders, US-based, with a physical US office, working out of that office (not remote-first).

**Product wedges** — the angles worth building content and conversation around:
- Commitments: the things you agreed to and didn't write down
- Decisions: what was decided weeks ago and why, when nobody can reconstruct it
- Context: what AI tools do and don't know about your company

---

## 2. Division of labor

| Claude does | Human does |
|---|---|
| Discovery and qualification of ICP founders | Approves everything |
| Monitoring their recent posts | Posts, comments, follows, DMs |
| Writing **final, paste-ready** comment text | Pastes and clicks |
| Drafting own-account content | Queues approved posts in Typefully |
| Building the ordered daily queue | ~10 min execution |

The human's job is execution, not authorship or judgment. Everything requiring reading, thinking, or writing happens before 9 AM.

---

## 3. Daily routine

### Claude — delivered by 9:00 AM IST

1. Pull new US funding announcements (seed / Series A / Series B) from §4 sources.
2. Filter: US HQ with a real street address, headcount roughly under 50, stage confirmed.
3. Run office-signal queries (§4) to establish in-office status.
4. Resolve founders to X handles.
5. Output the **execution queue** (§5) — ordered, paste-ready, no decisions left open.
6. Deliver 2–3 draft posts for the human's own account (§7).

### Human — ~10 min execution + ~10 min review

1. **Review** (10 min): approve, edit, or cut. Anything not approved is dropped, not deferred.
2. **Execute** (10 min): work the queue top to bottom. Open link → paste → post → next.
3. **Log**: track anyone who replies or follows back. Those are the only people worth DMing later (§6).

Approved own-account posts go into Typefully (~$13/mo, official X API) which handles scheduling and spacing automatically. This is the sanctioned path for own content and requires no further human involvement.

---

## 4. Discovery sources

**Funding / stage:**
- vcnewsdaily.com — daily, includes city and stage
- techstartups.com funding roundups
- news.crunchbase.com
- YC company directory (batch = reliable stage proxy)
- Apollo.io or Crunchbase for verification (**always verify — never trust a single source**)

**In-office signal — the hardest criterion, and the most valuable:**
- **Job listings are the strongest source.** Companies are forced to state office policy explicitly ("on-site in SF, 5 days/week", "hybrid NYC, 4 days in-office"). Nothing else gives stage + headcount + city + in-office policy in one indexed document.
- LinkedIn founder posts announcing office moves, new leases, relocations.
- Company blog posts announcing office openings.

**X handle resolution:**
- startupintros.com — founder profiles carrying X handle alongside funding history and location
- Company about/team pages

**Note:** x.com is not indexed by search engines. You cannot find people "on Twitter" via search. You find them elsewhere and resolve the handle last.

---

## 5. Execution queue format

The queue is an **ordered action list**, not a research dump. Every row must be executable without further thought.

```
### 1. @handle — Firstname Lastname, Company (Stage, City)

POST: <direct link to the specific post>

COMMENT (paste as-is):
<final comment text, 1–3 sentences, no placeholders>

WHY: <one line>

---
```

Rules for the queue:
- Ordered by priority. If the human runs out of time, they stop partway, having done the highest-value ones.
- Comment text is **final**. No brackets, no "[insert observation]", no options to choose between.
- Every comment must be different in structure, not just wording. Repeating a scaffold across comments is visible to readers.
- Maximum 5 entries. Research 10, queue the best 5.

**Research metadata** (stage source, headcount, in-office evidence, confidence) goes in a separate appendix, not inline. Keep the execution list clean.

Flag anything past Series B for exclusion. Several high-visibility founders posting about offices are Series D+ and are not ICP.

---

## 6. Comment guidance

### Post types, ranked

**Best — in-office culture posts.** The post topic *is* the product wedge. Real POV available without mentioning Audria.

**Good — retrospectives, "what we got wrong", decision post-mortems.** Direct line to the product premise.

**Skip — funding announcements.** 200+ congratulations comments. Yours is invisible. Worst ROI on the platform.

**Skip — pure hiring posts.** Nothing to add that isn't noise.

### The quality test

> Would this comment be useful to a stranger reading the thread, independent of the poster?

If it only functions as a signal to the founder that you exist, cut it from the queue.

### Volume

3–5 comments/day. Research 10, engage 3–5. Past ~5 the writing turns to filler and filler is visible to everyone.

### Sequencing to DM

No DMs for 2–3 weeks minimum, and only to people who followed back or replied. Cold X DMs from non-followers land in a request folder most founders never open — getting into the primary inbox is the actual problem, and only genuine engagement solves it.

### Feed hygiene

Onboarding interest selections control the *feed*, not posting. Build a **private X List** of ICP founders and work that list. It's a curated feed independent of the algorithm, and it makes the daily queue faster to execute.

---

## 7. Own-account content pillars

Target: 1–2 posts/day. Consistency over volume.

| Pillar | Share | Material |
|---|---|---|
| Business & Finance | ~35% | Outbound and GTM mechanics with real numbers, pricing, fundraising, hiring, early sales lessons |
| Technology | ~35% | AI tooling that works vs. demo-ware, building on LLMs, honest takes on the agent landscape |
| Travel | ~15% | *Founder* travel specifically — conferences, fundraising trips, offsites, cross-timezone building. On-thesis without pitching |
| Personal / off-topic | ~15% | Makes you a person rather than a content channel |

**Hard rules:**
- No generic startup advice, no "10 lessons from", no motivational content. Saturated tier, invisible.
- Specific beats abstract. Numbers beat adjectives.
- No Audria mention for the first several weeks. Roughly 5% product thereafter.

**Voice calibration is a prerequisite.** Drafts must be built from 5–10 samples of the founder's unedited writing (old tweets, Slack messages, email excerpts). Without this the drafts need more rewriting than writing and the system fails in week two.

---

## 8. Scope: why posting stays manual

This doc deliberately excludes agent-driven posting, commenting, following, and DMing on x.com. The reasoning, stated plainly so it doesn't need relitigating:

**The issue is the method, not the content.** X's automation rules prohibit non-API automation of the site — scripting the X website — and name it as grounds for permanent suspension. A browser agent operating x.com falls inside that rule regardless of who wrote the content, who approved it, or how it's paced. The rule addresses how the action reaches the platform, not authorship. Human approval of content is a real and meaningful safeguard; it just answers a different question than the one the rule asks.

**Official-API tools are the sanctioned path** and should be used for everything they cover. Typefully and Buffer connect via OAuth and handle own-content scheduling completely. There is no equivalent compliant tool for commenting on others' posts, which is why that stays manual.

**Two clarifications, since they come up:**
- *Stopping at a CAPTCHA is correct error handling, not evasion.* An agent that halts on a challenge it can't solve is behaving properly. This is not the objection.
- *Natural pacing is not inherently deceptive.* Spacing your own scheduled posts is normal practice and every scheduler does it. The concern was never rhythm.

**Where the line actually sits:** a person asking an agent to post one thing while they're present is functionally that person using a tool. A standing daily routine of agent-posted comments is a system operating on x.com. That boundary is genuinely fuzzy and plenty of operators cross it. This doc sits on the manual side, and the design goal is to make that side cost ~10 minutes rather than an hour.

**The commercial reason, which matters more than the rule:** Audria is a trust product sold to founders in a small, well-connected market. Being identified as running a comment bot is not a warning — it's the positioning destroyed by the method used to build it. A product about honoring what you committed to cannot be marketed with manufactured presence.

---

## 9. Handoff prompt

> I'm running the Audria X growth routine. Read the attached operating doc. Today's job: build the execution queue per §4 and §5 — ordered, paste-ready, 5 entries max — plus 2–3 posts for my own account per §7. My writing samples are attached for voice. Research metadata in an appendix, not inline.
