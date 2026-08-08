"""
Tests for what the pipeline actually hands to the analysis workflow: the order
of the lines, and its refusal to replace good documents with empty ones.

Everything heavy is faked (see test_pipeline_caching.py for the same approach
with diarization) — no torch, pyannote, whisper or ffmpeg involved.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from voxlib import pipeline
from voxlib.diarization import Segment
from voxlib.pipeline import _no_lines_message, _process_single_file
from voxlib.transcriber import TranscribedLine

from test_pipeline_caching import FakeDiarizer


class FakeSegmentTranscriber:
    """Stand-in for Transcriber in diarization mode: transcribes whatever is
    marked as mine and isn't already cached, honoring on_segment_done so the
    incremental cache writes in _process_single_file still get exercised."""

    def __init__(self):
        self.transcribed_keys: list[tuple[float, float]] = []

    def transcribe_my_segments(
        self, wav_path, identified_segments, language=None,
        already_done=None, on_segment_done=None,
    ):
        already_done = already_done or set()
        lines = []
        for seg in identified_segments:
            if not seg.is_me:
                continue
            key = (seg.start, seg.end)
            if key in already_done:
                continue
            self.transcribed_keys.append(key)
            line = TranscribedLine(start=seg.start, end=seg.end, text=f"line at {seg.start:.0f}s")
            lines.append(line)
            if on_segment_done is not None:
                on_segment_done(line)
        return lines


class FakeSoloTranscriber:
    """Stand-in for Transcriber in --no-diarization mode."""

    def __init__(self, lines: list[TranscribedLine]):
        self._lines = lines

    def transcribe_full_file(self, wav_path, language=None, already_done=None, on_segment_done=None):
        already_done = already_done or set()
        produced = []
        for line in self._lines:
            if (line.start, line.end) in already_done:
                continue
            produced.append(line)
            if on_segment_done is not None:
                on_segment_done(line)
        return produced


def _fake_extract_audio(input_path: Path, output_dir: Path) -> Path:
    """Drop-in for extract_audio: no ffmpeg, but still writes into the
    directory it was handed, so temp-directory lifetime stays observable."""
    output_dir.mkdir(parents=True, exist_ok=True)
    wav = output_dir / f"{input_path.stem}.wav"
    wav.write_bytes(b"fake wav bytes")
    return wav


def test_lines_are_sorted_when_a_lowered_threshold_adds_mid_file_segments(tmp_path, monkeypatch):
    """
    The regression this guards: cached lines and newly transcribed ones used to
    be concatenated, which is only chronological while the cache holds a
    PREFIX of the file. Lower --threshold on an already-processed recording and
    a segment from the middle becomes "mine" for the first time — it must land
    between its neighbours, not after everything else.
    """
    monkeypatch.setattr(pipeline, "extract_audio", _fake_extract_audio)

    input_file = tmp_path / "call.webm"
    input_file.write_bytes(b"fake recording bytes")
    cache_dir = tmp_path / ".cache"
    ref_fp = {"size": 1, "mtime": 1.0}
    params = {"whisper_model": "small", "language": "en", "batch_size": None}

    # SPEAKER_01 speaks in the MIDDLE, between two of my turns.
    segments = [
        Segment(start=0.0, end=2.0, speaker_label="SPEAKER_00"),
        Segment(start=2.0, end=4.0, speaker_label="SPEAKER_01"),
        Segment(start=4.0, end=6.0, speaker_label="SPEAKER_00"),
    ]
    diarizer = FakeDiarizer(segments, {"SPEAKER_00": 0.80, "SPEAKER_01": 0.60})

    def process(threshold: float) -> list[TranscribedLine]:
        return _process_single_file(
            file_path=input_file, tmp_dir=tmp_path / "tmp", cache_dir=cache_dir,
            use_cache=True, use_diarization=True, diarizer=diarizer,
            reference_embedding=object(), transcriber=FakeSegmentTranscriber(),
            language="en", threshold=threshold, remove_fillers=False,
            reference_fingerprint=ref_fp, transcription_params=params,
        )

    first = process(0.75)
    assert [line.start for line in first] == [0.0, 4.0]

    # Threshold now also admits SPEAKER_01 at 2.0-4.0, which is NOT cached yet.
    second = process(0.55)
    assert [line.start for line in second] == [0.0, 2.0, 4.0]


def test_solo_mode_lines_are_sorted(tmp_path, monkeypatch):
    """Same guarantee in --no-diarization mode, where the cached lines and the
    fresh ones come from two different whisper passes over the same file."""
    monkeypatch.setattr(pipeline, "extract_audio", _fake_extract_audio)

    input_file = tmp_path / "monologue.wav"
    input_file.write_bytes(b"fake recording bytes")
    params = {"whisper_model": "small", "language": "en", "batch_size": None}

    lines = [
        TranscribedLine(start=6.0, end=8.0, text="third"),
        TranscribedLine(start=0.0, end=2.0, text="first"),
        TranscribedLine(start=2.0, end=4.0, text="second"),
    ]

    result = _process_single_file(
        file_path=input_file, tmp_dir=tmp_path / "tmp", cache_dir=tmp_path / ".cache",
        use_cache=False, use_diarization=False, diarizer=None,
        reference_embedding=None, transcriber=FakeSoloTranscriber(lines),
        language="en", threshold=None, remove_fillers=False,
        transcription_params=params,
    )

    assert [line.text for line in result] == ["first", "second", "third"]


def _run_solo_pipeline(tmp_path, monkeypatch, transcriber, extract=_fake_extract_audio, **kwargs):
    monkeypatch.setattr(pipeline, "extract_audio", extract)
    monkeypatch.setattr(pipeline, "Transcriber", lambda **_: transcriber)
    return pipeline.run_pipeline(
        input_path=kwargs.pop("input_path"),
        reference_voice=None,
        output_dir=kwargs.pop("output_dir"),
        hf_token=None,
        use_diarization=False,
        use_cache=False,
        **kwargs,
    )


def test_empty_result_leaves_existing_documents_untouched(tmp_path, monkeypatch):
    """
    An empty transcript is indistinguishable from "you said nothing" once the
    analysis workflow has archived it — so a run that extracts no line at all
    must fail loudly instead of truncating the previous run's documents.
    """
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    clean = output_dir / "transcript_clean.txt"
    annotated = output_dir / "transcript_annotated.txt"
    clean.write_text("a good line from the previous session\n", encoding="utf-8")
    annotated.write_text("[00:00:00] a good line from the previous session\n", encoding="utf-8")

    input_file = tmp_path / "rec.wav"
    input_file.write_bytes(b"fake recording bytes")

    with pytest.raises(RuntimeError) as excinfo:
        _run_solo_pipeline(
            tmp_path, monkeypatch, FakeSoloTranscriber([]),
            input_path=input_file, output_dir=output_dir,
        )

    assert "left untouched" in str(excinfo.value)
    assert clean.read_text(encoding="utf-8") == "a good line from the previous session\n"
    assert annotated.read_text(encoding="utf-8") == "[00:00:00] a good line from the previous session\n"


def test_every_file_failing_names_each_error_and_writes_nothing(tmp_path, monkeypatch):
    output_dir = tmp_path / "output"
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    (recordings / "one.wav").write_bytes(b"fake")
    (recordings / "two.wav").write_bytes(b"fake")

    def exploding_extract(input_path: Path, output_dir: Path) -> Path:
        raise RuntimeError(f"ffmpeg could not read {input_path.name}")

    with pytest.raises(RuntimeError) as excinfo:
        _run_solo_pipeline(
            tmp_path, monkeypatch, FakeSoloTranscriber([]), extract=exploding_extract,
            input_path=recordings, output_dir=output_dir,
        )

    message = str(excinfo.value)
    assert "Every file failed" in message
    assert "one.wav" in message and "two.wav" in message
    assert not (output_dir / "transcript_clean.txt").exists()


def test_each_files_extracted_wav_is_freed_before_the_batch_ends(tmp_path, monkeypatch):
    """
    A decoded WAV is ~115 MB per hour of audio. Extracting every file in a
    batch into one shared directory that only gets cleaned up at the very end
    piles those up for no reason — and lets two inputs sharing a stem extract
    onto each other's path.
    """
    output_dir = tmp_path / "output"
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    (recordings / "one.wav").write_bytes(b"fake")
    (recordings / "two.wav").write_bytes(b"fake")

    handed_out_dirs: list[Path] = []

    def recording_extract(input_path: Path, output_dir: Path) -> Path:
        handed_out_dirs.append(output_dir)
        return _fake_extract_audio(input_path, output_dir)

    _run_solo_pipeline(
        tmp_path, monkeypatch,
        FakeSoloTranscriber([TranscribedLine(start=0.0, end=1.0, text="something")]),
        extract=recording_extract,
        input_path=recordings, output_dir=output_dir,
    )

    assert len(handed_out_dirs) == 2
    # Each file got its own directory, and none of them outlived the batch.
    assert len(set(handed_out_dirs)) == 2
    for directory in handed_out_dirs:
        assert not directory.exists()


def test_fluency_is_measured_and_logged_by_the_run_itself(tmp_path, monkeypatch):
    """The metric has to be produced by the run, not read off the finished
    transcript afterwards — that's the only way it stays comparable between
    sessions."""
    import csv

    output_dir = tmp_path / "output"
    history = tmp_path / "analysis" / "fluency_history.csv"

    input_file = tmp_path / "rec.wav"
    input_file.write_bytes(b"fake recording bytes")

    result = _run_solo_pipeline(
        tmp_path, monkeypatch,
        FakeSoloTranscriber([
            TranscribedLine(start=0.0, end=30.0, text="uh " + " ".join(["word"] * 29)),
            TranscribedLine(start=32.0, end=62.0, text=" ".join(["word"] * 30)),
        ]),
        input_path=input_file, output_dir=output_dir, fluency_log=history,
    )

    metrics = result["fluency"]
    assert metrics.total_words == 60
    assert metrics.words_per_minute == 60.0
    assert metrics.filler_count == 1
    assert metrics.median_pause_sec == 2.0

    assert (output_dir / "fluency.json").exists()
    row = next(iter(csv.DictReader(history.read_text(encoding="utf-8").splitlines())))
    assert row["mode"] == "solo"
    assert row["files"] == "1"
    assert row["fillers_per_100_words"] == "1.67"


def test_run_writes_lines_json_alongside_the_text_documents(tmp_path, monkeypatch):
    import json

    output_dir = tmp_path / "output"
    input_file = tmp_path / "rec.wav"
    input_file.write_bytes(b"fake recording bytes")

    result = _run_solo_pipeline(
        tmp_path, monkeypatch,
        FakeSoloTranscriber([
            TranscribedLine(start=0.0, end=2.0, text="a clear sentence", avg_logprob=-0.1),
            TranscribedLine(start=3.0, end=4.0, text="mumbled", avg_logprob=-0.9),
        ]),
        input_path=input_file, output_dir=output_dir, low_confidence_threshold=-0.5,
    )

    payload = json.loads(result["lines_json"].read_text(encoding="utf-8"))
    assert [line["low_confidence"] for line in payload["lines"]] == [False, True]
    assert payload["totals"]["reliable_words"] == 3
    assert payload["low_confidence_threshold"] == -0.5
    # The run's own threshold, not the default, is what got applied and recorded.
    assert payload["lines"][0]["source_file"] == "rec.wav"


def test_no_fluency_history_is_written_when_no_path_is_given(tmp_path, monkeypatch):
    # The analysis/ workspace doesn't exist for anyone using the extractor on
    # its own, and the run must not conjure one.
    output_dir = tmp_path / "output"
    input_file = tmp_path / "rec.wav"
    input_file.write_bytes(b"fake recording bytes")

    _run_solo_pipeline(
        tmp_path, monkeypatch,
        FakeSoloTranscriber([TranscribedLine(start=0.0, end=1.0, text="something")]),
        input_path=input_file, output_dir=output_dir,
    )

    assert not (tmp_path / "analysis").exists()
    assert (output_dir / "fluency.json").exists()


def test_collect_input_files_accepts_a_single_file(tmp_path):
    f = tmp_path / "one.webm"
    f.write_bytes(b"x")
    assert pipeline.collect_input_files(f) == [f]


def test_collect_input_files_sorts_and_filters_a_folder(tmp_path):
    for name in ["b.webm", "a.mp4", "c.wav", "notes.txt", "cover.jpg"]:
        (tmp_path / name).write_bytes(b"x")
    (tmp_path / "nested").mkdir()

    found = pipeline.collect_input_files(tmp_path)

    # Sorted, so batch order (and therefore the order of the final document)
    # doesn't depend on the filesystem's iteration order.
    assert [p.name for p in found] == ["a.mp4", "b.webm", "c.wav"]


def test_collect_input_files_is_case_insensitive_about_extensions(tmp_path):
    (tmp_path / "LOUD.WEBM").write_bytes(b"x")
    assert [p.name for p in pipeline.collect_input_files(tmp_path)] == ["LOUD.WEBM"]


def test_collect_input_files_rejects_an_empty_folder(tmp_path):
    (tmp_path / "readme.txt").write_bytes(b"x")
    with pytest.raises(FileNotFoundError, match="No supported audio/video files"):
        pipeline.collect_input_files(tmp_path)


def test_collect_input_files_rejects_a_missing_path(tmp_path):
    with pytest.raises(FileNotFoundError, match="Path not found"):
        pipeline.collect_input_files(tmp_path / "nope.webm")


class FakeDiarizationEngine:
    """Stands in for the pyannote-backed engine across a whole run_pipeline call."""

    def __init__(self, segments, similarity_by_speaker):
        self._inner = FakeDiarizer(segments, similarity_by_speaker)

    def compute_embedding(self, wav_path, start=None, end=None):
        return object()

    def diarize(self, wav_path):
        return self._inner.diarize(wav_path)

    def identify_my_segments(self, wav_path, segments, reference_embedding, threshold=None):
        return self._inner.identify_my_segments(wav_path, segments, reference_embedding, threshold)


def test_diarized_run_writes_only_my_lines_end_to_end(tmp_path, monkeypatch):
    """
    The diarization branch of run_pipeline had no end-to-end coverage at all —
    only its pieces did. This walks the whole path: reference embedding,
    diarization, identification, transcription, documents.
    """
    output_dir = tmp_path / "output"
    input_file = tmp_path / "call.webm"
    input_file.write_bytes(b"fake recording bytes")
    reference = tmp_path / "me.wav"
    reference.write_bytes(b"fake reference bytes")

    segments = [
        Segment(start=0.0, end=2.0, speaker_label="SPEAKER_00"),   # mine
        Segment(start=2.0, end=4.0, speaker_label="SPEAKER_01"),   # someone else
        Segment(start=4.0, end=6.0, speaker_label="SPEAKER_00"),   # mine
    ]
    engine = FakeDiarizationEngine(segments, {"SPEAKER_00": 0.90, "SPEAKER_01": 0.20})

    monkeypatch.setattr(pipeline, "extract_audio", _fake_extract_audio)
    monkeypatch.setattr(pipeline, "DiarizationEngine", lambda **_: engine)
    monkeypatch.setattr(pipeline, "Transcriber", lambda **_: FakeSegmentTranscriber())

    result = pipeline.run_pipeline(
        input_path=input_file,
        reference_voice=reference,
        output_dir=output_dir,
        hf_token="hf_fake",
        threshold=0.75,
        use_diarization=True,
        use_cache=False,
    )

    clean = (output_dir / "transcript_clean.txt").read_text(encoding="utf-8").splitlines()
    assert clean == ["line at 0s", "line at 4s"]  # the other speaker's turn is absent
    assert result["stats"]["total_lines"] == 2
    # Pause stats stay blank for diarized recordings, where a gap between my
    # lines is mostly the other person talking.
    assert result["fluency"].median_pause_sec is None


def test_no_lines_message_distinguishes_no_match_from_no_speech():
    files = [Path("a.webm")]

    diarized = _no_lines_message(files, [], use_diarization=True)
    assert "recognized as your voice" in diarized
    assert "--threshold" in diarized

    solo = _no_lines_message(files, [], use_diarization=False)
    assert "no speech was recognized" in solo
    assert "--threshold" not in solo


def test_no_lines_message_separates_partial_failures_from_total_ones():
    files = [Path("a.webm"), Path("b.webm")]
    one_failed = [{"file": "a.webm", "error": "boom"}]

    partial = _no_lines_message(files, one_failed, use_diarization=True)
    assert "1 of them failed" in partial
    assert "recognized as your voice" in partial  # the other file still needs explaining

    total = _no_lines_message(files, one_failed + [{"file": "b.webm", "error": "boom"}],
                              use_diarization=True)
    assert "Every file failed" in total
    assert "recognized as your voice" not in total  # nothing was successfully processed
