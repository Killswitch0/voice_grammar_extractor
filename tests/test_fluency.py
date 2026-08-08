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


def test_metrics_from_transcript_text_reports_no_timing_instead_of_guessing():
    """Archived transcripts have no timestamps, so speaking rate and pauses
    are genuinely unrecoverable — they must not be estimated."""
    # "Uh I think uh so" is 5 words, 2 of them fillers.
    metrics = fluency.metrics_from_transcript_text("Uh I think uh so " + " ".join(["word"] * 95))

    assert metrics.total_words == 100
    assert metrics.filler_count == 2
    assert metrics.fillers_per_100_words == 2.0
    assert metrics.words_per_minute == 0.0
    assert metrics.median_pause_sec is None


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


def test_reproduces_the_hand_counted_history_of_this_project():
    """
    Guards continuity of the tracked series: these are the real archived
    session texts' counts, and the values already recorded in
    analysis/scores_history.csv for them. If a change to the pattern ever
    breaks this, the metric has silently become a different metric.
    """
    session = "Uh-huh. " * 7 + "Mm-hmm. " * 32 + "I, uh, skydive. " + " ".join(["word"] * 50)

    metrics = fluency.metrics_from_transcript_text(session)

    assert metrics.filler_count == 1
