"""
The level line — a sub-band CEFR estimate that can be recomputed.

`scores_history.csv` records one CEFR band per session, and it does not move.
That is not a measurement problem, it is a resolution problem: a band is about a
year wide, and over a history measured in weeks the honest reading of a flat
column is "no band change yet", which is useless as feedback. This module cuts
the band into rungs and says which one the evidence supports.

**The level is earned, not judged.** Every rung has explicit thresholds on
measurements already in `analysis/`, so the same history always yields the same
level and a rung can be argued with. The alternative — a model re-reading its
own previous prose each session and nudging a letter — is how a hedged band
label sits still for months while the numbers underneath it move a great deal.

Four dimensions, taken from CEFR's own qualitative features of spoken language,
with the fifth left out on purpose:

  - **Accuracy** — the clarity-tier error rate, gated above B2.1 by the polish
    tier as well. The split matters more than anything else here. A total
    mistake rate can climb steeply while being driven almost entirely by one
    low-severity category, and the clarity-tier rate — errors that cost the
    listener the meaning, which is what the CEFR accuracy descriptors are
    about — move the other way underneath it. Gating on the total would report a
    speaker falling apart at the moment the part that impedes comprehension had
    improved.
  - **Fluency** — filler and discourse-marker rates. Deliberately *not* words
    per minute: it is only comparable within one `speech_time_basis`, and a
    session that is mostly short backchannels reads as slow however fluently it
    was spoken. A gate on it would call that a loss of fluency.
  - **Range** — MATTR and rolling novelty, from `lexis.py`.
  - **Interaction** — the share of scenario criteria met in question practice,
    if that evidence is recent enough to describe the speaker now.

Coherence is absent because nothing here measures it, and a dimension scored on
impression would reintroduce exactly the drift this module exists to remove.

**What this is not.** It is a scale calibrated against one speaker's own record,
anchored so that their recent sessions land where the coach's standing holistic
judgment puts them. A rung here is a position on that line, not an exam result,
and nothing in this module certifies a CEFR level.
"""

from __future__ import annotations

import csv
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import date as date_type
from pathlib import Path
from typing import Optional

from . import asking, fluency, lexis, mistakes

logger = logging.getLogger(__name__)

# The rungs, lowest first. The index is what gets plotted; the label is what
# gets read.
SCALE = ["B1", "B1+", "B2.1", "B2.2", "B2.3", "B2.4", "B2 consolidated", "C1.1"]

# A measured value that clears no rung at all. Distinct from None, which means
# nothing was measured: conflating the two would let the worst possible reading
# on a dimension be treated as an absent one and quietly ignored, which is the
# direction that inflates a level.
BELOW_SCALE = -1


def label(index: Optional[int]) -> str:
    if index is None:
        return "not measured"
    return "below B1" if index < 0 else SCALE[index]

# Consecutive qualifying sessions before the level moves. Three, matching every
# other window in this project: one session is a mood, two cannot tell a trend
# from a bad day. Without this the line would yo-yo on session length alone.
PROMOTION_SESSIONS = 3
DEMOTION_SESSIONS = 3

# How many dimensions must be measured before a rung is stated rather than
# offered. With Coherence permanently absent and Interaction present only when
# question practice has happened recently, this is often the binding condition.
MIN_MEASURED_DIMENSIONS = 3

# How old question-practice evidence may be and still describe the speaker now.
INTERACTION_MAX_AGE_DAYS = 30

# Which set of thresholds produced a row. Every reading here is derived — from
# the mistake, fluency, lexical and scenario histories, through the numbers in
# DIMENSIONS — so unlike the judgments in `scores_history.csv` it can always be
# recomputed, and this file is rewritten rather than appended to. That is only
# safe if a reader can tell which calibration a row came from: bump this
# whenever a threshold moves, and the old line stops being silently comparable
# to the new one.
CALIBRATION = "2026-09-17"


@dataclass
class Measure:
    key: str
    label: str
    unit: str
    lower_is_better: bool
    # One threshold per rung, index-aligned with SCALE. None means this measure
    # does not gate that rung — the polish tier is free below B2.2, because a
    # B2 speaker is allowed to say "in USA".
    thresholds: list[Optional[float]]
    note: str = ""


@dataclass
class Dimension:
    key: str
    label: str
    measures: list[Measure]
    note: str = ""


DIMENSIONS = [
    Dimension(
        key="accuracy",
        label="Accuracy",
        note="Errors that cost the listener meaning, and — higher up — the ones that "
             "merely sound foreign.",
        measures=[
            Measure("clarity", "Clarity-tier errors", "per 1,000 reliable words", True,
                    [12.0, 6.0, 4.0, 3.0, 2.0, 1.5, 1.0, 0.5],
                    "severity 3+ in mistakes.csv: the listener loses or has to "
                    "reconstruct the meaning"),
            Measure("polish", "Polish-tier errors", "per 1,000 reliable words", True,
                    [None, None, 18.0, 14.0, 11.0, 8.0, 6.0, 4.0],
                    "severity 1-2: understood instantly, just not native. Ungated below "
                    "B2.1 by design — a B2 speaker is allowed to say “in USA” "
                    "— and tightening from there"),
        ],
    ),
    Dimension(
        key="fluency",
        label="Fluency",
        note="Hesitation and crutch phrases, over reliable words only.",
        measures=[
            Measure("fillers", "Filler sounds", "per 100 words", True,
                    [2.0, 1.2, 0.8, 0.6, 0.45, 0.35, 0.25, 0.15],
                    "um / uh / erm — a lower bound, since whisper drops many"),
            Measure("markers", "Discourse markers", "per 100 words", True,
                    [5.0, 4.0, 3.2, 2.8, 2.4, 2.0, 1.6, 1.2],
                    "“you know”, “I mean” and friends: often a far larger "
                    "habit than the filler sounds"),
        ],
    ),
    Dimension(
        key="range",
        label="Range",
        note="Vocabulary variety, and whether it is still moving.",
        measures=[
            Measure("mattr", "Lexical variety (MATTR)", "ratio", False,
                    [0.290, 0.330, 0.365, 0.380, 0.395, 0.410, 0.425, 0.440],
                    "the lower rungs are calibrated against observed speech, so the "
                    "rungs past B2.2 are extrapolations beyond anything yet measured"),
            Measure("novelty", "Words new in 3 sessions", "per 1,000 words", False,
                    [45.0, 60.0, 72.0, 82.0, 92.0, 102.0, 112.0, 125.0],
                    "against a fixed three-session baseline, so the figure does not decay "
                    "as the archive grows"),
        ],
    ),
    Dimension(
        key="interaction",
        label="Interaction",
        note="Asking well enough to get what you need, scored against criteria written "
             "in advance.",
        measures=[
            Measure("scenarios", "Scenario criteria met", "share", False,
                    [0.30, 0.45, 0.60, 0.70, 0.80, 0.875, 0.95, 1.0],
                    "from asking_scenarios.csv, only while less than "
                    f"{INTERACTION_MAX_AGE_DAYS} days old"),
        ],
    ),
]

MEASURES = {m.key: m for d in DIMENSIONS for m in d.measures}

HISTORY_COLUMNS = [
    "date", "level", "level_index", "session_rung", "session_label",
    "reliable", "provisional", "measured_dimensions",
    "accuracy", "fluency", "range", "interaction",
    *MEASURES, "blockers", "calibration",
]


def rung_for(value: Optional[float], measure: Measure) -> Optional[int]:
    """The highest rung this value clears.

    None when nothing was measured, `BELOW_SCALE` when something was measured
    and cleared nothing. A measure that does not gate a rung (a `None`
    threshold) counts as cleared there, so the polish tier cannot hold anyone
    below B2.1.
    """
    if value is None:
        return None
    best = BELOW_SCALE
    for index in range(len(SCALE)):
        threshold = measure.thresholds[index]
        if threshold is None:
            cleared = True
        elif measure.lower_is_better:
            cleared = value <= threshold
        else:
            cleared = value >= threshold
        if cleared:
            best = index
        else:
            break
    return best


@dataclass
class Reading:
    date: str
    reliable: bool
    values: dict[str, Optional[float]]
    measure_rungs: dict[str, Optional[int]] = field(default_factory=dict)
    dimension_rungs: dict[str, Optional[int]] = field(default_factory=dict)
    rung: Optional[int] = None
    provisional: bool = False
    level: Optional[int] = None
    blockers: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return "not yet established" if self.level is None else label(self.level)

    @property
    def session_label(self) -> str:
        return "\u2014" if self.rung is None else label(self.rung)


def session_rung(dimension_rungs: dict[str, Optional[int]]) -> Optional[int]:
    """The rung a single session supports.

    All but at most one measured dimension must reach it, and the laggard may be
    no more than one rung below. Requiring every dimension lets one noisy
    measure freeze the line for months; averaging them lets strong fluency hide
    weak accuracy, which is the thing CEFR profiling exists to prevent.
    """
    measured = [r for r in dimension_rungs.values() if r is not None]
    if not measured:
        return None
    best = None
    for candidate in range(BELOW_SCALE, len(SCALE)):
        if all(r >= candidate - 1 for r in measured) and \
                sum(1 for r in measured if r < candidate) <= 1:
            best = candidate
    return best


def read_session(date: str, values: dict[str, Optional[float]], *, reliable: bool) -> Reading:
    """One session's rung, and what is holding it there."""
    reading = Reading(date=date, reliable=reliable, values=values)
    for measure in MEASURES.values():
        reading.measure_rungs[measure.key] = rung_for(values.get(measure.key), measure)
    for dimension in DIMENSIONS:
        rungs = [reading.measure_rungs[m.key] for m in dimension.measures]
        present = [r for r in rungs if r is not None]
        # A dimension is as strong as its weakest measured part, and unmeasured
        # when none of its parts were.
        reading.dimension_rungs[dimension.key] = min(present) if present else None

    reading.rung = session_rung(reading.dimension_rungs)
    measured = sum(1 for r in reading.dimension_rungs.values() if r is not None)
    reading.provisional = measured < MIN_MEASURED_DIMENSIONS
    if reading.rung is not None:
        reading.blockers = sorted(
            d.key for d in DIMENSIONS
            if reading.dimension_rungs[d.key] is not None
            and reading.dimension_rungs[d.key] < reading.rung + 1
        )
    return reading


def walk(readings: list[Reading]) -> list[Reading]:
    """Apply the hysteresis, oldest first, assigning each reading a level.

    Promotion takes the *minimum* of the qualifying window and demotion the
    *maximum*, so neither direction overshoots on one good or bad session.
    """
    level: Optional[int] = None
    window: deque[int] = deque(maxlen=max(PROMOTION_SESSIONS, DEMOTION_SESSIONS))
    for reading in readings:
        if reading.reliable and reading.rung is not None and not reading.provisional:
            window.append(reading.rung)
            recent = list(window)
            if level is None:
                level = reading.rung
            elif len(recent) >= PROMOTION_SESSIONS and \
                    all(r > level for r in recent[-PROMOTION_SESSIONS:]):
                level = min(recent[-PROMOTION_SESSIONS:])
            elif len(recent) >= DEMOTION_SESSIONS and \
                    all(r < level for r in recent[-DEMOTION_SESSIONS:]):
                level = max(recent[-DEMOTION_SESSIONS:])
        reading.level = level
    return readings


def _days_between(earlier: str, later: str) -> Optional[int]:
    try:
        return (date_type.fromisoformat(later) - date_type.fromisoformat(earlier)).days
    except ValueError:
        return None


def gather(analysis_dir: Path) -> list[Reading]:
    """Assemble every session's measurements from the histories that own them."""
    mistake_rows = mistakes.load(analysis_dir / "mistakes.csv")
    recordings = {r.date: r for r in
                  fluency.latest_per_date(
                      fluency.load_history(analysis_dir / "fluency_history.csv"))}
    lexical = {m.date: m for m in lexis.load_history(analysis_dir / "lexis_history.csv")}
    scenarios = asking.load_history(analysis_dir / "asking_scenarios.csv")

    # Question practice happens on its own days, so the most recent evidence is
    # carried forward — but only while it is still about the speaker now.
    by_practice_date: dict[str, list[asking.ScenarioRun]] = {}
    for run in scenarios:
        by_practice_date.setdefault(run.date, []).append(run)
    practice_dates = sorted(by_practice_date)

    readings = []
    for date in mistakes.session_dates(mistake_rows):
        day = [r for r in mistake_rows if r.date == date]
        words = day[0].reliable_words if day else 0
        clarity = sum(r.occurrences or 0 for r in day
                      if r.severity >= mistakes.CLARITY_SEVERITY)
        polish = sum(r.occurrences or 0 for r in day
                     if r.severity < mistakes.CLARITY_SEVERITY)
        recording = recordings.get(date)
        lex = lexical.get(date)

        share = None
        recent = [d for d in practice_dates if d <= date]
        if recent:
            age = _days_between(recent[-1], date)
            if age is not None and age <= INTERACTION_MAX_AGE_DAYS:
                runs = by_practice_date[recent[-1]]
                total = sum(r.criteria_total for r in runs)
                if total:
                    share = round(sum(r.criteria_met for r in runs) / total, 3)

        values = {
            "clarity": round(clarity / words * 1000, 2) if words else None,
            "polish": round(polish / words * 1000, 2) if words else None,
            "fillers": recording.fillers_per_100_words if recording else None,
            "markers": recording.discourse_markers_per_100_words if recording else None,
            "mattr": lex.mattr if lex else None,
            # Only once the rolling baseline is actually full: the first two
            # sessions are measured against one and two sessions of vocabulary
            # and read far higher for that reason alone.
            "novelty": (lex.new_vs_recent_per_1000 if lex
                        and lex.recent_baseline_sessions == lexis.RECENT_BASELINE_SESSIONS
                        else None),
            "scenarios": share,
        }
        # A session that lost too many words to low-confidence recognition is
        # not a comparable measurement of anything, so it neither promotes nor
        # demotes — the same threshold `fluency.warn_if_unreliable` fires on.
        reliable = not (recording and recording.low_confidence_word_share is not None
                        and recording.low_confidence_word_share
                        >= fluency.LOW_CONFIDENCE_WARN_SHARE)
        readings.append(read_session(date, values, reliable=reliable))

    return walk(readings)


def next_rung_requirements(reading: Reading) -> list[dict]:
    """For every measure, what the rung above the current level asks for."""
    if reading.level is None or reading.level + 1 >= len(SCALE):
        return []
    target = max(reading.level, 0) + 1
    out = []
    for dimension in DIMENSIONS:
        for measure in dimension.measures:
            threshold = measure.thresholds[target]
            value = reading.values.get(measure.key)
            met = None if value is None or threshold is None else (
                value <= threshold if measure.lower_is_better else value >= threshold)
            out.append({
                "dimension": dimension.label,
                "measure": measure.label,
                "unit": measure.unit,
                "value": value,
                "threshold": threshold,
                "met": met,
                "lower_is_better": measure.lower_is_better,
            })
    return out


def closest_gap(reading: Reading) -> Optional[dict]:
    """The single measure nearest to clearing the next rung, and how far short.

    The level line is deliberately slow — three qualifying sessions before it
    moves — which is right for a level and useless as weekly feedback: it has
    read B1+ for twelve sessions running while the numbers underneath moved a
    great deal. `blockers` names the dimensions holding it, but a dimension is
    not something anyone can act on. A measure is, and the distance to the next
    threshold changes every session even when the rung does not.

    Ranked by relative shortfall rather than absolute, because the measures are
    in four different units — 0.88 fillers per 100 words and 0.3565 MATTR cannot
    be compared as distances, only as proportions of what is being asked for.
    """
    if reading.level is None or reading.level + 1 >= len(SCALE):
        return None
    # `reading.level` can be BELOW_SCALE (-1), which is a real reading and not a
    # missing one. Clamping it to 0 first made the next rung B1+ when the rung
    # actually above "below B1" is B1, and the headline then measured progress
    # against a threshold two rungs away.
    target = reading.level + 1

    unmet = []
    for dimension in DIMENSIONS:
        for measure in dimension.measures:
            value = reading.values.get(measure.key)
            threshold = measure.thresholds[target]
            if value is None or threshold is None:
                continue
            met = value <= threshold if measure.lower_is_better else value >= threshold
            if met:
                continue
            # A zero used to be skipped here to keep it out of the division
            # below. That was right for a lower-is-better measure and wrong for
            # the others: zero is the worst reading a share or a ratio can take,
            # and dropping it meant the panel went silent on the one session
            # where a single measure was holding the level back. The `met` test
            # above already guards the division — a lower-is-better zero clears
            # every threshold and never reaches it.
            # 1.0 means "at the threshold"; below it is how far short.
            progress = (threshold / value) if measure.lower_is_better else (value / threshold)
            unmet.append({
                "dimension": dimension.label,
                "measure": measure.label,
                "key": measure.key,
                "unit": measure.unit,
                "value": value,
                "threshold": threshold,
                "lower_is_better": measure.lower_is_better,
                "progress": round(min(progress, 1.0), 3),
                "shortfall": round(abs(value - threshold), 4),
                "target": SCALE[target],
            })
    if not unmet:
        return None
    unmet.sort(key=lambda m: -m["progress"])
    return unmet[0]


def format_report(readings: list[Reading]) -> str:
    if not readings:
        return "No sessions recorded yet, so there is nothing to place on the scale."
    latest = readings[-1]
    lines = [
        f"Level: {latest.label}"
        + (f"  (this session alone reads {latest.session_label})"
           if latest.rung != latest.level else ""),
        f"Scale: {' < '.join(SCALE)}",
        "",
        f"{'Dimension':<13}{'Rung':<20}{'Measure':<26}{'Value':>9}  Needed for next",
        "-" * 92,
    ]
    target = (None if latest.level is None
              else min(max(latest.level, 0) + 1, len(SCALE) - 1))
    for dimension in DIMENSIONS:
        shown = label(latest.dimension_rungs[dimension.key])
        first = True
        for measure in dimension.measures:
            value = latest.values.get(measure.key)
            threshold = None if target is None else measure.thresholds[target]
            lines.append(
                f"{dimension.label if first else '':<13}"
                f"{shown if first else '':<20}"
                f"{measure.label:<26}"
                f"{'—' if value is None else f'{value:g}':>9}  "
                + ("ungated" if threshold is None else
                   f"{'≤' if measure.lower_is_better else '≥'} {threshold:g}"))
            first = False

    lines.append("")
    if latest.provisional:
        lines.append(f"PROVISIONAL: only "
                     f"{sum(1 for r in latest.dimension_rungs.values() if r is not None)} of "
                     f"{len(DIMENSIONS)} dimensions were measured this session "
                     f"({MIN_MEASURED_DIMENSIONS} needed).")
    if latest.blockers:
        names = ", ".join(d.label for d in DIMENSIONS if d.key in latest.blockers)
        lines.append(f"Holding the line here: {names}.")
    lines.append("")
    lines.append(f"{'Date':<12}{'Session':<20}{'Level':<20}Reliable")
    lines.append("-" * 64)
    for reading in readings:
        lines.append(f"{reading.date:<12}{reading.session_label:<20}{reading.label:<20}"
                     + ("yes" if reading.reliable else "no — not comparable"))
    return "\n".join(lines)


def record(path: Path, readings: list[Reading]) -> None:
    """One row per session, rewritten in full.

    The exception to this project's append-only rule, and deliberately so. Every
    other history holds something that happened once — a count, a measurement, a
    judgment made on the day — and rewriting it would destroy the record. These
    rows hold no new information at all: they are the other histories read
    through the thresholds in `DIMENSIONS`. Appending instead would leave the
    file holding rows computed under different calibrations, with nothing but
    the date to tell them apart, and the trend drawn through them would be part
    speaker and part threshold change. So it is rewritten, and every row carries
    the calibration that produced it.
    """
    rows = []
    for reading in readings:
        row = {
            "date": reading.date,
            "level": reading.label,
            "level_index": "" if reading.level is None else reading.level,
            "session_rung": "" if reading.rung is None else reading.rung,
            "session_label": reading.session_label,
            "reliable": int(reading.reliable),
            "provisional": int(reading.provisional),
            "measured_dimensions": sum(1 for r in reading.dimension_rungs.values()
                                       if r is not None),
            "blockers": ";".join(reading.blockers),
            "calibration": CALIBRATION,
        }
        for dimension in DIMENSIONS:
            rung = reading.dimension_rungs[dimension.key]
            row[dimension.key] = "" if rung is None else rung
        for key in MEASURES:
            value = reading.values.get(key)
            row[key] = "" if value is None else value
        rows.append(row)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote %d level readings to %s (calibration %s)",
                len(rows), path, CALIBRATION)


def load_history(path: Path) -> list[dict]:
    """The recorded readings, oldest first — what the dashboard will plot."""
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = [dict(row) for row in csv.DictReader(f)]
    rows.sort(key=lambda r: r.get("date", ""))
    return rows


def _repo_root() -> Path:
    return Path(__file__).parent.parent


def main(argv: list[str] | None = None) -> int:
    """`python -m voxlib.level` — where the evidence puts the level, and why."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m voxlib.level",
        description="Place the spoken level on a sub-band scale from the recorded history.",
    )
    parser.add_argument("--analysis", type=Path, default=_repo_root() / "analysis",
                        help="Directory holding the histories (default: analysis/)")
    parser.add_argument("--write", action="store_true",
                        help="Write analysis/level_history.csv (rewritten, not appended)")
    args = parser.parse_args(argv)

    readings = gather(args.analysis)
    print(format_report(readings))
    if args.write and readings:
        record(args.analysis / "level_history.csv", readings)
        print(f"\nWrote {args.analysis / 'level_history.csv'} "
              f"(calibration {CALIBRATION})")
    return 0 if readings else 1


if __name__ == "__main__":
    raise SystemExit(main())
