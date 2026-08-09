import csv
import json
from pathlib import Path

import pytest

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


def test_short_backchannels_dominate_the_line_share_but_not_the_word_share():
    """
    The 2026-08-08 session, reduced to its shape: a pile of two-word "Yeah."
    lines that whisper scored badly (it has almost nothing to be confident from
    on a 0.6-second utterance) alongside a few long, well-recognized sentences.
    By line, most of the session looks lost. By word, almost none of it is.
    Getting this backwards put "fix your recording setup" at the top of the
    coaching priorities for two sessions running.
    """
    lines = [_scored(float(i), i + 0.6, "Yeah.", avg_logprob=-0.75) for i in range(80)] + [
        _scored(float(200 + i * 20), 220.0 + i * 20, " ".join(["word"] * 22), avg_logprob=-0.3)
        for i in range(70)
    ]

    metrics = fluency.compute_fluency(
        lines, use_diarization=True, fillers_removed=False, low_confidence_threshold=-0.5,
    )

    assert metrics.low_confidence_share == 0.533        # most of the lines
    assert metrics.low_confidence_word_share == 0.049   # almost none of the speech
    assert fluency.warn_if_unreliable(metrics) is None


def test_the_warning_fires_on_words_lost_not_lines_lost():
    """A session where the uncertain lines really do carry the speech — that's
    the case worth warning about, and it survives the switch."""
    lines = [_scored(0.0, 60.0, " ".join(["mumbled"] * 90), avg_logprob=-0.9)] + [
        _scored(100.0, 110.0, " ".join(["word"] * 10), avg_logprob=-0.1)
    ]

    metrics = fluency.compute_fluency(
        lines, use_diarization=True, fillers_removed=False, low_confidence_threshold=-0.5,
    )

    assert metrics.low_confidence_share == 0.5          # half the lines
    assert metrics.low_confidence_word_share == 0.9     # nearly all the words
    assert "90% of your words" in fluency.warn_if_unreliable(metrics)


def test_discourse_markers_are_counted_over_reliable_lines_only():
    """Same population as the filler rate: a "you know" inside a line whisper
    misheard is no more trustworthy than a mistake in it."""
    lines = [
        _scored(0.0, 30.0, "you know " + " ".join(["word"] * 98), avg_logprob=-0.1),
        _scored(30.0, 60.0, "you know you know garbled", avg_logprob=-0.9),
    ]

    metrics = fluency.compute_fluency(
        lines, use_diarization=False, fillers_removed=False, low_confidence_threshold=-0.5,
    )

    assert metrics.discourse_marker_count == 1
    assert metrics.discourse_markers_per_100_words == 1.0
    assert metrics.discourse_marker_breakdown == {"you know": 1}


def test_discourse_markers_stay_measurable_when_fillers_are_stripped():
    """--remove-fillers strips um/uh, never "you know" — so unlike the filler
    rate, this one is never a blank."""
    lines = [_line(0.0, 60.0, "you know I think so")]

    metrics = fluency.compute_fluency(lines, use_diarization=False, fillers_removed=True)

    assert metrics.filler_count is None
    assert metrics.discourse_marker_count == 1
    assert "discourse markers" in fluency.describe(metrics)


def test_speaking_rate_records_which_basis_it_was_measured_on():
    """
    The same speech measured two ways. Diarization hands over VAD-tight turns,
    so the denominator is speech; without it, whisper's own segments swallow
    the pauses inside them, so the denominator is closer to wall clock. On this
    project's own recordings that's 55% coverage against 93%, and the rate came
    out 104.7 against 58.1 — a gap that has nothing to do with the speaker.
    Recording the basis is what stops the next session reading it as one.
    """
    # 60 words spoken in 30s, sitting inside a line 60s long (the other 30s
    # being pauses whisper folded into the same segment).
    lines = [_line(0.0, 60.0, " ".join(["word"] * 60))]

    solo = fluency.compute_fluency(lines, use_diarization=False, fillers_removed=False)
    diarized = fluency.compute_fluency(lines, use_diarization=True, fillers_removed=False)

    assert solo.speech_time_basis == fluency.SEGMENT_BASIS
    assert diarized.speech_time_basis == fluency.VAD_BASIS
    assert "segment basis" in fluency.describe(solo)


def test_an_archived_transcript_claims_no_basis_because_it_has_no_rate():
    """No timing survives in the annotated format, so there is no denominator
    to describe — and an empty basis must not read as "vad"."""
    metrics = fluency.metrics_from_annotated_text("[00:00:00] hello there")

    assert metrics.words_per_minute == 0.0
    assert metrics.speech_time_basis == ""


def test_every_measured_field_has_a_history_column():
    """
    A measurement added to the dataclass but not to HISTORY_COLUMNS is invisible
    in the trend — and DictWriter would reject the row outright. The one
    exception is the per-marker breakdown, which is JSON-only by design.
    """
    from dataclasses import fields

    measured = {f.name for f in fields(fluency.FluencyMetrics)} - {"discourse_marker_breakdown"}

    assert measured <= set(fluency.HISTORY_COLUMNS), (
        f"not in HISTORY_COLUMNS: {sorted(measured - set(fluency.HISTORY_COLUMNS))}"
    )


def test_breakdown_goes_to_json_but_never_to_the_csv(tmp_path: Path):
    """One column per marker would make the history table grow sideways every
    time a marker is added; nesting is free in JSON."""
    metrics = fluency.compute_fluency(
        [_line(0.0, 60.0, "you know, I mean, you know")],
        use_diarization=False, fillers_removed=False,
    )

    fluency.write_json(tmp_path / "fluency.json", metrics, mode="solo", files=1)
    fluency.append_history(tmp_path / "history.csv", metrics, mode="solo", files=1)

    payload = json.loads((tmp_path / "fluency.json").read_text(encoding="utf-8"))
    assert payload["discourse_marker_breakdown"] == {"you know": 2, "i mean": 1}

    row = next(iter(csv.DictReader((tmp_path / "history.csv").read_text().splitlines())))
    assert row["discourse_marker_count"] == "3"
    assert "discourse_marker_breakdown" not in row


def test_adding_a_column_rewrites_the_header_without_shifting_old_rows(tmp_path: Path):
    """
    A history file written by an older version has fewer columns. Appending a
    wider row to it would leave every value after the insertion point read back
    against the wrong column name — silent corruption of the one file that isn't
    supposed to be rewritable. The header is brought forward instead, and the
    older sessions get empty cells for what was never measured.
    """
    history = tmp_path / "fluency_history.csv"
    old_columns = [c for c in fluency.HISTORY_COLUMNS if c != "discourse_marker_count"]
    with history.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=old_columns)
        writer.writeheader()
        writer.writerow({**{c: "" for c in old_columns},
                         "date": "2026-08-03", "total_words": 2440, "reliable_words": 2154})

    metrics = fluency.compute_fluency(
        [_line(0.0, 60.0, "you know I think so")], use_diarization=False, fillers_removed=False,
    )
    fluency.append_history(history, metrics, mode="solo", files=1, date="2026-08-09")

    rows = list(csv.DictReader(history.read_text(encoding="utf-8").splitlines()))
    assert [r["date"] for r in rows] == ["2026-08-03", "2026-08-09"]
    # The pre-existing row keeps its values against the right names...
    assert rows[0]["reliable_words"] == "2154"
    # ...and reads as "not measured", not as zero, for the new column.
    assert rows[0]["discourse_marker_count"] == ""
    assert rows[1]["discourse_marker_count"] == "1"


def test_an_unknown_column_is_refused_rather_than_dropped(tmp_path: Path):
    history = tmp_path / "fluency_history.csv"
    with history.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fluency.HISTORY_COLUMNS + ["measured_by_hand"])
        writer.writeheader()

    metrics = fluency.compute_fluency([_line(0.0, 60.0, "hello")],
                                      use_diarization=False, fillers_removed=False)

    with pytest.raises(RuntimeError, match="measured_by_hand"):
        fluency.append_history(history, metrics, mode="solo", files=1)


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
