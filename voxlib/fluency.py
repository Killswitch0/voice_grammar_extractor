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

Which is why the low-confidence share is itself reported and tracked. When it
moves, every other number here changes meaning, and a metric that can quietly
switch populations underneath a trend line is worse than no metric.

**The share is reported two ways, and the word-weighted one is the one to act
on.** Counted by line, a two-word "Yeah." weighs exactly as much as a
twenty-two-word sentence, and short backchannels are precisely where whisper's
avg_logprob is worst — it has almost no context to be confident from. On
2026-08-08, 79 of the 89 flagged lines were under three seconds and 60 of them
were some form of "yes"/"yeah"/"thank you", 217 words in total. By line that
session lost 57% of the transcript; by word it lost 15%. Across the four
sessions on record the two series read 24/30/60/57% against 12/11/23/15% — the
line-based one looks like a collapse in recording quality and the word-based one
looks like ordinary variation. The second is the true statement about how much
analyzable speech survived, so it is what `warn_if_unreliable` fires on.

What's measured:

  - **Filler rate** — pure pause sounds (um/uh/erm) per 100 reliable words,
    using the same pattern --remove-fillers strips (see filler_filter.py), so
    the metric can never disagree with the cleanup. A LOWER BOUND on real
    disfluency: whisper drops many hesitations before we ever see the text.
  - **Discourse-marker rate** — "you know", "I mean", "kind of" and friends per
    100 reliable words (see discourse.py). Tracked separately from the filler
    rate because they are a different thing measured a different way, and
    because for this speaker they are the larger problem by two orders of
    magnitude. Never stripped from the text, only counted.
  - **Speaking rate** — words per minute across your own reliable speech.
    **Only comparable against sessions recorded in the same mode**, which is
    why `speech_time_basis` is reported next to it. The denominator is the sum
    of your line durations, and a "line" is a different object in the two
    modes: diarization hands over VAD-tight turns, whisper's own segmentation
    hands over long stretches that swallow the pauses inside them. Measured on
    this project's own recordings, the lines cover 55% of the wall clock in a
    diarized session against 93% in a solo one — median line length 2.7s
    against 18s. So the same speaker at the same speed reads as roughly 105
    wpm diarized and 58 wpm solo, and reading that gap as a collapse in
    fluency would be the 2026-08-06 filler artifact all over again.
  - **Low-confidence share** — what fraction of your lines, and of your words,
    whisper wasn't sure about. A quality-of-input measure, not a
    quality-of-speech one: high values mean the microphone, not the speaker.
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
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Optional

from . import discourse
from .filler_filter import FILLER_SOUND_PATTERN
from .formatter import DEFAULT_LOW_CONFIDENCE_THRESHOLD, is_low_confidence

logger = logging.getLogger(__name__)

# A gap longer than this between two of your own lines reads as a hesitation
# rather than ordinary sentence spacing. Only meaningful for solo recordings.
LONG_PAUSE_SEC = 2.0

# Above this share of low-confidence WORDS (not lines — see the module
# docstring), the recording is telling you about itself rather than about the
# speaker: that much of the transcript is excluded from grammar judgment, and
# the word metrics rest on whatever is left.
LOW_CONFIDENCE_WARN_SHARE = 0.4

# What the words_per_minute denominator was built from. Diarization hands over
# VAD-tight turns; without it, whisper's own segments run long and include the
# pauses inside them. See the module docstring for the measured difference.
VAD_BASIS = "vad"
SEGMENT_BASIS = "segment"

# Everything on FluencyMetrics goes into the history CSV except this, which is a
# per-marker mapping: it belongs in fluency.json, where nesting is free, not in
# a column-per-session table that would need a new column per marker.
_BREAKDOWN_FIELD = "discourse_marker_breakdown"

HISTORY_COLUMNS = [
    "run_at",
    "date",
    "origin",
    "mode",
    "files",
    "total_lines",
    "low_confidence_lines",
    "low_confidence_share",
    "low_confidence_word_share",
    "total_words",
    "reliable_words",
    "speech_minutes",
    "words_per_minute",
    "speech_time_basis",
    "filler_count",
    "fillers_per_100_words",
    "discourse_marker_count",
    "discourse_markers_per_100_words",
    "median_pause_sec",
    "long_pauses",
]


@dataclass
class FluencyMetrics:
    total_lines: int
    low_confidence_lines: int
    # 0.0-1.0, by line. Kept because it's what the [?] markers in the annotated
    # document look like when you scroll through them, and because the first
    # four sessions were logged this way — but it over-weights short
    # backchannels, so don't act on it. See low_confidence_word_share.
    low_confidence_share: float
    # 0.0-1.0, by word. Read this before reading anything else here: it says how
    # much of the analyzable transcript the rest of the numbers rest on.
    low_confidence_word_share: float
    total_words: int
    # The denominator for every rate below — words on lines whisper was
    # confident about.
    reliable_words: int
    speech_minutes: float
    words_per_minute: float
    # "vad" (diarization supplied tight speech turns) or "segment" (whisper's
    # own boundaries, which include the pauses inside them). words_per_minute
    # means a different thing under each, so never compare across the two.
    speech_time_basis: str
    # None when --remove-fillers stripped them before we could count: reporting
    # 0 there would look like flawless delivery instead of a missing reading.
    filler_count: Optional[int]
    fillers_per_100_words: Optional[float]
    # Never None: --remove-fillers strips um/uh, not "you know", so these stay
    # measurable on every run. See discourse.py.
    discourse_marker_count: int
    discourse_markers_per_100_words: float
    # None for diarized recordings — see the module docstring.
    median_pause_sec: Optional[float]
    long_pauses: Optional[int]
    # Which markers, not just how many. JSON only, never a CSV column.
    discourse_marker_breakdown: dict = field(default_factory=dict)


def count_words(text: str) -> int:
    return len(text.split())


def count_fillers(text: str) -> int:
    return len(FILLER_SOUND_PATTERN.findall(text))


def count_discourse_markers(text: str) -> int:
    return discourse.count_all(text)


def _rate_per_100_words(count: int, total_words: int) -> float:
    if total_words <= 0:
        return 0.0
    return round(count / total_words * 100, 2)


def _word_share(total_words: int, reliable_words: int) -> float:
    """How much of the SPEECH was lost to low confidence, as opposed to how many
    lines were — the distinction the module docstring is about."""
    if total_words <= 0:
        return 0.0
    return round((total_words - reliable_words) / total_words, 3)


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

    # Same population as the filler rate — reliable lines only. A "you know"
    # inside a line whisper misheard is no more trustworthy than a mistake in it.
    breakdown = discourse.merge_counts([discourse.count_markers(line.text) for line in reliable])
    marker_count = sum(breakdown.values())

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
        low_confidence_word_share=_word_share(total_words, reliable_words),
        total_words=total_words,
        reliable_words=reliable_words,
        speech_minutes=round(speech_minutes, 2),
        words_per_minute=round(reliable_words / speech_minutes, 1) if speech_minutes > 0 else 0.0,
        speech_time_basis=VAD_BASIS if use_diarization else SEGMENT_BASIS,
        filler_count=filler_count,
        fillers_per_100_words=filler_rate,
        discourse_marker_count=marker_count,
        discourse_markers_per_100_words=_rate_per_100_words(marker_count, reliable_words),
        median_pause_sec=median_pause,
        long_pauses=long_pauses,
        discourse_marker_breakdown=breakdown,
    )


def warn_if_unreliable(metrics: FluencyMetrics) -> str | None:
    """
    Returns a warning when so much of the transcript is low-confidence that the
    session isn't comparable with the others — or None when it's fine.

    Fires on the WORD share, not the line share. Fired on lines, this check
    would have gone off for 2026-08-06 and 2026-08-08 (60% and 57%) and put
    "fix your recording setup" at the top of the coaching priorities — where it
    duly ended up. But those sessions lost 23% and 15% of their words: what the
    line count was really reporting is that this speaker says "Yeah." a lot, and
    that whisper is least sure of itself on two-word utterances. Warning on that
    spends the owner's top priority on the microphone instead of on their
    English. See the module docstring for the full numbers.
    """
    if metrics.total_words == 0 or metrics.low_confidence_word_share < LOW_CONFIDENCE_WARN_SHARE:
        return None
    lost_words = metrics.total_words - metrics.reliable_words
    return (
        f"{metrics.low_confidence_word_share:.0%} of your words ({lost_words} of "
        f"{metrics.total_words}, spread over {metrics.low_confidence_lines} of "
        f"{metrics.total_lines} lines) were recognized with low confidence. That's a "
        f"recording-quality signal, not a speaking one: the grammar analysis skips those lines "
        f"entirely, and the numbers here rest on the {metrics.reliable_words} words that remain — "
        f"so don't compare them against sessions with cleaner audio. Check the mic, the distance "
        f"and the background noise before reading anything into this session's fluency."
    )


_ANNOTATED_LINE = re.compile(r"^\[(\d\d):(\d\d):(\d\d)\](?P<marker>\s\[\?\])?\s*(?P<text>.*)$")


def reliable_lines_from_annotated(text: str) -> list[str]:
    """The spoken text of every line whisper was confident about.

    Which lines to trust is this module's rule, and it is not a detail — see the
    module docstring on what happens to a filler count when mis-recognised lines
    are included. Anything else measuring the speaker's words over a session's
    transcript reads them through here rather than re-deriving the marker
    convention.
    """
    lines = []
    for raw in text.splitlines():
        match = _ANNOTATED_LINE.match(raw.strip())
        if match and not match.group("marker"):
            lines.append(match.group("text"))
    return lines


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
    per_line_markers: list[dict[str, int]] = []

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
            per_line_markers.append(discourse.count_markers(line_text))

    breakdown = discourse.merge_counts(per_line_markers)
    marker_count = sum(breakdown.values())

    return FluencyMetrics(
        total_lines=total_lines,
        low_confidence_lines=low_confidence_lines,
        low_confidence_share=round(low_confidence_lines / total_lines, 3) if total_lines else 0.0,
        low_confidence_word_share=_word_share(total_words, reliable_words),
        total_words=total_words,
        reliable_words=reliable_words,
        speech_minutes=0.0,
        words_per_minute=0.0,
        # No timing survives in the annotated format, so there's no rate to
        # attach a basis to.
        speech_time_basis="",
        filler_count=filler_count,
        fillers_per_100_words=_rate_per_100_words(filler_count, reliable_words),
        discourse_marker_count=marker_count,
        discourse_markers_per_100_words=_rate_per_100_words(marker_count, reliable_words),
        median_pause_sec=None,
        long_pauses=None,
        discourse_marker_breakdown=breakdown,
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
    row.update({
        k: ("" if v is None else v)
        for k, v in asdict(metrics).items() if k != _BREAKDOWN_FIELD
    })
    return row


def _align_history_header(history_path: Path) -> None:
    """
    Brings an existing history file up to the current HISTORY_COLUMNS.

    Adding a measurement adds a column, and a file written under the old header
    would then get rows longer than its own header — every column after the
    insertion point silently shifted by one for anyone reading it back. So the
    header (and only the header) is rewritten, with empty cells filled in for
    the sessions that predate the new columns. Empty is the correct value there:
    those measurements genuinely weren't taken, and `_history_row` already uses
    the same convention for anything unmeasured.

    Refuses rather than drops if the file has a column this version doesn't know
    about — that would be deleting recorded measurements to make a schema fit,
    and this file is append-only precisely so that can't happen.
    """
    if not history_path.exists():
        return

    with history_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        existing = list(reader.fieldnames or [])
        rows = list(reader)

    if existing == HISTORY_COLUMNS:
        return

    unknown = [c for c in existing if c not in HISTORY_COLUMNS]
    if unknown:
        raise RuntimeError(
            f"{history_path} has column(s) this version doesn't know about: {unknown}. "
            "Refusing to rewrite the header, because that would drop them. Either restore "
            "the version of voxlib that wrote them, or move the file aside deliberately."
        )

    with history_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in HISTORY_COLUMNS})

    added = [c for c in HISTORY_COLUMNS if c not in existing]
    logger.info(
        "Extended %s with new column(s) %s; the %d existing row(s) keep empty cells there "
        "(those measurements were never taken).", history_path, added, len(rows),
    )


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
    _align_history_header(history_path)
    with history_path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow(row)

    logger.info("Fluency measurement appended to %s", history_path)


@dataclass
class HistoryRow:
    """One recorded run, as read back out of the history CSV.

    Every numeric field is Optional for the same reason `_history_row` writes an
    empty cell rather than a 0: the older rows predate columns that exist now,
    and a backfilled row never had a clock to measure speech time with. A reader
    that turns those blanks into zeros invents a session that was measured and
    came out at nothing.
    """
    run_at: str
    date: str
    origin: str
    mode: str
    files: Optional[int]
    total_lines: Optional[int]
    low_confidence_lines: Optional[int]
    low_confidence_share: Optional[float]
    low_confidence_word_share: Optional[float]
    total_words: Optional[int]
    reliable_words: Optional[int]
    speech_minutes: Optional[float]
    words_per_minute: Optional[float]
    speech_time_basis: str
    filler_count: Optional[int]
    fillers_per_100_words: Optional[float]
    discourse_marker_count: Optional[int]
    discourse_markers_per_100_words: Optional[float]
    median_pause_sec: Optional[float]
    long_pauses: Optional[int]

    @property
    def comparable_pace(self) -> bool:
        """Whether this row's words_per_minute can be plotted beside another's.

        It cannot be, across a change of basis. Diarization hands over VAD-tight
        turns and whisper's own segments include the pauses inside them, so the
        same speaker at the same speed measures substantially faster on the
        first than on the second — the module docstring has the measured gap. A
        history that crosses that line, drawn as one series, shows a collapse in
        pace that never happened.
        """
        return bool(self.speech_time_basis) and self.words_per_minute is not None


def _number(raw: str, cast):
    raw = (raw or "").strip()
    if raw == "":
        return None
    try:
        return cast(raw)
    except ValueError:
        # A malformed cell is missing data, not a reason to refuse the file:
        # this history is the only copy of every past run.
        logger.warning("Unreadable numeric cell %r in the fluency history", raw)
        return None


def load_history(path: Path) -> list[HistoryRow]:
    """Every recorded run, oldest first. Missing file means nothing measured yet.

    Rows are returned as recorded, including two runs of the same date — see
    `latest_per_date` for the one-row-per-session view most readers want.
    """
    if not path.exists():
        return []

    rows: list[HistoryRow] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            rows.append(HistoryRow(
                run_at=(raw.get("run_at") or "").strip(),
                date=(raw.get("date") or "").strip(),
                origin=(raw.get("origin") or "").strip(),
                mode=(raw.get("mode") or "").strip(),
                files=_number(raw.get("files"), int),
                total_lines=_number(raw.get("total_lines"), int),
                low_confidence_lines=_number(raw.get("low_confidence_lines"), int),
                low_confidence_share=_number(raw.get("low_confidence_share"), float),
                low_confidence_word_share=_number(raw.get("low_confidence_word_share"), float),
                total_words=_number(raw.get("total_words"), int),
                reliable_words=_number(raw.get("reliable_words"), int),
                speech_minutes=_number(raw.get("speech_minutes"), float),
                words_per_minute=_number(raw.get("words_per_minute"), float),
                speech_time_basis=(raw.get("speech_time_basis") or "").strip(),
                filler_count=_number(raw.get("filler_count"), int),
                fillers_per_100_words=_number(raw.get("fillers_per_100_words"), float),
                discourse_marker_count=_number(raw.get("discourse_marker_count"), int),
                discourse_markers_per_100_words=_number(
                    raw.get("discourse_markers_per_100_words"), float),
                median_pause_sec=_number(raw.get("median_pause_sec"), float),
                long_pauses=_number(raw.get("long_pauses"), int),
            ))
    rows.sort(key=lambda r: (r.date, r.run_at))
    return rows


def latest_per_date(rows: list[HistoryRow]) -> list[HistoryRow]:
    """One row per session date — the last run of that date wins.

    A recording re-run after a fix appends a second row for the same date rather
    than replacing the first (the file is append-only). The later run is the
    current measurement of that session; the earlier one stays on record.
    """
    by_date: dict[str, HistoryRow] = {}
    for row in rows:
        by_date[row.date] = row
    return [by_date[date] for date in sorted(by_date)]


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


def _top_markers(breakdown: dict, limit: int = 3) -> str:
    ranked = sorted(breakdown.items(), key=lambda item: -item[1])[:limit]
    return ", ".join(f'"{name}" {count}x' for name, count in ranked)


def describe(metrics: FluencyMetrics) -> str:
    """One line for the log and the console summary."""
    basis = f" ({metrics.speech_time_basis} basis)" if metrics.speech_time_basis else ""
    parts = [f"{metrics.words_per_minute:.0f} words/min{basis}"]
    if metrics.fillers_per_100_words is None:
        parts.append("fillers not measurable (--remove-fillers stripped them)")
    else:
        parts.append(f"{metrics.fillers_per_100_words:.2f} fillers per 100 words "
                     f"({metrics.filler_count} total)")
    markers = f"{metrics.discourse_markers_per_100_words:.2f} discourse markers per 100 words"
    if metrics.discourse_marker_breakdown:
        markers += f" ({_top_markers(metrics.discourse_marker_breakdown)})"
    parts.append(markers)
    if metrics.median_pause_sec is not None:
        parts.append(f"median pause {metrics.median_pause_sec:.2f}s, "
                     f"{metrics.long_pauses} over {LONG_PAUSE_SEC:.0f}s")
    # Last, but always present: it's the caveat on everything before it. Both
    # shares, because the gap between them is itself the finding — see the
    # module docstring.
    parts.append(f"{metrics.low_confidence_word_share:.0%} of words low-confidence "
                 f"({metrics.low_confidence_share:.0%} of lines)")
    return "; ".join(parts)
