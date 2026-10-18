"""The processing pipeline: every layer between fetched listings and the digest.

Layers, in order (each one's drops are kept so main can count and show them):
  1. term         drop off-cycle titles (all sources)              raw listings
  2. filter       keep product-adjacent internships, set category   raw listings
  3. dedupe       merge the same role across sources                listings -> roles
  4. location     drop roles whose locations are ALL clearly non-US merged roles
  5. eligibility  flag grad-only roles: kept, but hidden from digest merged roles

Location runs after dedupe so "keep if ANY location is US" sees every source's locations.
"""

from dataclasses import dataclass

from src.dedupe import dedupe
from src.eligibility import eligibility_flag
from src.filter import is_relevant
from src.location import is_us_or_unclear
from src.models import Role
from src.terms import is_off_cycle


@dataclass
class PipelineResult:
    fetched: list[Role]  # everything the sources returned
    dropped_term: list[Role]
    dropped_filter: list[Role]  # passed the term layer, no category
    kept: list[Role]  # passed term + filter, before dedupe
    merged: list[Role]  # after dedupe
    dropped_location: list[Role]
    hidden: list[Role]  # flagged by eligibility; stays in the data, not in the digest
    digest: list[Role]


def _split(roles: list[Role], keep) -> tuple[list[Role], list[Role]]:
    kept, dropped = [], []
    for role in roles:
        (kept if keep(role) else dropped).append(role)
    return kept, dropped


def run_pipeline(roles: list[Role]) -> PipelineResult:
    """Run all layers. Sets `category` and `eligibility_flag` on the roles it keeps."""
    after_term, dropped_term = _split(roles, lambda r: not is_off_cycle(r.title, r.term))

    for role in after_term:
        role.category = is_relevant(role)
    kept, dropped_filter = _split(after_term, lambda r: r.category is not None)

    merged = dedupe(kept)
    located, dropped_location = _split(merged, lambda r: is_us_or_unclear(r.location))

    for role in located:
        role.eligibility_flag = eligibility_flag(role)
    digest, hidden = _split(located, lambda r: not r.eligibility_flag)

    return PipelineResult(
        fetched=roles,
        dropped_term=dropped_term,
        dropped_filter=dropped_filter,
        kept=kept,
        merged=merged,
        dropped_location=dropped_location,
        hidden=hidden,
        digest=digest,
    )
