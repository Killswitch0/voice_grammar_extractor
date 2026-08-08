import csv
import json
from pathlib import Path

from voxlib import fluency
from voxlib.filler_filter import remove_fillers
from voxlib.formatter import SourcedLine


def _line(start: float, end: float, text: str, source: str = "a.webm") -> SourcedLine:
    return SourcedLine(source_file=source, start=start, end=end, text=text)


def test_filler_rate_is_per_100_words_not_a_raw_ratio():
    """The unit is per 100 words, matching analysis/scores_history.csv's
    filler_rate_per_100_words column — not a bare count/total ratio."""
    lines = [_line(0.0, 5.0, "uh " + " ".join(["word"] * 99))]

    metrics = fluency.compute_fluency(lines, use_diarization=False, fillers_removed=False)

    assert metrics.total_words == 100
    assert metrics.filler_count == 1
    assert metrics.fillers_per_100_words == 1.0


def test_counting_agrees_with_what_remove_fillers_strips():
    """Both sides share one regex on purpose — a metric that disagrees with
    the cleanup it describes is worse than no metric."""
    text = "Um, I uh think erm so"

    assert fluency.count_fillers(text) == 3
    assert fluency.count_fillers(remove_fillers(text)) == 0


def test_words_per_minute_uses_your_speech_duration():
    # 30 words spoken across 60 seconds of my own segments -> 30 wpm.
    lines = [
        _line(0.0, 30.0, " ".join(["word"] * 15)),
        _line(100.0, 130.0, " ".join(["word"] * 15)),
    ]

    metrics = fluency.compute_fluency(lines, use_diarization=False, fillers_removed=False)

    assert metrics.speech_minutes == 1.0
    assert metrics.words_per_minute == 30.0


def test_removed_fillers_report_none_rather_than_zero():
    """A stripped transcript must not read as flawless delivery — 'not
    measured' and 'measured as zero' are different facts."""
    lines = [_line(0.0, 5.0, "I think so")]

    metrics = fluency.compute_fluency(lines, use_diarization=False, fillers_removed=True)

    assert metrics.filler_count is None
    assert metrics.fillers_per_100_words is None


def test_pauses_are_measured_for_solo_recordings():
    lines = [
        _line(0.0, 1.0, "first"),
        _line(2.0, 3.0, "second"),    # 1.0s gap
        _line(9.0, 10.0, "third"),    # 6.0s gap -> long
    ]

    metrics = fluency.compute_fluency(lines, use_diarization=False, fillers_removed=False)

    assert metrics.median_pause_sec == 3.5  # median of [1.0, 6.0]
    assert metrics.long_pauses == 1


def test_pauses_are_not_reported_for_diarized_recordings():
    """
    In a diarized recording the gap between two of your lines is mostly the
    other person's turn, so the same number would mean something different
    depending on the recording — precisely the drift that makes a tracked
    metric worthless. Better absent than misleading.
    """
    lines = [_line(0.0, 1.0, "first"), _line(30.0, 31.0, "second")]

    metrics = fluency.compute_fluency(lines, use_diarization=True, fillers_removed=False)

    assert metrics.median_pause_sec is None
    assert metrics.long_pauses is None
    # Rate metrics stay comparable across modes and are still reported.
    assert metrics.words_per_minute > 0


def test_pauses_do_not_span_two_source_files():
    # The "gap" between the end of one recording and the start of the next is
    # not a pause in speech — it's a different day, possibly.
    lines = [
        _line(0.0, 1.0, "first", source="a.webm"),
        _line(500.0, 501.0, "second", source="b.webm"),
        _line(502.0, 503.0, "third", source="b.webm"),
    ]

    metrics = fluency.compute_fluency(lines, use_diarization=False, fillers_removed=False)

    assert metrics.median_pause_sec == 1.0  # only the within-b.webm gap
    assert metrics.long_pauses == 0


def test_overlapping_segments_do_not_count_as_zero_length_pauses():
    lines = [
        _line(0.0, 5.0, "first"),
        _line(3.0, 6.0, "overlaps the previous line"),
        _line(8.0, 9.0, "third"),
    ]

    metrics = fluency.compute_fluency(lines, use_diarization=False, fillers_removed=False)

    # The negative gap is skipped, not clamped to 0.0, which would have pulled
    # the median down and understated the real pause.
    assert metrics.median_pause_sec == 2.0


def test_empty_input_does_not_divide_by_zero():
    metrics = fluency.compute_fluency([], use_diarization=False, fillers_removed=False)

    assert metrics.total_words == 0
    assert metrics.words_per_minute == 0.0
    assert metrics.fillers_per_100_words == 0.0
    assert metrics.median_pause_sec is None


def test_metrics_from_annotated_text_reports_no_timing_instead_of_guessing():
    """The annotated format records each line's start but not its end, so
    speaking rate and pauses are genuinely unrecoverable — they must not be
    estimated from the gaps between starts, which would conflate a pause with
    how long the previous line took to say."""
    annotated = "\n".join([
        "=== call.webm ===",
        "[00:00:00] Uh I think uh so " + " ".join(["word"] * 95),
    ])

    metrics = fluency.metrics_from_annotated_text(annotated)

    assert metrics.total_words == 100
    assert metrics.filler_count == 2
    assert metrics.fillers_per_100_words == 2.0
    assert metrics.words_per_minute == 0.0
    assert metrics.median_pause_sec is None


def test_metrics_from_annotated_text_excludes_low_confidence_lines():
    annotated = "\n".join([
        "=== call.webm ===",
        "[00:00:00] uh a reliable line with words",
        "[00:00:05] [?] uh uh uh a garbled one",
    ])

    metrics = fluency.metrics_from_annotated_text(annotated)

    assert metrics.total_lines == 2
    assert metrics.low_confidence_lines == 1
    assert metrics.low_confidence_share == 0.5
    assert metrics.total_words == 12          # both lines
    assert metrics.reliable_words == 6        # only the first
    assert metrics.filler_count == 1          # the three "uh"s in [?] don't count


def test_append_history_writes_a_header_once_then_appends(tmp_path: Path):
    history = tmp_path / "analysis" / "fluency_history.csv"
    metrics = fluency.compute_fluency(
        [_line(0.0, 60.0, "uh " + " ".join(["word"] * 59))],
        use_diarization=False, fillers_removed=False,
    )

    fluency.append_history(history, metrics, mode="solo", files=1, date="2026-08-08")
    fluency.append_history(history, metrics, mode="solo", files=1, date="2026-08-09")

    rows = list(csv.DictReader(history.read_text(encoding="utf-8").splitlines()))
    assert [r["date"] for r in rows] == ["2026-08-08", "2026-08-09"]
    assert rows[0]["fillers_per_100_words"] == "1.67"
    assert rows[0]["mode"] == "solo"
    assert rows[0]["origin"] == "pipeline"
    assert rows[0]["run_at"]  # two runs on one day stay distinguishable


def test_unmeasured_values_are_empty_cells_not_zeros(tmp_path: Path):
    history = tmp_path / "fluency_history.csv"
    metrics = fluency.compute_fluency(
        [_line(0.0, 60.0, "I think so")], use_diarization=True, fillers_removed=True,
    )

    fluency.append_history(history, metrics, mode="diarization", files=1)

    row = next(iter(csv.DictReader(history.read_text(encoding="utf-8").splitlines())))
    assert row["filler_count"] == ""
    assert row["median_pause_sec"] == ""
    assert row["words_per_minute"] != ""


def test_write_json_records_the_pause_threshold_it_used(tmp_path: Path):
    metrics = fluency.compute_fluency(
        [_line(0.0, 60.0, "I think so")], use_diarization=False, fillers_removed=False,
    )

    fluency.write_json(tmp_path / "fluency.json", metrics, mode="solo", files=1)

    payload = json.loads((tmp_path / "fluency.json").read_text(encoding="utf-8"))
    assert payload["mode"] == "solo"
    assert payload["long_pause_threshold_sec"] == fluency.LONG_PAUSE_SEC
    assert payload["total_words"] == 3


def test_describe_says_when_fillers_could_not_be_measured():
    stripped = fluency.compute_fluency(
        [_line(0.0, 60.0, "I think so")], use_diarization=False, fillers_removed=True,
    )
    assert "not measurable" in fluency.describe(stripped)

    measured = fluency.compute_fluency(
        [_line(0.0, 60.0, "uh I think so")], use_diarization=False, fillers_removed=False,
    )
    assert "fillers per 100 words" in fluency.describe(measured)


def test_backchannel_is_not_counted_as_hesitation():
    """
    The analysis workflow has always excluded "uh-huh"/"mm-hmm" by hand,
    calling them backchannel acknowledgment rather than hesitation. The metric
    has to apply the same rule, or the new numbers silently stop being
    comparable with the sessions already on record.
    """
    text = "Uh-huh. Mm-hmm. Uh, I think so."

    assert fluency.count_fillers(text) == 1


def test_backchannel_and_low_confidence_are_both_excluded_together():
    """
    The shape of a real session in this project: plenty of "Uh-huh"/"Mm-hmm"
    acknowledgment (agreement, not hesitation) plus a run of garbled short
    lines that whisper flagged. Only the one genuine hesitation on a reliable
    line should register.
    """
    annotated = "\n".join(
        ["=== part_01.webm ==="]
        + [f"[00:00:{i:02d}] Uh-huh." for i in range(7)]
        + [f"[00:01:{i:02d}] Mm-hmm." for i in range(32)]
        + ["[00:02:00] I, uh, skydive."]
        + [f"[00:03:{i:02d}] [?] uh uh" for i in range(10)]
    )

    metrics = fluency.metrics_from_annotated_text(annotated)

    assert metrics.filler_count == 1
    assert metrics.low_confidence_lines == 10


def test_low_confidence_lines_do_not_inflate_the_filler_rate():
    """
    This is the 2026-08-06 case, reduced: nearly every "filler" sat inside a
    line whisper wasn't sure about, which read as a sudden fluency collapse
    when it was really the audio degrading. Counted over reliable lines, the
    session is unremarkable.
    """
    annotated = "\n".join(
        ["=== part_01.webm ==="]
        + [f"[00:00:{i:02d}] [?] uh uh uh" for i in range(17)]
        + ["[00:01:00] uh " + " ".join(["word"] * 99)]
    )

    metrics = fluency.metrics_from_annotated_text(annotated)

    assert metrics.filler_count == 1               # not 18
    assert metrics.fillers_per_100_words == 1.0    # denominator is reliable words too
    assert metrics.low_confidence_share == 0.944


def _scored(start, end, text, avg_logprob):
    return SourcedLine(source_file="a.webm", start=start, end=end, text=text, avg_logprob=avg_logprob)


def test_live_metrics_exclude_low_confidence_lines():
    """Same rule as the archived path, applied to the run's own lines: the
    threshold is whatever produced the [?] markers in the document, so the
    metrics and the markers can't disagree about which lines counted."""
    lines = [
        _scored(0.0, 30.0, "uh " + " ".join(["word"] * 29), avg_logprob=-0.1),
        _scored(30.0, 60.0, "uh uh uh garbled", avg_logprob=-0.9),
    ]

    metrics = fluency.compute_fluency(
        lines, use_diarization=False, fillers_removed=False, low_confidence_threshold=-0.5,
    )

    assert metrics.low_confidence_lines == 1
    assert metrics.total_words == 34
    assert metrics.reliable_words == 30
    assert metrics.filler_count == 1
    # 30 reliable words over the 0.5 min of reliable speech, not 34 over 1.0.
    assert metrics.words_per_minute == 60.0


def test_a_missing_logprob_counts_as_confident():
    """Mirrors write_annotated_document: no score means no [?] marker, so
    inventing doubt here would shrink the analyzable transcript silently."""
    lines = [_scored(0.0, 60.0, "I think so", avg_logprob=None)]

    metrics = fluency.compute_fluency(
        lines, use_diarization=False, fillers_removed=False, low_confidence_threshold=-0.5,
    )

    assert metrics.low_confidence_lines == 0
    assert metrics.reliable_words == 3


def test_pauses_still_use_every_line_including_uncertain_ones():
    """A timestamp is valid whether or not the words on it were recognized."""
    lines = [
        _scored(0.0, 1.0, "first", avg_logprob=-0.1),
        _scored(2.0, 3.0, "mumbled", avg_logprob=-0.9),
        _scored(4.0, 5.0, "third", avg_logprob=-0.1),
    ]

    metrics = fluency.compute_fluency(
        lines, use_diarization=False, fillers_removed=False, low_confidence_threshold=-0.5,
    )

    assert metrics.median_pause_sec == 1.0  # both gaps counted


def test_warning_fires_only_above_the_share_threshold():
    def metrics_with(share_numerator, total):
        lines = (
            [_scored(float(i), i + 1.0, "bad", -0.9) for i in range(share_numerator)]
            + [_scored(float(i + 100), i + 101.0, "good", -0.1)
               for i in range(total - share_numerator)]
        )
        return fluency.compute_fluency(
            lines, use_diarization=False, fillers_removed=False, low_confidence_threshold=-0.5,
        )

    assert fluency.warn_if_unreliable(metrics_with(6, 10)) is not None   # 60%, the 2026-08-06 case
    assert fluency.warn_if_unreliable(metrics_with(3, 10)) is None       # 30%, the sessions before it
    assert fluency.warn_if_unreliable(metrics_with(0, 0)) is None        # no lines, nothing to say


def test_warning_explains_it_is_about_the_recording_not_the_speaker():
    lines = [_scored(float(i), i + 1.0, "bad", -0.9) for i in range(9)] + [
        _scored(100.0, 101.0, "good", -0.1)
    ]
    metrics = fluency.compute_fluency(
        lines, use_diarization=False, fillers_removed=False, low_confidence_threshold=-0.5,
    )

    warning = fluency.warn_if_unreliable(metrics)

    assert "recording-quality signal, not a speaking one" in warning
    assert "90%" in warning
