"""
Checks on the project's own documents, not its code.

Both of these guard drift that actually happened while this suite was being
written: a setting added to the CLI but not to config.example.yaml, and a rule
inserted into CLAUDE.md that broke the numbering and left the cross-references
pointing at the wrong rules. Neither is a code bug, so nothing else catches
them — but CLAUDE.md is an executable instruction for the analysis workflow,
and a reference to the wrong rule quietly changes what that workflow does.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from voxlib.config import ALLOWED_KEYS, load_config

REPO_ROOT = Path(__file__).parent.parent
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"


def test_config_example_is_valid_and_complete():
    """
    Every setting the config file accepts should appear in the example — it's
    the only place a user finds out a setting exists, and an unlisted one is
    invisible. Passing it through load_config also proves the example itself
    survives validation.
    """
    example = load_config(REPO_ROOT / "config.example.yaml")

    missing = ALLOWED_KEYS - set(example)
    assert not missing, f"config.example.yaml is missing: {sorted(missing)}"


def _general_rules_section() -> str:
    text = CLAUDE_MD.read_text(encoding="utf-8")
    start = text.index("# General rules")
    end = text.index("# Workflow: when asked to analyze a new recording")
    return text[start:end]


def _numbered_rules() -> list[int]:
    return [int(n) for n in re.findall(r"^(\d+)\. ", _general_rules_section(), flags=re.M)]


def test_general_rules_are_numbered_contiguously():
    """Inserting a rule mid-list is easy to get wrong — it happened, leaving
    two rules numbered 4 and every later reference off by one."""
    numbers = _numbered_rules()

    assert numbers, "no numbered rules found — did the section heading change?"
    assert numbers == list(range(1, len(numbers) + 1)), f"rule numbering is not 1..N: {numbers}"


def test_every_rule_cross_reference_points_at_a_rule_that_exists():
    text = CLAUDE_MD.read_text(encoding="utf-8")
    highest = max(_numbered_rules())

    referenced = {int(n) for n in re.findall(r"(?:General rule|rule) (\d+)", text)}

    dangling = {n for n in referenced if not 1 <= n <= highest}
    assert not dangling, f"CLAUDE.md references rules that don't exist: {sorted(dangling)}"


def test_the_practice_rules_preamble_states_the_right_range():
    """
    The P1-P18 block explains that it's numbered that way so it can't collide
    with the general rules `1`-`N`. That N was already stale once (it said 13
    when there were 14), which is exactly the confusion the note exists to
    prevent.
    """
    text = CLAUDE_MD.read_text(encoding="utf-8")
    highest = max(_numbered_rules())

    match = re.search(r"`1`–`(\d+)` above", text)
    assert match, "the P-rules preamble no longer states a general-rules range"
    assert int(match.group(1)) == highest, (
        f"the preamble says the general rules run to {match.group(1)}, but there are {highest}"
    )


@pytest.mark.parametrize("filename", ["transcript_clean.txt", "transcript_annotated.txt",
                                      "lines.json", "fluency.json"])
def test_claude_md_knows_about_every_file_the_pipeline_writes(filename):
    """The workflow archives and reads these by name; a file the pipeline
    produces but CLAUDE.md never mentions won't be archived, and the session
    can't be re-measured later."""
    assert filename in CLAUDE_MD.read_text(encoding="utf-8"), (
        f"CLAUDE.md never mentions {filename}, which run_pipeline writes"
    )


def test_claude_md_tells_the_workflow_to_read_the_drill_history():
    """
    Same reasoning as the fluency columns below: a measurement nothing instructs
    the analysis to look at may as well not exist. Drills are the only score
    here with a known denominator, and a workflow that never opens them would
    keep ranking mistakes on rates alone.
    """
    text = CLAUDE_MD.read_text(encoding="utf-8")

    assert "voxlib.drill" in text, "CLAUDE.md never tells the workflow to run a drill"
    assert "drills.csv" in text, "CLAUDE.md never tells the workflow to read drill results"


def test_the_readme_tells_a_person_how_to_use_drills():
    """
    CLAUDE.md is instructions for the model and drills/README.txt is the file
    format; neither tells a person how to reach the feature. `next` and `score`
    are deliberately absent here — those are run by the model inside a practice
    session, and documenting them as user commands is how the workflow grew an
    errand nobody wanted to perform.
    """
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    assert "let's practice" in readme, "README.md never says how to start a drill"
    missing = [c for c in ("list", "items") if f"python -m voxlib.drill {c}" not in readme]
    assert not missing, f"README.md documents no `drill {missing}` for reading your own data"


def test_local_drills_load_and_have_distinct_names():
    """
    The workflow names drills by filename; a drill that doesn't load is one the
    report can point at and the owner can't run.

    `drills/` holds content built from the owner's own mistakes, so it is
    gitignored and empty on a fresh clone — absent is fine here, broken is not.
    """
    from voxlib import drill

    drills = drill.load_all(REPO_ROOT / "drills")

    assert len({d.name for d in drills}) == len(drills), "two drills share a name"


@pytest.mark.parametrize("column", ["low_confidence_word_share", "fillers_per_100_words",
                                    "discourse_markers_per_100_words", "words_per_minute"])
def test_claude_md_tells_the_workflow_to_read_every_measured_column(column):
    """
    A measurement nothing instructs the analysis to look at may as well not
    exist: the pipeline would keep writing it to fluency_history.csv every
    session and no report would ever mention it. Step 4 is where the workflow
    is told which columns to read, so a new metric has to reach that list.
    """
    from voxlib.fluency import HISTORY_COLUMNS

    assert column in HISTORY_COLUMNS, f"{column} is no longer a measured column"
    assert column in CLAUDE_MD.read_text(encoding="utf-8"), (
        f"the pipeline measures {column} but CLAUDE.md never tells the workflow to read it"
    )


def test_practice_mode_is_told_to_record_the_session_it_just_ran():
    """
    Same reasoning as the drill history above, one rung down. Typed practice is
    the only measurement of attended production, and a file nothing instructs the
    model to write stays empty — which is how the mode ran for two weeks
    recording only the date it had run on.
    """
    text = CLAUDE_MD.read_text(encoding="utf-8")

    assert "voxlib.practice" in text, "CLAUDE.md never tells practice mode to record a session"
    assert "practice_history.csv" in text, "CLAUDE.md never names the practice history"


def test_the_personal_data_files_are_all_gitignored():
    """
    Every history under analysis/ is the owner's own speech data, and this repo
    may be public. A new one is easy to add to CLAUDE.md and forget here.
    """
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    for name in ("memory.md", "mistakes.csv", "scores_history.csv", "fluency_history.csv",
                 "drills.csv", "drill_items.csv", "practice_history.csv",
                 "conversation_focus_log.md"):
        assert f"analysis/{name}" in ignored, f"analysis/{name} would be committed"
