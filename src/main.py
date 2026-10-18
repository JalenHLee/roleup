"""Roleup entry point (Day 3b): fetch all sources, filter, dedupe, print.

The Gmail alert source runs only when its env vars are set.

Output goes to public Actions logs, so roles are printed only through
format_role (company, title, location, category, sources, canonical links),
and emails only through format_email_report (sender domain + hashed ID).

Run with:  python -m src.main
"""

import logging
import os
from collections import Counter, defaultdict

from src import llm_extract
from src.dedupe import dedupe
from src.filter import is_relevant
from src.links import canonicalize
from src.models import Role
from src.sources import gmail_alerts, jobright, simplify
from src.sources.gmail_alerts import EmailResult

# Env vars the Gmail alert source needs (read by gmail_alerts and llm_extract).
GMAIL_ENV = ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "ANTHROPIC_API_KEY")


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


def gmail_missing_env() -> list[str]:
    return [name for name in GMAIL_ENV if not os.environ.get(name)]


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    fetched, errors = [], {}
    for name, adapter in {"simplify": simplify, "jobright": jobright}.items():
        roles, errors[name] = adapter.fetch_roles()
        fetched.extend(roles)

    email_report = None
    missing = gmail_missing_env()
    if missing:
        # Names only, never values.
        print(f"Gmail source skipped: missing env vars: {', '.join(missing)}\n")
    else:
        emails = gmail_alerts.fetch_emails()
        roles, errors["gmail"], email_report = gmail_alerts.parse_emails(
            emails, llm_extract.call_claude)
        fetched.extend(roles)

    for role in fetched:
        role.category = is_relevant(role)
    kept = [r for r in fetched if r.category]
    merged = dedupe(kept)

    for r in sorted(merged, key=lambda r: (r.category, r.company.lower())):
        print(format_role(r))

    if email_report is not None:
        print(f"\n=== Alert emails ({len(email_report)}) ===")
        print("\n".join(format_email_report(email_report)) or "  (none in lookback window)")

    print("\n=== Summary ===")
    # Keyed by each role's own source: the Gmail adapter yields linkedin, early-career-radar, ...
    fetched_by_source = Counter(r.sources[0] for r in fetched)
    kept_by_source = Counter(r.sources[0] for r in kept)
    for source, n in fetched_by_source.items():
        print(f"{source}: {n} listings in target terms, {kept_by_source[source]} kept by filter")
    print(f"Total after dedupe: {len(merged)}")

    overlap = [r for r in merged if len(r.sources) > 1]
    print(f"\nOverlap (found in more than one source): {len(overlap)}")
    for r in overlap[:10]:
        print(f"  - {r.company} | {r.title} | {r.location} | {','.join(r.sources)}")

    multi_link = [r for r in merged if len(r.links) > 1]
    print(f"\nMerged roles with more than one link: {len(multi_link)}")

    print("\nKept per term:")
    for term, n in Counter(r.term for r in merged).most_common():
        print(f"  {term}: {n}")

    print("\nKept per category:")
    for cat, n in Counter(r.category for r in merged).most_common():
        print(f"  {cat}: {n}")

    # Coverage check: roles Simplify itself calls "Product" that our filter dropped.
    missed = [r for r in fetched
              if "simplify" in r.sources and "product" in r.source_category.lower()
              and not r.category]
    print(f"\nCoverage check: {len(missed)} Simplify 'Product' listings dropped by our filter")
    for r in missed[:15]:
        print(f"  - {r.company} | {r.title}")

    for name, errs in errors.items():
        print(f"\nParse errors ({name}): {len(errs)}")
        for e in errs[:20]:
            print(f"  - {e}")


if __name__ == "__main__":
    main()
