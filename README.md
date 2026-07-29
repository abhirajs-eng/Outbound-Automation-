# Outbound Automation — Audria Growth

Operating system for Audria's growth motions across X/Twitter and LinkedIn: Claude handles research, qualification, and writing; a human handles all posting, commenting, following, connecting, and messaging.

## Why it's split this way

Both platforms' automation rules prohibit non-API scripting of the site, full stop — regardless of who wrote the content or how well-paced it is. So every action that touches x.com or linkedin.com directly (posting, commenting, following, DMing, connecting, messaging) stays manual, always. Own-account *scheduling* is the one exception on each platform, and only through an official-API tool (Typefully/Buffer for X; Buffer/Hootsuite/Taplio for LinkedIn), never through this repo or a browser agent. See `docs/audria-x-growth-operating-doc.md` §8 and `docs/audria-linkedin-growth-operating-doc.md` §8 for the full reasoning on each — it is deliberate and shouldn't need relitigating each session.

**No automation in this repo ever posts, comments, follows, connects, or messages on X or LinkedIn.** It only produces text for a human to review and paste.

## Layout

```
docs/
  audria-x-growth-operating-doc.md         X/Twitter operating doc — source of truth, paste-portable
  audria-linkedin-growth-operating-doc.md  LinkedIn operating doc — source of truth, paste-portable
daily/
  YYYY-MM-DD.md                            one file per day: X execution queue + appendix + own-account drafts
daily-linkedin/
  YYYY-MM-DD.md                            one file per day: LinkedIn connects/follow-ups + appendix + own-account drafts
.claude/skills/audria-daily/
  SKILL.md                                 runs the X daily routine on demand (/audria-daily)
.claude/skills/linkedin-daily/
  SKILL.md                                 runs the LinkedIn daily routine on demand (/linkedin-daily)
```

## Running the daily routines

In a Claude Code session with this repo open:

```
/audria-daily
```

Reads the X operating doc, does live research (funding sources, office-signal queries, handle resolution), and writes `daily/<today>.md` with:
- an ordered, paste-ready execution queue (max 5 entries)
- a research appendix (sources, confidence, exclusions)
- 2–3 own-account draft posts per the content pillars in §7

```
/linkedin-daily
```

Reads the LinkedIn operating doc, does live research (funding sources, office-signal queries, profile resolution via external sources only), and writes `daily-linkedin/<today>.md` with:
- new connection requests (max 5, paste-ready notes ≤300 characters)
- any follow-ups due per the accept/reply log (§6 sequencing)
- optional engagement comments, only where the underlying post content was independently verified
- a research appendix
- 2–3 own-account draft posts/week (optional track, §7)

A human then reviews the relevant daily file, approves/edits/cuts, and executes manually — pasting comments/notes/messages by hand, and queuing approved own-account posts in the platform's official-API scheduler.

### Voice calibration

Own-account drafts are generic until real writing samples are supplied (§7 in either doc: "voice calibration is a prerequisite"). Drop 5–10 samples of your unedited writing (old tweets, Slack messages, emails) into `docs/voice-samples/` and future runs will use them for both tracks; until then, drafts are flagged as generic in the daily file.

## Automation

A scheduled job can run `/audria-daily` and/or `/linkedin-daily` each morning and leave the output as a Gmail draft for review — see the session notes for setup status. It never touches x.com or linkedin.com; it only prepares the file/draft for a human to act on.
