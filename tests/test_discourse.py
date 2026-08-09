from voxlib import discourse


def test_counts_the_marker_this_project_actually_has_a_problem_with():
    """
    Reduced from 2026-08-08, where "you know" ran to 101 occurrences against a
    measured filler rate of 0.10 per 100 words. The whole point of the module is
    that this number stops being counted by hand.
    """
    text = "so you know I think you know it's fine, y'know"

    assert discourse.count_markers(text) == {"you know": 3}
    assert discourse.count_all(text) == 3


def test_like_and_so_are_deliberately_not_counted():
    """
    Both are genuinely ambiguous, and a metric whose definition can't be pinned
    down can't be compared against itself months later. They're excluded on
    purpose, so pin it: a change here would silently redefine the series.
    """
    text = "I like it, so it was like really good, so yeah"

    assert discourse.count_all(text) == 0
    assert discourse.DELIBERATELY_NOT_COUNTED == ("like", "so")


def test_markers_are_matched_case_insensitively_and_on_word_boundaries():
    assert discourse.count_all("You Know, BASICALLY") == 2
    # Not a marker: substrings of longer words must not fire.
    assert discourse.count_all("unknowable actualization sortie") == 0


def test_multiword_markers_survive_whitespace_whisper_introduces():
    assert discourse.count_all("you\n  know what I    mean") == 2


def test_breakdown_omits_zeros_and_keeps_a_stable_order():
    """Two sessions' breakdowns get read side by side; ordering by declaration
    rather than by first appearance is what makes that possible."""
    per_line = [
        {"basically": 1},
        {"you know": 2},
        {"i mean": 1, "you know": 1},
    ]

    merged = discourse.merge_counts(per_line)

    assert merged == {"you know": 3, "i mean": 1, "basically": 1}
    assert list(merged) == ["you know", "i mean", "basically"]


def test_contractions_and_variants_count_as_the_same_marker():
    assert discourse.count_markers("kinda, kind of, sorta") == {"kind of": 2, "sort of": 1}
