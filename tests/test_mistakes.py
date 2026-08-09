import csv
from pathlib import Path

import pytest

from voxlib import mistakes
from voxlib.mistakes import MistakeCount


def _record(path: Path, date: str, reliable_words: int, counts, source: str = "report") -> None:
    mistakes.record_session(
        path, date=date, reliable_words=reliable_words,
        counts=[MistakeCount(*c) if isinstance(c, tuple) else c for c in counts],
        source=source,
    )


def test_rates_are_normalized_so_sessions_of_different_length_compare(tmp_path: Path):
    """
    The reason raw counts couldn't be trended: the four sessions on record run
    from 1,844 to 2,547 reliable words, so "5 last time, 13 this time" mixes a
    change in the speaker with a change in how much they said. Here, the same
    error density in two differently-sized sessions reads as the same number.
    """
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-03", 2000, [("Article Errors", 3, 10)])
    _record(path, "2026-08-04", 1000, [("Article Errors", 3, 5)])

    rows = mistakes.load(path)

    assert [r.rate_per_1000 for r in rows] == [5.0, 5.0]


def test_untested_is_recorded_as_blank_and_never_as_zero(tmp_path: Path):
    """
    2026-08-08 produced zero if-clauses, so "conditional will" wasn't clean that
    session — it was untried. Writing 0 there would have counted toward the
    three-session absence streak and promoted a mistake nobody had tested.
    """
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-08", 1956, [("Conditional will In If-Clauses", 4, None)])

    row = next(iter(csv.DictReader(path.read_text(encoding="utf-8").splitlines())))
    assert row["occurrences"] == ""

    loaded = mistakes.load(path)[0]
    assert loaded.occurrences is None
    assert loaded.rate_per_1000 is None


def test_absence_streak_counts_explicit_zeros_only(tmp_path: Path):
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-03", 2000, [("Third-Person -s", 3, 2)])
    _record(path, "2026-08-04", 2000, [("Third-Person -s", 3, 0)])
    _record(path, "2026-08-06", 2000, [("Third-Person -s", 3, 0)])

    trend = mistakes.summarize(mistakes.load(path))[0]
    assert trend.absence_streak == 2
    assert not trend.ready_for_improvements

    _record(path, "2026-08-08", 2000, [("Third-Person -s", 3, 0)])

    trend = mistakes.summarize(mistakes.load(path))[0]
    assert trend.absence_streak == 3
    assert trend.ready_for_improvements


def test_an_untested_session_neither_extends_nor_breaks_the_streak(tmp_path: Path):
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-03", 2000, [("Propose Complementation", 3, 2)])
    _record(path, "2026-08-04", 2000, [("Propose Complementation", 3, 0)])
    _record(path, "2026-08-06", 2000, [("Propose Complementation", 3, None)])
    _record(path, "2026-08-08", 2000, [("Propose Complementation", 3, 0)])

    trend = mistakes.summarize(mistakes.load(path))[0]

    assert trend.absence_streak == 2      # not 3 — the untested session doesn't count
    assert trend.untested_since == 1
    assert not trend.ready_for_improvements


def test_sessions_before_a_category_existed_are_not_absences(tmp_path: Path):
    """A category first tracked on the third session hasn't been "absent" from
    the first two — nobody was looking for it yet."""
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-03", 2000, [("Article Errors", 3, 5)])
    _record(path, "2026-08-04", 2000, [("Article Errors", 3, 6)])
    _record(path, "2026-08-06", 2000, [
        ("Article Errors", 3, 6), ("Adverb Placement", 2, 0),
    ])

    by_name = {t.category: t for t in mistakes.summarize(mistakes.load(path))}

    assert by_name["Adverb Placement"].absence_streak == 1
    assert by_name["Adverb Placement"].first_seen == "2026-08-06"


def test_a_category_missing_from_a_later_session_counts_as_absent(tmp_path: Path):
    """Forgetting to list a clean category is the common case; treating the
    omission as absence keeps the streak honest without demanding perfect
    bookkeeping."""
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-03", 2000, [("Noun-as-Adjective", 3, 3)])
    _record(path, "2026-08-04", 2000, [("Article Errors", 3, 6)])
    _record(path, "2026-08-06", 2000, [("Article Errors", 3, 6)])

    by_name = {t.category: t for t in mistakes.summarize(mistakes.load(path))}

    assert by_name["Noun-as-Adjective"].absence_streak == 2


def test_impact_lets_a_severe_rare_mistake_outrank_a_mild_frequent_one(tmp_path: Path):
    """
    Rule 15, made arithmetic: a missing article is frequent and survivable, a
    broken verb form is rarer and actually costs the listener. Ranking by count
    alone would always put articles first.
    """
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-08", 1000, [
        ("Article Errors", 1, 10),        # impact 1 x 10.0 = 10
        ("Verb Agreement", 5, 4),         # impact 5 x  4.0 = 20
    ])

    ranked = [t.category for t in mistakes.summarize(mistakes.load(path))]

    assert ranked == ["Verb Agreement", "Article Errors"]


def test_recent_sessions_weigh_more_than_older_ones(tmp_path: Path):
    """A mistake that is fading shouldn't keep outranking one that's getting
    worse just because it used to be common."""
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-03", 1000, [("Fading", 3, 10), ("Growing", 3, 1)])
    _record(path, "2026-08-04", 1000, [("Fading", 3, 5), ("Growing", 3, 5)])
    _record(path, "2026-08-06", 1000, [("Fading", 3, 1), ("Growing", 3, 10)])

    by_name = {t.category: t for t in mistakes.summarize(mistakes.load(path))}

    assert by_name["Fading"].direction == "improving"
    assert by_name["Growing"].direction == "worsening"
    assert by_name["Growing"].impact > by_name["Fading"].impact
    # The two are mirror images: unweighted they're identical, and the ranking
    # would come down to alphabetical order.
    assert by_name["Fading"].total_occurrences == by_name["Growing"].total_occurrences == 16


def test_recording_the_same_session_twice_is_refused(tmp_path: Path):
    """The counters in memory.md were inflatable exactly this way, which is why
    the pipeline grew processed.json. Same failure, same answer."""
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-08", 2000, [("Article Errors", 3, 5)])

    with pytest.raises(ValueError, match="already has rows for 2026-08-08"):
        _record(path, "2026-08-08", 2000, [("Article Errors", 3, 5)])

    assert len(mistakes.load(path)) == 1


def test_a_category_listed_twice_in_one_session_is_refused(tmp_path: Path):
    path = tmp_path / "mistakes.csv"

    with pytest.raises(ValueError, match="listed twice"):
        _record(path, "2026-08-08", 2000, [
            ("Article Errors", 3, 5), ("Article Errors", 3, 2),
        ])


def test_the_cli_adds_a_session_and_prints_the_table(tmp_path: Path, capsys):
    path = tmp_path / "mistakes.csv"

    exit_code = mistakes.main([
        "--path", str(path), "add", "--date", "2026-08-09", "--reliable-words", "2000",
        "Article Errors:3:6", "Conditional will:4:",
    ])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "Article Errors" in out
    # The untested category still gets a row, with no rate to show.
    assert [r.occurrences for r in mistakes.load(path)] == [6, None]


def test_the_table_flags_what_is_ready_to_move_to_improvements(tmp_path: Path):
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-03", 2000, [("Solved Thing", 3, 4)])
    for date in ("2026-08-04", "2026-08-06", "2026-08-08"):
        _record(path, date, 2000, [("Solved Thing", 3, 0)])

    table = mistakes.format_table(mistakes.summarize(mistakes.load(path)))

    assert "move to Improvements" in table
    assert "Solved Thing" in table


def test_empty_history_says_so_instead_of_crashing(tmp_path: Path):
    assert mistakes.load(tmp_path / "nothing.csv") == []
    assert "No mistakes recorded yet" in mistakes.format_table([])
