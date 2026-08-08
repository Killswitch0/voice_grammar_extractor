"""
Diarization cuts wherever the voice stops, mid-sentence pauses included, and
each fragment then goes to whisper alone. In this project's archived sessions
the low-confidence lines run 1-2 words while the confident ones run 6-13 —
the same fact from both ends. These cover the stitching that undoes it.
"""

from voxlib.diarization import (
    DEFAULT_MERGE_GAP_SEC,
    MAX_MERGED_DURATION_SEC,
    Segment,
    merge_adjacent_segments,
)


def _seg(start, end, speaker="SPEAKER_00"):
    return Segment(start=start, end=end, speaker_label=speaker)


def _spans(segments):
    return [(s.start, s.end, s.speaker_label) for s in segments]


def test_same_speaker_across_a_short_pause_becomes_one_segment():
    segments = [_seg(0.0, 2.0), _seg(2.5, 4.0)]

    merged = merge_adjacent_segments(segments, max_gap=0.8)

    assert _spans(merged) == [(0.0, 4.0, "SPEAKER_00")]


def test_a_long_pause_is_left_as_a_boundary():
    segments = [_seg(0.0, 2.0), _seg(5.0, 7.0)]

    merged = merge_adjacent_segments(segments, max_gap=0.8)

    assert _spans(merged) == [(0.0, 2.0, "SPEAKER_00"), (5.0, 7.0, "SPEAKER_00")]


def test_another_speaker_in_between_always_blocks_the_merge():
    """The whole point of diarization: A, B, A is three turns, however small
    the gaps. Merging across B would put someone else's words in your line."""
    segments = [
        _seg(0.0, 2.0, "SPEAKER_00"),
        _seg(2.1, 2.4, "SPEAKER_01"),
        _seg(2.5, 4.0, "SPEAKER_00"),
    ]

    merged = merge_adjacent_segments(segments, max_gap=0.8)

    assert _spans(merged) == [
        (0.0, 2.0, "SPEAKER_00"),
        (2.1, 2.4, "SPEAKER_01"),
        (2.5, 4.0, "SPEAKER_00"),
    ]


def test_a_run_of_fragments_collapses_into_one_line():
    # The pattern that produces "So, and I just..." as its own transcript line.
    segments = [_seg(i * 1.0, i * 1.0 + 0.7) for i in range(6)]

    merged = merge_adjacent_segments(segments, max_gap=0.8)

    assert _spans(merged) == [(0.0, 5.7, "SPEAKER_00")]


def test_merging_stops_at_the_whisper_window():
    """Past ~30s whisper chunks internally anyway, so a longer segment buys
    nothing — and a merged line shouldn't swallow a whole monologue."""
    segments = [_seg(i * 5.0, i * 5.0 + 4.9) for i in range(10)]  # ~50s of near-continuous speech

    merged = merge_adjacent_segments(segments, max_gap=0.8, max_duration=MAX_MERGED_DURATION_SEC)

    assert len(merged) > 1
    assert all(s.end - s.start <= MAX_MERGED_DURATION_SEC for s in merged)
    # No speech is lost or duplicated at the seams.
    assert merged[0].start == 0.0
    assert merged[-1].end == 49.9


def test_overlapping_segments_merge_without_shrinking():
    # A fully contained segment must not pull the merged end backwards.
    segments = [_seg(0.0, 10.0), _seg(2.0, 4.0)]

    merged = merge_adjacent_segments(segments, max_gap=0.8)

    assert _spans(merged) == [(0.0, 10.0, "SPEAKER_00")]


def test_zero_gap_disables_merging_entirely():
    segments = [_seg(0.0, 2.0), _seg(2.1, 4.0)]

    assert _spans(merge_adjacent_segments(segments, max_gap=0.0)) == _spans(segments)


def test_unsorted_input_is_ordered_before_merging():
    segments = [_seg(2.5, 4.0), _seg(0.0, 2.0)]

    merged = merge_adjacent_segments(segments, max_gap=0.8)

    assert _spans(merged) == [(0.0, 4.0, "SPEAKER_00")]


def test_the_input_list_is_not_mutated():
    """Callers keep the raw segments to re-merge with a different gap later —
    the cache depends on them surviving untouched."""
    segments = [_seg(0.0, 2.0), _seg(2.5, 4.0)]

    merge_adjacent_segments(segments, max_gap=0.8)

    assert _spans(segments) == [(0.0, 2.0, "SPEAKER_00"), (2.5, 4.0, "SPEAKER_00")]


def test_empty_and_single_segment_inputs():
    assert merge_adjacent_segments([], max_gap=0.8) == []
    assert _spans(merge_adjacent_segments([_seg(0.0, 1.0)], max_gap=0.8)) == [(0.0, 1.0, "SPEAKER_00")]


def test_default_gap_is_short_enough_to_keep_real_turns_apart():
    """A sanity bound on the default: it should join a breath, not a silence
    long enough that the other person could have replied."""
    assert 0.3 <= DEFAULT_MERGE_GAP_SEC <= 1.5
