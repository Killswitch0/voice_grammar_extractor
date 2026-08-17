"""
Tests for the session brief.

The brief is P14, P15 and P24 carried out in code instead of by hand, so what
these check is that the encoded rules still say what the prose says: unlogged
patterns before scheduled ones, a stalled pattern pulled forward but not handed
the session outright, clarity preferred only where impact is close, and a
missing file never blocking the session (P14's explicit instruction).

The parsing tests exist because `memory.md` is a document a person edits, not a
data format, and the failure mode of a parser over one of those is silence — an
empty candidate list reads exactly like "nothing is tracked yet".

Every document below is invented, like `tests/fixtures/drills/`: a real
`memory.md` is the owner's own learning record and is gitignored for that
reason.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from voxlib import brief
from voxlib.brief import VocabularyItem
from voxlib.focus_log import FocusRow

TODAY = "2024-05-20"

# Invented, but shaped exactly like the real thing — including a heading with
# double quotes in it, which is what the copy-pasteable commands have to survive.
QUOTED_CATEGORY = 'Verb Complementation With "Suggest"/"Recommend"'

MEMORY = f"""\
# English Memory

Last updated: 2024-05-18

---

# Current English Level

Estimated CEFR: B2 (leaning C1)
Confidence: Medium

---

# Current Priorities

1. Missing Article with countable singular nouns — impact **4.10**, polish tier.
2. "Very" as a universal intensifier — the reserved vocabulary slot.

---

# Persistent Grammar Mistakes

## Missing Article

Status: Active
Severity: 2

## Wrong Preposition After A Verb

Status: Active

## {QUOTED_CATEGORY}

Status: Active

---

# Vocabulary To Replace

| I usually say | Better alternatives |
|---|---|
| nice (for anything positive) | thoughtful / useful / a relief |
| very (as a universal intensifier) | genuinely / remarkably — or drop it (N uses last session) |
| thing (as a vague noun) | name the actual noun |

---

# Improvements

## Tense Agreement
Last seen: 2024-04-30

---

# Conversation History

| Session date | Main problems | Improvements |
|---|---|---|
| 2024-05-18 | articles | none |
"""

FOCUS_LOG = """\
# Conversation Focus Log

| Mistake name | Last drilled | Correct streak | Next due |
|---|---|---|---|
| Missing Article | 2024-05-14 | 0 | 2024-05-15 |
| Wrong Preposition After A Verb | 2024-05-19 | 3 | 2024-05-27 |
"""


class _Trend:
    """Enough of `mistakes.CategoryTrend` for the selection to sort on."""

    def __init__(self, impact: float, tier: str = "polish", stalled: bool = False):
        self.impact = impact
        self.tier = tier
        self.stalled = stalled


@pytest.fixture
def memory_file(tmp_path: Path) -> Path:
    path = tmp_path / "memory.md"
    path.write_text(MEMORY, encoding="utf-8")
    return path


# --- reading memory.md --------------------------------------------------------

def test_memory_yields_the_four_things_practice_mode_needs(memory_file):
    memory = brief.parse_memory(memory_file)

    assert memory.cefr == "B2 (leaning C1)"
    assert memory.persistent == ["Missing Article", "Wrong Preposition After A Verb",
                                 QUOTED_CATEGORY]
    assert len(memory.priorities) == 2
    assert [v.word for v in memory.vocabulary] == ["nice", "very", "thing"]


def test_resolved_mistakes_are_not_offered_as_candidates(memory_file):
    """`# Improvements` carries `## <Mistake Name>` headings of its own, and a
    pattern in there is one that stopped appearing — drilling it would spend the
    session on the one thing already known to be fine."""
    memory = brief.parse_memory(memory_file)

    assert "Tense Agreement" not in memory.persistent


def test_a_replacement_is_trimmed_to_the_suggestion(memory_file):
    """The right-hand column carries counts and dates; a constraint held while
    speaking cannot."""
    row = next(v for v in brief.parse_memory(memory_file).vocabulary if v.word == "very")

    assert row.replacement == "genuinely / remarkably"


def test_a_missing_memory_file_is_empty_rather_than_fatal(tmp_path):
    """P14: never block on it."""
    memory = brief.parse_memory(tmp_path / "nothing.md")

    assert memory.persistent == [] and not memory.usable


# --- choosing the focus (P15) -------------------------------------------------

def test_an_unlogged_pattern_beats_an_overdue_one():
    """"A category with no logged row yet counts as more overdue than any
    category that has one" — nothing has ever said it holds up."""
    log = {"Missing Article": FocusRow("Missing Article", "2024-05-14", 0, "2024-05-15")}

    choice = brief.choose_focus(["Missing Article", "Tense Agreement"], log,
                                {"Missing Article": _Trend(9.0)}, TODAY)

    assert choice.category == "Tense Agreement"
    assert "never drilled" in choice.reason


def test_the_most_overdue_logged_pattern_wins_on_the_date_not_the_impact():
    log = {
        "Missing Article": FocusRow("Missing Article", "2024-05-14", 0, "2024-05-15"),
        "Tense Agreement": FocusRow("Tense Agreement", "2024-05-08", 0, "2024-05-09"),
    }
    trends = {"Missing Article": _Trend(9.0), "Tense Agreement": _Trend(1.0)}

    choice = brief.choose_focus(list(log), log, trends, TODAY)

    assert choice.category == "Tense Agreement"
    assert choice.runners_up == ["Missing Article"]


def test_equally_due_patterns_break_on_impact():
    log = {name: FocusRow(name, "2024-05-12", 0, "2024-05-13") for name in ("A", "B")}

    choice = brief.choose_focus(["A", "B"], log, {"A": _Trend(1.0), "B": _Trend(4.0)}, TODAY)

    assert choice.category == "B"


def test_clarity_wins_a_close_call_and_loses_a_clear_one():
    """P15 prefers clarity "where impact is close" — a tie-break, not a second
    ranking, so a genuinely higher-impact polish item still wins."""
    log = {name: FocusRow(name, "2024-05-12", 0, "2024-05-13") for name in ("polish", "clarity")}

    close = brief.choose_focus(["polish", "clarity"], log,
                               {"polish": _Trend(3.2), "clarity": _Trend(3.0, "clarity")}, TODAY)
    clear = brief.choose_focus(["polish", "clarity"], log,
                               {"polish": _Trend(9.0), "clarity": _Trend(3.0, "clarity")}, TODAY)

    assert close.category == "clarity"
    assert clear.category == "polish"


def test_a_stalled_pattern_is_pulled_forward_but_not_handed_the_session():
    """Rule 18 makes drilling it here the changed approach, so a future `Next
    due` shouldn't hide it — but P15 calls it a strong candidate, not an
    override, so something already overdue still goes first."""
    log = {
        "stalled": FocusRow("stalled", "2024-05-19", 2, "2024-05-27"),
        "overdue": FocusRow("overdue", "2024-05-04", 0, "2024-05-05"),
        "later": FocusRow("later", "2024-05-19", 2, "2024-05-23"),
    }
    trends = {"stalled": _Trend(2.0, stalled=True), "overdue": _Trend(2.0), "later": _Trend(2.0)}

    against_nothing_due = brief.choose_focus(["stalled", "later"], log, trends, TODAY)
    against_overdue = brief.choose_focus(["stalled", "overdue"], log, trends, TODAY)

    assert against_nothing_due.category == "stalled"
    assert "rule 18" in against_nothing_due.reason
    assert against_overdue.category == "overdue"


def test_no_candidates_means_no_focus():
    """P15's first branch: nothing persistent yet, so pick a topic normally."""
    assert brief.choose_focus([], {}, {}, TODAY) is None


# --- choosing the words (P24) -------------------------------------------------

def test_the_vocabulary_item_named_in_priorities_is_pinned():
    """Rule 17 already reserved a slot in that ranking for vocabulary, so the
    analysis has decided which word costs most — re-deciding it here would be a
    second, worse ranking of the same thing."""
    items = [VocabularyItem("nice (positive)", "useful"),
             VocabularyItem("very (intensifier)", "genuinely"),
             VocabularyItem("thing (vague)", "name the noun")]

    chosen = brief.choose_vocabulary(items, ['"Very" as a universal intensifier'], rotation=2)

    assert chosen[0].word == "very"
    assert len(chosen) == 3


def test_the_unpinned_slots_rotate_so_the_list_is_a_rota_not_a_fossil():
    items = [VocabularyItem(w, "x") for w in ("a", "b", "c", "d", "e")]

    first = brief.choose_vocabulary(items, [], rotation=0)
    later = brief.choose_vocabulary(items, [], rotation=3)

    assert [v.word for v in first] == ["a", "b", "c"]
    assert [v.word for v in later] == ["d", "e", "a"]


def test_never_more_than_three_words_are_banned():
    """P24's cap: the constraint has to be holdable while talking."""
    items = [VocabularyItem(w, "x") for w in ("a", "b", "c", "d", "e", "f")]

    assert len(brief.choose_vocabulary(items, [])) == brief.VOCABULARY_SLOTS


def test_an_empty_table_bans_nothing_rather_than_failing():
    assert brief.choose_vocabulary([], ["anything"]) == []


# --- the whole brief ----------------------------------------------------------

def _build(tmp_path: Path, **overrides):
    paths = dict(
        today=TODAY,
        memory_path=tmp_path / "memory.md",
        focus_log_path=tmp_path / "log.md",
        mistakes_path=tmp_path / "mistakes.csv",
        practice_path=tmp_path / "practice.csv",
        drills_dir=tmp_path / "drills",
        item_history=tmp_path / "items.csv",
        pending=tmp_path / "pending.json",
    )
    paths.update(overrides)
    return brief.build(**paths)


def test_a_brief_survives_every_file_being_missing(tmp_path):
    """The whole of P14 is conditional on this: "if any of these is missing or
    unreadable, say nothing and fall back to normal topic selection"."""
    result = _build(tmp_path)

    assert result.focus is None
    assert result.block is None
    assert "recording" in result.budget
    assert brief.format_brief(result)


def test_the_brief_names_the_focus_and_the_words(tmp_path, memory_file):
    (tmp_path / "log.md").write_text(FOCUS_LOG, encoding="utf-8")

    result = _build(tmp_path, memory_path=memory_file)
    rendered = brief.format_brief(result)

    # Missing Article is overdue; the third heading has no logged row at all, so
    # it goes first (P15).
    assert result.focus.category == QUOTED_CATEGORY
    assert "B2" in rendered and QUOTED_CATEGORY in rendered
    assert "very" in rendered


def test_an_overridden_focus_says_so(tmp_path, memory_file):
    """A brief that ignored the schedule must never look like one that applied
    it."""
    result = _build(tmp_path, memory_path=memory_file,
                    focus_override="Wrong Preposition After A Verb")

    assert result.focus.category == "Wrong Preposition After A Verb"
    assert "overriding" in result.focus.reason


def test_an_untracked_override_is_flagged(tmp_path, memory_file):
    result = _build(tmp_path, memory_path=memory_file, focus_override="Something Invented")

    assert any("not a tracked persistent pattern" in note for note in result.notes)


def test_the_command_it_prints_can_actually_be_run(tmp_path, memory_file):
    """Category names contain double quotes of their own, so the copy-pasteable
    `practice add` line has to be quoted for a shell, not just wrapped."""
    import shlex

    result = _build(tmp_path, memory_path=memory_file, focus_override=QUOTED_CATEGORY)
    line = next(line for line in brief.format_brief(result).splitlines()
                if "practice end" in line)

    assert QUOTED_CATEGORY in shlex.split(line.rstrip("\\"))


# --- the drill block (P19) ----------------------------------------------------

DRILL = """\
name: {name}
category: {category}
target: a target
items:
  - prompt: he / teacher
    example: He is a teacher.
    wrong: He is teacher.
    attempted: he is
    correct: he is a
  - prompt: she / doctor
    example: She is a doctor.
    wrong: She is doctor.
    attempted: she is
    correct: she is a
"""


def _drills(tmp_path: Path, **names) -> Path:
    directory = tmp_path / "drills"
    directory.mkdir(exist_ok=True)
    for name, category in names.items():
        (directory / f"{name}.yaml").write_text(
            DRILL.format(name=name, category=category), encoding="utf-8")
    return directory


def test_the_block_runs_even_when_the_focus_has_no_drill(tmp_path, memory_file):
    """The old reading of P19 skipped the block entirely in this case, which
    left those sessions with nothing scored at all."""
    _drills(tmp_path, other="Wrong Preposition After A Verb")
    (tmp_path / "log.md").write_text(FOCUS_LOG, encoding="utf-8")

    result = _build(tmp_path, memory_path=memory_file)

    assert result.focus.category == QUOTED_CATEGORY and result.focus.drill is None
    assert result.block and result.block.prompts
    assert any("still runs" in note for note in result.notes)


def test_the_block_is_written_where_score_will_look_for_it(tmp_path, memory_file):
    from voxlib import drill as drill_module

    _drills(tmp_path, recipient=QUOTED_CATEGORY)
    (tmp_path / "log.md").write_text(FOCUS_LOG, encoding="utf-8")

    result = _build(tmp_path, memory_path=memory_file)
    pending = drill_module.read_mixed_pending(tmp_path / "pending.json")

    assert result.focus.drill == "recipient"
    assert pending and len(pending) == len(result.block.prompts)


def test_replacing_an_unscored_block_is_said_out_loud(tmp_path, memory_file):
    _drills(tmp_path, recipient=QUOTED_CATEGORY)
    _build(tmp_path, memory_path=memory_file)

    second = _build(tmp_path, memory_path=memory_file)

    assert any("replaced" in note for note in second.notes)


def test_no_drill_leaves_the_pending_file_alone(tmp_path, memory_file):
    _drills(tmp_path, recipient=QUOTED_CATEGORY)

    result = _build(tmp_path, memory_path=memory_file, with_block=False)

    assert result.block is None
    assert not (tmp_path / "pending.json").exists()
