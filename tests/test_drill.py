"""
Tests for spoken drills.

The important one is `test_every_shipped_drill_item_scores_its_own_examples`.
Every item carries a model answer and a counter-example, and the patterns that
score it are hand-written regexes over speech-to-text output — the one place in
this project where a silent authoring mistake produces a plausible-looking
number instead of an error. A pattern that doesn't match its own example scores
a correct answer as "not heard"; one that accepts its own counter-example scores
a mistake as a hit. Both are worse than no drill at all, because the number
still gets recorded.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from voxlib import drill
from voxlib.drill import Drill, DrillItem

import re

DRILLS_DIR = Path(__file__).parent.parent / "drills"


def _item(prompt="say it", example="He's a fanatic.", wrong="He's fanatic.",
          attempted=r"\b(he'?s|he is)\s+(a\s+)?fanatic\b",
          correct=r"\b(he'?s|he is)\s+a\s+fanatic\b") -> DrillItem:
    return DrillItem(prompt=prompt, example=example, wrong=wrong,
                     attempted=re.compile(attempted), correct=re.compile(correct))


def _drill(items) -> Drill:
    return Drill(name="test", category="Test Category", target="testing",
                 instructions="", items=items)


# --- the shipped content -----------------------------------------------------

def test_the_drills_directory_is_not_empty():
    assert drill.load_all(DRILLS_DIR), "no drills shipped — the feature has no content"


@pytest.mark.parametrize("path", sorted(DRILLS_DIR.glob("*.yaml")), ids=lambda p: p.stem)
def test_every_shipped_drill_item_scores_its_own_examples(path: Path):
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


@pytest.mark.parametrize("path", sorted(DRILLS_DIR.glob("*.yaml")), ids=lambda p: p.stem)
def test_a_shipped_drill_is_long_enough_to_mean_something(path: Path):
    """A handful of items is noise: one slip in five is 20%. Ten is the floor at
    which a score is worth writing down."""
    assert drill.load_drill(path).size >= 10


# --- normalization -----------------------------------------------------------

def test_punctuation_is_the_transcribers_guess_and_never_decides_a_score():
    assert drill.normalize("He's, a FANATIC!") == "he's a fanatic"


def test_curly_apostrophes_are_folded_so_contractions_still_match():
    assert drill.normalize("He’s a fanatic") == drill.normalize("He's a fanatic")


# --- scoring -----------------------------------------------------------------

def test_a_correct_line_scores_as_attempted_and_correct():
    result = drill.score(_drill([_item()]), ["He's a fanatic."])

    assert (result.attempted, result.correct) == (1, 1)
    assert result.accuracy == 1.0


def test_the_target_structure_produced_wrongly_is_an_error_not_a_miss():
    result = drill.score(_drill([_item()]), ["He's fanatic."])

    assert (result.attempted, result.correct) == (1, 0)
    assert result.accuracy == 0.0


def test_an_item_that_was_never_said_is_not_counted_against_the_speaker():
    """
    A prompt that was skipped, or that the transcriber mangled beyond
    recognition, says nothing about grammar. Folding it into the denominator
    would make a bad microphone look like a bad session — the same confusion
    the low-confidence handling elsewhere exists to prevent.
    """
    result = drill.score(_drill([_item(), _item()]), ["He's a fanatic."])

    assert (result.attempted, result.correct) == (1, 1)
    assert result.accuracy == 1.0          # 1 of 1 attempted, not 1 of 2 items
    assert [r.attempted for r in result.items] == [True, False]


def test_accuracy_is_none_when_nothing_was_attempted():
    """Zero would read as total failure; the honest answer is that there is
    nothing to score."""
    result = drill.score(_drill([_item()]), ["Something else entirely."])

    assert result.accuracy is None
    assert result.attempted == 0


def test_one_good_sentence_cannot_satisfy_several_items():
    """
    Items in a drill deliberately share a frame, so matching each item against
    the whole transcript independently would let a single sentence score three
    hits on one attempt. Matching runs forward in order, never re-using a line.
    """
    result = drill.score(_drill([_item(), _item(), _item()]), ["He's a fanatic."])

    assert (result.attempted, result.correct) == (1, 1)


def test_matching_survives_a_false_start_between_items():
    items = [_item(), _item(attempted=r"\bshe'?s\s+(a\s+)?teacher\b",
                            correct=r"\bshe'?s\s+a\s+teacher\b",
                            example="She's a teacher.", wrong="She's teacher.")]

    result = drill.score(_drill(items), [
        "He's a fanatic.",
        "Wait, let me say that again.",
        "She's a teacher.",
    ])

    assert (result.attempted, result.correct) == (2, 2)


def test_items_answered_out_of_order_are_reported_as_missed():
    """Order is load-bearing, and the drill says so: the prompts are numbered
    and spoken in sequence. Saying them backwards costs the later matches, which
    is visible in the result rather than silently absorbed."""
    items = [_item(), _item(attempted=r"\bshe'?s\s+(a\s+)?teacher\b",
                            correct=r"\bshe'?s\s+a\s+teacher\b",
                            example="She's a teacher.", wrong="She's teacher.")]

    result = drill.score(_drill(items), ["She's a teacher.", "He's a fanatic."])

    assert result.attempted == 1


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
    path = tmp_path / "drills.csv"
    result = drill.score(_drill([_item()]), ["He's fanatic."])
    drill.record_result(path, date="2026-08-10", result=result)
    better = drill.score(_drill([_item()]), ["He's a fanatic."])
    drill.record_result(path, date="2026-08-10", result=better)

    rows = drill.load_history(path)
    assert [(r.correct, r.attempted) for r in rows] == [(0, 1), (1, 1)]


def test_the_history_records_the_category_so_it_joins_to_the_mistake_trend(tmp_path: Path):
    path = tmp_path / "drills.csv"
    drill.record_result(path, date="2026-08-10", result=drill.score(_drill([_item()]),
                                                                   ["He's a fanatic."]))

    row = next(iter(csv.DictReader(path.read_text(encoding="utf-8").splitlines())))
    assert row["category"] == "Test Category"


def test_empty_history_says_so_instead_of_crashing(tmp_path: Path):
    assert drill.load_history(tmp_path / "nothing.csv") == []
    assert "No drills recorded yet" in drill.format_history([])


# --- CLI ---------------------------------------------------------------------

def test_show_prints_the_prompts_without_giving_away_the_answers(capsys):
    exit_code = drill.main(["--drills-dir", str(DRILLS_DIR), "show", "articles-linking-verb"])
    out = capsys.readouterr().out

    assert exit_code == 0
    assert "he / fanatic" in out
    assert "He's a fanatic." not in out, "reading the answer first makes it recognition practice"


def test_show_with_answers_reveals_both_the_right_and_the_wrong_form(capsys):
    drill.main(["--drills-dir", str(DRILLS_DIR), "show", "articles-linking-verb", "--answers"])
    out = capsys.readouterr().out

    assert "He's a fanatic." in out
    assert "He's fanatic." in out


def test_scoring_writes_a_row_and_prints_the_misses(tmp_path: Path, capsys):
    transcript = tmp_path / "transcript_clean.txt"
    transcript.write_text("He's fanatic.\nI'm an open-minded person.\n", encoding="utf-8")
    history = tmp_path / "drills.csv"

    exit_code = drill.main([
        "--drills-dir", str(DRILLS_DIR), "--history", str(history),
        "score", "articles-linking-verb", "--transcript", str(transcript),
        "--date", "2026-08-10",
    ])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "He's a fanatic." in out          # the model answer, shown against the miss
    assert "1/2 correct" in out
    assert drill.load_history(history)[0].correct == 1


def test_a_dry_run_scores_without_recording(tmp_path: Path):
    transcript = tmp_path / "t.txt"
    transcript.write_text("He's a fanatic.\n", encoding="utf-8")
    history = tmp_path / "drills.csv"

    drill.main(["--drills-dir", str(DRILLS_DIR), "--history", str(history),
                "score", "articles-linking-verb", "--transcript", str(transcript),
                "--dry-run"])

    assert not history.exists()


def test_an_unknown_drill_name_lists_what_is_available(capsys):
    with pytest.raises(SystemExit):
        drill.main(["--drills-dir", str(DRILLS_DIR), "show", "nope"])

    assert "articles-linking-verb" in capsys.readouterr().err
