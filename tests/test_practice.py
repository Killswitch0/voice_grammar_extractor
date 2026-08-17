"""
Tests for the practice history.

The rule this file is built around is that an error count without a word count is
not a measurement. Everything below is either about keeping that denominator
honest, or about the two readings it makes possible: a per-category rate in the
same units as `mistakes.csv`, and rule 19's count of corrected repetitions
against the count of recordings.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from voxlib import practice
from voxlib.practice import PracticeSession

# A real category name, kept because it contains a colon — the breakdown is
# parsed from the right, and a naive split on ":" loses half of this one.
COLON_CATEGORY = 'Word Order: "just" With Modal "can"'


def _session(date="2026-08-17", focus="Article Errors", words=400,
             errors=None, reproductions=0, long_turns=0) -> PracticeSession:
    return PracticeSession(date=date, focus=focus, learner_words=words,
                           errors_by_category=errors if errors is not None else {},
                           reproductions=reproductions, long_turns=long_turns)


# --- the denominator ---------------------------------------------------------

def test_the_rate_is_per_thousand_words_like_the_mistake_history():
    session = _session(words=500, errors={"Article Errors": 2})

    assert session.errors == 2
    assert session.rate_per_1000 == 4.0


def test_a_session_without_a_word_count_is_refused(tmp_path: Path):
    """The whole reason this file exists: errors with no denominator cannot be
    compared with anything, including the same mode last week."""
    with pytest.raises(ValueError, match="learner_words"):
        practice.record_session(tmp_path / "p.csv", date="2026-08-17", focus="x",
                                learner_words=0, errors_by_category={"Article Errors": 3})


def test_a_clean_session_is_recorded_rather_than_left_out(tmp_path: Path):
    """A session with no errors is data — leaving it out makes a clean session
    indistinguishable from one nobody logged."""
    path = tmp_path / "p.csv"
    practice.record_session(path, date="2026-08-17", focus="Article Errors",
                            learner_words=380, errors_by_category={})

    (session,) = practice.load(path)
    assert session.errors == 0 and session.rate_per_1000 == 0.0


def test_two_practice_sessions_in_one_day_are_two_rows(tmp_path: Path):
    """Unlike a recording, there is no transcript here to merge in twice."""
    path = tmp_path / "p.csv"
    for words in (120, 300):
        practice.record_session(path, date="2026-08-17", focus="Article Errors",
                                learner_words=words, errors_by_category={})

    assert [s.learner_words for s in practice.load(path)] == [120, 300]


def test_negative_counts_are_refused(tmp_path: Path):
    with pytest.raises(ValueError, match="Negative"):
        practice.record_session(tmp_path / "p.csv", date="2026-08-17", focus="x",
                                learner_words=100, errors_by_category={"Article Errors": -1})


# --- the breakdown -----------------------------------------------------------

def test_a_category_whose_name_contains_a_colon_survives_the_round_trip(tmp_path: Path):
    path = tmp_path / "p.csv"
    practice.record_session(path, date="2026-08-17", focus=COLON_CATEGORY,
                            learner_words=400,
                            errors_by_category={COLON_CATEGORY: 2, "Article Errors": 1})

    (session,) = practice.load(path)
    assert session.errors_by_category == {COLON_CATEGORY: 2, "Article Errors": 1}


def test_a_category_with_quotes_and_a_slash_survives_the_round_trip(tmp_path: Path):
    category = 'Verb Complementation With "Propose"/"Allow"'
    path = tmp_path / "p.csv"
    practice.record_session(path, date="2026-08-17", focus=category, learner_words=400,
                            errors_by_category={category: 1})

    (session,) = practice.load(path)
    assert session.errors_by_category == {category: 1}


def test_an_unreadable_count_is_skipped_rather_than_crashing(tmp_path: Path):
    path = tmp_path / "p.csv"
    path.write_text(
        "date,focus,learner_words,errors,error_breakdown,reproductions,long_turns,notes\n"
        "2026-08-17,x,400,1,Article Errors:many;Redundant Subject Pronoun:1,0,0,\n",
        encoding="utf-8")

    (session,) = practice.load(path)
    assert session.errors_by_category == {"Redundant Subject Pronoun": 1}


def test_columns_left_blank_by_hand_read_as_zero(tmp_path: Path):
    path = tmp_path / "p.csv"
    path.write_text(
        "date,focus,learner_words,errors,error_breakdown,reproductions,long_turns,notes\n"
        "2026-08-17,x,400,0,,,,\n",
        encoding="utf-8")

    (session,) = practice.load(path)
    assert (session.reproductions, session.long_turns) == (0, 0)


# --- per-category rates ------------------------------------------------------

def test_rates_pool_the_words_instead_of_averaging_the_sessions():
    """A 90-word session and a 400-word one are not two equal observations, and
    averaging their rates lets the short one decide the answer."""
    sessions = [
        _session(date="2026-08-16", words=100, errors={"Article Errors": 2}),
        _session(date="2026-08-17", words=900, errors={"Article Errors": 2}),
    ]

    # 4 errors over 1,000 words, not the average of 20.0 and 2.22.
    assert practice.practice_rates(sessions) == {"Article Errors": 4.0}


def test_rates_look_only_at_the_recent_window():
    sessions = [
        _session(date="2026-08-01", words=1000, errors={"Article Errors": 50}),
        _session(date="2026-08-15", words=1000, errors={"Article Errors": 1}),
        _session(date="2026-08-16", words=1000, errors={"Article Errors": 1}),
        _session(date="2026-08-17", words=1000, errors={"Article Errors": 1}),
    ]

    assert practice.practice_rates(sessions, window=3) == {"Article Errors": 1.0}


def test_the_comparison_puts_the_typed_rate_next_to_the_spoken_one():
    sessions = [_session(words=1000, errors={"Article Errors": 4})]

    table = practice.format_table(sessions, speech_rates={"Article Errors": 4.05},
                                  today="2026-08-17")

    assert "Attended vs unmonitored" in table
    assert "4.00" in table and "4.05" in table


def test_a_category_only_speech_has_seen_is_left_out_of_the_comparison():
    """The comparison is between two measurements of the same category; printing
    a spoken rate with an empty typed column invites reading the blank as zero."""
    sessions = [_session(words=1000, errors={"Article Errors": 4})]

    table = practice.format_table(sessions, speech_rates={"Article Errors": 4.05,
                                                          "Extra \"to\" After Modal": 0.14},
                                  today="2026-08-17")

    assert "After Modal" not in table


# --- rule 19's budget --------------------------------------------------------

def test_the_budget_counts_both_sides_of_rule_19():
    sessions = [_session(date="2026-08-16", reproductions=6)]

    table = practice.format_table(sessions, recording_dates=["2026-08-15"],
                                  today="2026-08-17")

    assert "1 recording(s), 1 practice session(s), 6 corrected repetition(s)" in table


def test_more_recordings_than_practice_sessions_is_called_out():
    """Rule 19's actual failure mode: the instrument runs and the treatment
    doesn't."""
    sessions = [_session(date="2026-08-16", reproductions=4)]

    table = practice.format_table(
        sessions, recording_dates=["2026-08-09", "2026-08-10", "2026-08-15"],
        today="2026-08-17")

    assert "instrument is running ahead of the treatment" in table


def test_practice_that_produced_no_repetitions_is_called_out():
    sessions = [_session(date="2026-08-16", reproductions=0)]

    table = practice.format_table(sessions, recording_dates=[], today="2026-08-17")

    assert "no corrected repetitions" in table


def test_the_budget_window_ends_at_two_weeks():
    sessions = [_session(date="2026-08-16", reproductions=2)]

    table = practice.format_table(sessions, recording_dates=["2026-07-20"],
                                  today="2026-08-17")

    assert "0 recording(s), 1 practice session(s)" in table


def test_an_empty_history_says_so_instead_of_printing_a_table(tmp_path: Path):
    assert practice.load(tmp_path / "nothing.csv") == []
    assert "No practice sessions recorded yet" in practice.format_table([])


def test_an_empty_history_still_prints_the_budget():
    """No practice against six recordings is rule 19's signal at its loudest —
    the one state where suppressing the line would hide the whole point."""
    table = practice.format_table([], recording_dates=["2026-08-10", "2026-08-15"],
                                  today="2026-08-17")

    assert "2 recording(s), 0 practice session(s)" in table
    assert "instrument is running ahead" in table


# --- CLI ---------------------------------------------------------------------

def test_the_cli_records_a_session_and_reads_it_back(tmp_path: Path, capsys):
    path = tmp_path / "p.csv"
    args = ["--path", str(path), "--mistakes", str(tmp_path / "none.csv")]

    practice.main(args + ["add", "--date", "2026-08-17", "--focus", "Article Errors",
                          "--words", "412", "--reproductions", "7", "--long-turns", "2",
                          "Article Errors:3", COLON_CATEGORY + ":1"])
    capsys.readouterr()
    practice.main(args)
    out = capsys.readouterr().out

    assert "412" in out and "9.71" in out, "4 errors in 412 words"
    assert "7" in out


def test_the_cli_refuses_a_count_it_cannot_parse(tmp_path: Path, capsys):
    with pytest.raises(SystemExit):
        practice.main(["--path", str(tmp_path / "p.csv"), "add", "--words", "100",
                       "Article Errors"])

    assert "Category:count" in capsys.readouterr().err


def test_the_cli_refuses_the_same_category_twice(tmp_path: Path, capsys):
    with pytest.raises(SystemExit):
        practice.main(["--path", str(tmp_path / "p.csv"), "add", "--words", "100",
                       "Article Errors:1", "Article Errors:2"])

    assert "listed twice" in capsys.readouterr().err


def test_the_cli_refuses_a_session_with_no_words(tmp_path: Path, capsys):
    with pytest.raises(SystemExit):
        practice.main(["--path", str(tmp_path / "p.csv"), "add", "--words", "0"])

    assert "learner_words" in capsys.readouterr().err


def test_an_unreadable_mistake_history_costs_the_comparison_not_the_table(tmp_path: Path,
                                                                         capsys):
    path = tmp_path / "p.csv"
    practice.record_session(path, date="2026-08-17", focus="x", learner_words=400,
                            errors_by_category={"Article Errors": 2})
    broken = tmp_path / "mistakes.csv"
    broken.write_text("not,a,mistake,history\n1,2,3,4\n", encoding="utf-8")

    practice.main(["--path", str(path), "--mistakes", str(broken)])
    out = capsys.readouterr().out

    assert "2026-08-17" in out
    assert "Attended vs unmonitored" not in out


# --- closing a session -------------------------------------------------------
#
# Three steps used to be run by hand at the point where the session was already
# over: score the block, append the row, move the schedule on. Each one is silent
# when skipped, and they share their inputs — whether a pattern held up is the
# drill result *and* the conversation errors, and neither step could see both.

DRILLS_DIR = Path(__file__).parent / "fixtures" / "drills"
DRILLED_CATEGORY = "Test Article Choice"    # a-or-an.yaml
OTHER_CATEGORY = "Test Verb Agreement"      # verb-s.yaml


def _close(tmp_path: Path, **overrides):
    from voxlib import practice as practice_module

    arguments = dict(
        date="2024-05-20", focus=DRILLED_CATEGORY, learner_words=400,
        errors_by_category={}, reproductions=2, long_turns=2, notes="",
        history_path=tmp_path / "practice.csv",
        focus_log_path=tmp_path / "log.md",
        pending=tmp_path / "pending.json",
        drills_dir=DRILLS_DIR,
        drill_history=tmp_path / "drills.csv",
        drill_item_history=tmp_path / "drill_items.csv",
    )
    arguments.update(overrides)
    return practice_module.close_session(**arguments)


def _block(tmp_path: Path, *answers, count: int = 2) -> None:
    from voxlib import drill as drill_module

    drill_module.main(["--drills-dir", str(DRILLS_DIR),
                       "--pending", str(tmp_path / "pending.json"),
                       "--mistakes", str(tmp_path / "none.csv"),
                       "next", "--mixed", "--count", str(count)])
    for answer in answers:
        drill_module.record_answer(tmp_path / "pending.json", answer)


def test_closing_a_session_scores_the_block_and_writes_both_files(tmp_path):
    from voxlib import drill as drill_module, focus_log, practice as practice_module

    _block(tmp_path, "I have an apple.", "She teaches English.")

    outcome = _close(tmp_path)

    assert drill_module.load_history(tmp_path / "drills.csv"), "the block went unscored"
    assert practice_module.load(tmp_path / "practice.csv")[0].learner_words == 400
    assert focus_log.load(tmp_path / "log.md")[DRILLED_CATEGORY].last_drilled == "2024-05-20"
    assert not (tmp_path / "pending.json").exists()
    assert outcome.session.errors == 0


def test_a_miss_in_the_block_resets_the_streak_like_any_other_error(tmp_path):
    """P18: it is the same pattern failing, under an easier condition."""
    from voxlib import focus_log

    _block(tmp_path, "I have a apple.", "She teaches English.")

    _close(tmp_path)
    rows = focus_log.load(tmp_path / "log.md")

    assert rows[DRILLED_CATEGORY].streak == 0
    assert rows[DRILLED_CATEGORY].next_due == "2024-05-21"
    assert rows[OTHER_CATEGORY].streak == 1


def test_an_error_in_conversation_resets_a_pattern_the_block_got_right(tmp_path):
    """The two sources are read together, which is the reason to do these steps
    in one place at all."""
    from voxlib import focus_log

    _block(tmp_path, "I have an apple.", "She teaches English.")

    _close(tmp_path, errors_by_category={DRILLED_CATEGORY: 2})

    assert focus_log.load(tmp_path / "log.md")[DRILLED_CATEGORY].streak == 0


def test_every_pattern_the_block_asked_about_is_logged_not_only_the_focus(tmp_path):
    from voxlib import focus_log

    _block(tmp_path, "I have an apple.", "She teaches English.")

    _close(tmp_path)

    assert set(focus_log.load(tmp_path / "log.md")) == {DRILLED_CATEGORY, OTHER_CATEGORY}


def test_a_category_that_was_never_tested_keeps_its_schedule(tmp_path):
    """An error made in conversation on a pattern nothing tested says nothing
    about when that pattern is next due."""
    from voxlib import focus_log

    _block(tmp_path, "I have an apple.", "She teaches English.")

    outcome = _close(tmp_path, errors_by_category={"Some Untested Category": 1})

    assert "Some Untested Category" not in focus_log.load(tmp_path / "log.md")
    assert any("unchanged" in note for note in outcome.notes)


def test_an_unanswered_block_is_left_pending_rather_than_scored_as_zero(tmp_path):
    from voxlib import drill as drill_module

    _block(tmp_path)

    outcome = _close(tmp_path)

    assert not drill_module.load_history(tmp_path / "drills.csv")
    assert (tmp_path / "pending.json").exists(), "an unasked block should survive to be asked"
    assert any("no answers were recorded" in note for note in outcome.notes)


def test_a_session_with_no_block_still_records(tmp_path):
    from voxlib import focus_log, practice as practice_module

    outcome = _close(tmp_path, errors_by_category={DRILLED_CATEGORY: 1})

    assert practice_module.load(tmp_path / "practice.csv")
    assert focus_log.load(tmp_path / "log.md")[DRILLED_CATEGORY].streak == 0
    assert any("No drill block" in note for note in outcome.notes)


def test_a_session_with_no_words_is_refused_before_anything_is_written(tmp_path):
    """Two files disagreeing about whether a session happened is worse than a
    refused command."""
    from voxlib import drill as drill_module

    _block(tmp_path, "I have an apple.", "She teaches English.")

    with pytest.raises(ValueError):
        _close(tmp_path, learner_words=0)

    assert not drill_module.load_history(tmp_path / "drills.csv")
    assert not (tmp_path / "practice.csv").exists()
    assert not (tmp_path / "log.md").exists()


def test_a_dry_run_writes_nothing(tmp_path):
    _block(tmp_path, "I have an apple.", "She teaches English.")

    outcome = _close(tmp_path, dry_run=True)

    assert outcome.changes, "a dry run should still say what it would do"
    assert not (tmp_path / "practice.csv").exists()
    assert not (tmp_path / "drills.csv").exists()
    assert not (tmp_path / "log.md").exists()
    assert (tmp_path / "pending.json").exists()


def test_a_session_with_no_corrected_repetitions_says_so(tmp_path):
    """Rule 19's whole argument: a practice session that produced none of them
    is the failure, not a clean run."""
    from voxlib import practice as practice_module

    outcome = _close(tmp_path, reproductions=0)

    assert "No corrected repetitions" in practice_module.format_outcome(outcome)
