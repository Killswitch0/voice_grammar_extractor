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


@dataclass
class DenominatorVerdict:
    """Which denominator a category has actually earned.

    The per-word rate is this project's default and is embedded everywhere, so
    replacing it for a category is a claim that has to be paid for: the
    opportunity count must predict that category's errors *better* than words
    do, and well enough to be a relationship rather than scatter. Anything
    short of that keeps the word denominator, and the page says which one it is
    showing — a mixed table is honest, a silently swapped denominator is not.
    """
    category: str
    pairs: int
    r_words: Optional[float]
    r_opportunities: Optional[float]

    @property
    def prefer_opportunities(self) -> bool:
        if self.r_opportunities is None or self.pairs < MIN_PAIRS:
            return False
        if self.r_opportunities < SUPPORTS_PER_WORD:
            return False
        # A word correlation that is absent is not a bar to clear; one that is
        # present has to be beaten.
        return self.r_words is None or self.r_opportunities > self.r_words

    @property
    def verdict(self) -> str:
        if self.r_opportunities is None or self.pairs < MIN_PAIRS:
            return f"too few sessions to test (needs {MIN_PAIRS})"
        if self.prefer_opportunities:
            return "chances predict the errors better than words do"
        if self.r_opportunities < SUPPORTS_PER_WORD:
            return "the trigger does not predict the errors either — rewrite it or drop it"
        return "no better than words; keeping the per-1,000 rate"


def compare_denominators(rows: list[mistakes.SessionRow], counts: list) -> list[DenominatorVerdict]:
    """Score both denominators for every category that has a frame.

    `counts` is `list[opportunity.Count]`, passed in rather than imported, so
    this module keeps its single dependency and `opportunity` keeps its own —
    the two would otherwise import each other.

    Both correlations are taken over exactly the same sessions: the ones where
    the category was measured *and* a chance count exists. Scored over different
    session sets, the comparison would be between two different questions.
    """
    opportunities = {(c.date, c.category): c.opportunities for c in counts}
    by_category: dict[str, list[mistakes.SessionRow]] = {}
    for row in rows:
        if row.occurrences is not None and (row.date, row.category) in opportunities:
            by_category.setdefault(row.category, []).append(row)

    verdicts = []
    for category, observed in sorted(by_category.items()):
        observed.sort(key=lambda r: r.date)
        errors = [float(r.occurrences) for r in observed]
        words = [float(r.reliable_words) for r in observed]
        chances = [float(opportunities[(r.date, r.category)]) for r in observed]
        verdicts.append(DenominatorVerdict(
            category=category,
            pairs=len(observed),
            r_words=correlation(words, errors),
            r_opportunities=correlation(chances, errors),
        ))
    return verdicts


def format_denominators(verdicts: list[DenominatorVerdict]) -> str:
    if not verdicts:
        return ("No frames to test — nothing counts chances yet. See frames/README.txt.")

    def show(value: Optional[float]) -> str:
        return "—" if value is None else f"{value:+.2f}"

    header = f"{'Category':<44}{'vs words':>10}{'vs chances':>12}{'n':>4}  Verdict"
    lines = [header, "-" * len(header)]
    for v in sorted(verdicts, key=lambda v: (not v.prefer_opportunities, v.category)):
        lines.append(f"{v.category[:42]:<44}{show(v.r_words):>10}"
                     f"{show(v.r_opportunities):>12}{v.pairs:>4}  {v.verdict}")
    winners = [v.category for v in verdicts if v.prefer_opportunities]
    lines += ["", f"{len(winners)} of {len(verdicts)} categories have earned the chance-based "
                  f"denominator." + (" The rest keep the per-1,000 rate." if winners else "")]
    return "\n".join(lines)


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
    parser.add_argument("--frames", type=Path, default=_default_path().parent.parent / "frames",
                        help="Trigger definitions, to score the chance-based denominator "
                             "against the per-word one (default: frames/)")
    args = parser.parse_args(argv)

    rows = mistakes.load(args.path)
    report = analyse(rows)
    print(format_report(report))

    # The second question, and the one with something to do about it: where a
    # frame exists, is dividing by chances better than dividing by words?
    from . import opportunity
    frames = opportunity.load_frames(args.frames)
    if frames:
        counts = opportunity.count(args.path.parent / "sessions", frames)
        print()
        print(format_denominators(compare_denominators(rows, counts)))
    return 0 if report else 1


if __name__ == "__main__":
    raise SystemExit(main())
