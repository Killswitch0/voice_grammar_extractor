"""
The practice history — the middle rung, and the one that was missing.

Three things can be true of a grammar pattern, and until this file existed only
the outer two were measured:

1. **Known.** A drill asks for it directly, one structure in mind, unlimited
   thinking time. `drills.csv` answers this, and by 2026-08-17 it answered "yes"
   for every category on record: four attempts, all 100%.
2. **Produced when attending.** A typed conversation where the topic is real and
   the structure isn't announced — harder than a drill, far easier than speech.
   Nothing measured this at all. `conversation_focus_log.md` recorded that a
   pattern had been practised and on what date, never how it went.
3. **Produced unmonitored.** A recording. `mistakes.csv` answers this, and it
   kept answering "no" for the same categories the drills scored 100% on.

The gap between 1 and 3 is where the whole loop was stuck, and it has two very
different explanations that the two files together cannot distinguish: either the
pattern isn't really known and the drill is too easy, or it is known and simply
not automatic. Rung 2 separates them. A category that survives attended
production and still fails in speech needs volume, not explanation — and a
category that fails already under attention needs the explanation after all.

Two other things this makes possible, both asked for by CLAUDE.md and neither
answerable before:

**A denominator on the practice side.** Errors are counted against the words the
learner actually produced, per 1,000, the same normalization `mistakes.csv` uses
— so the two rates sit in the same units and can be read against each other.
That is the reason a practice session is asked for a couple of long turns rather
than a run of one-line answers: without a few hundred words there is nothing to
divide by.

**The treatment/instrument budget.** General rule 19 says a recording measures
and only corrected repetitions train, and asks for the two counts to be compared
each session. Nothing counted the repetitions, so the comparison was done from
memory or not at all. `reproductions` counts them, and the table prints the two
side by side.

Written by hand, via `python -m voxlib.practice add`, at the end of a practice
session — the same arrangement as `mistakes.csv`: append-only, one row per
session, and nothing edits a row once it is written. Unlike `mistakes.csv` a
repeated date is allowed, because two practice sessions in one day are two
sessions.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

HISTORY_COLUMNS = [
    "date",
    "focus",
    "learner_words",
    "errors",
    "error_breakdown",
    "reproductions",
    "long_turns",
    "notes",
]

# Errors and words are separated by a colon in the breakdown, sessions by a
# semicolon: "Article Errors:3;Redundant Reflexive Pronoun:1". A CSV cell rather
# than its own file because nothing joins on it — it is read whole or not at all.
_CATEGORY_SEPARATOR = ";"
_COUNT_SEPARATOR = ":"

# The window the budget line covers. Two weeks, because rule 19 budgets in weeks
# ("roughly two recordings a week") and a single week is short enough that one
# quiet weekend reads as a collapse.
BUDGET_DAYS = 14

# How many recent practice sessions the attended-vs-unmonitored comparison pools.
# Three, matching the recency window the mistake history uses: one session is too
# few words to divide by, and the whole history would average away the present.
COMPARISON_SESSIONS = 3


@dataclass
class PracticeSession:
    date: str
    focus: str
    learner_words: int
    errors_by_category: dict[str, int] = field(default_factory=dict)
    reproductions: int = 0
    long_turns: int = 0
    notes: str = ""

    @property
    def errors(self) -> int:
        return sum(self.errors_by_category.values())

    @property
    def rate_per_1000(self) -> Optional[float]:
        """Errors per 1,000 words the learner produced — the same unit as
        `mistakes.csv`, so the two can be read against each other."""
        if self.learner_words <= 0:
            return None
        return round(self.errors * 1000 / self.learner_words, 2)


def _format_breakdown(errors: dict[str, int]) -> str:
    return _CATEGORY_SEPARATOR.join(
        f"{category}{_COUNT_SEPARATOR}{count}" for category, count in sorted(errors.items())
    )


def _parse_breakdown(raw: str) -> dict[str, int]:
    errors: dict[str, int] = {}
    for entry in raw.split(_CATEGORY_SEPARATOR):
        entry = entry.strip()
        if not entry:
            continue
        category, _, count = entry.rpartition(_COUNT_SEPARATOR)
        try:
            errors[category.strip()] = int(count)
        except ValueError:
            logger.warning("Ignoring unreadable error count %r", entry)
    return errors


def load(path: Path) -> list[PracticeSession]:
    if not path.exists():
        return []
    sessions = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            sessions.append(PracticeSession(
                date=raw["date"].strip(),
                focus=(raw.get("focus") or "").strip(),
                learner_words=int(raw["learner_words"]),
                errors_by_category=_parse_breakdown(raw.get("error_breakdown") or ""),
                reproductions=int(raw.get("reproductions") or 0),
                long_turns=int(raw.get("long_turns") or 0),
                notes=(raw.get("notes") or "").strip(),
            ))
    sessions.sort(key=lambda s: s.date)
    return sessions


def record_session(path: Path, *, date: str, focus: str, learner_words: int,
                   errors_by_category: dict[str, int], reproductions: int = 0,
                   long_turns: int = 0, notes: str = "") -> None:
    """
    Appends one practice session.

    A date that already has a row is fine — two practice sessions in a day are
    two sessions, and unlike a recording there is no transcript to merge twice.
    What is refused is a session with no words in it: an error count without a
    denominator is the thing this file exists to stop producing.
    """
    if learner_words <= 0:
        raise ValueError(
            f"learner_words must be positive, got {learner_words}. Errors without a word "
            f"count cannot be normalized, which makes them uncomparable with mistakes.csv "
            f"and with every other practice session."
        )
    if reproductions < 0 or long_turns < 0:
        raise ValueError("reproductions and long_turns cannot be negative.")
    negative = sorted(c for c, n in errors_by_category.items() if n < 0)
    if negative:
        raise ValueError(f"Negative error counts for: {negative}")

    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow({
            "date": date,
            "focus": focus,
            "learner_words": learner_words,
            "errors": sum(errors_by_category.values()),
            "error_breakdown": _format_breakdown(errors_by_category),
            "reproductions": reproductions,
            "long_turns": long_turns,
            "notes": notes,
        })

    logger.info("Recorded a practice session for %s: %d words, %d errors", date,
                learner_words, sum(errors_by_category.values()))


def practice_rates(sessions: list[PracticeSession],
                   window: int = COMPARISON_SESSIONS) -> dict[str, float]:
    """
    Per-category error rate per 1,000 learner words, over the last `window`
    sessions.

    Pooled rather than averaged per session: a 90-word session and a 400-word one
    are not two equal observations, and averaging their rates would let the short
    one swing the result. One numerator over one denominator.
    """
    recent = sessions[-window:] if window else sessions
    words = sum(s.learner_words for s in recent)
    if not words:
        return {}
    totals: dict[str, int] = {}
    for session in recent:
        for category, count in session.errors_by_category.items():
            totals[category] = totals.get(category, 0) + count
    return {category: round(count * 1000 / words, 2) for category, count in totals.items()}


def format_table(sessions: list[PracticeSession], *,
                 recording_dates: Optional[list[str]] = None,
                 speech_rates: Optional[dict[str, float]] = None,
                 today: Optional[str] = None) -> str:
    if not sessions:
        return ("No practice sessions recorded yet. Say \"let's practice\" to run one — and "
                "see general rule 19 about which side of the budget that is.")

    header = (f"{'Date':<12} {'Focus':<34} {'Words':>7} {'Errors':>7} {'Per 1k':>7} "
              f"{'Repro':>6} {'Long':>5}")
    lines = [header, "-" * len(header)]
    for s in sessions:
        rate = "—" if s.rate_per_1000 is None else f"{s.rate_per_1000:.2f}"
        lines.append(f"{s.date:<12} {s.focus[:34]:<34} {s.learner_words:>7} {s.errors:>7} "
                     f"{rate:>7} {s.reproductions:>6} {s.long_turns:>5}")

    if speech_rates:
        practice = practice_rates(sessions)
        shared = sorted(set(practice) & set(speech_rates),
                        key=lambda c: -speech_rates[c])
        if shared:
            lines.append("")
            lines.append(f"Attended vs unmonitored, errors per 1,000 words "
                         f"(last {COMPARISON_SESSIONS} practice sessions against the latest "
                         f"recording):")
            lines.append(f"  {'Category':<42} {'Typed':>7} {'Spoken':>7}")
            for category in shared:
                lines.append(f"  {category[:42]:<42} {practice[category]:>7.2f} "
                             f"{speech_rates[category]:>7.2f}")
            lines.append("  Worse typed than spoken: the pattern isn't reliably known yet — "
                         "explain it. Clean typed and failing spoken: it's known and not "
                         "automatic — that needs volume, not another explanation.")

    lines.append("")
    lines.append(_budget_line(sessions, recording_dates or [], today))
    return "\n".join(lines)


def _budget_line(sessions: list[PracticeSession], recording_dates: list[str],
                 today: Optional[str]) -> str:
    """
    Rule 19's two counts, side by side.

    The recording is the instrument and the corrected repetitions are the
    treatment, and the failure mode the rule was written for is a report that
    recommends five things to notice into a fortnight containing no corrected
    repetitions at all.
    """
    end = date_type.fromisoformat(today) if today else date_type.today()
    start = (end - timedelta(days=BUDGET_DAYS)).isoformat()

    recent = [s for s in sessions if s.date > start]
    recordings = [d for d in recording_dates if d > start]
    repetitions = sum(s.reproductions for s in recent)

    line = (f"Last {BUDGET_DAYS} days: {len(recordings)} recording(s), {len(recent)} practice "
            f"session(s), {repetitions} corrected repetition(s).")
    if len(recordings) > len(recent):
        line += (" The instrument is running ahead of the treatment — rule 19: more "
                 "recordings don't improve the measurement, they consume the time the "
                 "practice needed.")
    elif not repetitions and recent:
        line += (" Practice sessions with no corrected repetitions in them are the failure "
                 "rule 19 describes (P22).")
    return line


def _default_path() -> Path:
    return Path(__file__).parent.parent / "analysis" / "practice_history.csv"


def main(argv: list[str] | None = None) -> int:
    """`python -m voxlib.practice` — the practice history, and a way to append to
    it without hand-editing an append-only file."""
    import argparse

    analysis = _default_path().parent
    parser = argparse.ArgumentParser(
        prog="python -m voxlib.practice",
        description="Read or extend the conversation-practice history.",
    )
    parser.add_argument("--path", type=Path, default=_default_path(),
                        help="History CSV (default: analysis/practice_history.csv)")
    parser.add_argument("--mistakes", type=Path, default=analysis / "mistakes.csv",
                        help="Recording history, for the comparison and the budget line")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("show", help="Print the history (default)")

    add = sub.add_parser("add", help="Append one practice session")
    add.add_argument("--date", default=date_type.today().isoformat())
    add.add_argument("--focus", default="",
                     help="The `## <Mistake Name>` heading drilled, or free text if none")
    add.add_argument("--words", type=int, required=True,
                     help="Words the learner produced this session — the denominator")
    add.add_argument("--reproductions", type=int, default=0,
                     help="P22 re-productions they completed")
    add.add_argument("--long-turns", type=int, default=0,
                     help="P23 long turns they gave")
    add.add_argument("--notes", default="")
    add.add_argument("errors", nargs="*", metavar="CATEGORY:COUNT",
                    help='One per category that produced an error, e.g. "Article Errors:3". '
                         "Nothing at all means a clean session.")

    args = parser.parse_args(argv)

    if args.command == "add":
        errors: dict[str, int] = {}
        for raw in args.errors:
            category, _, count = raw.rpartition(_COUNT_SEPARATOR)
            if not category or not count.strip().isdigit():
                parser.error(f'Expected "Category:count", got {raw!r}')
            if category in errors:
                parser.error(f"{category!r} is listed twice — add the counts up instead.")
            errors[category] = int(count)

        try:
            record_session(args.path, date=args.date, focus=args.focus,
                           learner_words=args.words, errors_by_category=errors,
                           reproductions=args.reproductions, long_turns=args.long_turns,
                           notes=args.notes)
        except ValueError as error:
            parser.error(str(error))
        print(f"Recorded {args.date} in {args.path}: {args.words} words, "
              f"{sum(errors.values())} errors, {args.reproductions} re-productions.")
        return 0

    recording_dates: list[str] = []
    speech_rates: dict[str, float] = {}
    try:
        from voxlib import mistakes as mistakes_module

        rows = mistakes_module.load(args.mistakes)
        recording_dates = mistakes_module.session_dates(rows)
        speech_rates = {
            trend.category: trend.latest_rate
            for trend in mistakes_module.summarize(rows)
            if trend.latest_rate is not None
        }
    except Exception:  # missing or malformed — the practice table still stands alone
        logger.warning("Could not read %s; printing the practice history without the "
                       "comparison", args.mistakes)

    print(format_table(load(args.path), recording_dates=recording_dates,
                       speech_rates=speech_rates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
