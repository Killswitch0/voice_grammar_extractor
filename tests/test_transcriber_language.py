"""
Covers language handling in transcribe_my_segments without pulling in
faster-whisper (which the default CI job doesn't install — see
.github/workflows/tests.yml). Only the module's own decision-making is
exercised: what language it passes down, and how often it decides.
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from voxlib.diarization import IdentifiedSegment
from voxlib.transcriber import Transcriber


@pytest.fixture
def fake_faster_whisper(monkeypatch):
    audio_module = types.ModuleType("faster_whisper.audio")
    audio_module.decode_audio = lambda path, sampling_rate=16000: np.zeros(16000, dtype=np.float32)
    package = types.ModuleType("faster_whisper")
    package.audio = audio_module
    monkeypatch.setitem(sys.modules, "faster_whisper", package)
    monkeypatch.setitem(sys.modules, "faster_whisper.audio", audio_module)


class FakeSegment:
    def __init__(self, text):
        self.text = text
        self.avg_logprob = -0.2


class FakeModel:
    """Records what language each transcribe call was given."""

    def __init__(self, detected=("ru", 0.97)):
        self.languages_used: list = []
        self.detect_calls = 0
        self._detected = detected

    def detect_language(self, audio=None, language_detection_segments=1):
        self.detect_calls += 1
        language, probability = self._detected
        return language, probability, []

    def transcribe(self, audio, language=None, **kwargs):
        self.languages_used.append(language)
        return iter([FakeSegment("some words")]), None


def _transcriber(model: FakeModel) -> Transcriber:
    # Bypass __init__ so no real whisper model is loaded.
    transcriber = Transcriber.__new__(Transcriber)
    transcriber.model = model
    transcriber.batch_size = None
    transcriber.batched_pipeline = None
    return transcriber


def _segments(count: int) -> list[IdentifiedSegment]:
    return [
        IdentifiedSegment(start=float(i) * 2, end=float(i) * 2 + 1.5, is_me=True, similarity=0.9)
        for i in range(count)
    ]


def test_language_is_detected_once_per_file_not_once_per_segment(fake_faster_whisper, tmp_path):
    """
    With --language auto, each segment used to be handed to whisper with
    language=None — meaning the language was re-guessed from one or two
    seconds of audio, far too little to be reliable. A single English segment
    coming back as Russian would then look like a grammar mistake the speaker
    never made.
    """
    model = FakeModel(detected=("en", 0.99))
    transcriber = _transcriber(model)

    transcriber.transcribe_my_segments(tmp_path / "f.wav", _segments(5), language=None)

    assert model.detect_calls == 1
    assert model.languages_used == ["en"] * 5


def test_an_explicit_language_is_never_second_guessed(fake_faster_whisper, tmp_path):
    model = FakeModel()
    transcriber = _transcriber(model)

    transcriber.transcribe_my_segments(tmp_path / "f.wav", _segments(3), language="en")

    assert model.detect_calls == 0
    assert model.languages_used == ["en"] * 3


def test_failed_detection_falls_back_instead_of_aborting_the_run(fake_faster_whisper, tmp_path):
    class ExplodingModel(FakeModel):
        def detect_language(self, audio=None, language_detection_segments=1):
            raise RuntimeError("detection unavailable")

    model = ExplodingModel()
    transcriber = _transcriber(model)

    lines = transcriber.transcribe_my_segments(tmp_path / "f.wav", _segments(2), language=None)

    # Old per-segment behavior, rather than losing a long transcription run
    # over a diagnostic.
    assert model.languages_used == [None, None]
    assert len(lines) == 2


def test_short_segments_that_get_dropped_are_reported(fake_faster_whisper, tmp_path, caplog):
    import logging

    caplog.set_level(logging.INFO)
    model = FakeModel()
    transcriber = _transcriber(model)

    segments = [
        IdentifiedSegment(start=0.0, end=2.0, is_me=True, similarity=0.9),
        IdentifiedSegment(start=3.0, end=3.1, is_me=True, similarity=0.9),  # 0.1s
    ]
    transcriber.transcribe_my_segments(tmp_path / "f.wav", segments, language="en")

    assert "Skipped 1 of your segments shorter than" in caplog.text


def test_dropped_short_segments_are_reported_even_when_nothing_is_left(
    fake_faster_whisper, tmp_path, caplog,
):
    """The case where silence is most confusing: every one of your segments
    was too short, so the file contributes nothing at all."""
    import logging

    caplog.set_level(logging.INFO)
    transcriber = _transcriber(FakeModel())

    segments = [IdentifiedSegment(start=0.0, end=0.1, is_me=True, similarity=0.9)]
    lines = transcriber.transcribe_my_segments(tmp_path / "f.wav", segments, language="en")

    assert lines == []
    assert "Skipped 1 of your segments shorter than" in caplog.text
