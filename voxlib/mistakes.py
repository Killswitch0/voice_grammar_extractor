"""
The mistake history — the one series this project exists to produce.

`analysis/scores_history.csv` records five numbers a session. `analysis/
fluency_history.csv` records how the recording came out. Neither records the
thing the owner actually wants tracked over months: which mistakes keep coming
back, and whether any of them is fading. That lived only as prose in
`analysis/memory.md`, in fields like

    Occurrences: 4 sessions (5, 6, 6, then ~13 instances)

which cannot be graphed, cannot be checked, and — being rewritten from scratch
by a language model every session — is a retelling of a retelling by the fourth
one. Things already went missing that way: 2026-08-04's report tracked a
"just placement with modal can" pattern with two instances, and it appears
nowhere in memory.md.

So the counts live here as data, and memory.md becomes the readable rendering of
them rather than the record itself.

Three things this file fixes beyond durability:

**Counts are normalized.** Five article errors in a 2,154-word session and
thirteen in a 1,956-word one are not comparable as raw counts, and the sessions
on record range from 1,844 to 2,547 reliable words. Every rate here is per
1,000 reliable words, with the denominator stored on each row so it can always
be recomputed.

**"Absent" and "untested" are different facts.** `occurrences` may be blank,
meaning the category had no chance to show up — 2026-08-08 produced zero
if-clauses, so "conditional will" was not clean that session, it was untried.
Only an explicit 0 counts toward the three-session absence streak that promotes
a mistake to Improvements. This is the same discipline `fluency.py` applies to
an unmeasured metric, for the same reason.

**Impact is computed, not judged.** CLAUDE.md rule 15 asks for severity ×
occurrences with recent sessions weighted more heavily. That is an arithmetic
instruction, and arithmetic carried out in prose by a model reading its own
previous prose is where the ranking quietly drifts.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

HISTORY_COLUMNS = [
    "date",
    "category",
    "severity",
    "occurrences",
    "reliable_words",
    "source",
    "notes",
]

# How many sessions back the impact ranking looks, and with what weight. Newest
# first: the most recent session counts three times what the one before last
# does. Rule 15 asks for recent sessions to weigh more without saying how much;
# this is the smallest scheme that does it, and being explicit here is the point
# — a decay constant buried in a formula is a judgment call nobody can see.
RECENCY_WEIGHTS = (3, 2, 1)

# Consecutive sessions a mistake must be explicitly absent from before it moves
# to Improvements. Mirrors the rule in CLAUDE.md step 6.
ABSENCE_STREAK_FOR_IMPROVEMENT = 3


@dataclass
class MistakeCount:
    """One category's result in one session."""
    category: str
    severity: int
    # None = the category had no opportunity to appear (the structure was never
    # attempted). 0 = it had the opportunity and stayed clean. The difference is
    # the whole reason the absence streak can be trusted.
    occurrences: Optional[int]
    notes: str = ""


@dataclass
class SessionRow:
    date: str
    category: str
    severity: int
    occurrences: Optional[int]
    reliable_words: int
    source: str
    notes: str

    @property
    def rate_per_1000(self) -> Optional[float]:
        if self.occurrences is None or self.reliable_words <= 0:
            return None
        return round(self.occurrences / self.reliable_words * 1000, 2)


@dataclass
class CategoryTrend:
    category: str
    severity: int
    first_seen: str
    last_seen: Optional[str]        # last session with occurrences > 0
    sessions_measured: int          # sessions where it was actually testable
    total_occurrences: int
    latest_rate: Optional[float]    # per 1,000 reliable words, most recent measured session
    weighted_rate: float            # recency-weighted, per 1,000 reliable words
    impact: float                   # severity x weighted_rate — the ranking key
    absence_streak: int             # consecutive explicit zeros, most recent first
    untested_since: int             # sessions since the last measurable one
    direction: str                  # "worsening" / "improving" / "steady" / "n/a"

    @property
    def ready_for_improvements(self) -> bool:
        return self.absence_streak >= ABSENCE_STREAK_FOR_IMPROVEMENT


def _parse_occurrences(raw: str) -> Optional[int]:
    raw = (raw or "").strip()
    return None if raw == "" else int(raw)


def load(path: Path) -> list[SessionRow]:
    """Every recorded row, oldest first. Missing file means no history yet."""
    if not path.exists():
        return []

    rows: list[SessionRow] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            rows.append(SessionRow(
                date=raw["date"].strip(),
                category=raw["category"].strip(),
                severity=int(raw["severity"]),
                occurrences=_parse_occurrences(raw["occurrences"]),
                reliable_words=int(raw["reliable_words"]),
                source=(raw.get("source") or "").strip(),
                notes=(raw.get("notes") or "").strip(),
            ))
    rows.sort(key=lambda r: r.date)
    return rows


def session_dates(rows: list[SessionRow]) -> list[str]:
    """Every date in the history, oldest first, deduplicated."""
    return sorted({r.date for r in rows})


def record_session(
    path: Path,
    *,
    date: str,
    reliable_words: int,
    counts: list[MistakeCount],
    source: str = "report",
) -> None:
    """
    Appends one session's counts — one row per tracked category, including the
    ones that stayed at zero.

    The zeros are not padding. Without a row saying "this category was measured
    on this date and found clean", absence can only be inferred from silence,
    and silence is indistinguishable from "nobody looked". The absence streak
    that promotes a mistake to Improvements is built entirely out of those rows.

    Refuses to write a date that already has rows: this file is append-only, and
    a session recorded twice would double every count in it. Re-analysing a
    session means editing the existing rows deliberately, not appending over them.
    """
    if not counts:
        raise ValueError("No categories to record — a session with nothing to say is not a session.")
    if reliable_words <= 0:
        raise ValueError(f"reliable_words must be positive, got {reliable_words}.")

    existing = load(path)
    if any(r.date == date for r in existing):
        raise ValueError(
            f"{path} already has rows for {date}. This file is append-only; recording the "
            f"session twice would double its counts. Edit the existing rows if the analysis "
            f"genuinely changed."
        )

    duplicates = {c.category for c in counts if [x.category for x in counts].count(c.category) > 1}
    if duplicates:
        raise ValueError(f"The same category is listed twice for {date}: {sorted(duplicates)}")

    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS)
        if is_new:
            writer.writeheader()
        for count in counts:
            writer.writerow({
                "date": date,
                "category": count.category,
                "severity": count.severity,
                # Blank, never 0, for "no opportunity to appear".
                "occurrences": "" if count.occurrences is None else count.occurrences,
                "reliable_words": reliable_words,
                "source": source,
                "notes": count.notes,
            })

    logger.info("Recorded %d categories for %s in %s", len(counts), date, path)


def _weighted_rate(measured: list[tuple[str, float]]) -> float:
    """
    Recency-weighted mean rate over the last len(RECENCY_WEIGHTS) measured
    sessions. `measured` is (date, rate) oldest first; only sessions where the
    category was testable are passed in, so an untested session doesn't dilute
    the average toward zero.
    """
    if not measured:
        return 0.0
    recent = [rate for _, rate in measured[-len(RECENCY_WEIGHTS):]][::-1]  # newest first
    weights = RECENCY_WEIGHTS[:len(recent)]
    return round(sum(r * w for r, w in zip(recent, weights)) / sum(weights), 2)


def _direction(measured: list[tuple[str, float]]) -> str:
    """Latest measured rate against the mean of the ones before it. Needs at
    least two measured sessions to say anything at all."""
    if len(measured) < 2:
        return "n/a"
    latest = measured[-1][1]
    earlier = [rate for _, rate in measured[:-1]]
    baseline = sum(earlier) / len(earlier)
    if baseline == 0:
        return "worsening" if latest > 0 else "steady"
    change = (latest - baseline) / baseline
    if change > 0.25:
        return "worsening"
    if change < -0.25:
        return "improving"
    return "steady"


def summarize(rows: list[SessionRow]) -> list[CategoryTrend]:
    """Per-category trends, ranked by impact (highest first)."""
    all_dates = session_dates(rows)
    trends: list[CategoryTrend] = []

    by_category: dict[str, list[SessionRow]] = {}
    for row in rows:
        by_category.setdefault(row.category, []).append(row)

    for category, category_rows in by_category.items():
        category_rows.sort(key=lambda r: r.date)
        measured = [
            (r.date, r.rate_per_1000) for r in category_rows if r.rate_per_1000 is not None
        ]
        seen = [r for r in category_rows if r.occurrences]

        # Newest first, over every session since this category was first
        # tracked — a category simply not listed on a later date is as absent as
        # one listed with a 0, but a blank (untested) neither extends nor breaks
        # the streak. Sessions from before it was ever tracked are not absences:
        # nobody was looking for it yet.
        streak = 0
        untested_since = 0
        occurrences_by_date = {r.date: r.occurrences for r in category_rows}
        first_tracked = category_rows[0].date
        for date in reversed([d for d in all_dates if d >= first_tracked]):
            if date not in occurrences_by_date:
                streak += 1
                continue
            value = occurrences_by_date[date]
            if value is None:
                untested_since += 1
                continue
            if value > 0:
                break
            streak += 1

        weighted = _weighted_rate(measured)
        trends.append(CategoryTrend(
            category=category,
            # The latest severity on record: a category's severity can be
            # reassessed, and the current judgment is the one to rank by.
            severity=category_rows[-1].severity,
            first_seen=category_rows[0].date,
            last_seen=seen[-1].date if seen else None,
            sessions_measured=len(measured),
            total_occurrences=sum(r.occurrences or 0 for r in category_rows),
            latest_rate=measured[-1][1] if measured else None,
            weighted_rate=weighted,
            impact=round(category_rows[-1].severity * weighted, 2),
            absence_streak=streak,
            untested_since=untested_since,
            direction=_direction(measured),
        ))

    trends.sort(key=lambda t: (-t.impact, t.category))
    return trends


def format_table(trends: list[CategoryTrend]) -> str:
    """Plain-text rendering — readable in a terminal and pasteable into a report."""
    if not trends:
        return "No mistakes recorded yet."

    header = f"{'Category':<44} {'Sev':>3} {'Impact':>7} {'Rate/1k':>8} {'Latest':>7} {'Trend':>10} {'Absent':>7}"
    lines = [header, "-" * len(header)]
    for t in trends:
        latest = "—" if t.latest_rate is None else f"{t.latest_rate:.2f}"
        absent = f"{t.absence_streak}" + ("*" if t.ready_for_improvements else "")
        lines.append(
            f"{t.category[:44]:<44} {t.severity:>3} {t.impact:>7.2f} "
            f"{t.weighted_rate:>8.2f} {latest:>7} {t.direction:>10} {absent:>7}"
        )

    promotable = [t.category for t in trends if t.ready_for_improvements]
    if promotable:
        lines.append("")
        lines.append(
            f"* absent {ABSENCE_STREAK_FOR_IMPROVEMENT}+ measured sessions — move to "
            f"Improvements in memory.md: {', '.join(promotable)}"
        )
    untested = [t.category for t in trends if t.untested_since and not t.ready_for_improvements]
    if untested:
        lines.append(
            "Untested recently (no opportunity to appear — absence proves nothing): "
            + ", ".join(untested)
        )
    lines.append("")
    lines.append("Rates are per 1,000 reliable words. Impact = severity x recency-weighted rate.")
    return "\n".join(lines)


def _default_path() -> Path:
    return Path(__file__).parent.parent / "analysis" / "mistakes.csv"


def main(argv: list[str] | None = None) -> int:
    """`python -m voxlib.mistakes` — the trend table, and a way to append to it
    without hand-editing an append-only file."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m voxlib.mistakes",
        description="Read or extend the cross-session mistake history.",
    )
    parser.add_argument("--path", type=Path, default=_default_path(),
                        help="History CSV (default: analysis/mistakes.csv)")
    sub = parser.add_subparsers(dest="command")

    show = sub.add_parser("show", help="Print the trend table (default)")
    show.add_argument("--category", help="Show one category's session-by-session history")

    add = sub.add_parser("add", help="Append one session's counts")
    add.add_argument("--date", required=True, help="Session date, YYYY-MM-DD")
    add.add_argument("--reliable-words", type=int, required=True,
                     help="From this session's row in fluency_history.csv")
    add.add_argument("--source", default="report")
    add.add_argument(
        "counts", nargs="+",
        help='One per tracked category: "Category name:severity:occurrences". '
             'Use an empty occurrences ("Category:3:") when the structure never came up.',
    )

    args = parser.parse_args(argv)

    if args.command == "add":
        counts = []
        for raw in args.counts:
            try:
                category, severity, occurrences = raw.rsplit(":", 2)
            except ValueError:
                parser.error(f'Expected "Category:severity:occurrences", got {raw!r}')
            counts.append(MistakeCount(
                category=category.strip(),
                severity=int(severity),
                occurrences=_parse_occurrences(occurrences),
            ))
        record_session(args.path, date=args.date, reliable_words=args.reliable_words,
                       counts=counts, source=args.source)
        print(f"Recorded {len(counts)} categories for {args.date}.")
        print()

    rows = load(args.path)
    if args.command == "show" and args.category:
        matching = [r for r in rows if r.category.lower() == args.category.lower()]
        if not matching:
            print(f"No rows for {args.category!r}.")
            return 1
        for row in matching:
            rate = "untested" if row.rate_per_1000 is None else f"{row.rate_per_1000:.2f}/1k words"
            print(f"{row.date}  {row.occurrences if row.occurrences is not None else '—':>3}  {rate}")
        return 0

    print(format_table(summarize(rows)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
