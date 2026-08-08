from pathlib import Path

from voxlib.diarization import DiarizationEngine, IdentifiedSegment, Segment
from voxlib.pipeline import _diarize_and_identify, _filter_cached_transcription


class FakeDiarizer:
    """Duck-typed stand-in for DiarizationEngine — no torch/pyannote needed."""

    def __init__(self, segments, similarity_by_speaker):
        self._segments = segments
        self._similarity_by_speaker = similarity_by_speaker
        self.diarize_calls = 0
        self.identify_calls = 0

    def diarize(self, wav_path):
        self.diarize_calls += 1
        return self._segments

    def identify_my_segments(self, wav_path, segments, reference_embedding, threshold):
        self.identify_calls += 1
        # DiarizationEngine.resolve_threshold is a plain static method (no
        # torch/pyannote dependency), so the fake can delegate to it for real
        # to mirror actual auto-calibration behavior when threshold=None.
        effective_threshold = DiarizationEngine.resolve_threshold(self._similarity_by_speaker, threshold)
        result = []
        for seg in segments:
            sim = self._similarity_by_speaker[seg.speaker_label]
            result.append(IdentifiedSegment(start=seg.start, end=seg.end, is_me=sim >= effective_threshold, similarity=sim))
        # Mirrors the real signature: the threshold comes back out, because
        # under auto-calibration only this call knows what it ended up being.
        return result, effective_threshold


def _make_input_and_wav(tmp_path: Path):
    input_file = tmp_path / "call.webm"
    input_file.write_bytes(b"fake recording bytes")
    wav_path = tmp_path / "call.wav"
    wav_path.write_bytes(b"fake wav bytes")
    return input_file, wav_path


def test_threshold_change_updates_is_me_without_recomputing_identification(tmp_path):
    input_file, wav_path = _make_input_and_wav(tmp_path)
    cache_dir = tmp_path / ".cache"
    ref_fp = {"size": 1, "mtime": 1.0}

    segments = [Segment(start=0.0, end=1.0, speaker_label="SPEAKER_00")]
    diarizer = FakeDiarizer(segments, {"SPEAKER_00": 0.70})

    _, identified, _, _ = _diarize_and_identify(
        input_file, wav_path, cache_dir, True, diarizer, object(), threshold=0.75,
        reference_fingerprint=ref_fp,
    )
    assert identified[0].is_me is False
    assert diarizer.identify_calls == 1

    # Lower threshold on the SAME file/reference -> is_me flips to True,
    # without calling identify_my_segments again (similarity is reused from cache).
    _, identified2, _, _ = _diarize_and_identify(
        input_file, wav_path, cache_dir, True, diarizer, object(), threshold=0.6,
        reference_fingerprint=ref_fp,
    )
    assert identified2[0].is_me is True
    assert diarizer.identify_calls == 1


def test_cache_hit_auto_calibrates_when_threshold_not_given(tmp_path):
    input_file, wav_path = _make_input_and_wav(tmp_path)
    cache_dir = tmp_path / ".cache"
    ref_fp = {"size": 1, "mtime": 1.0}

    segments = [
        Segment(start=0.0, end=1.0, speaker_label="SPEAKER_00"),
        Segment(start=1.0, end=2.0, speaker_label="SPEAKER_01"),
    ]
    similarity = {"SPEAKER_00": 0.7275804281234741, "SPEAKER_01": 0.09839118272066116}
    diarizer = FakeDiarizer(segments, similarity)

    # First run (cache miss) with an explicit threshold to populate the cache.
    _, identified, _, _ = _diarize_and_identify(
        input_file, wav_path, cache_dir, True, diarizer, object(), threshold=0.75,
        reference_fingerprint=ref_fp,
    )
    assert identified[0].is_me is False  # 0.7275 < 0.75, matches the real-world bug report
    assert diarizer.identify_calls == 1

    # Re-run with no --threshold at all (None) -> served from cache, but the
    # cache-hit branch must reconstruct per-speaker similarity and auto-calibrate,
    # rather than blindly comparing against a raw threshold=None.
    _, identified2, _, _ = _diarize_and_identify(
        input_file, wav_path, cache_dir, True, diarizer, object(), threshold=None,
        reference_fingerprint=ref_fp,
    )
    assert identified2[0].is_me is True  # auto-calibrated threshold (~0.41) now catches it
    assert identified2[1].is_me is False
    assert diarizer.identify_calls == 1  # still served from cache, no recomputation


def test_reference_change_forces_reidentification(tmp_path):
    input_file, wav_path = _make_input_and_wav(tmp_path)
    cache_dir = tmp_path / ".cache"

    segments = [Segment(start=0.0, end=1.0, speaker_label="SPEAKER_00")]
    diarizer = FakeDiarizer(segments, {"SPEAKER_00": 0.70})

    _diarize_and_identify(
        input_file, wav_path, cache_dir, True, diarizer, object(), threshold=0.5,
        reference_fingerprint={"size": 1, "mtime": 1.0},
    )
    assert diarizer.identify_calls == 1

    # A different reference voice sample -> similarity must be recomputed,
    # not blindly reused from comparisons against the old reference.
    _diarize_and_identify(
        input_file, wav_path, cache_dir, True, diarizer, object(), threshold=0.5,
        reference_fingerprint={"size": 2, "mtime": 2.0},
    )
    assert diarizer.identify_calls == 2


def test_diarization_is_not_recomputed_when_only_reference_changes(tmp_path):
    # Diarization (speaker segmentation) doesn't depend on the reference
    # voice at all, so it should survive a reference change untouched.
    input_file, wav_path = _make_input_and_wav(tmp_path)
    cache_dir = tmp_path / ".cache"

    segments = [Segment(start=0.0, end=1.0, speaker_label="SPEAKER_00")]
    diarizer = FakeDiarizer(segments, {"SPEAKER_00": 0.70})

    _diarize_and_identify(
        input_file, wav_path, cache_dir, True, diarizer, object(), threshold=0.5,
        reference_fingerprint={"size": 1, "mtime": 1.0},
    )
    _diarize_and_identify(
        input_file, wav_path, cache_dir, True, diarizer, object(), threshold=0.5,
        reference_fingerprint={"size": 2, "mtime": 2.0},
    )
    assert diarizer.diarize_calls == 1


def test_filter_cached_transcription_drops_lines_for_segments_no_longer_mine():
    identified = [
        IdentifiedSegment(start=0.0, end=1.0, is_me=True, similarity=0.9),   # still mine
        IdentifiedSegment(start=1.0, end=2.0, is_me=False, similarity=0.3),  # no longer mine
    ]
    cached = [
        {"start": 0.0, "end": 1.0, "text": "keep me"},
        {"start": 1.0, "end": 2.0, "text": "drop me - not mine anymore"},
    ]

    result = _filter_cached_transcription(cached, identified)

    assert result == [{"start": 0.0, "end": 1.0, "text": "keep me"}]


def test_filter_cached_transcription_keeps_nothing_for_empty_identified():
    cached = [{"start": 0.0, "end": 1.0, "text": "orphaned"}]
    assert _filter_cached_transcription(cached, []) == []


def test_no_cache_does_not_write_to_disk(tmp_path):
    # --no-cache is documented as "ignoring saved progress" — it must not
    # write to the cache either, not just skip reading from it.
    input_file, wav_path = _make_input_and_wav(tmp_path)
    cache_dir = tmp_path / ".cache"

    segments = [Segment(start=0.0, end=1.0, speaker_label="SPEAKER_00")]
    diarizer = FakeDiarizer(segments, {"SPEAKER_00": 0.9})

    _diarize_and_identify(
        input_file, wav_path, cache_dir, False, diarizer, object(), threshold=0.5,
    )

    assert not cache_dir.exists()
