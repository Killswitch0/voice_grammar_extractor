"""
Tests for drills.

The important one is `test_every_drill_item_scores_its_own_examples`. Every item
carries a model answer and a counter-example, and the patterns that score it are
hand-written regexes — the one place in this project where a silent authoring
mistake produces a plausible-looking number instead of an error. A pattern that
misses its own example scores a correct answer as "not attempted"; one that
accepts its own counter-example scores a mistake as a hit. Both are worse than no
drill at all, because the number still gets recorded. It runs over the committed
fixture and over the owner's own `drills/` when that exists, since those never
reach CI and are exactly the ones written in a hurry.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest

from voxlib import csvfile, drill
from voxlib.drill import Drill, DrillItem, ItemRow

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


def _answers(*texts) -> list[str]:
    return list(texts)


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
    A pool barely larger than one session's block stops testing the pattern and
    starts testing the list: after a few sessions it's memorised and the score is
    meaningless. Sampling only helps if there is something to sample from.
    """
    assert drill.load_drill(path).size > 3 * drill.DEFAULT_ITEMS


# --- normalization -----------------------------------------------------------

def test_punctuation_never_decides_a_score():
    assert drill.normalize("He's, a FANATIC!") == "he's a fanatic"


def test_curly_apostrophes_are_folded_so_contractions_still_match():
    assert drill.normalize("He’s a fanatic") == drill.normalize("He's a fanatic")


# --- scoring -----------------------------------------------------------------

def test_a_correct_line_scores_as_attempted_and_correct():
    result = drill.score(_drill([_item()]), _answers("He's a fanatic."))

    assert (result.attempted, result.correct) == (1, 1)
    assert result.accuracy == 1.0


def test_the_target_structure_produced_wrongly_is_an_error_not_a_miss():
    result = drill.score(_drill([_item()]), _answers("He's fanatic."))

    assert (result.attempted, result.correct) == (1, 0)
    assert result.accuracy == 0.0


def test_an_item_that_was_never_said_is_not_counted_against_the_speaker():
    result = drill.score(_drill([_item(), _teacher_item()]), _answers("He's a fanatic."))

    assert (result.attempted, result.correct) == (1, 1)
    assert result.accuracy == 1.0          # 1 of 1 attempted, not 1 of 2 items
    assert [r.attempted for r in result.items] == [True, False]


def test_accuracy_is_none_when_nothing_was_attempted():
    """Zero would read as total failure; the honest answer is that there is
    nothing to score."""
    result = drill.score(_drill([_item()]), _answers("Something else entirely."))

    assert result.accuracy is None
    assert result.attempted == 0


def test_one_good_sentence_cannot_satisfy_several_items():
    result = drill.score(_drill([_item(), _item(), _item()]), _answers("He's a fanatic."))

    assert (result.attempted, result.correct) == (1, 1)


def test_matching_survives_a_false_start_between_items():
    result = drill.score(_drill([_item(), _teacher_item()]), _answers(
        "He's a fanatic.", "Wait, let me say that again.", "She's a teacher."))

    assert (result.attempted, result.correct) == (2, 2)


def test_items_answered_out_of_order_are_reported_as_missed():
    result = drill.score(_drill([_item(), _teacher_item()]),
                         _answers("She's a teacher.", "He's a fanatic."))

    assert result.attempted == 1


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


def _row(pool: Drill, index: int, *, date: str, attempted=True, correct=True) -> ItemRow:
    item = pool.items[index]
    return ItemRow(date=date, drill=pool.name, item_id=item.item_id,
                   prompt=item.prompt, attempted=attempted, correct=correct)


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
                            result=drill.score(_drill([_item()]), _answers(line)))

    assert [(r.correct, r.attempted) for r in drill.load_history(history)] == [(0, 1), (1, 1)]


def test_each_item_gets_its_own_row_so_a_repeat_offender_is_visible(tmp_path: Path):
    history, items = tmp_path / "drills.csv", tmp_path / "drill_items.csv"
    result = drill.score(_drill([_item(), _teacher_item()]),
                         _answers("He's fanatic.", "She's a teacher."))

    drill.record_result(history, items, date="2026-08-10", result=result)

    rows = drill.load_item_history(items)
    assert [(r.prompt, r.correct) for r in rows] == [("say it", False), ("she / teacher", True)]


def test_the_attempt_row_records_the_fingerprint_and_the_category(tmp_path: Path):
    history, items = tmp_path / "drills.csv", tmp_path / "drill_items.csv"
    result = drill.score(_drill([_item()]), _answers("He's a fanatic."))

    drill.record_result(history, items, date="2026-08-10", result=result)

    row = next(iter(csv.DictReader(history.read_text(encoding="utf-8").splitlines())))
    assert row["fingerprint"] == _drill([_item()]).pool_fingerprint
    assert row["category"] == "Test Category", "the join key back to memory.md"


def test_the_history_warns_when_the_item_set_changed_underneath_a_trend():
    rows = [
        drill.HistoryRow(date="2026-08-09", drill="d", category="c", fingerprint="aaa",
                         items=5, attempted=5, correct=3, notes=""),
        drill.HistoryRow(date="2026-08-10", drill="d", category="c", fingerprint="bbb",
                         items=5, attempted=5, correct=4, notes=""),
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
            "--pending", str(tmp_path / "pending.json"),
            # Pointed at nothing on purpose: the ranking a mixed block uses must
            # not depend on the owner's own mistake history, which is not in the
            # repository and differs between machines.
            "--mistakes", str(tmp_path / "no-mistakes.csv")]


def test_a_dry_run_scores_without_recording(tmp_path: Path):
    transcript = tmp_path / "t.txt"
    transcript.write_text("I have an apple.\n", encoding="utf-8")

    drill.main(_cli_paths(tmp_path) + ["score", FIXTURE_DRILL,
                                       "--answers", str(transcript), "--dry-run"])

    assert not (tmp_path / "drills.csv").exists()


def test_the_items_view_shows_which_prompts_keep_failing(tmp_path: Path, capsys):
    transcript = tmp_path / "t.txt"
    transcript.write_text("I have a apple.\n", encoding="utf-8")
    paths = _cli_paths(tmp_path)
    drill.main(paths + ["score", FIXTURE_DRILL, "--answers", str(transcript),
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
    assert "--answers" in out


def test_next_records_the_selection_so_the_typed_answers_can_be_scored(tmp_path: Path, capsys):
    drill.main(_cli_paths(tmp_path) + ["next", FIXTURE_DRILL, "--count", "3"])
    capsys.readouterr()

    assert len(drill.read_pending(tmp_path / "pending.json", FIXTURE_DRILL)) == 3


def test_an_unknown_drill_name_lists_what_is_available(tmp_path: Path, capsys):
    with pytest.raises(SystemExit):
        drill.main(_cli_paths(tmp_path) + ["next", "nope"])

    assert FIXTURE_DRILL in capsys.readouterr().err


# --- mixed blocks ------------------------------------------------------------
#
# Every score on record before this existed was 100%, on blocks where all five
# prompts trained one frame. Interleaving is the attempt to measure retrieval
# instead of what is still sitting in working memory from the prompt before.

SECOND_FIXTURE = "verb-s"


def _named_pool(name: str, category: str, n: int) -> Drill:
    pool = _pool(n)
    return Drill(name=name, category=category, target=pool.target,
                 instructions=pool.instructions, items=pool.items)


def test_a_mixed_block_never_asks_two_prompts_from_one_pattern_in_a_row():
    """The property being bought: nothing in the previous prompt primes the next
    one. Without it, four of five items measure short-term memory."""
    a = _named_pool("a", "Cat A", 6)
    b = _named_pool("b", "Cat B", 6)

    chosen = drill.select_mixed([a, b], [], count=6, patterns=2)

    names = [d.name for d, _ in chosen]
    assert names == ["a", "b", "a", "b", "a", "b"]


def test_a_mixed_block_spans_no_more_patterns_than_asked_for():
    pools = [_named_pool(name, f"Cat {name}", 6) for name in ("a", "b", "c", "d")]

    chosen = drill.select_mixed(pools, [], count=6, patterns=3)

    assert {d.name for d, _ in chosen} == {"a", "b", "c"}
    assert len(chosen) == 6


def test_an_uneven_count_is_shared_out_from_the_front_of_the_ranking():
    """Seven items over three patterns gives the worst-ranked pattern the extra
    one, not the one that happens to sort first."""
    pools = [_named_pool(name, f"Cat {name}", 6) for name in ("a", "b", "c")]

    chosen = drill.select_mixed(pools, [], count=7, patterns=3)

    counts = {name: sum(1 for d, _ in chosen if d.name == name) for name in ("a", "b", "c")}
    assert counts == {"a": 3, "b": 2, "c": 2}


def test_a_mixed_block_still_leads_each_pattern_with_what_it_missed():
    """Interleaving changes the order prompts are asked in, not which ones are
    due — a miss is still the first thing that pattern asks again."""
    a = _named_pool("a", "Cat A", 6)
    b = _named_pool("b", "Cat B", 6)
    missed = _row(a, 4, date="2026-08-10", correct=False)

    chosen = drill.select_mixed([a, b], [missed], count=2, patterns=2)

    assert chosen[0][1] is a.items[4]


def test_a_drill_with_no_items_cannot_take_a_slot_in_a_mixed_block():
    empty = Drill(name="empty", category="Cat", target="t", instructions="", items=[])
    real = _named_pool("real", "Cat B", 6)

    chosen = drill.select_mixed([empty, real], [], count=2, patterns=2)

    assert {d.name for d, _ in chosen} == {"real"}


def _mistakes_csv(path: Path, rows: list[tuple[str, int, int]]) -> Path:
    """`category, severity, occurrences` for one 1,000-word session."""
    lines = ["date,category,severity,occurrences,reliable_words,source,notes"]
    lines += [f"2026-08-10,{c},{sev},{n},1000,test," for c, sev, n in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_patterns_enter_a_mixed_block_by_impact_not_alphabetically(tmp_path: Path):
    quiet = _named_pool("aaa", "Quiet Category", 6)
    loud = _named_pool("zzz", "Loud Category", 6)
    history = _mistakes_csv(tmp_path / "mistakes.csv",
                            [("Quiet Category", 2, 1), ("Loud Category", 4, 12)])

    ranked = drill.priority_order([quiet, loud], history)

    assert [d.name for d in ranked] == ["zzz", "aaa"]


def test_a_pattern_no_mistake_history_mentions_sorts_last(tmp_path: Path):
    known = _named_pool("known", "Loud Category", 6)
    unknown = _named_pool("aaa", "Never Measured", 6)
    history = _mistakes_csv(tmp_path / "mistakes.csv", [("Loud Category", 3, 5)])

    ranked = drill.priority_order([unknown, known], history)

    assert [d.name for d in ranked] == ["known", "aaa"]


def test_a_missing_mistake_history_costs_the_ranking_not_the_block(tmp_path: Path):
    pools = [_named_pool("b", "Cat B", 6), _named_pool("a", "Cat A", 6)]

    ranked = drill.priority_order(pools, tmp_path / "nothing.csv")

    assert [d.name for d in ranked] == ["a", "b"], "falls back to name order"


def test_a_mixed_block_hides_which_pattern_each_prompt_tests(tmp_path: Path, capsys):
    """The learner reads this output. Naming the pattern next to the prompt is
    most of the answer, and it would put the priming back."""
    drill.main(_cli_paths(tmp_path) + ["next", "--mixed", "--count", "4"])
    out = capsys.readouterr().out

    assert FIXTURE_DRILL not in out and SECOND_FIXTURE not in out
    assert "Test Article Choice" not in out and "Test Verb Agreement" not in out
    assert "4 prompts, 2 patterns" in out


def test_a_mixed_block_records_the_drill_behind_every_prompt(tmp_path: Path, capsys):
    """The answers come back as one list; without this the scoring cannot tell
    which pattern each one belongs to."""
    drill.main(_cli_paths(tmp_path) + ["next", "--mixed", "--count", "4"])
    capsys.readouterr()

    pending = drill.read_mixed_pending(tmp_path / "pending.json")

    assert [name for name, _ in pending] == [FIXTURE_DRILL, SECOND_FIXTURE] * 2
    assert drill.read_pending(tmp_path / "pending.json", FIXTURE_DRILL) is None, (
        "a mixed block must not be readable as a blocked one for a single drill"
    )


def test_the_session_focus_can_be_pinned_into_a_mixed_block(tmp_path: Path, capsys):
    """The focus is chosen on a spaced-repetition schedule, which the impact
    ranking knows nothing about."""
    history = _mistakes_csv(tmp_path / "mistakes.csv",
                            [("Test Article Choice", 4, 20), ("Test Verb Agreement", 1, 1)])

    drill.main(_cli_paths(tmp_path) + ["--mistakes", str(history), "next", "--mixed",
                                       "--count", "2", "--patterns", "1",
                                       "--include", SECOND_FIXTURE])
    capsys.readouterr()

    pending = drill.read_mixed_pending(tmp_path / "pending.json")

    assert {name for name, _ in pending} == {SECOND_FIXTURE}


def test_a_mixed_block_scores_as_one_row_per_pattern(tmp_path: Path, capsys):
    paths = _cli_paths(tmp_path)
    drill.main(paths + ["next", "--mixed", "--count", "2"])
    capsys.readouterr()
    answers = tmp_path / "answers.txt"
    answers.write_text("I have a apple.\nShe teaches English.\n", encoding="utf-8")

    drill.main(paths + ["score", "--mixed", "--answers", str(answers),
                        "--date", "2026-08-17"])

    rows = drill.load_history(tmp_path / "drills.csv")
    assert [(r.drill, r.correct, r.attempted) for r in rows] == [
        (FIXTURE_DRILL, 0, 1), (SECOND_FIXTURE, 1, 1),
    ]
    assert {r.condition for r in rows} == {drill.MIXED}
    assert {r.condition for r in drill.load_item_history(tmp_path / "drill_items.csv")} \
        == {drill.MIXED}


def test_scoring_a_mixed_block_clears_it(tmp_path: Path, capsys):
    """A sample left lying around would score the next block against prompts
    nobody was asked."""
    paths = _cli_paths(tmp_path)
    drill.main(paths + ["next", "--mixed", "--count", "2"])
    answers = tmp_path / "answers.txt"
    answers.write_text("I have an apple.\nShe teaches English.\n", encoding="utf-8")
    drill.main(paths + ["score", "--mixed", "--answers", str(answers)])
    capsys.readouterr()

    assert drill.read_mixed_pending(tmp_path / "pending.json") is None


def test_a_mixed_block_cannot_be_scored_without_the_sample_it_was_drawn_from(tmp_path: Path):
    answers = tmp_path / "answers.txt"
    answers.write_text("I have an apple.\n", encoding="utf-8")

    with pytest.raises(SystemExit):
        drill.main(_cli_paths(tmp_path) + ["score", "--mixed", "--answers", str(answers)])


def test_a_drill_name_and_mixed_together_are_refused(tmp_path: Path, capsys):
    with pytest.raises(SystemExit):
        drill.main(_cli_paths(tmp_path) + ["next", FIXTURE_DRILL, "--mixed"])

    assert "not both" in capsys.readouterr().err


def test_a_blocked_attempt_is_still_recorded_as_blocked(tmp_path: Path):
    history, items = tmp_path / "drills.csv", tmp_path / "drill_items.csv"

    drill.record_result(history, items, date="2026-08-17",
                        result=drill.score(_drill([_item()]), _answers("He's a fanatic.")))

    assert [r.condition for r in drill.load_history(history)] == [drill.BLOCKED]


def test_an_unknown_condition_is_refused(tmp_path: Path):
    result = drill.score(_drill([_item()]), _answers("He's a fanatic."))

    with pytest.raises(ValueError, match="condition"):
        drill.record_result(tmp_path / "d.csv", tmp_path / "i.csv", date="2026-08-17",
                            result=result, condition="spoken")


def test_rows_written_before_the_condition_existed_read_as_blocked(tmp_path: Path):
    """The history is append-only for rows, so the column had to be added to a
    file that already held four attempts — all of them blocked."""
    history = tmp_path / "drills.csv"
    history.write_text(
        "date,drill,category,fingerprint,items,attempted,correct,notes\n"
        "2026-08-10,a-or-an,Test Article Choice,abc,5,5,5,\n",
        encoding="utf-8")

    drill.record_result(history, tmp_path / "items.csv", date="2026-08-17",
                        result=drill.score(_drill([_item()]), _answers("He's a fanatic.")),
                        condition=drill.MIXED)

    rows = drill.load_history(history)
    assert [r.condition for r in rows] == [drill.BLOCKED, drill.MIXED]
    assert rows[0].correct == 5, "the old row keeps every value it had"


def test_a_header_that_is_not_an_older_version_of_this_file_is_refused(tmp_path: Path):
    """Padding an unrecognised file would silently shift its columns."""
    history = tmp_path / "drills.csv"
    history.write_text("when,what\n2026-08-10,something\n", encoding="utf-8")

    with pytest.raises(ValueError, match="refusing to migrate"):
        csvfile.widen_header(history, drill.HISTORY_COLUMNS)


def test_the_history_warns_when_one_drill_was_asked_under_both_conditions():
    rows = [
        drill.HistoryRow(date="2026-08-11", drill="d", category="c", fingerprint="aaa",
                         items=5, attempted=5, correct=5, notes="", condition=drill.BLOCKED),
        drill.HistoryRow(date="2026-08-17", drill="d", category="c", fingerprint="aaa",
                         items=2, attempted=2, correct=1, notes="", condition=drill.MIXED),
    ]

    assert "both conditions" in drill.format_history(rows)


# --- answers recorded as they are given --------------------------------------
#
# The block is asked one prompt at a time across a conversation that runs on for
# another half hour afterwards. Collecting the answers at the end means holding
# them verbatim through everything that came in between, and the failure is
# silent: a paraphrase still scores, just not against what was said.

def test_answers_are_recorded_against_the_block_in_order(tmp_path: Path):
    paths = _cli_paths(tmp_path)
    drill.main(paths + ["next", "--mixed", "--count", "2"])

    drill.main(paths + ["answer", "She's a teacher."])
    block = drill.read_block(tmp_path / "pending.json")

    assert block.answers == ["She's a teacher."]
    assert not block.complete


def test_a_block_knows_when_it_is_full(tmp_path: Path, capsys):
    paths = _cli_paths(tmp_path)
    drill.main(paths + ["next", "--mixed", "--count", "2"])

    drill.main(paths + ["answer", "one"])
    drill.main(paths + ["answer", "two"])

    assert drill.read_block(tmp_path / "pending.json").complete
    assert "score it" in capsys.readouterr().out


def test_a_seventh_answer_to_a_six_prompt_block_is_refused(tmp_path: Path):
    paths = _cli_paths(tmp_path)
    drill.main(paths + ["next", "--mixed", "--count", "2"])
    drill.main(paths + ["answer", "one"])
    drill.main(paths + ["answer", "two"])

    with pytest.raises(SystemExit):
        drill.main(paths + ["answer", "three"])


def test_a_whole_block_can_be_recorded_in_one_call(tmp_path: Path):
    """The block does not have to cost six exchanges. It is written, with time to
    think, and scored against a key either way — so handing over all the prompts
    and taking the answers back together measures the same thing for a fraction
    of the session."""
    paths = _cli_paths(tmp_path)
    drill.main(paths + ["next", "--mixed", "--count", "2"])

    drill.main(paths + ["answer", "She's a teacher.", "He works here."])
    block = drill.read_block(tmp_path / "pending.json")

    assert block.answers == ["She's a teacher.", "He works here."]
    assert block.complete


def test_a_batch_longer_than_the_block_is_refused(tmp_path: Path):
    """Answers are paired with prompts by position, so recording an extra one
    would score an answer against a prompt nobody was asked."""
    paths = _cli_paths(tmp_path)
    drill.main(paths + ["next", "--mixed", "--count", "2"])

    with pytest.raises(SystemExit):
        drill.main(paths + ["answer", "one", "two", "three"])

    assert drill.read_block(tmp_path / "pending.json").answers == []


def test_a_batch_lands_after_the_answers_already_recorded(tmp_path: Path):
    paths = _cli_paths(tmp_path)
    drill.main(paths + ["next", "--mixed", "--count", "3"])
    drill.main(paths + ["answer", "one"])

    drill.main(paths + ["answer", "two", "three"])

    assert drill.read_block(tmp_path / "pending.json").answers == ["one", "two", "three"]


def test_recording_an_answer_with_no_block_says_so(tmp_path: Path):
    with pytest.raises(SystemExit):
        drill.main(_cli_paths(tmp_path) + ["answer", "anything"])


def test_the_last_answer_can_be_taken_back(tmp_path: Path):
    """For one written down wrong — not for one the speaker went on to repair."""
    paths = _cli_paths(tmp_path)
    drill.main(paths + ["next", "--mixed", "--count", "2"])
    drill.main(paths + ["answer", "mistyped"])

    drill.main(paths + ["answer", "--undo"])

    assert drill.read_block(tmp_path / "pending.json").answers == []


def test_recorded_answers_are_scored_against_the_item_they_were_given_to():
    """`score` has to infer the pairing from order and regexes; recorded answers
    carry it, and inferring what you already know can only lose."""
    running = _drill([_item(), _teacher_item()])

    result = drill.score_recorded(running, {
        running.items[0].item_id: "He's fanatic.",
        running.items[1].item_id: "She's a teacher.",
    })

    assert [(r.attempted, r.correct) for r in result.items] == [(True, False), (True, True)]


def test_an_unanswered_item_counts_as_unattempted_not_as_a_miss():
    """A block abandoned halfway is a shorter block, not a failed one."""
    running = _drill([_item(), _teacher_item()])

    result = drill.score_recorded(running, {running.items[0].item_id: "He's a fanatic."})

    assert result.attempted == 1 and result.correct == 1


def test_a_block_scores_from_its_recorded_answers_without_a_file(tmp_path: Path, capsys):
    paths = _cli_paths(tmp_path)
    drill.main(paths + ["next", "--mixed", "--count", "2"])
    for answer in ("He's a fanatic.", "She teaches English."):
        drill.main(paths + ["answer", answer])
    capsys.readouterr()

    drill.main(paths + ["score"])

    rows = drill.load_history(tmp_path / "drills.csv")
    assert rows and all(row.condition == drill.MIXED for row in rows)
    assert not (tmp_path / "pending.json").exists()


def test_scoring_with_nothing_answered_and_no_file_is_refused(tmp_path: Path):
    """Silently recording 0/0 would put a row in the history for a block nobody
    was ever asked."""
    paths = _cli_paths(tmp_path)
    drill.main(paths + ["next", "--mixed", "--count", "2"])

    with pytest.raises(SystemExit):
        drill.main(paths + ["score"])


def test_a_single_pattern_block_also_scores_from_recorded_answers(tmp_path: Path, capsys):
    paths = _cli_paths(tmp_path)
    drill.main(paths + ["next", FIXTURE_DRILL, "--count", "2"])
    drill.main(paths + ["answer", "He's a fanatic."])
    drill.main(paths + ["answer", "She's an engineer."])
    capsys.readouterr()

    drill.main(paths + ["score", FIXTURE_DRILL])

    rows = drill.load_history(tmp_path / "drills.csv")
    assert len(rows) == 1 and rows[0].drill == FIXTURE_DRILL
