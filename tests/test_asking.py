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


# --- the module that runs the session ----------------------------------------
#
# Everything above checks the *content*. What follows checks `voxlib.asking`,
# which reads that content and does the selecting and recording Q2, Q12 and Q16
# used to ask for by hand.

from voxlib import asking  # noqa: E402


def _scenario(name: str, register: str, criteria: int = 4) -> asking.Scenario:
    return asking.Scenario(
        name=name, pack="p", setting="work", register=register, function="f",
        situation="s", ask_for="one question", reply="r", holds_back="h",
        criteria=[asking.Criterion(f"c{i}", "check") for i in range(criteria)],
        trap="t")


def test_a_pack_loads_with_everything_a_session_reads():
    scenarios = asking.load_pack(FIXTURES / "scenarios" / "invented.yaml")

    assert scenarios, "the fixture pack loaded as empty"
    first = scenarios[0]
    assert first.pack == "invented" and first.register
    assert first.situation and first.reply and first.holds_back and first.trap
    assert {c.id for c in first.criteria} >= {"form", "function", "register", "followup"}


def test_never_run_scenarios_come_first():
    pool = [_scenario("old", "peer"), _scenario("new", "manager")]
    history = [asking.ScenarioRun(date="2026-01-01", scenario="old", criteria_met=4,
                                  criteria_total=4)]

    chosen = asking.choose_scenarios(pool, history, count=2)

    assert [c.scenario.name for c in chosen] == ["new", "old"]


def test_a_scenario_that_failed_outranks_one_that_was_clean():
    pool = [_scenario("clean", "peer"), _scenario("failed", "manager")]
    history = [
        asking.ScenarioRun(date="2026-01-01", scenario="clean", criteria_met=4,
                           criteria_total=4),
        asking.ScenarioRun(date="2026-01-01", scenario="failed", criteria_met=2,
                           criteria_total=4, failed=["register"]),
    ]

    chosen = asking.choose_scenarios(pool, history, count=1)

    assert chosen[0].scenario.name == "failed"
    assert "register" in chosen[0].reason


def test_registers_are_varied_before_a_second_one_is_taken():
    """Q12: five peer-level scenarios train less than one peer, one manager and
    one stranger — so the pass takes a register before it takes a repeat."""
    pool = [_scenario("peer-a", "peer"), _scenario("peer-b", "peer"),
            _scenario("boss", "manager")]

    chosen = asking.choose_scenarios(pool, [], count=2)

    assert {c.scenario.register for c in chosen} == {"peer", "manager"}


def test_a_small_pool_still_fills_the_session():
    """Variety is a preference, not a reason to run three scenarios when five
    were asked for."""
    pool = [_scenario("a", "peer"), _scenario("b", "peer"), _scenario("c", "peer")]

    chosen = asking.choose_scenarios(pool, [], count=3)

    assert len(chosen) == 3


def test_last_sessions_clean_scenario_is_ranked_last():
    pool = [_scenario("yesterday", "peer"), _scenario("older", "peer")]
    history = [
        asking.ScenarioRun(date="2026-01-01", scenario="older", criteria_met=4,
                           criteria_total=4),
        asking.ScenarioRun(date="2026-02-01", scenario="yesterday", criteria_met=4,
                           criteria_total=4),
    ]

    chosen = asking.choose_scenarios(pool, history, count=2)

    assert [c.scenario.name for c in chosen] == ["older", "yesterday"]


def test_a_result_takes_its_denominator_from_the_scenario():
    pool = {"lib": _scenario("lib", "stranger", criteria=4)}

    run = asking.parse_run("lib:3:register,followup", pool, "2026-03-01")

    assert (run.criteria_met, run.criteria_total) == (3, 4)
    assert run.failed == ["register", "followup"]
    assert run.register == "stranger"


def test_a_result_for_an_unknown_scenario_needs_its_own_total():
    with pytest.raises(ValueError, match="no criteria count"):
        asking.parse_run("gone:3", {}, "2026-03-01")

    run = asking.parse_run("gone:3/4", {}, "2026-03-01")
    assert run.criteria_total == 4


def test_more_criteria_met_than_exist_is_refused():
    with pytest.raises(ValueError, match="not possible"):
        asking.parse_run("lib:5/4", {}, "2026-03-01")


def test_runs_survive_a_write_and_a_read(tmp_path):
    path = tmp_path / "asking_scenarios.csv"
    runs = [asking.ScenarioRun(date="2026-03-01", scenario="lib", pack="p",
                               register="stranger", function="f", criteria_met=3,
                               criteria_total=4, failed=["register", "followup"])]

    asking.record_runs(path, runs)
    back = asking.load_history(path)

    assert len(back) == 1
    assert back[0].failed == ["register", "followup"]
    assert back[0].score == "3/4"


def test_the_log_tables_get_this_sessions_rows(tmp_path):
    """Q16's two tables are generated from the same results the CSV row is built
    from, so they cannot disagree with it."""
    path = tmp_path / "asking_memory.md"
    path.write_text(
        "# Question Practice Memory\n\n## Scenario log\n\n"
        "| Date | Scenario | Criteria met | Failed |\n|---|---|---|---|\n"
        "| 2026-01-01 | old | 4/4 | — |\n\n"
        "## Session history\n\n"
        "| Date | Scenarios | Criteria met | Drill score | Biggest problem |\n"
        "|---|---|---|---|---|\n", encoding="utf-8")

    written = asking.append_log_rows(
        path, date="2026-03-01",
        runs=[asking.ScenarioRun(date="2026-03-01", scenario="lib", criteria_met=3,
                                 criteria_total=4, failed=["register"])],
        drill_score="4/6", biggest_problem="Question Register And Softening Frames")

    text = path.read_text(encoding="utf-8")
    assert written
    assert "| 2026-03-01 | lib | 3/4 | register |" in text
    assert "| 2026-03-01 | 1 | 3/4 | 4/6 | Question Register And Softening Frames |" in text
    assert "| 2026-01-01 | old | 4/4 | — |" in text, "the row already there was lost"


def test_a_tracker_without_the_tables_is_left_alone(tmp_path):
    path = tmp_path / "asking_memory.md"
    path.write_text("# Question Practice Memory\n\n## Patterns\n", encoding="utf-8")

    assert not asking.append_log_rows(path, date="2026-03-01", runs=[])
    assert "2026-03-01" not in path.read_text(encoding="utf-8")


def test_the_memory_digest_finds_the_pattern_to_watch(tmp_path):
    path = tmp_path / "asking_memory.md"
    path.write_text(
        "# Question Practice Memory\n\n## Patterns\n\n"
        "### Embedded Question Word Order\n\nStatus: Active\nSessions with an error: 1\n"
        "Last error: 2026-01-01\nTypical examples:\nNotes: repaired on the first flag.\n\n"
        "### Question Register And Softening Frames\n\nStatus: Active\n"
        "Sessions with an error: 3\nLast error: 2026-02-01\nNotes: **over-hedging** plus a "
        "broad request.\n\n"
        "## Register notes\n\n**Peer, low stakes — fine.** Nothing to add.\n\n"
        "Prose with no lead.\n", encoding="utf-8")

    memory = asking.parse_memory(path)

    assert memory.usable
    assert memory.worst.name == "Question Register And Softening Frames"
    assert "broad request" in memory.worst.note
    assert memory.register_notes == ["Peer, low stakes — fine."]


def test_a_missing_tracker_is_not_fatal(tmp_path):
    memory = asking.parse_memory(tmp_path / "nothing.md")

    assert not memory.usable and memory.patterns == []
