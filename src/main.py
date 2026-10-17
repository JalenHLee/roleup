"""Roleup entry point (Day 1): fetch Simplify, filter, print matches and counts.

Run with:  python -m src.main
"""

import logging
from collections import Counter

from src.filter import is_relevant
from src.sources import simplify


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    roles, errors = simplify.fetch_roles()
    for role in roles:
        role.category = is_relevant(role)
    kept = [r for r in roles if r.category]

    for r in sorted(kept, key=lambda r: (r.category, r.company.lower())):
        print(f"[{r.category}] {r.company} | {r.title} | {r.location} | {r.term} | {r.link}")

    print("\n=== Summary ===")
    print(f"Simplify listings in target terms: {len(roles)}")
    print(f"Kept by filter: {len(kept)}")

    print("\nKept per term:")
    for term, n in Counter(r.term for r in kept).most_common():
        print(f"  {term}: {n}")

    print("\nKept per category:")
    for cat, n in Counter(r.category for r in kept).most_common():
        print(f"  {cat}: {n}")

    # Coverage check: roles Simplify itself calls "Product" that our filter dropped.
    missed = [r for r in roles if "product" in r.source_category.lower() and not r.category]
    print(f"\nCoverage check: {len(missed)} Simplify 'Product' listings dropped by our filter")
    for r in missed[:15]:
        print(f"  - {r.company} | {r.title}")

    print(f"\nParse errors: {len(errors)}")
    for e in errors[:5]:
        print(f"  - {e}")


if __name__ == "__main__":
    main()
