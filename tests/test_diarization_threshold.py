import logging

import pytest

from voxlib.diarization import DiarizationEngine, DEFAULT_THRESHOLD

# _suggest_threshold_from_gap and resolve_threshold are @staticmethods with no
# torch/pyannote usage, so they're callable directly on the class without ever
# constructing a DiarizationEngine (which would require a HuggingFace token
# and the ML deps).


def test_suggests_midpoint_of_biggest_gap():
    suggested, gap = DiarizationEngine._suggest_threshold_from_gap({"A": 0.9, "B": 0.3})
    assert round(suggested, 2) == 0.6
    assert round(gap, 2) == 0.6


def test_single_speaker_is_a_no_op():
    assert DiarizationEngine._suggest_threshold_from_gap({"A": 0.9}) is None


def test_picks_biggest_gap_among_three_speakers():
    # Sorted values: 0.9, 0.5, 0.4 -> gaps are 0.4 (between 0.9/0.5) and 0.1 (between 0.5/0.4).
    # The biggest gap is the first one, so the suggestion should be its midpoint: 0.7.
    suggested, gap = DiarizationEngine._suggest_threshold_from_gap({"A": 0.9, "B": 0.5, "C": 0.4})
    assert suggested == 0.7
    assert gap == 0.4


def test_resolve_threshold_returns_explicit_value_unchanged(caplog):
    caplog.set_level(logging.INFO)
    result = DiarizationEngine.resolve_threshold({"A": 0.9, "B": 0.3}, explicit_threshold=0.75)
    assert result == 0.75


def test_resolve_threshold_logs_hint_when_explicit_disagrees_with_suggestion(caplog):
    caplog.set_level(logging.INFO)
    DiarizationEngine.resolve_threshold({"A": 0.9, "B": 0.3}, explicit_threshold=0.75)

    assert len(caplog.records) == 1
    assert "0.60" in caplog.records[0].getMessage()


def test_resolve_threshold_no_hint_when_suggestion_matches_explicit(caplog):
    caplog.set_level(logging.INFO)
    # Midpoint of 0.76 and 0.74 is exactly 0.75 -> matches explicit threshold -> no hint.
    DiarizationEngine.resolve_threshold({"A": 0.76, "B": 0.74}, explicit_threshold=0.75)

    assert caplog.records == []


def test_resolve_threshold_auto_calibrates_on_clear_gap(caplog):
    caplog.set_level(logging.INFO)
    result = DiarizationEngine.resolve_threshold(
        {"SPEAKER_02": 0.7275804281234741, "SPEAKER_01": 0.09839118272066116, "SPEAKER_00": -0.11865130066871643},
        explicit_threshold=None,
    )
    assert round(result, 2) == 0.41
    assert any("Auto-selected threshold" in r.getMessage() for r in caplog.records)


def test_resolve_threshold_falls_back_when_best_match_is_too_weak(caplog):
    caplog.set_level(logging.INFO)
    result = DiarizationEngine.resolve_threshold({"A": 0.2, "B": -0.1}, explicit_threshold=None)

    assert result == DEFAULT_THRESHOLD
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_resolve_threshold_trusts_gap_exactly_at_confidence_floor(caplog):
    caplog.set_level(logging.INFO)
    # Top similarity is exactly MIN_CONFIDENT_SIMILARITY (0.3) -> the floor
    # check is strict (<), so this is still trusted, not a fallback.
    result = DiarizationEngine.resolve_threshold({"A": 0.3, "B": 0.1}, explicit_threshold=None)

    assert result == 0.2
    assert not any(r.levelno == logging.WARNING for r in caplog.records)


def test_resolve_threshold_falls_back_with_single_speaker(caplog):
    caplog.set_level(logging.INFO)
    result = DiarizationEngine.resolve_threshold({"A": 0.9}, explicit_threshold=None)

    assert result == DEFAULT_THRESHOLD
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def _warnings(caplog) -> str:
    return "\n".join(r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


def test_warns_when_several_speakers_pass_the_threshold(caplog):
    """
    "Is this speaker me" is decided per speaker independently, so two people
    can clear the same bar — and gap-based calibration makes it easy, since
    the biggest gap can sit between speakers 2 and 3. The result is someone
    else's sentences in a document that's supposed to hold only yours.
    """
    caplog.set_level(logging.INFO)
    # Biggest gap is between B (0.70) and C (0.10), so the auto threshold
    # (~0.40) admits BOTH A and B.
    result = DiarizationEngine.resolve_threshold(
        {"A": 0.85, "B": 0.70, "C": 0.10}, explicit_threshold=None
    )

    assert result == pytest.approx(0.40)
    warning = _warnings(caplog)
    assert "2 speakers passed" in warning
    assert "A=0.85" in warning and "B=0.70" in warning
    # Points at the value that would fix it: just above the runner-up.
    assert "0.70" in warning


def test_warns_when_no_speaker_passes_the_threshold(caplog):
    caplog.set_level(logging.INFO)
    result = DiarizationEngine.resolve_threshold({"A": 0.20, "B": 0.10}, explicit_threshold=0.9)

    assert result == 0.9
    warning = _warnings(caplog)
    assert "No speaker passed" in warning
    assert "empty transcript" in warning


def test_no_ambiguity_warning_for_a_clean_single_match(caplog):
    caplog.set_level(logging.INFO)
    DiarizationEngine.resolve_threshold({"A": 0.85, "B": 0.10}, explicit_threshold=0.5)

    warning = _warnings(caplog)
    assert "passed the threshold" not in warning


def test_ambiguity_warning_also_fires_for_an_explicit_threshold(caplog):
    # The check lives at resolve_threshold's single exit point precisely so it
    # covers explicitly-passed thresholds and the pipeline's cache-hit path
    # too, not just fresh auto-calibration.
    caplog.set_level(logging.INFO)
    DiarizationEngine.resolve_threshold({"A": 0.85, "B": 0.80}, explicit_threshold=0.5)

    assert "2 speakers passed" in _warnings(caplog)
