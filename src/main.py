"""Roleup entry point (Day 2): fetch Simplify + Jobright, filter, dedupe, print.

Run with:  python -m src.main
"""

import logging
from collections import Counter

from src.dedupe import dedupe
from src.filter import is_relevant
from src.sources import jobright, simplify

SOURCES = {"simplify": simplify, "jobright": jobright}


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    fetched, kept, errors = {}, {}, {}
    for name, adapter in SOURCES.items():
        roles, errors[name] = adapter.fetch_roles()
        for role in roles:
            role.category = is_relevant(role)
        fetched[name] = roles
        kept[name] = [r for r in roles if r.category]

    merged = dedupe([r for name in SOURCES for r in kept[name]])

    for r in sorted(merged, key=lambda r: (r.category, r.company.lower())):
        print(f"[{r.category}] {r.company} | {r.title} | {r.location} | "
              f"{','.join(r.sources)} | {r.term} | {r.link}")

    print("\n=== Summary ===")
    for name in SOURCES:
        print(f"{name}: {len(fetched[name])} listings in target terms, {len(kept[name])} kept by filter")
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
    missed = [r for r in fetched["simplify"]
              if "product" in r.source_category.lower() and not r.category]
    print(f"\nCoverage check: {len(missed)} Simplify 'Product' listings dropped by our filter")
    for r in missed[:15]:
        print(f"  - {r.company} | {r.title}")

    for name in SOURCES:
        print(f"\nParse errors ({name}): {len(errors[name])}")
        for e in errors[name][:5]:
            print(f"  - {e}")


if __name__ == "__main__":
    main()
