from pathlib import Path

import numpy as np
import pytest

from voxlib.diarization import DiarizationEngine, Segment


def _make_engine(embeddings_by_segment: dict, raise_for: frozenset = frozenset()) -> DiarizationEngine:
    """
    Bare DiarizationEngine — __init__ needs torch/pyannote, so it's skipped
    entirely via __new__. compute_embedding is faked from a (start, end)
    lookup table, which is enough to exercise identify_my_segments' own logic
    (grouping, top-5-longest averaging, threshold application, error
    fallback) without any ML dependency.
    """
    engine = DiarizationEngine.__new__(DiarizationEngine)

    def fake_compute_embedding(wav_path, start=None, end=None):
        key = (start, end)
        if key in raise_for:
            raise RuntimeError(f"boom for segment {key}")
        return embeddings_by_segment[key]

    engine.compute_embedding = fake_compute_embedding
    return engine


REFERENCE = np.array([1.0, 0.0, 0.0])
MATCH = np.array([1.0, 0.0, 0.0])       # same direction as reference -> similarity 1.0
NO_MATCH = np.array([0.0, 1.0, 0.0])    # orthogonal to reference -> similarity 0.0


def test_cosine_similarity_identical_orthogonal_opposite():
    assert DiarizationEngine.cosine_similarity(REFERENCE, MATCH) == pytest.approx(1.0)
    assert DiarizationEngine.cosine_similarity(REFERENCE, NO_MATCH) == pytest.approx(0.0)
    assert DiarizationEngine.cosine_similarity(REFERENCE, -REFERENCE) == pytest.approx(-1.0)


def test_identify_my_segments_matches_and_rejects_by_threshold():
    segments = [
        Segment(start=0.0, end=2.0, speaker_label="SPEAKER_00"),
        Segment(start=2.0, end=4.0, speaker_label="SPEAKER_01"),
    ]
    embeddings = {
        (0.0, 2.0): MATCH,
        (2.0, 4.0): NO_MATCH,
    }
    engine = _make_engine(embeddings)

    result, _ = engine.identify_my_segments(Path("fake.wav"), segments, REFERENCE, threshold=0.5)

    by_start = {s.start: s for s in result}
    assert by_start[0.0].is_me is True
    assert by_start[0.0].similarity == pytest.approx(1.0)
    assert by_start[2.0].is_me is False
    assert by_start[2.0].similarity == pytest.approx(0.0)


def test_identify_my_segments_excludes_speakers_with_only_short_segments():
    # SPEAKER_01's only segment is below the default min_segment_duration
    # (0.3s) -> it never enters the per-speaker centroid computation at all,
    # so it falls back to similarity -1.0 (never "mine"), regardless of what
    # its (untested here) actual voice embedding would have said.
    segments = [
        Segment(start=0.0, end=2.0, speaker_label="SPEAKER_00"),
        Segment(start=2.0, end=2.1, speaker_label="SPEAKER_01"),  # 0.1s < 0.3s
    ]
    embeddings = {(0.0, 2.0): MATCH}
    engine = _make_engine(embeddings)

    result, _ = engine.identify_my_segments(Path("fake.wav"), segments, REFERENCE, threshold=0.5)

    by_start = {s.start: s for s in result}
    assert by_start[2.0].similarity == -1.0
    assert by_start[2.0].is_me is False


def test_identify_my_segments_averages_only_5_longest_segments_per_speaker():
    # 5 long (2.0s) matching segments + 1 shorter (0.5s, still above the
    # 0.3s floor) mismatching segment for the SAME speaker. The code only
    # averages the 5 LONGEST segments per speaker, so the shorter
    # mismatching one must be excluded from the centroid entirely.
    long_matches = [
        Segment(start=float(i), end=float(i) + 2.0, speaker_label="SPEAKER_00")
        for i in range(5)
    ]
    short_mismatch = Segment(start=100.0, end=100.5, speaker_label="SPEAKER_00")
    segments = long_matches + [short_mismatch]

    embeddings = {(s.start, s.end): MATCH for s in long_matches}
    embeddings[(short_mismatch.start, short_mismatch.end)] = NO_MATCH
    engine = _make_engine(embeddings)

    result, _ = engine.identify_my_segments(Path("fake.wav"), segments, REFERENCE, threshold=0.5)

    # Every segment for this speaker shares the same speaker-level
    # similarity, which should stay ~1.0 since the mismatching (shortest)
    # segment never made it into the top-5-longest average.
    assert all(s.similarity == pytest.approx(1.0) for s in result)


def test_identify_my_segments_falls_back_when_all_embeddings_fail():
    segments = [Segment(start=0.0, end=2.0, speaker_label="SPEAKER_00")]
    engine = _make_engine({}, raise_for=frozenset({(0.0, 2.0)}))

    result, _ = engine.identify_my_segments(Path("fake.wav"), segments, REFERENCE, threshold=0.5)

    assert result[0].similarity == -1.0
    assert result[0].is_me is False
