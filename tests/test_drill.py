"""
Tests for spoken drills.

The important one is `test_every_drill_item_scores_its_own_examples`. Every item
carries a model answer and a counter-example, and the patterns that score it are
hand-written regexes over speech-to-text output — the one place in this project
where a silent authoring mistake produces a plausible-looking number instead of
an error. A pattern that doesn't match its own example scores
a correct answer as "not heard"; one that accepts its own counter-example scores
a mistake as a hit. Both are worse than no drill at all, because the number
still gets recorded. It runs over the committed fixture and over the owner's own
`drills/` when that exists, since those never reach CI and are exactly the ones
written in a hurry.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import pytest

from voxlib import drill
from voxlib.drill import Drill, DrillItem, ItemRow, SpokenLine

# Engine and CLI tests run against invented content. The real drills are built
# from the owner's own mistakes, which makes them personal data — `drills/` is
# gitignored, so nothing here may depend on it being populated.
DRILLS_DIR = Path(__file__).parent / "fixtures" / "drills"
LOCAL_DRILLS = Path(__file__).parent.parent / "drills"
FIXTURE_DRILL = "a-or-an"


def _item(prompt="say it", example="He's a fanatic.", wrong="He's fanatic.",
          attempted=r"\b(he'?s|he is)\s+(a\s+)?fanatic\b",
          correct=r"\b(he'?s|he is)\s+a\s+fanatic\b") -> DrillItem:
    return DrillItem(prompt=prompt, example=example, wrong=wrong,
                     attempted=re.compile(attempted), correct=re.compile(correct))


def _teacher_item() -> DrillItem:
    return _item(prompt="she / teacher", example="She's a teacher.", wrong="She's teacher.",
                 attempted=r"\bshe'?s\s+(a\s+)?teacher\b",
                 correct=r"\bshe'?s\s+a\s+teacher\b")


def _drill(items) -> Drill:
    return Drill(name="test", category="Test Category", target="testing",
                 instructions="", items=items)


def _spoken(*texts) -> list[SpokenLine]:
    return [SpokenLine(text=t) for t in texts]


# --- the shipped content -----------------------------------------------------

def test_the_fixture_drill_loads():
    assert drill.load_all(DRILLS_DIR), "the test fixture is missing — nothing to exercise"


@pytest.mark.parametrize(
    "path",
    sorted(DRILLS_DIR.glob("*.yaml")) + sorted(LOCAL_DRILLS.glob("*.yaml")),
    ids=lambda p: p.stem,
)
def test_every_drill_item_scores_its_own_examples(path: Path):
    """
    Runs over the fixture and, when present, over the owner's own drills — the
    latter never reach CI, and this is the only thing standing between a
    mistyped regex and a score that looks reasonable while measuring nothing.
    """
    loaded = drill.load_drill(path)
    assert loaded.name == path.stem, "the drill's name is how it's invoked; keep it the filename"

    for i, item in enumerate(loaded.items, 1):
        good, bad = drill.normalize(item.example), drill.normalize(item.wrong)
        where = f"{path.name} item {i} ({item.prompt!r})"

        assert item.attempted.search(good), f"{where}: 'attempted' misses its own example"
        assert item.attempted.search(bad), (
            f"{where}: 'attempted' misses its own counter-example, so a real mistake "
            f"would be recorded as 'not heard' rather than as an error"
        )
        assert item.correct.search(good), f"{where}: 'correct' rejects its own example"
        assert not item.correct.search(bad), (
            f"{where}: 'correct' accepts its own counter-example — this item would "
            f"score a mistake as a hit"
        )


@pytest.mark.parametrize(
    "path",
    sorted(DRILLS_DIR.glob("*.yaml")) + sorted(LOCAL_DRILLS.glob("*.yaml")),
    ids=lambda p: p.stem,
)
def test_a_pool_is_bigger_than_one_take(path: Path):
    """
    A fixed list of exactly the length you speak stops testing the pattern and
    starts testing the list: after a few runs it's memorised and the score is
    meaningless. Sampling only helps if there is something to sample from.
    """
    assert drill.load_drill(path).size > drill.DEFAULT_SAMPLE


# --- normalization -----------------------------------------------------------

def test_punctuation_is_the_transcribers_guess_and_never_decides_a_score():
    assert drill.normalize("He's, a FANATIC!") == "he's a fanatic"


def test_curly_apostrophes_are_folded_so_contractions_still_match():
    assert drill.normalize("He’s a fanatic") == drill.normalize("He's a fanatic")


# --- scoring -----------------------------------------------------------------

def test_a_correct_line_scores_as_attempted_and_correct():
    result = drill.score(_drill([_item()]), _spoken("He's a fanatic."))

    assert (result.attempted, result.correct) == (1, 1)
    assert result.accuracy == 1.0


def test_the_target_structure_produced_wrongly_is_an_error_not_a_miss():
    result = drill.score(_drill([_item()]), _spoken("He's fanatic."))

    assert (result.attempted, result.correct) == (1, 0)
    assert result.accuracy == 0.0


def test_an_item_that_was_never_said_is_not_counted_against_the_speaker():
    result = drill.score(_drill([_item(), _teacher_item()]), _spoken("He's a fanatic."))

    assert (result.attempted, result.correct) == (1, 1)
    assert result.accuracy == 1.0          # 1 of 1 attempted, not 1 of 2 items
    assert [r.attempted for r in result.items] == [True, False]


def test_accuracy_is_none_when_nothing_was_attempted():
    """Zero would read as total failure; the honest answer is that there is
    nothing to score."""
    result = drill.score(_drill([_item()]), _spoken("Something else entirely."))

    assert result.accuracy is None
    assert result.attempted == 0


def test_one_good_sentence_cannot_satisfy_several_items():
    result = drill.score(_drill([_item(), _item(), _item()]), _spoken("He's a fanatic."))

    assert (result.attempted, result.correct) == (1, 1)


def test_matching_survives_a_false_start_between_items():
    result = drill.score(_drill([_item(), _teacher_item()]), _spoken(
        "He's a fanatic.", "Wait, let me say that again.", "She's a teacher."))

    assert (result.attempted, result.correct) == (2, 2)


def test_items_answered_out_of_order_are_reported_as_missed():
    result = drill.score(_drill([_item(), _teacher_item()]),
                         _spoken("She's a teacher.", "He's a fanatic."))

    assert result.attempted == 1


# --- the recogniser is part of the instrument --------------------------------

def test_a_line_the_recogniser_doubted_is_never_scored_as_a_mistake():
    """
    An article is a short unstressed function word — exactly what speech-to-text
    drops and inserts. Scoring such a line puts the recogniser's uncertainty on
    the speaker's record as a grammar error, which is the one thing rule 1 of
    this project exists to prevent.
    """
    lines = [SpokenLine(text="He's fanatic.", low_confidence=True)]

    result = drill.score(_drill([_item()]), lines)

    assert (result.attempted, result.correct) == (0, 0)
    assert result.unscorable_lines == 1


def test_a_doubted_line_does_not_block_the_item_from_matching_later():
    lines = [SpokenLine(text="He's fanatic.", low_confidence=True),
             SpokenLine(text="He's a fanatic.")]

    result = drill.score(_drill([_item()]), lines)

    assert (result.attempted, result.correct) == (1, 1)


def test_lines_json_carries_confidence_and_timings_into_scoring(tmp_path: Path):
    path = tmp_path / "lines.json"
    path.write_text(json.dumps({"lines": [
        {"text": "He's a fanatic.", "start": 0.0, "end": 2.0, "low_confidence": False},
        {"text": "mumble", "start": 2.0, "end": 3.0, "low_confidence": True},
    ]}), encoding="utf-8")

    lines = drill.load_spoken_lines(path)

    assert [l.low_confidence for l in lines] == [False, True]
    assert lines[0].end == 2.0


def test_a_plain_transcript_still_loads_with_nothing_known_about_it(tmp_path: Path):
    path = tmp_path / "transcript_clean.txt"
    path.write_text("He's a fanatic.\n\nShe's a teacher.\n", encoding="utf-8")

    lines = drill.load_spoken_lines(path)

    assert [l.text for l in lines] == ["He's a fanatic.", "She's a teacher."]
    assert all(l.end is None and not l.low_confidence for l in lines)


# --- pace --------------------------------------------------------------------

def test_pace_counts_the_thinking_pause_not_just_the_speaking():
    """
    Fifteen right with four seconds of thinking before each and fifteen right at
    conversational speed are different states of the same skill, and only the
    second is automaticity. So the clock runs from the end of the previous
    answer, not from the start of this one.
    """
    lines = [SpokenLine(text="He's a fanatic.", start=0.0, end=2.0),
             SpokenLine(text="She's a teacher.", start=6.0, end=8.0)]

    result = drill.score(_drill([_item(), _teacher_item()]), lines)

    assert [r.seconds for r in result.items] == [2.0, 6.0]
    assert result.median_seconds == 4.0


def test_pace_is_none_rather_than_zero_when_the_transcript_has_no_timings():
    result = drill.score(_drill([_item()]), _spoken("He's a fanatic."))

    assert result.median_seconds is None


# --- item identity and fingerprints ------------------------------------------

def test_an_items_identity_follows_its_answer_not_its_position():
    """Inserting an item must not silently re-label every item after it, or the
    per-item history moves onto the wrong prompts."""
    first, second = _item(), _teacher_item()

    assert first.item_id != second.item_id
    assert _drill([first, second]).items[1].item_id == _drill([second]).items[0].item_id


def test_editing_the_pool_changes_the_fingerprint():
    """An old score and a new one are not the same measurement if the items
    changed, and the history has to be able to say so."""
    before = _drill([_item()]).pool_fingerprint
    after = _drill([_item(), _teacher_item()]).pool_fingerprint

    assert before != after


def test_a_sample_carries_the_pools_fingerprint_not_its_own():
    """The sample is meant to differ every run. If the fingerprint tracked it,
    the history would report the drill as edited every single time and the
    warning would be worth nothing."""
    pool = _drill([_item(), _teacher_item()])

    sample = pool.subset([pool.items[0].item_id])

    assert sample.size == 1
    assert sample.pool_fingerprint == pool.pool_fingerprint


def test_two_items_with_the_same_answer_are_refused(tmp_path: Path):
    """Their histories would merge into one, and neither prompt could be tracked."""
    path = tmp_path / "dupe.yaml"
    path.write_text(
        "name: dupe\ncategory: X\ntarget: Y\nitems:\n"
        + 2 * ("  - prompt: p\n    example: He's a fanatic.\n    wrong: He's fanatic.\n"
               "    attempted: fanatic\n    correct: a fanatic\n"),
        encoding="utf-8")

    with pytest.raises(ValueError, match="same model answer"):
        drill.load_drill(path)


# --- sampling ----------------------------------------------------------------

def _pool(n: int) -> Drill:
    return _drill([_item(prompt=f"p{i}", example=f"He's a fanatic {i}.",
                         wrong=f"He's fanatic {i}.",
                         attempted=rf"\b(he'?s|he is)\s+(a\s+)?fanatic {i}\b",
                         correct=rf"\b(he'?s|he is)\s+a\s+fanatic {i}\b")
                  for i in range(n)])


def _row(pool: Drill, index: int, *, date: str, attempted=True, correct=True,
         mode=drill.DRILL_MODE) -> ItemRow:
    item = pool.items[index]
    return ItemRow(date=date, drill=pool.name, mode=mode, item_id=item.item_id,
                   prompt=item.prompt, attempted=attempted, correct=correct, seconds=None)


def test_a_sample_at_least_as_big_as_the_pool_is_the_whole_pool():
    pool = _pool(5)

    assert drill.select_items(pool, [], 5) == pool.items


def test_items_never_seen_come_before_items_already_answered_right():
    pool = _pool(4)
    history = [_row(pool, 0, date="2026-08-01"), _row(pool, 1, date="2026-08-01")]

    chosen = drill.select_items(pool, history, 2)

    assert {i.prompt for i in chosen} == {"p2", "p3"}


def test_a_missed_item_comes_back_before_anything_else_including_unseen_ones():
    """
    Closing a miss is what the drill is for. Ranked behind the unseen items it
    would wait for the whole pool to cycle — weeks, on a pool twice the sample
    size — which is not drilling it at all.
    """
    pool = _pool(6)
    history = [_row(pool, 4, date="2026-08-01", correct=False)]

    assert drill.select_items(pool, history, 1)[0].prompt == "p4"


def test_items_missed_last_time_come_back_before_items_already_right():
    pool = _pool(3)
    history = [
        _row(pool, 0, date="2026-08-01", correct=True),
        _row(pool, 1, date="2026-08-01", correct=False),
        _row(pool, 2, date="2026-08-01", correct=True),
    ]

    assert [i.prompt for i in drill.select_items(pool, history, 1)] == ["p1"]


def test_among_items_already_right_the_least_recent_comes_first():
    """Otherwise the pool narrows to a favourite handful and the rest is never
    checked again."""
    pool = _pool(3)
    history = [
        _row(pool, 0, date="2026-08-09"),
        _row(pool, 1, date="2026-08-01"),
        _row(pool, 2, date="2026-08-05"),
    ]

    assert [i.prompt for i in drill.select_items(pool, history, 1)] == ["p1"]


def test_a_typed_miss_brings_an_item_back_like_any_other_miss():
    """Getting it wrong with time to think and no recogniser in the way is
    strong evidence the item isn't known."""
    pool = _pool(6)
    history = [_row(pool, 3, date="2026-08-01", correct=False, mode=drill.TYPED_MODE)]

    assert drill.select_items(pool, history, 1)[0].prompt == "p3"


def test_a_typed_hit_does_not_retire_an_item_from_the_spoken_drill():
    """
    The asymmetry is the point. Typing is the easier test, so a hit there is
    weak evidence of mastery — counting it would quietly remove items from the
    spoken drill on the strength of a condition the speaker never faces in
    conversation.
    """
    pool = _pool(3)
    history = [_row(pool, 0, date="2026-08-09", correct=True, mode=drill.TYPED_MODE)]

    # p0 is still treated as never attempted, so it stays ahead of nothing in
    # particular — but crucially it is not sorted behind the unseen items.
    assert drill.select_items(pool, history, 1)[0].prompt == "p0"


def test_a_calibration_run_does_not_mark_items_as_mastered():
    """Reading the answer sheet aloud says nothing about which items are hard;
    letting it count would retire exactly the ones worth drilling."""
    pool = _pool(2)
    history = [_row(pool, 0, date="2026-08-09", mode=drill.CALIBRATION_MODE)]

    chosen = drill.select_items(pool, history, 2)

    assert len(chosen) == 2
    assert drill.select_items(pool, history, 1)[0].prompt == "p0"   # still unseen


def test_a_sample_keeps_the_drills_own_order():
    pool = _pool(6)

    chosen = drill.select_items(pool, [], 3)

    assert [i.prompt for i in chosen] == ["p0", "p1", "p2"]


# --- the pending sample ------------------------------------------------------

def test_the_sample_is_written_down_rather_than_recomputed(tmp_path: Path):
    """
    Scoring happens after the history has moved, so recomputing the selection
    would be reproducible only by luck — and a mismatch means being scored
    against prompts that were never shown, with almost every item reading as
    "not heard".
    """
    path = tmp_path / "pending.json"
    pool = _pool(3)
    drill.write_pending(path, pool, [pool.items[1].item_id])

    assert drill.read_pending(path, "test") == [pool.items[1].item_id]


def test_a_pending_sample_for_another_drill_is_ignored(tmp_path: Path):
    path = tmp_path / "pending.json"
    drill.write_pending(path, _pool(2), ["abc"])

    assert drill.read_pending(path, "other-drill") is None


def test_an_unreadable_pending_file_falls_back_instead_of_crashing(tmp_path: Path):
    path = tmp_path / "pending.json"
    path.write_text("{not json", encoding="utf-8")

    assert drill.read_pending(path, "test") is None


# --- loading -----------------------------------------------------------------

def test_a_drill_missing_a_field_is_refused_by_name(tmp_path: Path):
    path = tmp_path / "broken.yaml"
    path.write_text("name: broken\ncategory: X\ntarget: Y\nitems:\n  - prompt: say it\n",
                    encoding="utf-8")

    with pytest.raises(ValueError, match="item 1 is missing"):
        drill.load_drill(path)


def test_a_drill_with_no_items_is_refused(tmp_path: Path):
    path = tmp_path / "empty.yaml"
    path.write_text("name: empty\ncategory: X\ntarget: Y\nitems: []\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no items"):
        drill.load_drill(path)


# --- history -----------------------------------------------------------------

def test_running_the_same_drill_twice_in_a_day_records_two_attempts(tmp_path: Path):
    """Unlike the session history, repetition here is the point: two runs are two
    observations, not one counted twice."""
    history, items = tmp_path / "drills.csv", tmp_path / "drill_items.csv"
    for line in ("He's fanatic.", "He's a fanatic."):
        drill.record_result(history, items, date="2026-08-10",
                            result=drill.score(_drill([_item()]), _spoken(line)))

    assert [(r.correct, r.attempted) for r in drill.load_history(history)] == [(0, 1), (1, 1)]


def test_each_item_gets_its_own_row_so_a_repeat_offender_is_visible(tmp_path: Path):
    history, items = tmp_path / "drills.csv", tmp_path / "drill_items.csv"
    result = drill.score(_drill([_item(), _teacher_item()]),
                         _spoken("He's fanatic.", "She's a teacher."))

    drill.record_result(history, items, date="2026-08-10", result=result)

    rows = drill.load_item_history(items)
    assert [(r.prompt, r.correct) for r in rows] == [("say it", False), ("she / teacher", True)]


def test_the_attempt_row_records_the_fingerprint_and_the_mode(tmp_path: Path):
    history, items = tmp_path / "drills.csv", tmp_path / "drill_items.csv"
    result = drill.score(_drill([_item()]), _spoken("He's a fanatic."),
                         mode=drill.CALIBRATION_MODE)

    drill.record_result(history, items, date="2026-08-10", result=result)

    row = next(iter(csv.DictReader(history.read_text(encoding="utf-8").splitlines())))
    assert row["mode"] == drill.CALIBRATION_MODE
    assert row["fingerprint"] == _drill([_item()]).pool_fingerprint
    assert row["category"] == "Test Category"


def test_an_unmeasured_pace_is_blank_and_never_zero(tmp_path: Path):
    history, items = tmp_path / "drills.csv", tmp_path / "drill_items.csv"
    drill.record_result(history, items, date="2026-08-10",
                        result=drill.score(_drill([_item()]), _spoken("He's a fanatic.")))

    row = next(iter(csv.DictReader(history.read_text(encoding="utf-8").splitlines())))
    assert row["median_seconds"] == ""
    assert drill.load_history(history)[0].median_seconds is None


def test_the_history_warns_when_the_item_set_changed_underneath_a_trend():
    rows = [
        drill.HistoryRow(date="2026-08-09", drill="d", category="c", fingerprint="aaa",
                         mode=drill.DRILL_MODE, items=15, attempted=15, correct=10,
                         median_seconds=None, unscorable_lines=0, notes=""),
        drill.HistoryRow(date="2026-08-10", drill="d", category="c", fingerprint="bbb",
                         mode=drill.DRILL_MODE, items=15, attempted=15, correct=14,
                         median_seconds=None, unscorable_lines=0, notes=""),
    ]

    assert "Item set changed" in drill.format_history(rows)


def test_empty_history_says_so_instead_of_crashing(tmp_path: Path):
    assert drill.load_history(tmp_path / "nothing.csv") == []
    assert drill.load_item_history(tmp_path / "nothing.csv") == []
    assert "No drills recorded yet" in drill.format_history([])


# --- CLI ---------------------------------------------------------------------

def _cli_paths(tmp_path: Path) -> list[str]:
    return ["--drills-dir", str(DRILLS_DIR),
            "--history", str(tmp_path / "drills.csv"),
            "--item-history", str(tmp_path / "drill_items.csv"),
            "--pending", str(tmp_path / "pending.json")]


def test_show_prints_a_sample_without_giving_away_the_answers(tmp_path: Path, capsys):
    exit_code = drill.main(_cli_paths(tmp_path) + ["show", FIXTURE_DRILL])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert f"{drill.DEFAULT_SAMPLE} of 18 items" in out
    assert "I have an apple." not in out, "reading the answer first makes it recognition practice"


def test_show_records_the_selection_for_scoring(tmp_path: Path, capsys):
    drill.main(_cli_paths(tmp_path) + ["show", FIXTURE_DRILL, "--sample", "3"])
    capsys.readouterr()

    pending = drill.read_pending(tmp_path / "pending.json", FIXTURE_DRILL)
    assert pending is not None and len(pending) == 3


def test_show_with_answers_reveals_both_the_right_and_the_wrong_form(tmp_path: Path, capsys):
    drill.main(_cli_paths(tmp_path) + ["show", FIXTURE_DRILL, "--answers"])
    out = capsys.readouterr().out

    assert "I have an apple." in out
    assert "I have a apple." in out


def test_scoring_uses_the_sample_that_was_shown(tmp_path: Path, capsys):
    transcript = tmp_path / "t.txt"
    transcript.write_text("I have a apple.\n", encoding="utf-8")
    paths = _cli_paths(tmp_path)

    drill.main(paths + ["show", FIXTURE_DRILL, "--sample", "2"])
    capsys.readouterr()
    drill.main(paths + ["score", FIXTURE_DRILL, "--transcript", str(transcript),
                        "--date", "2026-08-10"])
    out = capsys.readouterr().out

    assert "of 2 items attempted" in out
    assert drill.load_history(tmp_path / "drills.csv")[0].items == 2
    assert not (tmp_path / "pending.json").exists(), "a used sample must not linger"


def test_scoring_a_plain_transcript_says_what_it_cannot_see(tmp_path: Path, capsys):
    transcript = tmp_path / "t.txt"
    transcript.write_text("I have an apple.\n", encoding="utf-8")

    drill.main(_cli_paths(tmp_path) + ["score", FIXTURE_DRILL,
                                       "--transcript", str(transcript), "--dry-run"])

    assert "no confidence flags and no timings" in capsys.readouterr().out


def test_a_calibration_run_is_labelled_as_the_instruments_error(tmp_path: Path, capsys):
    transcript = tmp_path / "t.txt"
    transcript.write_text("I have a apple.\n", encoding="utf-8")

    drill.main(_cli_paths(tmp_path) + ["score", FIXTURE_DRILL, "--calibrate",
                                       "--transcript", str(transcript), "--date", "2026-08-10"])
    out = capsys.readouterr().out

    assert "CALIBRATION RUN" in out
    assert "the drill's own error rate" in out
    assert drill.load_history(tmp_path / "drills.csv")[0].mode == drill.CALIBRATION_MODE


def test_a_dry_run_scores_without_recording(tmp_path: Path):
    transcript = tmp_path / "t.txt"
    transcript.write_text("I have an apple.\n", encoding="utf-8")

    drill.main(_cli_paths(tmp_path) + ["score", FIXTURE_DRILL,
                                       "--transcript", str(transcript), "--dry-run"])

    assert not (tmp_path / "drills.csv").exists()


def test_the_items_view_shows_which_prompts_keep_failing(tmp_path: Path, capsys):
    transcript = tmp_path / "t.txt"
    transcript.write_text("I have a apple.\n", encoding="utf-8")
    paths = _cli_paths(tmp_path)
    drill.main(paths + ["score", FIXTURE_DRILL, "--transcript", str(transcript),
                        "--whole-drill", "--date", "2026-08-10"])
    capsys.readouterr()

    drill.main(paths + ["items", FIXTURE_DRILL])
    out = capsys.readouterr().out

    assert "I have / apple" in out
    assert "2026-08-10" in out


def test_next_hands_practice_mode_the_prompts_without_the_answers(tmp_path: Path, capsys):
    """This output is visible to the person answering, so printing the key would
    turn the block into a reading exercise."""
    exit_code = drill.main(_cli_paths(tmp_path) + ["next", FIXTURE_DRILL])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "I have / apple" in out
    assert "I have an apple." not in out
    assert "--typed" in out


def test_next_records_the_selection_so_the_typed_answers_can_be_scored(tmp_path: Path, capsys):
    drill.main(_cli_paths(tmp_path) + ["next", FIXTURE_DRILL, "--count", "3"])
    capsys.readouterr()

    assert len(drill.read_pending(tmp_path / "pending.json", FIXTURE_DRILL)) == 3


def test_a_typed_run_is_recorded_as_its_own_series(tmp_path: Path, capsys):
    answers = tmp_path / "answers.txt"
    answers.write_text("I have an apple.\n", encoding="utf-8")
    paths = _cli_paths(tmp_path)
    drill.main(paths + ["next", FIXTURE_DRILL, "--count", "1"])
    capsys.readouterr()

    drill.main(paths + ["score", FIXTURE_DRILL, "--typed",
                        "--transcript", str(answers), "--date", "2026-08-10"])
    out = capsys.readouterr().out

    assert "TYPED RUN" in out
    assert "no confidence flags" not in out, "there was no recogniser to warn about"
    assert drill.load_history(tmp_path / "drills.csv")[0].mode == drill.TYPED_MODE


def test_the_history_says_when_typed_and_spoken_runs_are_being_mixed():
    def row(mode):
        return drill.HistoryRow(date="2026-08-10", drill="d", category="c",
                                fingerprint="aaa", mode=mode, items=5, attempted=5,
                                correct=4, median_seconds=None, unscorable_lines=0, notes="")

    assert "two series" in drill.format_history([row(drill.DRILL_MODE), row(drill.TYPED_MODE)])
    assert "two series" not in drill.format_history([row(drill.DRILL_MODE)])


def test_an_unknown_drill_name_lists_what_is_available(tmp_path: Path, capsys):
    with pytest.raises(SystemExit):
        drill.main(_cli_paths(tmp_path) + ["show", "nope"])

    assert FIXTURE_DRILL in capsys.readouterr().err
