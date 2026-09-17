"""
Does dividing by words actually make sessions comparable?

Every number in `analysis/` that matters is a rate per 1,000 reliable words, and
the reasoning behind that is sound on its face: a count from a long session and
a count from a short one are not the same evidence, so divide by how much was
said. `mistakes.py` says exactly this, and it is the spine of the whole project.

Dividing is only right if the thing being counted actually scales with the
divisor. If a speaker makes article errors at some rate per word, then twice the
words should mean roughly twice the errors, and the rate is the stable quantity.
If instead the number of errors *found* is set by something else — how closely
the transcript was read, how many categories were being looked for that day —
then the count does not scale with words at all, and dividing by them does not
remove a length effect. It manufactures one: the same count in a shorter session
reads as a higher rate, and the shortest session on record becomes the worst.

This module measures which of those is true, rather than assuming. Three
questions, all answerable from the recorded history:

  - **Within one category, do instances rise with words?** The direct test. A
    per-word phenomenon says yes.
  - **Does the session total rise with words, or with the number of categories
    being tracked?** If it tracks the categories, the total is a measure of
    attention rather than of speech.
  - **Does the resulting rate fall as sessions get longer?** The symptom. A
    strong negative here with no positive answer to the first question means the
    normalization is the cause of the pattern, not the cure for it.

It changes no metric and writes no history. The normalization is the owner's
design decision, embedded in the trackers, the level scale and every chart, and
a diagnostic's job is to say what the evidence supports — not to quietly swap
the denominator underneath months of recorded numbers. Re-run it as sessions
accumulate: the answer depends on the spread of session lengths on record, and
early on that spread is narrow enough that a real relationship could hide in it.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import mistakes

# Below this many paired observations a correlation is not worth reporting: with
# a handful of points, any value at all is ordinary.
MIN_PAIRS = 5

# How strong a within-category relationship has to be before the per-word model
# is considered supported. Deliberately low — this is asking whether there is
# any signal, not whether it is strong.
SUPPORTS_PER_WORD = 0.3

# And how strong the rate-versus-length relationship has to be before it is
# called a problem rather than scatter.
CONCERNING = -0.4


def correlation(xs: list[float], ys: list[float]) -> Optional[float]:
    """Pearson's r, or None when there are too few points to mean anything."""
    if len(xs) < MIN_PAIRS or len(xs) != len(ys):
        return None
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    spread = math.sqrt(sum((x - mean_x) ** 2 for x in xs)
                       * sum((y - mean_y) ** 2 for y in ys))
    if spread == 0:
        return None
    return round(sum((x - mean_x) * (y - mean_y)
                     for x, y in zip(xs, ys)) / spread, 3)


@dataclass
class Finding:
    """One category's answer to "do instances rise with words?"."""
    category: str
    pairs: int
    r: Optional[float]


@dataclass
class Report:
    sessions: int
    word_range: tuple[int, int]
    per_category: list[Finding]
    mean_within_category: Optional[float]
    total_vs_words: Optional[float]
    total_vs_categories: Optional[float]
    rate_vs_words: Optional[float]

    @property
    def supports_per_word(self) -> bool:
        return (self.mean_within_category is not None
                and self.mean_within_category >= SUPPORTS_PER_WORD)

    @property
    def length_effect(self) -> bool:
        return self.rate_vs_words is not None and self.rate_vs_words <= CONCERNING

    @property
    def verdict(self) -> str:
        if self.mean_within_category is None:
            return "not enough history to tell yet"
        if self.supports_per_word:
            return "counts rise with words, so the per-1,000 rate is doing its job"
        if self.length_effect:
            return ("counts do not rise with words, and the rate falls as sessions "
                    "get longer — the normalization is adding the length effect, "
                    "not removing it")
        return "counts do not rise with words; the rate is not obviously distorted, "\
               "but it is not correcting for anything either"

    @property
    def spread(self) -> float:
        """How wide the session lengths are. A narrow spread can hide a real
        relationship, and is the first thing to check before believing a null."""
        low, high = self.word_range
        return round(high / low, 2) if low else 0.0


def analyse(rows: list[mistakes.SessionRow]) -> Optional[Report]:
    dates = mistakes.session_dates(rows)
    if len(dates) < MIN_PAIRS:
        return None

    words_by_date, count_by_date, cats_by_date = {}, {}, {}
    for date in dates:
        day = [r for r in rows if r.date == date]
        words_by_date[date] = day[0].reliable_words
        count_by_date[date] = sum(r.occurrences or 0 for r in day)
        cats_by_date[date] = len(day)

    per_category = []
    for category in sorted({r.category for r in rows}):
        observed = [(r.reliable_words, r.occurrences) for r in rows
                    if r.category == category and r.occurrences is not None]
        if len(observed) < MIN_PAIRS:
            continue
        per_category.append(Finding(
            category=category,
            pairs=len(observed),
            r=correlation([o[0] for o in observed], [float(o[1]) for o in observed]),
        ))

    usable = [f.r for f in per_category if f.r is not None]
    words = [float(words_by_date[d]) for d in dates]
    counts = [float(count_by_date[d]) for d in dates]
    cats = [float(cats_by_date[d]) for d in dates]
    rates = [count_by_date[d] / words_by_date[d] * 1000 if words_by_date[d] else 0.0
             for d in dates]

    return Report(
        sessions=len(dates),
        word_range=(min(words_by_date.values()), max(words_by_date.values())),
        per_category=per_category,
        # Averaged across categories: one category's correlation over a handful
        # of sessions is mostly noise, but the average of many independent ones
        # would still lean positive if the per-word model held.
        mean_within_category=(round(statistics.mean(usable), 3) if usable else None),
        total_vs_words=correlation(words, counts),
        total_vs_categories=correlation(cats, counts),
        rate_vs_words=correlation(words, rates),
    )


def format_report(report: Optional[Report]) -> str:
    if report is None:
        return f"Fewer than {MIN_PAIRS} sessions recorded — nothing to test yet."

    def show(value: Optional[float]) -> str:
        return "—" if value is None else f"{value:+.2f}"

    lines = [
        f"Sessions: {report.sessions}.  Reliable words range {report.word_range[0]:,}"
        f"–{report.word_range[1]:,} ({report.spread}x).",
        "",
        "  Within a category, instances vs words spoken",
    ]
    for finding in report.per_category:
        lines.append(f"      {finding.category[:46]:<46} {show(finding.r):>7}"
                     f"  ({finding.pairs} sessions)")
    lines += [
        f"      {'mean across categories':<46} {show(report.mean_within_category):>7}",
        "",
        f"  Session total vs words spoken                   {show(report.total_vs_words):>7}",
        f"  Session total vs categories tracked             "
        f"{show(report.total_vs_categories):>7}",
        f"  Rate per 1,000 vs words spoken                  {show(report.rate_vs_words):>7}",
        "",
        f"  Verdict: {report.verdict}.",
    ]
    if not report.supports_per_word and report.spread < 2:
        lines.append(f"  Caution: session lengths span only {report.spread}x, which is "
                     f"narrow enough to hide a real relationship. Re-run this as longer "
                     f"and shorter sessions accumulate.")
    lines += [
        "",
        "  This changes nothing on its own. The per-1,000 normalization is embedded in",
        "  the trackers, the level scale and every chart; what to do about it is a",
        "  decision, not a calculation.",
    ]
    return "\n".join(lines)


def _default_path() -> Path:
    return Path(__file__).parent.parent / "analysis" / "mistakes.csv"


def main(argv: list[str] | None = None) -> int:
    """`python -m voxlib.exposure` — is the per-1,000 rate comparing like with like?"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m voxlib.exposure",
        description="Test whether mistake counts scale with how much was said.",
    )
    parser.add_argument("--path", type=Path, default=_default_path(),
                        help="Mistake history (default: analysis/mistakes.csv)")
    args = parser.parse_args(argv)

    report = analyse(mistakes.load(args.path))
    print(format_report(report))
    return 0 if report else 1


if __name__ == "__main__":
    raise SystemExit(main())
