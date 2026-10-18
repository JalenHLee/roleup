"""Build the digest email (pure: no network, no clock, no env).

The digest lists exactly the rows the sheet sync appended this run with Status
"New", grouped by category, then counts, a link to the sheet, and problems.
Role text comes from external data, so every value is HTML-escaped and only
http(s) links become clickable.

The email is private (it goes only to the owner), unlike the public Actions logs:
main never prints anything built here.
"""

from datetime import date, datetime
from html import escape

from src.config import DIGEST_CATEGORY_ORDER, HEARTBEAT_LABELS, RUN_LABEL_CUTOFF_HOUR
from src.sheet import SyncCounts

MORNING, EVENING = "Morning", "Evening"


def run_label(now: datetime) -> str:
    """"Morning" before RUN_LABEL_CUTOFF_HOUR (in now's time zone, KST in main), else "Evening"."""
    return MORNING if now.hour < RUN_LABEL_CUTOFF_HOUR else EVENING


def should_send(label: str, n_new: int, failures: dict[str, str], force: bool = False) -> bool:
    """Heartbeat runs always send; others only with new roles or failures. force always sends."""
    return force or label in HEARTBEAT_LABELS or n_new > 0 or bool(failures)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _subject(n_new: int, n_problems: int, label: str, today: date) -> str:
    day = f"{today:%b} {today.day}"  # e.g. "Oct 19"
    if n_new:
        subject = f"Roleup ({label}): {_plural(n_new, 'new role')} — {day}"
    else:
        subject = f"Roleup ({label}): no new roles today — {day}"
    if n_problems:
        subject += f" — {_plural(n_problems, 'problem')}"
    return subject


def _grouped(rows: list[dict[str, str]]) -> list[tuple[str, list[dict[str, str]]]]:
    """(category, rows) in DIGEST_CATEGORY_ORDER (unknown categories last), rows by company."""
    def rank(category: str) -> tuple[int, str]:
        if category in DIGEST_CATEGORY_ORDER:
            return DIGEST_CATEGORY_ORDER.index(category), ""
        return len(DIGEST_CATEGORY_ORDER), category

    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault(row.get("Category") or "Uncategorized", []).append(row)
    return [(cat, sorted(groups[cat], key=lambda r: r.get("Company", "").lower()))
            for cat in sorted(groups, key=rank)]


def _is_web_link(url: str) -> bool:
    return url.lower().startswith(("https://", "http://"))


def _count_lines(n_new: int, counts: SyncCounts | None) -> list[str]:
    if counts is None:
        return ["Sheet sync did not complete: no roles were recorded this run; "
                "they'll appear in the next run's digest."]
    return [
        f"New roles: {n_new}",
        f"Hidden added (eligibility): {counts.appended_hidden}",
        f"Skipped as already applied (tracker): {counts.already_applied}",
    ]


def _problem_lines(failures: dict[str, str], parse_error_count: int) -> list[str]:
    lines = [f"{name}: {message}" for name, message in failures.items()]
    if parse_error_count:
        lines.append(f"Parse errors: {parse_error_count} (see the Actions log)")
    return lines


def build_digest(
    new_rows: list[dict[str, str]],
    counts: SyncCounts | None,
    failures: dict[str, str],
    parse_error_count: int,
    sheet_url: str,
    run_label: str,
    today: date,
) -> tuple[str, str, str]:
    """Return (subject, html, text).

    new_rows: rows appended this run with Status "New", as {header: value}.
    counts: the sheet sync counts, or None if the sync failed or didn't run.
    failures: {step name: masked message}, from main.describe_failure.
    """
    subject = _subject(len(new_rows), len(failures), run_label, today)
    groups = _grouped(new_rows)
    count_lines = _count_lines(len(new_rows), counts)
    problems = _problem_lines(failures, parse_error_count)

    # --- plain text ---
    text = [subject, ""]
    if not new_rows:
        text.append("No new roles this run.")
    for category, rows in groups:
        text.append(f"{category} ({len(rows)})")
        for r in rows:
            text.append(f"  - {r.get('Company', '')} — {r.get('Title', '')} — "
                        f"{r.get('Location', '')} — {r.get('Link', '')} — {r.get('Sources', '')}")
        text.append("")
    text += ["", "Counts", *[f"  {line}" for line in count_lines], "", f"Sheet: {sheet_url}"]
    if problems:
        text += ["", "Problems", *[f"  - {line}" for line in problems]]

    # --- HTML (every external value escaped) ---
    h = [f"<h2>{escape(subject)}</h2>"]
    if not new_rows:
        h.append("<p>No new roles this run.</p>")
    for category, rows in groups:
        h.append(f"<h3>{escape(category)} ({len(rows)})</h3><ul>")
        for r in rows:
            link = r.get("Link", "")
            apply = (f'<a href="{escape(link, quote=True)}">Apply</a>' if _is_web_link(link)
                     else escape(link))
            h.append(f"<li><b>{escape(r.get('Company', ''))}</b> — {escape(r.get('Title', ''))}"
                     f" — {escape(r.get('Location', ''))} — {apply}"
                     f" — <small>{escape(r.get('Sources', ''))}</small></li>")
        h.append("</ul>")
    h.append("<h3>Counts</h3><ul>" + "".join(f"<li>{escape(x)}</li>" for x in count_lines) + "</ul>")
    if _is_web_link(sheet_url):
        h.append(f'<p><a href="{escape(sheet_url, quote=True)}">Open the Roleup sheet</a></p>')
    if problems:
        h.append("<h3>Problems</h3><ul>"
                 + "".join(f"<li>{escape(x)}</li>" for x in problems) + "</ul>")

    return subject, "\n".join(h), "\n".join(text)
