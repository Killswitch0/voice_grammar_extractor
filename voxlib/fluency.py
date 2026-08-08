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

**Word-based metrics count only lines whisper was confident about** (the ones
without a `[?]` marker in the annotated document). This mirrors the rule the
analysis workflow already applies to grammar — a mis-recognized line says
nothing about how the speaker actually spoke — and it is not a detail. In this
project's own history, 17 of the 20 "fillers" in the 2026-08-06 session sat
inside `[?]` lines, and that session's low-confidence share was 60% against
24-30% before it. Counted over reliable lines only, the filler series reads
1 / 0 / 3 rather than 1 / 1 / 20: what looked like a sharp regression in
fluency was the recording quality falling over.

Which is why `low_confidence_share` is itself reported and tracked. When it
moves, every other number here changes meaning, and a metric that can quietly
switch populations underneath a trend line is worse than no metric.

What's measured:

  - **Filler rate** — pure pause sounds (um/uh/erm) per 100 reliable words,
    using the same pattern --remove-fillers strips (see filler_filter.py), so
    the metric can never disagree with the cleanup. A LOWER BOUND on real
    disfluency: whisper drops many hesitations before we ever see the text.
  - **Speaking rate** — words per minute across your own reliable speech.
    Comparable between solo and diarized recordings.
  - **Low-confidence share** — what fraction of your lines whisper wasn't sure
    about. A quality-of-input measure, not a quality-of-speech one: high
    values mean the microphone, not the speaker.
  - **Pauses** — gaps between your consecutive lines. Computed over ALL lines,
    unlike the word metrics: a timestamp is valid whether or not the words on
    it were recognized correctly. Solo recordings only, though, and
    deliberately so: in a diarized recording the gap between two of your lines
    is mostly the other person talking, so the same number would mean two
    different things depending on the recording.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Optional

from .filler_filter import FILLER_SOUND_PATTERN
from .formatter import DEFAULT_LOW_CONFIDENCE_THRESHOLD, is_low_confidence

logger = logging.getLogger(__name__)

# A gap longer than this between two of your own lines reads as a hesitation
# rather than ordinary sentence spacing. Only meaningful for solo recordings.
LONG_PAUSE_SEC = 2.0

# Above this share of [?] lines, the recording is telling you about itself
# rather than about the speaker: most of the transcript is excluded from
# grammar judgment, and the word metrics rest on whatever is left.
LOW_CONFIDENCE_WARN_SHARE = 0.4

HISTORY_COLUMNS = [
    "run_at",
    "date",
    "origin",
    "mode",
    "files",
    "total_lines",
    "low_confidence_lines",
    "low_confidence_share",
    "total_words",
    "reliable_words",
    "speech_minutes",
    "words_per_minute",
    "filler_count",
    "fillers_per_100_words",
    "median_pause_sec",
    "long_pauses",
]


@dataclass
class FluencyMetrics:
    total_lines: int
    low_confidence_lines: int
    # 0.0-1.0. Read this before reading anything else here: it says how much of
    # the transcript the rest of the numbers are actually based on.
    low_confidence_share: float
    total_words: int
    # The denominator for every rate below — words on lines whisper was
    # confident about.
    reliable_words: int
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


def compute_fluency(
    lines,
    *,
    use_diarization: bool,
    fillers_removed: bool,
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
) -> FluencyMetrics:
    reliable = [
        line for line in lines
        if not is_low_confidence(getattr(line, "avg_logprob", None), low_confidence_threshold)
    ]
    low_confidence_lines = len(lines) - len(reliable)
    share = low_confidence_lines / len(lines) if lines else 0.0

    total_words = sum(count_words(line.text) for line in lines)
    reliable_words = sum(count_words(line.text) for line in reliable)

    # Duration from the reliable lines too, so the rate's numerator and
    # denominator describe the same stretch of speech.
    speech_minutes = sum(line.end - line.start for line in reliable) / 60

    filler_count = None if fillers_removed else sum(count_fillers(line.text) for line in reliable)
    filler_rate = None if filler_count is None else _rate_per_100_words(filler_count, reliable_words)

    # Pauses come from timestamps, which are valid regardless of whether the
    # words on them were recognized correctly — so they use every line.
    if use_diarization:
        median_pause, long_pauses = None, None
    else:
        median_pause, long_pauses = _pause_stats(lines)

    return FluencyMetrics(
        total_lines=len(lines),
        low_confidence_lines=low_confidence_lines,
        low_confidence_share=round(share, 3),
        total_words=total_words,
        reliable_words=reliable_words,
        speech_minutes=round(speech_minutes, 2),
        words_per_minute=round(reliable_words / speech_minutes, 1) if speech_minutes > 0 else 0.0,
        filler_count=filler_count,
        fillers_per_100_words=filler_rate,
        median_pause_sec=median_pause,
        long_pauses=long_pauses,
    )


def warn_if_unreliable(metrics: FluencyMetrics) -> str | None:
    """
    Returns a warning when so much of the transcript is low-confidence that the
    session isn't comparable with the others — or None when it's fine.

    This is the check that would have caught 2026-08-06 at the time: 60% of
    lines marked [?], against 24-30% in the sessions before it. Without it, the
    resulting drop in every word-based number reads as the speaker getting
    worse instead of the audio getting worse.
    """
    if metrics.total_lines == 0 or metrics.low_confidence_share < LOW_CONFIDENCE_WARN_SHARE:
        return None
    return (
        f"{metrics.low_confidence_share:.0%} of your lines ({metrics.low_confidence_lines} of "
        f"{metrics.total_lines}) were recognized with low confidence. That's a recording-quality "
        f"signal, not a speaking one: the grammar analysis skips those lines entirely, and the "
        f"numbers here rest on the {metrics.reliable_words} words that remain — so don't compare "
        f"them against sessions with cleaner audio. Check the mic, the distance and the "
        f"background noise before reading anything into this session's fluency."
    )


_ANNOTATED_LINE = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\](?P<marker>\s\[\?\])?\s*(?P<text>.*)$")


def metrics_from_annotated_text(text: str) -> FluencyMetrics:
    """
    Fluency for an already-archived transcript, read from the ANNOTATED file.

    Deliberately not the clean one: `transcript_clean.txt` carries no `[?]`
    markers, so counting from it would silently include lines whisper got
    wrong — the exact mistake that made 2026-08-06 look like a fluency
    collapse. The annotated file is the only archived form that knows which
    lines to trust.

    Timing still can't be recovered: the annotated format records each line's
    start but not its end, so speaking rate and pauses come back as zero/None
    rather than being estimated from the gaps between starts (which would
    conflate a pause with however long the previous line took to say).
    """
    total_lines = low_confidence_lines = 0
    total_words = reliable_words = filler_count = 0

    for raw in text.splitlines():
        match = _ANNOTATED_LINE.match(raw.strip())
        if not match:
            continue  # "=== file.webm ===" headers and blank lines
        total_lines += 1
        line_text = match.group("text")
        words = count_words(line_text)
        total_words += words
        if match.group("marker"):
            low_confidence_lines += 1
        else:
            reliable_words += words
            filler_count += count_fillers(line_text)

    return FluencyMetrics(
        total_lines=total_lines,
        low_confidence_lines=low_confidence_lines,
        low_confidence_share=round(low_confidence_lines / total_lines, 3) if total_lines else 0.0,
        total_words=total_words,
        reliable_words=reliable_words,
        speech_minutes=0.0,
        words_per_minute=0.0,
        filler_count=filler_count,
        fillers_per_100_words=_rate_per_100_words(filler_count, reliable_words),
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
    # Last, but always present: it's the caveat on everything before it.
    parts.append(f"{metrics.low_confidence_share:.0%} of lines low-confidence")
    return "; ".join(parts)
