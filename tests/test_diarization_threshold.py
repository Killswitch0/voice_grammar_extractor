import logging

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
