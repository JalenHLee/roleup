"""Roleup entry point (Day 3a): fetch all sources, filter, dedupe, print.

The Gmail alert source runs only when its env vars are set.

Run with:  python -m src.main
"""

import logging
import os
from collections import Counter

from src.dedupe import dedupe
from src.filter import is_relevant
from src.sources import gmail_alerts, jobright, simplify

# Env vars the Gmail alert source needs (read by gmail_alerts and llm_extract).
GMAIL_ENV = ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "ANTHROPIC_API_KEY")


def active_adapters() -> dict:
    """Return {name: adapter}; Gmail is included only when all its env vars are set."""
    adapters = {"simplify": simplify, "jobright": jobright}
    missing = [name for name in GMAIL_ENV if not os.environ.get(name)]
    if missing:
        # Names only, never values.
        print(f"Gmail source skipped: missing env vars: {', '.join(missing)}\n")
    else:
        adapters["gmail"] = gmail_alerts
    return adapters


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    fetched, errors = [], {}
    for name, adapter in active_adapters().items():
        roles, errors[name] = adapter.fetch_roles()
        for role in roles:
            role.category = is_relevant(role)
        fetched.extend(roles)
    kept = [r for r in fetched if r.category]

    merged = dedupe(kept)

    for r in sorted(merged, key=lambda r: (r.category, r.company.lower())):
        print(f"[{r.category}] {r.company} | {r.title} | {r.location} | "
              f"{','.join(r.sources)} | {r.term} | {r.link}")

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
        print(f"  - {r.company} | {r.title} | {r.location}")

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
        for e in errs[:5]:
            print(f"  - {e}")


if __name__ == "__main__":
    main()
