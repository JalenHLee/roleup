# Roleup

## What this is
Roleup is a nightly bot that merges product and product-adjacent internship postings from four sources into one Google Sheet, removes duplicates, hides roles already applied to, and emails a morning digest. Applying stays manual: this bot never submits applications.

Owner: Jalen (undergrad, graduating Dec 2028, recruiting for Summer 2027).
Full PRD: see the "Roleup — PRD" doc (linked in README).

## Current phase
**v1, Day 3a done** — Simplify + Jobright ingestion, role filter, dedupe, alert-email adapter (IMAP + Claude parser) tested on fake data only. Next: Day 3b (real Gmail label + app password, first live run, prompt tuning).
(Update this section at the end of every session.)

## Stack
- Python 3.12, plain scripts (no framework)
- GitHub Actions cron for the nightly run (3:00 KST = 18:00 UTC)
- Google Sheets API via a service account (tracker = source of truth)
- Gmail over IMAP (`imaplib`, app password) for reading the alert-email label
- Claude API (Anthropic SDK) for parsing alert emails, and fit scoring in v1.1
- Email digest sent via Gmail API

## Sources
| Source | Method |
|---|---|
| SimplifyJobs/Summer2027-Internships | Parse repo data from GitHub (check for a listings JSON first; else parse README tables) |
| jobright-ai/2026-Product-Management-Internship | Parse README markdown table (shows last 7 days only, so run at least daily) |
| LinkedIn, Early Career Radar | Their own job-alert emails, routed to the `job-alerts` Gmail label, read over IMAP; Claude extracts roles |

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
Product manager, APM, product intern, product analyst, product ops, growth, strategy, business operations, operations, strategy & operations, product marketing (titles containing "Product Marketing" only; not generic marketing/brand/social) — internships only.
The filter assigns a category: PM, PMM, Growth, Operations, Strategy, or Product (other). Keyword rules live in `src/config.py`. Expect fuzzy titles; prefer recall over precision in v1.

## Eligibility flags (hide from digest, keep in sheet)
MBA-only; graduate/master's-only; graduation-date window that excludes Dec 2028.

## Project layout (target)
```
src/
  config.py
  models.py
  sources/simplify.py
  sources/jobright.py
  sources/gmail_alerts.py
  llm_extract.py
  terms.py
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
| Simplify via `.github/scripts/listings.json` on `dev`, no README fallback | Structured data beats parsing tables; if it moves, fail loudly |
| `TARGET_TERMS` in config (Summer 2027 + N/A; N/A labeled "unknown") | Off-cycle terms are noise; one-line change for Summer 2028 |
| Filter returns a category via ordered keyword rules in config | Tune rules without touching logic; categories help the digest |
| Keep Product Marketing roles (exact phrase only) | Product-adjacent, but generic marketing is out of scope |
| Role carries `degrees` and Simplify's own category | `degrees` for eligibility (Day 4); category for the filter coverage check |
| role_id excludes location | Same company + title is one application; location formats differ across sources |
| Jobright term inferred from title; Fall 2026 / Winter / Spring / Co-op dropped unless Summer 2027 is also named | Jobright has no term column |
| role_id strips term phrases, bare years, intern words, country tokens (US/USA); keeps MBA/degree markers | Sources decorate the same title differently; degree-restricted roles are separate applications |
| Merged role keeps every distinct link (`links`); primary `link` = Simplify's, else first seen | Two postings can share company + title; one link would silently hide an application |
| `COMPANY_ALIASES` in config for company names that differ across sources | One-line fix per mismatch, no logic change |
| LLM (Claude, `LLM_MODEL` in config) parses alert emails; code validates every item | Alert layouts vary and change; validation (required fields, http link, link must appear verbatim in the email) catches bad or hallucinated output |
| Gmail via IMAP + app password, not the Gmail API | No OAuth consent screen or token refresh for a single-user bot |
| Stateless 2-day email lookback (`EMAIL_LOOKBACK_DAYS`) | No "last seen" state to store; dedupe absorbs re-read emails, and one missed night is covered |
| Lenny's Jobs cut from v1 | Alerts are paid, and few of its postings are internships |
| Email-sourced roles are dated by the email's date | Alerts carry no post date |
| Term inference from titles shared in `src/terms.py` (Jobright + emails) | One set of rules, no drift between sources |
| Email logs/errors name only Message-ID and sender domain; never subject, body, full address, or link URLs | Public repo means public Actions logs; tracking links can carry per-user tokens |
| Gmail source runs only when `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `ANTHROPIC_API_KEY` are all set | Local and CI runs work without secrets; the skip is printed, not silent |
