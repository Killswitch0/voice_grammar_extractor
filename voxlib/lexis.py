"""
Lexical range — the one CEFR dimension this project measured nowhere.

A level estimate rests on four things: how accurately the speaker speaks, how
fluently, how widely, and how well they interact. Three of those were already
being recorded. Range was not, so a CEFR estimate was carrying it on impression
alone — which is exactly the kind of judgment that drifts when a language model
re-reads its own previous prose every session.

What is measured, and why these two:

  - **Moving-average type-token ratio.** The obvious measure of vocabulary
    variety is distinct words over total words, and it is unusable: it falls as
    a transcript gets longer, purely because common words repeat. Across the
    sessions on record the distinct-word count tracks session length almost
    exactly — it measures how long the speaker talked, not how widely. MATTR
    averages the ratio over a fixed window instead, so a short session and a
    long one are comparable. In practice it varies within a narrow band from
    session to session, which is stable enough to gate a level on.

  - **New words per 1,000, against a rolling baseline.** Variety within a
    session says nothing about growth: the same words, well shuffled, score the
    same every time. So this counts words the speaker has not used recently.

    The baseline is the previous three sessions, not the whole archive, and that
    is the difference between a measure and an artefact. Counted against
    everything before it, novelty decays whatever the speaker does — the union
    grows every session, so there is less left to be new against. Measured
    that way the figure falls steadily whatever the speaker does — a saturation
    curve of the corpus, which reads as someone running out of vocabulary
    rather than as a fact about the archive. Held to a fixed three-session window the
    denominator of novelty stops moving and the number becomes comparable
    across months. Both are recorded; only the rolling one is fit to gate a
    level on.

    Either way it needs no external frequency list — the baseline is the
    speaker's own history, which also means the number is about them rather
    than about a published corpus.

Both are computed over the reliable lines only, the same population every other
metric in `analysis/` uses, read through `fluency.reliable_lines_from_annotated`
so the definition of "reliable" lives in one place. The annotated archive is
what makes this backfillable: it already exists for every session ever
analysed.
"""

from __future__ import annotations

import csv
import logging
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import fluency

logger = logging.getLogger(__name__)

# A word for counting purposes: letters, with internal apostrophes kept so
# "don't" and "it's" are one word each rather than two or three.
WORD = re.compile(r"[a-z]+(?:'[a-z]+)*")

# The window MATTR averages over, and how far it steps. Short enough that a
# brief session still yields dozens of windows, and long enough that the ratio
# is not dominated by one sentence's worth of repetition.
MATTR_WINDOW = 400
MATTR_STEP = 25

# How many previous sessions "new" is measured against. Fixed, so that the
# amount of vocabulary a word has to be absent from does not grow with the
# archive — see the module docstring.
RECENT_BASELINE_SESSIONS = 3

HISTORY_COLUMNS = [
    "date",
    "words",
    "distinct",
    "mattr",
    "new_words",
    "new_per_1000",
    "baseline_sessions",
    "new_vs_recent",
    "new_vs_recent_per_1000",
    "recent_baseline_sessions",
]


@dataclass
class LexisMetrics:
    date: str
    words: int
    distinct: int
    # None rather than 0.0 when the session is shorter than one window: a ratio
    # nobody could compute is not a ratio of zero.
    mattr: Optional[float]
    # None for the first session on record, which has no earlier vocabulary to
    # be new against — the same "absent is not untested" rule the mistake
    # history runs on.
    new_words: Optional[int]
    new_per_1000: Optional[float]
    baseline_sessions: int
    # Against the previous `RECENT_BASELINE_SESSIONS` only — the comparable one.
    new_vs_recent: Optional[int] = None
    new_vs_recent_per_1000: Optional[float] = None
    recent_baseline_sessions: int = 0


def words_in(text: str) -> list[str]:
    return WORD.findall(text.lower())


def words_from_annotated(text: str) -> list[str]:
    """Every reliable word of a session, in order."""
    words: list[str] = []
    for line in fluency.reliable_lines_from_annotated(text):
        words.extend(words_in(line))
    return words


def mattr(words: list[str], window: int = MATTR_WINDOW, step: int = MATTR_STEP) -> Optional[float]:
    """Type-token ratio averaged over a sliding window, or None if too short.

    The length-independence is the entire point; see the module docstring.
    """
    if len(words) < window:
        return None
    ratios = [len(set(words[i:i + window])) / window
              for i in range(0, len(words) - window + 1, step)]
    return round(statistics.mean(ratios), 4)


def measure_session(text: str, *, date: str, baseline: set[str], baseline_sessions: int,
                    recent: Optional[set[str]] = None,
                    recent_sessions: int = 0) -> LexisMetrics:
    """One session, against the vocabulary of the sessions before it."""
    words = words_from_annotated(text)
    distinct = set(words)
    new = distinct - baseline if baseline_sessions else None
    fresh = distinct - recent if recent is not None and recent_sessions else None

    def rate(count: int) -> Optional[float]:
        return round(count / len(words) * 1000, 2) if words else None

    return LexisMetrics(
        date=date,
        words=len(words),
        distinct=len(distinct),
        mattr=mattr(words),
        new_words=len(new) if new is not None else None,
        new_per_1000=rate(len(new)) if new is not None else None,
        baseline_sessions=baseline_sessions,
        new_vs_recent=len(fresh) if fresh is not None else None,
        new_vs_recent_per_1000=rate(len(fresh)) if fresh is not None else None,
        recent_baseline_sessions=recent_sessions,
    )


def measure_history(sessions_dir: Path) -> list[LexisMetrics]:
    """Every archived session, oldest first, each read against its own past.

    Order matters and is not optional: "new" means new at the time, so the
    baseline is the union of the sessions before this one, never the whole
    corpus.
    """
    archives = sorted(sessions_dir.glob("*.annotated.txt")) if sessions_dir.is_dir() else []
    baseline: set[str] = set()
    history: list[set[str]] = []
    out: list[LexisMetrics] = []
    for archive in archives:
        date = archive.name.split(".")[0]
        if len(date) != 10 or date.count("-") != 2:
            continue
        try:
            text = archive.read_text(encoding="utf-8")
        except OSError:
            logger.warning("Could not read %s; skipping it", archive)
            continue
        window = history[-RECENT_BASELINE_SESSIONS:]
        recent: set[str] = set().union(*window) if window else set()
        metrics = measure_session(text, date=date, baseline=baseline,
                                  baseline_sessions=len(out),
                                  recent=recent, recent_sessions=len(window))
        out.append(metrics)
        vocabulary = set(words_from_annotated(text))
        baseline |= vocabulary
        history.append(vocabulary)
    return out


def append_history(path: Path, metrics: list[LexisMetrics]) -> None:
    """Rewrites rather than appends: unlike every other history here, this one
    is derived wholly from the archived transcripts, so it can always be
    recomputed and there is no judgment in it to preserve."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS)
        writer.writeheader()
        for m in metrics:
            writer.writerow({
                "date": m.date,
                "words": m.words,
                "distinct": m.distinct,
                "mattr": "" if m.mattr is None else m.mattr,
                "new_words": "" if m.new_words is None else m.new_words,
                "new_per_1000": "" if m.new_per_1000 is None else m.new_per_1000,
                "baseline_sessions": m.baseline_sessions,
                "new_vs_recent": "" if m.new_vs_recent is None else m.new_vs_recent,
                "new_vs_recent_per_1000": ("" if m.new_vs_recent_per_1000 is None
                                           else m.new_vs_recent_per_1000),
                "recent_baseline_sessions": m.recent_baseline_sessions,
            })
    logger.info("Wrote %d lexical measurements to %s", len(metrics), path)


def load_history(path: Path) -> list[LexisMetrics]:
    if not path.exists():
        return []

    def number(raw: str, cast):
        raw = (raw or "").strip()
        return cast(raw) if raw else None

    rows = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            rows.append(LexisMetrics(
                date=(raw.get("date") or "").strip(),
                words=int(raw["words"]),
                distinct=int(raw["distinct"]),
                mattr=number(raw.get("mattr"), float),
                new_words=number(raw.get("new_words"), int),
                new_per_1000=number(raw.get("new_per_1000"), float),
                baseline_sessions=int(raw.get("baseline_sessions") or 0),
                new_vs_recent=number(raw.get("new_vs_recent"), int),
                new_vs_recent_per_1000=number(raw.get("new_vs_recent_per_1000"), float),
                recent_baseline_sessions=int(raw.get("recent_baseline_sessions") or 0),
            ))
    rows.sort(key=lambda r: r.date)
    return rows


def format_table(metrics: list[LexisMetrics]) -> str:
    if not metrics:
        return "No archived transcripts to measure."
    lines = [f"{'Date':<12} {'Words':>7} {'MATTR':>7} {'cumul/1k':>9} {'rolling/1k':>11}",
             "-" * 52]
    for m in metrics:
        lines.append(
            f"{m.date:<12} {m.words:>7} "
            f"{'—' if m.mattr is None else f'{m.mattr:.3f}':>7} "
            f"{'—' if m.new_per_1000 is None else f'{m.new_per_1000:.1f}':>9} "
            f"{'—' if m.new_vs_recent_per_1000 is None else f'{m.new_vs_recent_per_1000:.1f}':>11}")
    measured = [m.mattr for m in metrics if m.mattr is not None]
    rolling = [m.new_vs_recent_per_1000 for m in metrics
               if m.new_vs_recent_per_1000 is not None]
    if len(measured) >= 2:
        lines.append("")
        lines.append(f"MATTR {measured[0]:.3f} → {measured[-1]:.3f} "
                     f"(min {min(measured):.3f}, max {max(measured):.3f}) — the spread to read "
                     f"any single session against.")
    if len(rolling) >= 2:
        lines.append(f"New words against the previous {RECENT_BASELINE_SESSIONS} sessions: "
                     f"{rolling[0]:.1f} → {rolling[-1]:.1f} per 1,000 "
                     f"(min {min(rolling):.1f}, max {max(rolling):.1f}). The cumulative column "
                     f"beside it falls by construction and is context, not a measure.")
    return "\n".join(lines)


def _repo_root() -> Path:
    return Path(__file__).parent.parent


def main(argv: list[str] | None = None) -> int:
    """`python -m voxlib.lexis` — measure lexical range over the archive."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m voxlib.lexis",
        description="Measure lexical range from the archived annotated transcripts.",
    )
    parser.add_argument("--sessions", type=Path,
                        default=_repo_root() / "analysis" / "sessions",
                        help="Archive directory (default: analysis/sessions)")
    parser.add_argument("--out", type=Path,
                        default=_repo_root() / "analysis" / "lexis_history.csv",
                        help="Where to write the measurements")
    parser.add_argument("--write", action="store_true",
                        help="Write the history file as well as printing it")
    args = parser.parse_args(argv)

    metrics = measure_history(args.sessions)
    print(format_table(metrics))
    if args.write and metrics:
        append_history(args.out, metrics)
        print(f"\nWrote {args.out}")
    return 0 if metrics else 1


if __name__ == "__main__":
    raise SystemExit(main())
