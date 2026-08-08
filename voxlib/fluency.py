"""
Fluency measurement — the numbers the analysis workflow tracks over months.

Why this is code and not something read off the transcript by eye: the point
of a fluency number is comparing it against previous sessions, and that only
holds if the same input always yields the same value. Counting by hand can get
it right — the first three sessions of this project were logged at 0.04, 0.05
and 0.61 per 100 words, and this module reproduces all three exactly — but the
rule being applied (notably "uh-huh" is agreement, not hesitation, so it
doesn't count) lived only as prose inside each session report, where nothing
stops the next session from drawing the line somewhere slightly different.
Here it's executable, so the series can't quietly change meaning underneath
itself. test_fluency.py pins the reproduction.

What's measured:

  - **Filler rate** — pure pause sounds (um/uh/erm) per 100 words, using the
    same pattern --remove-fillers strips (see filler_filter.py), so the metric
    can never disagree with the cleanup. Note this is a LOWER BOUND on real
    disfluency: whisper drops many hesitations before we ever see the text.
  - **Speaking rate** — words per minute across your own speech only, since
    the durations come from your segments. Comparable between solo and
    diarized recordings.
  - **Pauses** — gaps between your consecutive lines. Solo recordings only,
    and deliberately so: in a diarized recording the gap between two of your
    lines is mostly the other person talking, so the same number would mean
    two different things depending on the recording, which is exactly the kind
    of noise that makes a tracked metric worthless.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Optional

from .filler_filter import FILLER_SOUND_PATTERN

logger = logging.getLogger(__name__)

# A gap longer than this between two of your own lines reads as a hesitation
# rather than ordinary sentence spacing. Only meaningful for solo recordings.
LONG_PAUSE_SEC = 2.0

HISTORY_COLUMNS = [
    "run_at",
    "date",
    "origin",
    "mode",
    "files",
    "total_words",
    "speech_minutes",
    "words_per_minute",
    "filler_count",
    "fillers_per_100_words",
    "median_pause_sec",
    "long_pauses",
]


@dataclass
class FluencyMetrics:
    total_words: int
    speech_minutes: float
    words_per_minute: float
    # None when --remove-fillers stripped them before we could count: reporting
    # 0 there would look like flawless delivery instead of a missing reading.
    filler_count: Optional[int]
    fillers_per_100_words: Optional[float]
    # None for diarized recordings — see the module docstring.
    median_pause_sec: Optional[float]
    long_pauses: Optional[int]


def count_words(text: str) -> int:
    return len(text.split())


def count_fillers(text: str) -> int:
    return len(FILLER_SOUND_PATTERN.findall(text))


def _rate_per_100_words(count: int, total_words: int) -> float:
    if total_words <= 0:
        return 0.0
    return round(count / total_words * 100, 2)


def _pause_stats(lines) -> tuple[Optional[float], Optional[int]]:
    """
    Gaps between consecutive lines, per source file. Lines are expected in
    chronological order (the pipeline sorts them). Negative gaps are skipped
    rather than clamped: they mean overlapping segments, not a pause, and
    folding them in as 0.0 would drag the median toward zero.
    """
    gaps: list[float] = []
    previous_end: Optional[float] = None
    previous_source: Optional[str] = None

    for line in lines:
        source = getattr(line, "source_file", None)
        if source != previous_source:
            previous_end = None
            previous_source = source
        if previous_end is not None:
            gap = line.start - previous_end
            if gap >= 0:
                gaps.append(gap)
        previous_end = line.end

    if not gaps:
        return None, None
    return round(median(gaps), 2), sum(1 for g in gaps if g > LONG_PAUSE_SEC)


def compute_fluency(lines, *, use_diarization: bool, fillers_removed: bool) -> FluencyMetrics:
    total_words = sum(count_words(line.text) for line in lines)
    speech_sec = sum(line.end - line.start for line in lines)
    speech_minutes = speech_sec / 60

    filler_count = None if fillers_removed else sum(count_fillers(line.text) for line in lines)
    filler_rate = None if filler_count is None else _rate_per_100_words(filler_count, total_words)

    if use_diarization:
        median_pause, long_pauses = None, None
    else:
        median_pause, long_pauses = _pause_stats(lines)

    return FluencyMetrics(
        total_words=total_words,
        speech_minutes=round(speech_minutes, 2),
        words_per_minute=round(total_words / speech_minutes, 1) if speech_minutes > 0 else 0.0,
        filler_count=filler_count,
        fillers_per_100_words=filler_rate,
        median_pause_sec=median_pause,
        long_pauses=long_pauses,
    )


def metrics_from_transcript_text(text: str) -> FluencyMetrics:
    """
    Fluency for an already-archived transcript, where only the words survive.

    Used to backfill history from analysis/sessions/*.txt: those files carry no
    timing at all, so speaking rate and pauses are genuinely unrecoverable and
    come back as zero/None rather than being estimated from line counts.
    """
    total_words = count_words(text)
    filler_count = count_fillers(text)
    return FluencyMetrics(
        total_words=total_words,
        speech_minutes=0.0,
        words_per_minute=0.0,
        filler_count=filler_count,
        fillers_per_100_words=_rate_per_100_words(filler_count, total_words),
        median_pause_sec=None,
        long_pauses=None,
    )


def _history_row(
    metrics: FluencyMetrics,
    *,
    date: str,
    origin: str,
    mode: str,
    files: int,
    run_at: str,
) -> dict:
    row = {
        "run_at": run_at,
        "date": date,
        "origin": origin,
        "mode": mode,
        "files": files,
    }
    # None becomes an empty cell, never 0 — "not measured" and "measured as
    # zero" must stay distinguishable to whoever reads the trend later.
    row.update({k: ("" if v is None else v) for k, v in asdict(metrics).items()})
    return row


def append_history(
    history_path: Path,
    metrics: FluencyMetrics,
    *,
    mode: str,
    files: int,
    date: str | None = None,
    origin: str = "pipeline",
    run_at: str | None = None,
) -> None:
    """
    Appends one row to the fluency history CSV, writing the header if the file
    is new. Append-only by design, same as analysis/scores_history.csv: a raw
    record of what was measured when, never rewritten in hindsight. `run_at`
    keeps two runs on the same day distinguishable.
    """
    now = datetime.now()
    row = _history_row(
        metrics,
        date=date or now.strftime("%Y-%m-%d"),
        origin=origin,
        mode=mode,
        files=files,
        run_at=run_at or now.isoformat(timespec="seconds"),
    )

    history_path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not history_path.exists()
    with history_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)

    logger.info("Fluency measurement appended to %s", history_path)


def write_json(path: Path, metrics: FluencyMetrics, *, mode: str, files: int) -> None:
    """This run's measurement, next to the transcripts it describes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "measured_at": datetime.now().isoformat(timespec="seconds"),
        "mode": mode,
        "files": files,
        "long_pause_threshold_sec": LONG_PAUSE_SEC,
        **asdict(metrics),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def describe(metrics: FluencyMetrics) -> str:
    """One line for the log and the console summary."""
    parts = [f"{metrics.words_per_minute:.0f} words/min"]
    if metrics.fillers_per_100_words is None:
        parts.append("fillers not measurable (--remove-fillers stripped them)")
    else:
        parts.append(f"{metrics.fillers_per_100_words:.2f} fillers per 100 words "
                     f"({metrics.filler_count} total)")
    if metrics.median_pause_sec is not None:
        parts.append(f"median pause {metrics.median_pause_sec:.2f}s, "
                     f"{metrics.long_pauses} over {LONG_PAUSE_SEC:.0f}s")
    return "; ".join(parts)
