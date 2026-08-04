import logging

from voxlib.diarization import DiarizationEngine

# _log_threshold_suggestion is a @staticmethod with no torch/pyannote usage,
# so it's callable directly on the class without ever constructing a
# DiarizationEngine (which would require a HuggingFace token and the ML deps).


def test_suggests_midpoint_of_biggest_gap(caplog):
    caplog.set_level(logging.INFO)
    DiarizationEngine._log_threshold_suggestion({"A": 0.9, "B": 0.3}, current_threshold=0.75)

    assert len(caplog.records) == 1
    assert "~0.60" in caplog.records[0].message or "0.60" in caplog.records[0].getMessage()


def test_no_hint_when_suggestion_matches_current_threshold(caplog):
    caplog.set_level(logging.INFO)
    # Midpoint of 0.76 and 0.74 is exactly 0.75 -> matches current threshold -> no hint.
    DiarizationEngine._log_threshold_suggestion({"A": 0.76, "B": 0.74}, current_threshold=0.75)

    assert caplog.records == []


def test_single_speaker_is_a_no_op(caplog):
    caplog.set_level(logging.INFO)
    DiarizationEngine._log_threshold_suggestion({"A": 0.9}, current_threshold=0.75)

    assert caplog.records == []


def test_picks_biggest_gap_among_three_speakers(caplog):
    caplog.set_level(logging.INFO)
    # Sorted values: 0.9, 0.5, 0.4 -> gaps are 0.4 (between 0.9/0.5) and 0.1 (between 0.5/0.4).
    # The biggest gap is the first one, so the suggestion should be its midpoint: 0.7.
    DiarizationEngine._log_threshold_suggestion({"A": 0.9, "B": 0.5, "C": 0.4}, current_threshold=0.75)

    assert len(caplog.records) == 1
    assert "0.70" in caplog.records[0].getMessage()
