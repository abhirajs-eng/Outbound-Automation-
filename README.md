# Outbound Automation — Audria X/Twitter Growth

Operating system for Audria's X/Twitter growth motion: Claude handles research, qualification, and writing; a human handles all posting, commenting, following, and DMing.

## Why it's split this way

X's automation rules prohibit non-API scripting of the site, full stop — regardless of who wrote the content or how well-paced it is. So every action that touches x.com directly (posting, commenting, following, DMing) stays manual, always. Own-account *scheduling* is the one exception, and only through an official-API tool (Typefully/Buffer), never through this repo or a browser agent. See `docs/audria-x-growth-operating-doc.md` §8 for the full reasoning — it is deliberate and shouldn't need relitigating each session.

**No automation in this repo ever posts, comments, follows, or DMs on X.** It only produces text for a human to review and paste.

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

This reads the operating doc, does live research (funding sources, office-signal queries, handle resolution), and writes `daily/<today>.md` with:
- an ordered, paste-ready execution queue (max 5 entries)
- a research appendix (sources, confidence, exclusions)
- 2–3 own-account draft posts per the content pillars in §7

A human then reviews `daily/<today>.md`, approves/edits/cuts, and executes manually — pasting comments, and queuing approved own-account posts in Typefully.

### Voice calibration

Own-account drafts are generic until real writing samples are supplied (§7: "voice calibration is a prerequisite"). Drop 5–10 samples of your unedited writing (old tweets, Slack messages, emails) into `docs/voice-samples/` and future runs will use them; until then, drafts are flagged as generic in the daily file.

## Automation

A scheduled job can run `/audria-daily` each morning and leave the output as a Gmail draft for review — see the session notes for setup status. It never touches x.com; it only prepares the file/draft for a human to act on.
