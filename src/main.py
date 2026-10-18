"""Roleup entry point: fetch all sources, run the pipeline, sync the sheet, print.

The Gmail alert source and the sheet sync each run only when their env vars are set. Each source runs in
isolation: one that crashes is reported and skipped, the others still run, and
the process exits with code 1 at the end so the Actions run shows as failed.

Output goes to public Actions logs, so roles are printed only through
format_role (company, title, location, category, sources, canonical links),
and emails only through format_email_report (sender domain + hashed ID).
The sheet sync prints counts only, never tracker or sheet contents. It runs after
the pipeline with the same isolation: a failure is reported and exits 1.

Run with:  python -m src.main
"""

import logging
import os
import json
import sys
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from src import llm_extract, sheet
from src.config import RUN_TIMEZONE
from src.links import canonicalize
from src.models import Role
from src.pipeline import PipelineResult, run_pipeline
from src.sources import gmail_alerts, jobright, simplify
from src.sources.gmail_alerts import EmailResult

# Env vars the Gmail alert source needs (read by gmail_alerts and llm_extract).
GMAIL_ENV = ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "ANTHROPIC_API_KEY")
# Env vars the sheet sync needs (read by sheet.open_spreadsheet).
SHEET_ENV = ("GOOGLE_SERVICE_ACCOUNT_JSON", "SHEET_ID")
FAILURE_MESSAGE_LIMIT = 300  # characters of an exception message to print


@dataclass
class SourceResult:
    roles: list[Role]
    errors: list[str]  # item-level parse errors
    email_report: list[EmailResult] | None = None  # Gmail only


def fetch_gmail() -> SourceResult:
    roles, errors, report = gmail_alerts.parse_emails(
        gmail_alerts.fetch_emails(), llm_extract.call_claude)
    return SourceResult(roles, errors, report)


def active_sources() -> dict[str, Callable[[], SourceResult]]:
    """Return {name: fetch}; Gmail is included only when all its env vars are set."""
    sources = {
        "simplify": lambda: SourceResult(*simplify.fetch_roles()),
        "jobright": lambda: SourceResult(*jobright.fetch_roles()),
    }
    missing = [name for name in GMAIL_ENV if not os.environ.get(name)]
    if missing:
        # Names only, never values.
        print(f"Gmail source skipped: missing env vars: {', '.join(missing)}\n")
    else:
        sources["gmail"] = fetch_gmail
    return sources


def run_sources(
    sources: dict[str, Callable[[], SourceResult]],
) -> tuple[dict[str, SourceResult], dict[str, str]]:
    """Run each source in isolation. Returns (results, failures by source name).

    A source that raises is recorded as a failure and skipped; the rest still run.
    """
    results, failures = {}, {}
    for name, fetch in sources.items():
        try:
            results[name] = fetch()
        except Exception as e:  # isolate any source failure
            failures[name] = describe_failure(e)
            logging.getLogger(__name__).error("Source %s failed: %s", name, failures[name])
    return results, failures


def _secrets() -> dict[str, str]:
    """{label: value} of every secret value to mask, incl. key fields of the service account JSON."""
    secrets = {name: os.environ[name] for name in GMAIL_ENV + SHEET_ENV if os.environ.get(name)}
    try:
        info = json.loads(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", ""))
    except ValueError:
        info = None
    if isinstance(info, dict):
        for key in ("private_key", "private_key_id", "client_email", "client_id"):
            if isinstance(info.get(key), str) and info[key]:
                secrets[f"service account {key}"] = info[key]
    return secrets


def describe_failure(e: Exception) -> str:
    """Exception type and message, with secret values masked and the length capped.

    Messages come from libraries (IMAP, HTTP, API), not from email content, but
    the masking is a second guard in case a library echoes a credential back.
    """
    message = str(e)
    # Longest first, so a value containing another is masked whole.
    for name, value in sorted(_secrets().items(), key=lambda kv: -len(kv[1])):
        message = message.replace(value, f"<{name}>")
    if len(message) > FAILURE_MESSAGE_LIMIT:
        message = message[:FAILURE_MESSAGE_LIMIT] + "..."
    return f"{type(e).__name__}: {message}"


def run_date() -> date:
    """Today in RUN_TIMEZONE: the "First Seen" date for rows added by this run."""
    return datetime.now(ZoneInfo(RUN_TIMEZONE)).date()


def run_sheet_sync(
    result: PipelineResult,
    open_spreadsheet: Callable | None = None,
    today: date | None = None,
) -> tuple[sheet.SyncCounts | None, str | None]:
    """Sync the sheet in isolation. Returns (counts, None), or (None, failure) if it raised.

    open_spreadsheet defaults to sheet.open_spreadsheet; tests inject a fake.
    """
    try:
        spreadsheet = (open_spreadsheet or sheet.open_spreadsheet)()
        return sheet.sync(spreadsheet, result, today or run_date()), None
    except Exception as e:  # isolate the sheet like a source
        failure = describe_failure(e)
        logging.getLogger(__name__).error("Sheet sync failed: %s", failure)
        return None, failure


def format_sync_counts(counts: sheet.SyncCounts) -> list[str]:
    """Counts only: never tracker or sheet contents (Actions logs are public)."""
    return [
        f"already in Roleup tab: {counts.already_in_roleup}",
        f"skipped as already applied (tracker): {counts.already_applied}",
        f"appended New: {counts.appended_new}",
        f"appended Hidden: {counts.appended_hidden}",
    ]


def format_role(role: Role) -> str:
    """One public-safe line per role. Links are canonicalized again as a second guard."""
    links = ", ".join(dict.fromkeys(canonicalize(link) for link in (role.links or [role.link])))
    return (f"[{role.category}] {role.company} | {role.title} | {role.location} | "
            f"{','.join(role.sources)} | {links}")


def format_email_report(report: list[EmailResult]) -> list[str]:
    """Per-email lines (domain, hashed ID, counts), then totals per source."""
    lines = []
    totals = defaultdict(lambda: [0, 0, 0])  # source -> [emails, roles, errors]
    for r in report:
        lines.append(f"  {r.domain}  #{r.short_id}  roles: {r.roles}  errors: {r.errors}")
        t = totals[r.source or "unknown sender"]
        t[0] += 1
        t[1] += r.roles
        t[2] += r.errors
    for source, (emails, roles, errors) in totals.items():
        lines.append(f"  total {source}: {emails} emails, {roles} roles, {errors} errors")
    return lines


def main() -> int:
    """Run everything and print the report. Returns the exit code (1 if any source failed)."""
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    results, failures = run_sources(active_sources())
    fetched = [role for result in results.values() for role in result.roles]
    errors = {name: result.errors for name, result in results.items()}
    email_report = results["gmail"].email_report if "gmail" in results else None

    result = run_pipeline(fetched)

    missing = [name for name in SHEET_ENV if not os.environ.get(name)]
    if missing:
        sync_counts = None
        print(f"Sheet sync skipped: missing env vars: {', '.join(missing)}\n")  # names only
    else:
        sync_counts, sync_failure = run_sheet_sync(result)
        if sync_failure:
            failures["sheet"] = sync_failure

    print(f"=== Digest ({len(result.digest)}) ===")
    for r in sorted(result.digest, key=lambda r: (r.category, r.company.lower())):
        print(format_role(r))

    print(f"\n=== Hidden (eligibility) ({len(result.hidden)}) ===")
    for r in sorted(result.hidden, key=lambda r: (r.category, r.company.lower())):
        print(f"{format_role(r)} | {r.eligibility_flag}")

    if email_report is not None:
        print(f"\n=== Alert emails ({len(email_report)}) ===")
        print("\n".join(format_email_report(email_report)) or "  (none in lookback window)")

    print("\n=== Pipeline ===")
    print(f"fetched: {len(result.fetched)} listings")
    print(f"dropped by term: {len(result.dropped_term)} listings")
    print(f"dropped by filter: {len(result.dropped_filter)} listings")
    print(f"merged by dedupe: {len(result.kept)} listings -> {len(result.merged)} roles")
    print(f"dropped by location: {len(result.dropped_location)} roles")
    for r in result.dropped_location[:10]:
        print(f"  - {r.company} | {r.title} | {r.location}")
    print(f"hidden by eligibility: {len(result.hidden)} roles")
    print(f"digest: {len(result.digest)} roles")

    recoveries = sum(e.company_recoveries for e in email_report or [])
    print(f"\nCompany recovered from subtitle (alert emails): {recoveries}")

    fixes = [fix for e in email_report or [] for fix in e.title_fixes]
    print(f"\nTitle company-suffix fixes (alert emails): {len(fixes)}")
    for before, after in fixes[:5]:
        print(f"  - {before!r} -> {after!r}")

    if sync_counts is not None:
        print("\n=== Sheet sync ===")
        print("\n".join(format_sync_counts(sync_counts)))

    print("\n=== Summary ===")
    # Keyed by each role's own source: the Gmail adapter yields linkedin, early-career-radar, ...
    fetched_by_source = Counter(r.sources[0] for r in result.fetched)
    kept_by_source = Counter(r.sources[0] for r in result.kept)
    for source, n in fetched_by_source.items():
        print(f"{source}: {n} listings fetched, {kept_by_source[source]} kept by term + filter")

    # Roles that survived location (digest + hidden).
    located = result.digest + result.hidden
    overlap = [r for r in located if len(r.sources) > 1]
    print(f"\nOverlap (found in more than one source): {len(overlap)}")
    for r in overlap[:10]:
        print(f"  - {r.company} | {r.title} | {r.location} | {','.join(r.sources)}")

    multi_link = [r for r in located if len(r.links) > 1]
    print(f"\nMerged roles with more than one link: {len(multi_link)}")

    print("\nDigest per term:")
    for term, n in Counter(r.term for r in result.digest).most_common():
        print(f"  {term}: {n}")

    print("\nDigest per category:")
    for cat, n in Counter(r.category for r in result.digest).most_common():
        print(f"  {cat}: {n}")

    # Coverage check: roles Simplify itself calls "Product" that our filter dropped.
    missed = [r for r in result.dropped_filter
              if "simplify" in r.sources and "product" in r.source_category.lower()]
    print(f"\nCoverage check: {len(missed)} Simplify 'Product' listings dropped by our filter")
    for r in missed[:15]:
        print(f"  - {r.company} | {r.title}")

    for name, errs in errors.items():
        print(f"\nParse errors ({name}): {len(errs)}")
        for e in errs[:20]:
            print(f"  - {e}")

    print(f"\n=== Source failures ({len(failures)}) ===")
    for name, failure in failures.items():
        print(f"  - {name}: {failure}")
    if not failures:
        print("  (none)")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
