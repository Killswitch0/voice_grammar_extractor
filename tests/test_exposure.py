"""
Checks on the normalization diagnostic.

Every number this project tracks is a rate per 1,000 reliable words, and that is
only the right move if what is being counted rises with words. This module asks
whether it does. It is a diagnostic, so the thing to guard is that it reaches
the right verdict on data where the answer is known, and refuses to reach one
where it cannot be known.
"""

from __future__ import annotations

from pathlib import Path

from voxlib import exposure, mistakes
from voxlib.mistakes import MistakeCount


def _history(path: Path, sessions: list[tuple]) -> None:
    for date, words, count in sessions:
        mistakes.record_session(path, date=date, reliable_words=words,
                                counts=[MistakeCount("A mistake", 3, count)])


def test_it_says_nothing_from_too_few_sessions(tmp_path: Path):
    """The whole point is to be conservative about weak evidence; it cannot then
    reach a verdict from four points."""
    path = tmp_path / "mistakes.csv"
    _history(path, [("2026-08-0%d" % d, 2000, 5) for d in range(1, 4)])

    assert exposure.analyse(mistakes.load(path)) is None
    assert "nothing to test" in exposure.format_report(None)


def test_counts_that_scale_with_words_are_recognised(tmp_path: Path):
    """
    The case where the per-1,000 rate is doing exactly what it claims: twice the
    words, twice the errors, a flat rate. The diagnostic should say the
    normalization is earning its place.
    """
    path = tmp_path / "mistakes.csv"
    # A constant 4 per 1,000 words, over a wide spread of session lengths.
    _history(path, [(f"2026-08-{d:02d}", words, round(words * 4 / 1000))
                    for d, words in enumerate([1000, 1600, 2200, 2800, 3400, 4000], start=1)])

    report = exposure.analyse(mistakes.load(path))

    assert report.supports_per_word is True
    assert report.length_effect is False
    assert "doing its job" in report.verdict


def test_a_count_that_ignores_words_is_reported_as_a_length_effect(tmp_path: Path):
    """
    The case this was written for. The same number of errors is found however
    much was said, so dividing by words turns session length into the signal and
    the shortest session into the worst one.
    """
    path = tmp_path / "mistakes.csv"
    # Counts that vary, but not with length: a constant count would have no
    # spread at all and no correlation could be computed from it either way.
    _history(path, [(f"2026-08-{d:02d}", words, count) for d, (words, count) in enumerate(
        zip([1000, 1600, 2200, 2800, 3400, 4000], [9, 6, 10, 5, 9, 6]), start=1)])

    report = exposure.analyse(mistakes.load(path))

    assert report.supports_per_word is False
    assert report.length_effect is True
    assert "not removing it" in report.verdict
    assert report.rate_vs_words < 0


def test_a_narrow_spread_of_session_lengths_is_flagged(tmp_path: Path):
    """
    A null result over sessions that are all much the same length says very
    little, and reporting it without that caveat would retire a good metric on
    no evidence.
    """
    path = tmp_path / "mistakes.csv"
    _history(path, [(f"2026-08-{d:02d}", words, count) for d, (words, count) in enumerate(
        zip([2000, 2050, 2100, 2150, 2200, 2250], [9, 6, 10, 5, 9, 6]), start=1)])

    report = exposure.analyse(mistakes.load(path))

    assert report.spread < 2
    assert "narrow enough to hide" in exposure.format_report(report)


def test_a_correlation_needs_enough_pairs_to_mean_anything():
    assert exposure.correlation([1, 2], [1, 2]) is None
    assert exposure.correlation([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == 1.0
    assert exposure.correlation([1, 1, 1, 1, 1], [1, 2, 3, 4, 5]) is None   # no spread
