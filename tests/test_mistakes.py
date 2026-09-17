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
        ("Article Errors", 1, 10),        # impact 1 x sqrt(10.0) = 3.16
        ("Verb Agreement", 5, 4),         # impact 5 x sqrt( 4.0) = 10.0
    ])

    ranked = [t.category for t in mistakes.summarize(mistakes.load(path))]

    assert ranked == ["Verb Agreement", "Article Errors"]


def test_severity_still_decides_when_the_frequency_gap_is_the_real_one(tmp_path: Path):
    """
    The failure the square root exists to fix, in the shape it actually took.
    These are the real 2026-08-09 numbers: severity spans a factor of two across
    every tracked category while the rate spans a factor of thirty, so under a
    raw severity x rate product the rate decides everything and severity is
    decorative. Conditional "will" carried the highest severity on record and
    ranked twelfth of fourteen.

    Damped, a three-point severity gap survives a seven-fold frequency gap. The
    frequent one is still ranked first here — it should be, it is seven times as
    common — but by a margin that leaves room for the rest of the table.
    """
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-09", 1000, [
        ("Article Errors", 2, 7),         # frequent, understood every time
        ("Conditional will", 5, 1),       # rare, changes what the listener hears
    ])

    by_name = {t.category: t for t in mistakes.summarize(mistakes.load(path))}

    assert by_name["Conditional will"].impact > by_name["Article Errors"].impact / 2
    # Under the old raw product this was 14.0 against 5.0 — a 2.8x gap on a pair
    # the owner should be splitting attention between.
    assert by_name["Article Errors"].impact / by_name["Conditional will"].impact < 1.5


def test_categories_split_into_a_clarity_tier_and_a_polish_tier(tmp_path: Path):
    """Rule 17 builds the action plan out of both buckets, so the bucket has to
    be readable off the trend rather than re-derived from severity by eye."""
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-09", 1000, [
        ("Verb Complementation", 4, 1),
        ("Third-Person -s", 3, 1),
        ("Article Errors", 2, 7),
        ("Redundant Subject Pronoun", 1, 2),
    ])

    tiers = {t.category: t.tier for t in mistakes.summarize(mistakes.load(path))}

    assert tiers == {
        "Verb Complementation": "clarity",
        "Third-Person -s": "clarity",
        "Article Errors": "polish",
        "Redundant Subject Pronoun": "polish",
    }


def test_a_priority_that_has_been_drilled_for_three_sessions_without_moving_is_flagged(
    tmp_path: Path,
):
    """
    Articles were goal #1 five sessions running while the rate climbed 2.32 ->
    6.77, and nothing in the numbers ever said so. The ranking has no memory of
    having been acted on; this flag is that memory.
    """
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-06", 1000, [("Article Errors", 2, 2)])
    _record(path, "2026-08-08", 1000, [("Article Errors", 2, 7)])
    _record(path, "2026-08-09", 1000, [("Article Errors", 2, 7)])

    assert mistakes.summarize(mistakes.load(path))[0].stalled


def test_a_quarter_drop_over_the_window_counts_as_movement(tmp_path: Path):
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-06", 1000, [("Article Errors", 2, 8)])
    _record(path, "2026-08-08", 1000, [("Article Errors", 2, 7)])
    _record(path, "2026-08-09", 1000, [("Article Errors", 2, 5)])

    assert not mistakes.summarize(mistakes.load(path))[0].stalled


def test_a_mistake_returning_after_clean_sessions_is_a_regression_not_a_stall(tmp_path: Path):
    """
    Third-person "-s" went clean, clean, then four instances. That needs the
    regression handling in step 3, not "the drill isn't working" — it had no
    drill to fail. Conflating the two flagged six of fourteen categories, which
    is the same as flagging none.
    """
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-06", 1000, [("Third-Person -s", 3, 0)])
    _record(path, "2026-08-08", 1000, [("Third-Person -s", 3, 0)])
    _record(path, "2026-08-09", 1000, [("Third-Person -s", 3, 4)])

    trend = mistakes.summarize(mistakes.load(path))[0]
    assert not trend.stalled
    assert trend.direction == "worsening"


def test_two_sessions_are_not_enough_to_call_something_stalled(tmp_path: Path):
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-08", 1000, [("Article Errors", 2, 7)])
    _record(path, "2026-08-09", 1000, [("Article Errors", 2, 7)])

    assert not mistakes.summarize(mistakes.load(path))[0].stalled


def test_an_untested_session_does_not_make_a_category_look_stalled(tmp_path: Path):
    """A session where the structure never came up says nothing about whether
    the drill is working, so it mustn't sit inside the stall window."""
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-04", 1000, [("Conditional will", 4, 4)])
    _record(path, "2026-08-06", 1000, [("Conditional will", 4, None)])
    _record(path, "2026-08-08", 1000, [("Conditional will", 4, None)])
    _record(path, "2026-08-09", 1000, [("Conditional will", 4, 1)])

    trend = mistakes.summarize(mistakes.load(path))[0]
    assert trend.sessions_measured == 2
    assert not trend.stalled          # only two measured sessions, not three


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


def test_the_table_shows_the_tier_and_names_what_has_stopped_moving(tmp_path: Path):
    path = tmp_path / "mistakes.csv"
    for date, count in (("2026-08-06", 2), ("2026-08-08", 7), ("2026-08-09", 7)):
        _record(path, date, 1000, [("Article Errors", 2, count), ("Verb Agreement", 4, 1)])

    table = mistakes.format_table(mistakes.summarize(mistakes.load(path)))

    assert "clarity" in table and "polish" in table
    assert "change the drill" in table
    assert "Article Errors" in table.split("change the drill")[1]


def test_empty_history_says_so_instead_of_crashing(tmp_path: Path):
    assert mistakes.load(tmp_path / "nothing.csv") == []
    assert "No mistakes recorded yet" in mistakes.format_table([])


def test_a_ranking_built_on_a_handful_of_instances_is_marked_as_such(tmp_path: Path):
    """
    Impact is severity x sqrt(rate), and severity is a judgment — so a serious
    category seen three times in one session can outrank one observed steadily
    for months. That is not wrong, but it must not look like the same kind of
    number, because the workflow acts on the ranking.
    """
    path = tmp_path / "mistakes.csv"
    _record(path, "2026-08-01", 2000, [("Rare but serious", 5, 3), ("Common", 2, 20)])
    _record(path, "2026-08-02", 2000, [("Rare but serious", 5, 0), ("Common", 2, 18)])

    by_name = {t.category: t for t in mistakes.summarize(mistakes.load(path))}

    assert by_name["Rare but serious"].evidence == 3
    assert by_name["Rare but serious"].thin is True
    assert by_name["Common"].evidence == 38
    assert by_name["Common"].thin is False


def test_a_stall_is_not_claimed_where_an_improvement_could_not_have_shown(tmp_path: Path):
    """
    The flag says "this has been drilled and the drill isn't working, change the
    approach". On one or two instances a session, an improvement of the size the
    window looks for could not have been seen — so the flag would be asking the
    owner to abandon something that may well be working.
    """
    path = tmp_path / "mistakes.csv"
    for date, count in [("2026-08-01", 1), ("2026-08-02", 1), ("2026-08-03", 1)]:
        _record(path, date, 2000, [("Barely seen", 3, count)])
    by_name = {t.category: t for t in mistakes.summarize(mistakes.load(path))}
    assert by_name["Barely seen"].stalled is False

    # The same shape, with enough instances for the claim to mean something.
    busy = tmp_path / "busy.csv"
    for date in ("2026-08-01", "2026-08-02", "2026-08-03"):
        _record(busy, date, 2000, [("Often seen", 3, 9)])

    assert mistakes.summarize(mistakes.load(busy))[0].stalled is True
