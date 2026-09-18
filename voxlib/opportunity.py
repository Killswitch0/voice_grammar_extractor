"""
How many chances a mistake had — the denominator everything else here lacks.

Every figure this project tracks is a numerator. `README.md` says so plainly:
"six article mistakes per thousand words" cannot say *out of how many chances*,
because nothing counted how many singular countable nouns were actually said.
Words spoken stood in for chances, and `voxlib.exposure` exists to check whether
that substitution holds. On this project's own record it does not:

    Within a category, instances vs words spoken      mean  -0.08
    Session total vs words spoken                           -0.26
    Session total vs categories tracked                     +0.57
    Rate per 1,000 vs words spoken                          -0.59

Counts track *how many categories were being looked for* better than they track
anything the speaker did, and the rate falls as sessions get longer — which
means dividing by words is adding a length effect rather than removing one, and
the shortest session on record becomes the worst one.

This module counts the chances instead.

**The machinery already existed, one level too specific.** Every drill item
carries two regexes — `attempted` ("was this structure tried at all?") and
`correct` — and `voxlib.vocab` already counts phrases across the archived
transcripts, on word boundaries, over reliable lines only. What was missing was
a *category-level* trigger: not "listen to music" but "the verbs whose
preposition this speaker gets wrong". That is what `frames/` holds.

    opportunities(c, s) = reliable lines in session s matching TRIGGER[c]
    accuracy(c, s)      = 1 - errors(c, s) / opportunities(c, s)

**This is a proxy, and the page must say so.** A regex matches a lexical frame,
not a grammatical opportunity: a trigger for third-person `-s` that looks for
`he|she|it` + a word also catches "it was", which is not a present-tense slot.
The bias is real. It is also *stable across sessions*, which is the property a
trend needs and the one the per-word rate demonstrably does not have. So this
buys a comparable series, not an exam grade, and nothing here should ever be
printed as "your accuracy is 94%".

**Nothing is adopted on faith.** `voxlib.exposure` scores both denominators for
every category and a frame is used only where the opportunity count predicts the
errors better than the word count does, over enough sessions to mean it. A
category that fails the test keeps the word denominator and the page says which
one it is using. That gate is the whole reason this can be added to a project
whose other metrics are this carefully hedged: it cannot quietly make anything
worse, because a frame that does not earn its place is not used.

Two consequences beyond the denominator, both of which the history has been
waiting for:

**An absence streak can be told from an absent opportunity.** `Comparative
Adjective Formation` sat at "2 of 3 toward promotion" for five sessions, not
because it was improving but because no short adjective in a comparative frame
ever came up. `memory.md` worked that out by hand, late. `frozen` computes it.

**A fall can be told from a mode change.** Article errors went 22 -> 4 between a
monologue and a conversation, and the session report had to argue at length that
this was the recording changing rather than the speaker. An opportunity count
makes that argument arithmetic.

Derived, so this file is rewritten rather than appended to — the same rule
`level.py` follows, and for the same reason: the rows hold no observation of
their own, only the archive read through the frames, so a file holding rows
computed under different frames would draw a trend that is part speaker and part
regex. Every row carries the frame set's fingerprint.
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import fluency, mistakes
from .drill import _short_hash

logger = logging.getLogger(__name__)

HISTORY_COLUMNS = [
    "date",
    "category",
    "opportunities",
    "reliable_lines",
    "reliable_words",
    "fingerprint",
]

# Below this many chances in a session, the session says nothing about accuracy.
# Eight, because one error against three opportunities is 67% and against four is
# 75%, and neither is a measurement — at these counts the rate moves further on
# one instance than any real change would move it. Sessions under the bar keep
# their opportunity count (it is the evidence that the structure did not come up)
# and report no accuracy.
MIN_OPPORTUNITIES = 8

# And how many sessions a category needs at or above that bar before its
# opportunity series is worth reading as a trend. Matches `exposure.MIN_PAIRS`,
# which is the test the frame has to pass anyway.
MIN_SESSIONS = 5


@dataclass
class Frame:
    """One category's trigger: what a chance to make this mistake looks like.

    `note` is not decoration. A regex is an assertion about what counts as an
    opportunity, it is always an approximation, and six months later nobody
    remembers which approximation was chosen. It is printed beside the number.
    """
    category: str
    pattern: re.Pattern
    note: str = ""
    source: str = ""

    @property
    def fingerprint(self) -> str:
        return _short_hash(self.pattern.pattern)


@dataclass
class Count:
    """One category's chances in one session."""
    date: str
    category: str
    opportunities: int
    reliable_lines: int
    # Counted off the archived transcript, not read from `mistakes.csv` — the
    # pipeline tokenizes differently and the two will not always agree to the
    # word. Context for reading the chance count beside it, never a
    # denominator: everything that divides uses the pipeline's figure, so the
    # two can never end up mixed into one rate.
    reliable_words: int
    fingerprint: str

    @property
    def measurable(self) -> bool:
        return self.opportunities >= MIN_OPPORTUNITIES


@dataclass
class Accuracy:
    """One category's chances against its errors, per session and pooled.

    Two different thresholds apply, and confusing them is what the first version
    of this class did. `MIN_OPPORTUNITIES` gates a *single session's* accuracy,
    because one error against three chances is 67% and means nothing. The
    *pooled* figure has no such problem: a frame that yields three chances a
    session across twelve sessions has thirty-six of them, which is a real
    denominator. So the pool takes every measured session and the series marks
    which individual ones were thin.
    """
    category: str
    sessions: int                       # measured sessions contributing to the pool
    opportunities: int                  # pooled chances
    errors: int                         # pooled errors over the same sessions
    fingerprint: str
    series: list[dict]                  # date, opportunities, errors, accuracy|None
    note: str = ""

    @property
    def undercounted(self) -> bool:
        """More errors on record than chances found.

        The two sides are counted in different units on purpose — a chance is a
        *line* where the structure came up, an error is an *occurrence*, and one
        line can hold several. Usually that only makes the accuracy slightly
        pessimistic. When errors exceed chances it means something else: the
        trigger is not matching the frames the errors were actually made in, so
        the denominator is missing lines rather than the speaker being unusually
        wrong. That is a fact about the frame, and it is reported as one.
        """
        return self.opportunities > 0 and self.errors > self.opportunities

    @property
    def accuracy(self) -> Optional[float]:
        """Pooled, not averaged. One numerator over one denominator, for the
        same reason `practice.practice_rates` pools: a session with forty
        chances and one with nine are not two equal observations.

        Withheld rather than clamped when the frame is under-counting. Clamping
        to zero would print "0% accurate", which reads as a statement about the
        speaker; the honest reading is that this frame cannot measure them yet.
        """
        if self.opportunities < MIN_OPPORTUNITIES or self.undercounted:
            return None
        return round(1 - self.errors / self.opportunities, 3)

    @property
    def enough(self) -> bool:
        """Whether the pool is deep enough to read as this speaker's rate rather
        than as this month's luck."""
        return (self.sessions >= MIN_SESSIONS
                and self.opportunities >= MIN_OPPORTUNITIES * MIN_SESSIONS)

    @property
    def frozen(self) -> bool:
        """Whether this category's recent silence is an absence of errors or an
        absence of chances.

        An absence streak built on sessions where the structure never came up is
        not evidence of anything, and reads identically to one built on clean
        production. This is the difference, and it is the reason the opportunity
        count is worth keeping even for a category whose frame fails the
        denominator test.
        """
        recent = self.series[-mistakes.STALL_WINDOW:]
        # No chance at all, not merely a thin one. A frame that yields two or
        # three chances a session is low-frequency, which is a fact about the
        # structure; a frame that yields none is the structure never arising,
        # which is what makes an absence streak meaningless.
        return bool(recent) and all(p["opportunities"] == 0 for p in recent)


def load_frames(directory: Path) -> list[Frame]:
    """Every frame on disk, by category.

    A missing directory is no frames, never an error: `frames/` is personal
    content like `drills/`, and a fresh clone has none. Everything downstream
    falls back to the word denominator, which is what the project did before
    this module existed.
    """
    if not directory.is_dir():
        return []
    import yaml

    frames: list[Frame] = []
    for path in sorted(directory.glob("*.yaml")):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for entry in raw.get("frames") or []:
            missing = {"category", "trigger"} - set(entry)
            if missing:
                raise ValueError(f"{path}: a frame is missing {sorted(missing)}")
            try:
                # VERBOSE so a trigger can be written across several lines and
                # still be readable — a category's frame is a long alternation
                # and on one line it is unreviewable. The cost is that a literal
                # space has to be written `\s`, which frames/README.txt states.
                pattern = re.compile(entry["trigger"], re.IGNORECASE | re.VERBOSE)
            except re.error as exc:
                raise ValueError(f"{path}: {entry['category']} has an unusable "
                                 f"trigger — {exc}") from exc
            frames.append(Frame(category=entry["category"].strip(), pattern=pattern,
                                note=(entry.get("note") or "").strip(), source=path.name))

    duplicates = {f.category for f in frames
                  if [x.category for x in frames].count(f.category) > 1}
    if duplicates:
        raise ValueError(f"More than one frame claims the same category: {sorted(duplicates)}")
    return frames


def count(sessions_dir: Path, frames: list[Frame]) -> list[Count]:
    """
    Chances per category per session, over the archived transcripts.

    Reliable lines only, read through `fluency.reliable_lines_from_annotated`,
    which is the same population every other measurement here divides by — a
    line whisper was unsure of cannot be counted as a chance any more than it
    can be counted as a mistake.

    Counted by *line*, not by match. A line that says "I listen music and he
    listen music" is one chance the speaker had to get this right at the moment
    of speaking, and `mistakes.csv` would record it as one or two occurrences
    depending on how the coach read it. Lines are the unit both sides can agree
    on, and inflating the denominator is the direction that flatters.
    """
    if not sessions_dir.is_dir() or not frames:
        return []

    counts: list[Count] = []
    for archive in sorted(sessions_dir.glob("*.annotated.txt")):
        date = archive.name[:-len(".annotated.txt")]
        if len(date) != 10 or date.count("-") != 2:
            continue
        lines = fluency.reliable_lines_from_annotated(archive.read_text(encoding="utf-8"))
        words = sum(len(line.split()) for line in lines)
        for frame in frames:
            counts.append(Count(
                date=date,
                category=frame.category,
                opportunities=sum(1 for line in lines if frame.pattern.search(line)),
                reliable_lines=len(lines),
                reliable_words=words,
                fingerprint=frame.fingerprint,
            ))
    counts.sort(key=lambda c: (c.date, c.category))
    return counts


def accuracy(counts: list[Count], rows: list[mistakes.SessionRow],
             frames: Optional[list[Frame]] = None) -> list[Accuracy]:
    """Chances against errors, per category.

    Only sessions the mistake history actually measured contribute: a session
    where the coach recorded a blank (no opportunity seen) is not evidence of
    clean production, whatever the regex found, and scoring it would invent an
    accuracy out of a session nobody judged.
    """
    notes = {f.category: f.note for f in frames or []}
    errors: dict[tuple[str, str], Optional[int]] = {
        (r.date, r.category): r.occurrences for r in rows}

    grouped: dict[str, list[Count]] = {}
    for item in counts:
        grouped.setdefault(item.category, []).append(item)

    out = []
    for category, items in sorted(grouped.items()):
        items.sort(key=lambda c: c.date)
        series, total_ops, total_errs, sessions = [], 0, 0, 0
        for item in items:
            recorded = errors.get((item.date, item.category))
            # Every session the coach actually judged joins the pool, however
            # few chances it held — the pool is where small frames become
            # measurable. Only the per-session figure needs the threshold.
            if recorded is not None:
                total_ops += item.opportunities
                total_errs += recorded
                sessions += 1
            series.append({
                "date": item.date,
                "opportunities": item.opportunities,
                "errors": recorded,
                "measurable": item.measurable,
                "accuracy": (round(1 - recorded / item.opportunities, 3)
                             if item.measurable and recorded is not None
                             and recorded <= item.opportunities else None),
            })
        out.append(Accuracy(
            category=category, sessions=sessions, opportunities=total_ops,
            errors=total_errs, fingerprint=items[-1].fingerprint, series=series,
            note=notes.get(category, ""),
        ))
    return out


def record(path: Path, counts: list[Count]) -> None:
    """One row per category per session, rewritten in full — see the module
    docstring on why this history is not append-only."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS)
        writer.writeheader()
        for item in counts:
            writer.writerow({
                "date": item.date, "category": item.category,
                "opportunities": item.opportunities,
                "reliable_lines": item.reliable_lines,
                "reliable_words": item.reliable_words,
                "fingerprint": item.fingerprint,
            })
    logger.info("Wrote %d opportunity counts to %s", len(counts), path)


def format_report(scores: list[Accuracy], verdicts: Optional[dict] = None,
                  frames_loaded: int = 0) -> str:
    if not scores:
        # Two different states, and telling someone to write the frames they
        # already have is the unhelpful half of the pair.
        if frames_loaded:
            return (f"{frames_loaded} frame(s) loaded, but no archived transcripts to count "
                    "chances in. Sessions are archived to analysis/sessions/*.annotated.txt "
                    "by the analyze-recording workflow — check --analysis points at the "
                    "right directory.")
        return ("No frames in frames/, so nothing counts chances yet. Each frame says what "
                "an opportunity to make one mistake looks like; see frames/README.txt.")

    verdicts = verdicts or {}
    header = (f"{'Category':<44}{'Chances':>9}{'Errors':>8}{'Accuracy':>10}"
              f"{'Sessions':>10}  Denominator")
    lines = [header, "-" * len(header)]
    for score in sorted(scores, key=lambda s: -s.opportunities):
        verdict = verdicts.get(score.category)
        using = "—"
        if verdict is not None:
            using = "opportunities" if verdict.get("prefer_opportunities") else "words"
        acc = "—" if score.accuracy is None else f"{score.accuracy * 100:.1f}%"
        lines.append(f"{score.category[:42]:<44}{score.opportunities:>9}{score.errors:>8}"
                     f"{acc:>10}{score.sessions:>10}  {using}")

    frozen = [s.category for s in scores if s.frozen]
    if frozen:
        lines += ["", f"No chance to make these in the last {mistakes.STALL_WINDOW} sessions — "
                      f"their absence streaks are frozen, not earned: " + ", ".join(frozen)]
    thin = [s.category for s in scores if not s.enough]
    if thin:
        lines.append(f"Fewer than {MIN_SESSIONS} measured sessions, or fewer than "
                     f"{MIN_OPPORTUNITIES * MIN_SESSIONS} chances pooled across them "
                     f"({len(thin)} of {len(scores)}) — counted, not yet a trend: "
                     + ", ".join(thin[:4]) + (", …" if len(thin) > 4 else ""))
    lines += [
        "",
        "A chance is a reliable line matching the category's trigger — a lexical frame, not",
        "a parsed structure, so this is a proxy and the same proxy every session. It buys a",
        "comparable series, not an exam grade. `python -m voxlib.exposure` decides which",
        "denominator each category actually gets.",
    ]
    return "\n".join(lines)


def _repo_root() -> Path:
    return Path(__file__).parent.parent


def main(argv: list[str] | None = None) -> int:
    """`python -m voxlib.opportunity` — how many chances each mistake had."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m voxlib.opportunity",
        description="Count the chances each tracked mistake had, from the archived "
                    "transcripts.",
    )
    parser.add_argument("--analysis", type=Path, default=_repo_root() / "analysis",
                        help="Directory holding the histories (default: analysis/)")
    parser.add_argument("--frames", type=Path, default=_repo_root() / "frames",
                        help="Directory holding the trigger definitions (default: frames/)")
    parser.add_argument("--write", action="store_true",
                        help="Write analysis/opportunity_history.csv (rewritten, not appended)")
    args = parser.parse_args(argv)

    frames = load_frames(args.frames)
    counts = count(args.analysis / "sessions", frames)
    rows = mistakes.load(args.analysis / "mistakes.csv")
    scores = accuracy(counts, rows, frames)

    from . import exposure
    verdicts = {v.category: {"prefer_opportunities": v.prefer_opportunities}
                for v in exposure.compare_denominators(rows, counts)}

    print(format_report(scores, verdicts, frames_loaded=len(frames)))
    if args.write and counts:
        record(args.analysis / "opportunity_history.csv", counts)
        print(f"\nWrote {args.analysis / 'opportunity_history.csv'}")
    return 0 if scores else 1


if __name__ == "__main__":
    raise SystemExit(main())
