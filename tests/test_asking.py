"""
Checks on Question Practice Mode's content.

`asking/` is the learner's own, the same way `drills/` and `analysis/` are: the
scenarios are written from situations that actually happened to them and the
`trap` lines are reconstructions of their own errors. So it is gitignored and
absent on a fresh clone — absent is fine here, broken is not, which is the rule
`test_local_drills_load_and_have_distinct_names` already follows for drills.

The committed example lives in `tests/fixtures/asking/`, is invented, and is what
these checks run against unconditionally. Everything that can be checked without
reading the learner's content is checked there; the real directories are checked
too whenever they happen to exist.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from voxlib.drill import load_all, load_drill, normalize

REPO_ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "asking"

# The learner's own content, when it is there at all.
ASKING_DRILLS = REPO_ROOT / "asking" / "drills"
ASKING_SCENARIOS = REPO_ROOT / "asking" / "scenarios"

# Q13 asks six prompts. A pool barely larger than one block stops testing the
# pattern and starts testing the list — the bound asking/README.txt states. It
# applies to a real pool; the fixture is deliberately smaller than a session.
MIN_ITEMS = 15


def _drill_files(*directories: Path) -> list[Path]:
    return [p for d in directories if d.is_dir() for p in sorted(d.glob("*.yaml"))]


def _scenario_files(*directories: Path) -> list[Path]:
    return [p for d in directories if d.is_dir() for p in sorted(d.glob("*.yaml"))]


def _scenarios(*directories: Path) -> list[tuple[Path, dict]]:
    out = []
    for path in _scenario_files(*directories):
        pack = yaml.safe_load(path.read_text(encoding="utf-8"))
        out.extend((path, s) for s in pack["scenarios"])
    return out


ALL_DRILLS = _drill_files(FIXTURES / "drills", ASKING_DRILLS)
ALL_SCENARIOS = _scenarios(FIXTURES / "scenarios", ASKING_SCENARIOS)


def test_the_committed_example_is_there():
    """The fixture is the only content guaranteed to exist, so it is the only
    thing whose absence is a failure rather than a fresh clone."""
    assert _drill_files(FIXTURES / "drills"), "no fixture question drill"
    assert _scenarios(FIXTURES / "scenarios"), "no fixture scenario pack"


@pytest.mark.parametrize("path", ALL_DRILLS, ids=lambda p: f"{p.parent.parent.name}/{p.stem}")
def test_question_drill_loads_and_is_named_after_its_file(path):
    """The mode invokes a drill by filename; a name that disagrees with the file
    is one the model can print and nobody can run."""
    drill = load_drill(path)

    assert drill.name == path.stem, f"{path.name} declares name: {drill.name}"


@pytest.mark.parametrize("path", _drill_files(ASKING_DRILLS), ids=lambda p: p.stem)
def test_a_real_pool_is_several_times_a_session(path):
    drill = load_drill(path)

    assert len(drill.items) >= MIN_ITEMS, (
        f"{drill.name} has {len(drill.items)} items — too close to one block of 6"
    )


@pytest.mark.parametrize("path", ALL_DRILLS, ids=lambda p: f"{p.parent.parent.name}/{p.stem}")
def test_every_item_scores_its_own_example_and_counter_example(path):
    """
    The two regexes are the whole scoring mechanism, and a wrong one fails
    silently: `attempted` that misses reports a correct answer as "not heard",
    and `correct` that also matches the counter-example scores the mistake as a
    pass. Both are invisible until a trend has been built out of them.

    This is not hypothetical. Written first as a second copy of `wrong`, these
    patterns missed three of the four answers in the mode's first session — the
    errors each item existed to catch were exactly the ones it could not see.
    """
    for item in load_drill(path).items:
        example, wrong = normalize(item.example), normalize(item.wrong)

        assert item.attempted.search(example), f"`attempted` misses its own example: {item.example}"
        assert item.attempted.search(wrong), f"`attempted` misses its counter-example: {item.wrong}"
        assert item.correct.search(example), f"`correct` misses its own example: {item.example}"
        assert not item.correct.search(wrong), f"`correct` accepts the mistake: {item.wrong}"


def test_the_question_pool_stays_out_of_the_grammar_pool():
    """
    Question drills live in `asking/drills` so that a Conversation Practice
    Mode block never draws one — the two modes track different skills into
    different histories, and `load_all` not recursing is what keeps them apart.
    A question drill copied into `drills/` would quietly join the grammar
    ranking.
    """
    grammar = {d.name for d in load_all(REPO_ROOT / "drills")}
    questions = {d.name for d in load_all(ASKING_DRILLS)} if ASKING_DRILLS.is_dir() else set()

    assert not grammar & questions, f"these drills are in both pools: {sorted(grammar & questions)}"


@pytest.mark.parametrize("path,scenario", ALL_SCENARIOS, ids=[s["name"] for _, s in ALL_SCENARIOS])
def test_scenario_has_everything_a_session_reads(path, scenario):
    for key in ("name", "function", "register", "situation", "ask_for", "reply", "criteria"):
        assert scenario.get(key), f"{path.name}: {scenario.get('name')} has no {key}"


@pytest.mark.parametrize("path,scenario", ALL_SCENARIOS, ids=[s["name"] for _, s in ALL_SCENARIOS])
def test_scenario_criteria_are_scorable_and_include_the_follow_up(path, scenario):
    """
    Q10 scores a scenario against these, so each one has to be a yes/no call and
    there have to be few enough that the same rubric is applied the same way
    twice. Q11 depends on the follow-up being one of them: accepting the first
    answer is the default behaviour, and a rubric without that line lets it pass
    unremarked.
    """
    criteria = scenario["criteria"]
    name = scenario["name"]

    assert 3 <= len(criteria) <= 4, f"{name} has {len(criteria)} criteria — Q10 asks for three or four"
    for criterion in criteria:
        assert criterion.get("id") and criterion.get("check"), f"{name} has an incomplete criterion"

    assert any(c["id"] == "followup" for c in criteria), f"{name} does not score the follow-up"


def test_scenario_names_are_unique():
    """Q12 tracks what has been run by name, in `asking_memory.md`. Two
    scenarios sharing one would merge into a single row."""
    names = [s["name"] for _, s in ALL_SCENARIOS]

    assert len(set(names)) == len(names), "two scenarios share a name"


def test_the_form_criterion_is_generic_everywhere():
    """
    `form` was originally written per scenario, naming the error each one
    expected. It passed vacuously the first time a scenario failed: the one it
    predicted never came up, and the error that did arrive was covered by no
    criterion and got charged to `register` instead.

    So it is one string, identical in every scenario — fixture and real alike —
    and the specific patterns live in the drills, which exist to test exactly one
    thing and have an answer key. A per-scenario `form` is the shape of the bug.
    """
    checks = {c["check"] for _, s in ALL_SCENARIOS for c in s["criteria"] if c["id"] == "form"}

    assert len(checks) == 1, f"`form` is worded {len(checks)} different ways — it should be one"


@pytest.mark.parametrize("path,scenario", ALL_SCENARIOS, ids=[s["name"] for _, s in ALL_SCENARIOS])
def test_register_does_not_score_grammar(path, scenario):
    """
    `register` is about intent and directness only. When it also covered
    phrasing, one form error cost two criteria — the same mistake counted
    twice, and the score stopped saying which half went wrong.
    """
    grammar_words = ("word order", "auxiliary", "article", "tense", "well-formed",
                     "well formed", "preposition", "-ing", "if-clause")

    check = next(c["check"] for c in scenario["criteria"] if c["id"] == "register")
    leaked = [w for w in grammar_words if w in check.lower()]

    assert not leaked, f"{scenario['name']}: `register` mentions grammar {leaked}"


def test_a_real_pack_covers_more_than_one_register():
    """Q12: five peer-level work scenarios train less than one peer, one manager
    and one stranger — the grammar is identical and the calibration is what
    differs. Only meaningful for a real pack; the fixture has two scenarios."""
    real = _scenarios(ASKING_SCENARIOS)
    if not real:
        pytest.skip("asking/scenarios is the learner's own and absent on a fresh clone")

    registers = {s["register"] for _, s in real}

    assert len(registers) >= 4, f"only these registers are covered: {sorted(registers)}"
