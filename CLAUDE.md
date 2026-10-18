# Roleup

## What this is
Roleup is a nightly bot that merges product and product-adjacent internship postings from four sources into one Google Sheet, removes duplicates, hides roles already applied to, and emails a morning digest. Applying stays manual: this bot never submits applications.

Owner: Jalen (undergrad, graduating Dec 2028, recruiting for Summer 2027).
Full PRD: see the "Roleup — PRD" doc (linked in README).

## Current phase
**v1, Day 3 done + quality pass** — four sources, link IDs + canonical links, source failure isolation, and a layered pipeline (`src/pipeline.py`: term → filter → dedupe → location → eligibility) with per-layer counts. Eligibility flags are built (grad-only). Pending: verify the LinkedIn prompt guidance (company/title split) on the next live run. Next: Day 4 (Google Sheet sync).
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
`role_id` (normalized company + title + location), `company`, `title`, `location`, `link`, `sources` (comma list), `first_seen` (date), `eligibility_flag` (blank / grad-only today; MBA-only / grad-date-conflict reserved), `status` (New / Applied / Skip / Interviewing / Rejected / Offer), `fit_score` (v1.1), `notes`

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
  links.py
  terms.py
  filter.py
  dedupe.py
  location.py
  eligibility.py
  pipeline.py
  sheet.py
  digest.py
  main.py
tests/
.github/workflows/roleup.yml
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
| Email logs/errors name only the sender domain and a short sha256 hash of the Message-ID; never the Message-ID, subject, body, full address, or raw link URLs | Public repo means public Actions logs; Message-IDs and tracking links can carry per-user tokens |
| Gmail source runs only when `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `ANTHROPIC_API_KEY` are all set | Local and CI runs work without secrets; the skip is printed, not silent |
| Link IDs: code numbers every URL in an email (L1..Ln, inline markers) and the LLM returns `link_id`, never a URL | The LLM can't mangle or invent a link; replaces the Day 3a verbatim-link check |
| `links.canonicalize` runs before a link is stored, deduped, or printed (LinkedIn → `/jobs/view/<id>/`; `utm_*` + `TRACKING_PARAMS` stripped) | One URL per posting for dedupe; tracking tokens never reach public logs or the API prompt |
| `main.py` prints roles only via `format_role` (category, company, title, location, sources, canonical links) | One choke point for what reaches public logs, covered by a test |
| Workflow is `workflow_dispatch` only until Day 5; secrets go to the main step only | Watch the first live runs by hand before scheduling; tests never see secrets |
| Each source runs in its own try/except; a failure is printed under "Source failures" (type + message, secrets masked) and the run exits 1 after printing everything | One broken source shouldn't block the digest; the Actions run still shows red so the failure isn't missed |
| Pipeline layers in `src/pipeline.py`: term → filter → dedupe → location → eligibility, each counted in the summary | One place to see what each rule removes; adapters no longer drop off-cycle roles themselves |
| Off-cycle term check for all sources: STRONG patterns (Fall 2026, Spring 2027, Winter, off-cycle, 2026 start) drop unless the title says Summer 2027; WEAK (co-op, part-time) drop only when the term is unknown | Sources mis-tag terms; but "Intern/Co-op" tagged Summer 2027 is usually a real summer role |
| `CATEGORY_EXCLUDES` per category; an excluded title falls through to later rules | "Systematic Strategy" isn't Strategy, but "Product Strategy … Trading" can still be PM |
| US-only location rule: drop only if ALL locations are clearly non-US; unclear (Remote, SF, blank) is kept; runs after dedupe | Prefer recall; a merged role keeps every source's locations |
| Eligibility: flag, don't delete. `grad-only` from title (MBA, Master's, Grad Intern, PhD) or Simplify degrees without Bachelor's; flagged roles stay in the data, hidden from the digest | The sheet keeps the full picture; the digest stays actionable |
| role_id strips a trailing " - City, ST" / " - City, State" only for real US states; adds `holdings` suffix, `multiple teams` noise | Same posting decorated differently; "- Payments, Risk" isn't a location |
| Company-suffix guard strips a company name the LLM appends to a title; fires are counted in the summary | Deterministic backstop for the prompt rule; the count shows if the prompt works |
