# Roleup

## What this is
Roleup is a nightly bot that merges product and product-adjacent internship postings from five sources into one Google Sheet, removes duplicates, hides roles already applied to, and emails a morning digest. Applying stays manual: this bot never submits applications.

Owner: Jalen (undergrad, graduating Dec 2028, recruiting for Summer 2027).
Full PRD: see the "Roleup — PRD" doc (linked in README).

## Current phase
**v1, Day 1** — repo setup + Simplify list ingestion.
(Update this section at the end of every session.)

## Stack
- Python 3.12, plain scripts (no framework)
- GitHub Actions cron for the nightly run (3:00 KST = 18:00 UTC)
- Google Sheets API via a service account (tracker = source of truth)
- Gmail API for reading the alert-email label
- Claude API (Anthropic SDK) for parsing alert emails, and fit scoring in v1.1
- Email digest sent via Gmail API

## Sources
| Source | Method |
|---|---|
| SimplifyJobs/Summer2027-Internships | Parse repo data from GitHub (check for a listings JSON first; else parse README tables) |
| jobright-ai/2026-Product-Management-Internship | Parse README markdown table (shows last 7 days only, so run at least daily) |
| LinkedIn, Lenny's Jobs, Early Career Radar | Their own job-alert emails, routed to one Gmail label; Claude extracts roles |

## Rules
- NEVER scrape LinkedIn, Lenny's Jobs, or Early Career Radar websites. Alert emails only.
- NEVER auto-submit applications.
- NEVER commit secrets, the resume, or the Google Sheet ID. All go in GitHub Actions secrets / a gitignored `.env`.
- This repo is public: keep personal data out of code, tests, fixtures, and logs.
- Keep code simple and commented; one module per responsibility.
- Write tests (pytest) for filtering, role-ID normalization, dedupe, and eligibility logic. Use fake fixture data.
- A failed parse is logged and reported, never silently dropped.

## Data model (one row per role)
`role_id` (normalized company + title + location), `company`, `title`, `location`, `link`, `sources` (comma list), `first_seen` (date), `eligibility_flag` (blank / MBA-only / grad-only / grad-date-conflict), `status` (New / Applied / Skip / Interviewing / Rejected / Offer), `fit_score` (v1.1), `notes`

## Role filter (keep)
Product manager, APM, product intern, product analyst, product ops, growth, strategy, business operations, operations, strategy & operations — internships only. Expect fuzzy titles; prefer recall over precision in v1.

## Eligibility flags (hide from digest, keep in sheet)
MBA-only; graduate/master's-only; graduation-date window that excludes Dec 2028.

## Project layout (target)
```
src/
  sources/simplify.py
  sources/jobright.py
  sources/gmail_alerts.py
  filter.py
  dedupe.py
  eligibility.py
  sheet.py
  digest.py
  main.py
tests/
.github/workflows/nightly.yml
```

## v1 milestones
1. Day 1: repo, secrets, Simplify ingestion printing results
2. Day 2: Jobright ingestion, role filter, dedupe
3. Day 3: Gmail label + alert-email parser
4. Day 4: Google Sheet sync + eligibility flags
5. Day 5: digest email + nightly schedule → v1 live
Then v1.1: fit score (disqualifiers first, full 0–100 range, evidence per score).

## Working style
- Start each session in plan mode; propose a plan before writing code.
- One small, testable outcome per session.
- End each session: commit, update "Current phase" above, and add any new decision to the Decision log below.

## Decision log
| Decision | Why |
|---|---|
| Aggregate existing sources, no new crawlers | The pain is fragmentation, not coverage |
| Alert emails for sites without open data | Within site terms; robust to redesigns |
| Human submits every application | Avoid account bans; PM hiring rewards tailoring |
| Google Sheet stays source of truth | It's already the tracker |
| Fit score after v1 | Summer 2027 postings are live now; speed first |
