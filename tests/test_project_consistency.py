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
