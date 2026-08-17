"""
Tests for the spaced-repetition schedule.

What these guard is arithmetic that used to be done by hand at the end of a
session, on a file that is its own only record. A miscounted streak leaves no
trace to notice later — the wrong number simply becomes the schedule, and the
pattern comes back on the wrong day for as long as it survives.

The write tests are mostly about *not* losing things: the table is rewritten in
place, so everything around it has to come back untouched.
"""

from __future__ import annotations

from pathlib import Path

from voxlib import focus_log
from voxlib.focus_log import FocusRow

TODAY = "2024-05-20"

EXISTING = """\
# Conversation Focus Log

Notes I keep at the top of this file.

| Mistake name | Last drilled | Correct streak | Next due |
|---|---|---|---|
| Missing Article | 2024-05-14 | 2 | 2024-05-18 |
| Tense Agreement | 2024-05-10 | 0 | 2024-05-11 |

A closing note.
"""


def _log(tmp_path: Path, text: str = EXISTING) -> Path:
    path = tmp_path / "conversation_focus_log.md"
    path.write_text(text, encoding="utf-8")
    return path


# --- the schedule -------------------------------------------------------------

def test_the_gap_doubles_for_each_session_a_pattern_holds_up():
    assert focus_log.due_date(0, TODAY) == "2024-05-21"    # tomorrow
    assert focus_log.due_date(1, TODAY) == "2024-05-22"
    assert focus_log.due_date(2, TODAY) == "2024-05-24"
    assert focus_log.due_date(3, TODAY) == "2024-05-28"


def test_the_gap_stops_at_a_fortnight():
    """Past two weeks a "check" has stopped being practice and become an exam."""
    assert focus_log.due_date(4, TODAY) == "2024-06-03"    # 16 days would be 2024-06-05
    assert focus_log.due_date(9, TODAY) == focus_log.due_date(4, TODAY)


def test_a_clean_session_extends_the_streak():
    rows = {"Missing Article": FocusRow("Missing Article", "2024-05-14", 2, "2024-05-18")}

    updated, changes = focus_log.apply(rows, {"Missing Article": True}, TODAY)

    assert updated["Missing Article"] == FocusRow("Missing Article", TODAY, 3, "2024-05-28")
    assert changes[0].previous_streak == 2 and changes[0].clean


def test_an_error_resets_the_streak_and_asks_for_tomorrow():
    """P18: a mistake that resurfaces needs re-checking soon, not a longer gap."""
    rows = {"Missing Article": FocusRow("Missing Article", "2024-05-14", 4, "2024-05-28")}

    updated, _ = focus_log.apply(rows, {"Missing Article": False}, TODAY)

    assert updated["Missing Article"].streak == 0
    assert updated["Missing Article"].next_due == "2024-05-21"


def test_a_pattern_drilled_for_the_first_time_starts_at_one():
    updated, changes = focus_log.apply({}, {"New Pattern": True}, TODAY)

    assert updated["New Pattern"].streak == 1
    assert changes[0].is_new


def test_a_pattern_that_was_not_drilled_is_left_alone():
    rows = {"Missing Article": FocusRow("Missing Article", "2024-05-14", 2, "2024-05-18"),
            "Tense Agreement": FocusRow("Tense Agreement", "2024-05-10", 0, "2024-05-11")}

    updated, changes = focus_log.apply(rows, {"Missing Article": True}, TODAY)

    assert updated["Tense Agreement"] == rows["Tense Agreement"]
    assert [c.category for c in changes] == ["Missing Article"]


# --- reading and writing the document -----------------------------------------

def test_the_table_is_read_back_as_rows(tmp_path):
    rows = focus_log.load(_log(tmp_path))

    assert rows["Missing Article"] == FocusRow("Missing Article", "2024-05-14", 2, "2024-05-18")
    assert rows["Tense Agreement"].streak == 0


def test_a_missing_file_is_an_empty_schedule_not_an_error(tmp_path):
    assert focus_log.load(tmp_path / "nothing.md") == {}


def test_an_unreadable_streak_does_not_lose_the_row(tmp_path):
    """The file is edited by hand; a typo in one cell shouldn't drop the pattern
    out of the schedule entirely."""
    path = _log(tmp_path, EXISTING.replace("| Missing Article | 2024-05-14 | 2 |",
                                           "| Missing Article | 2024-05-14 | ? |"))

    rows = focus_log.load(path)

    assert rows["Missing Article"].streak == 0


def test_everything_outside_the_table_survives_a_write(tmp_path):
    path = _log(tmp_path)

    focus_log.record(path, {"Missing Article": True}, TODAY)
    text = path.read_text(encoding="utf-8")

    assert "Notes I keep at the top of this file." in text
    assert "A closing note." in text
    assert text.startswith("# Conversation Focus Log")


def test_a_write_keeps_the_row_order_and_appends_new_patterns(tmp_path):
    path = _log(tmp_path)

    focus_log.record(path, {"Tense Agreement": False, "New Pattern": True}, TODAY)
    names = [row[0] for row in focus_log.table_rows(path.read_text(encoding="utf-8"))]

    assert names == ["Missing Article", "Tense Agreement", "New Pattern"]


def test_a_round_trip_changes_only_what_was_drilled(tmp_path):
    path = _log(tmp_path)
    before = focus_log.load(path)

    focus_log.record(path, {"Missing Article": True}, TODAY)
    after = focus_log.load(path)

    assert after["Tense Agreement"] == before["Tense Agreement"]
    assert after["Missing Article"].last_drilled == TODAY


def test_the_file_is_created_when_it_does_not_exist_yet(tmp_path):
    path = tmp_path / "nested" / "log.md"

    focus_log.record(path, {"Missing Article": True}, TODAY)

    assert focus_log.load(path)["Missing Article"].streak == 1
    assert path.read_text(encoding="utf-8").startswith("# Conversation Focus Log")


def test_nothing_drilled_writes_nothing(tmp_path):
    """P18 skips this step when the session fell back to topic selection —
    there's no formal pattern to log."""
    path = tmp_path / "log.md"

    assert focus_log.record(path, {}, TODAY) == []
    assert not path.exists()
