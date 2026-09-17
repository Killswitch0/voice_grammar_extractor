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

# The instructions are three skills plus the file that dispatches to them. They
# were one document until the modes were split apart: a practice session was
# loading the recording workflow and both other rule sets before it could ask a
# question, which is thousands of tokens of instruction for a mode that will
# never run. Splitting them means a check that used to read one file now has to
# say *which* file — the numbering lives in one skill each, while "is this
# measurement instructed anywhere" spans all four.
SKILLS = REPO_ROOT / ".claude" / "skills"
ANALYZE = SKILLS / "analyze-recording" / "SKILL.md"
PRACTICE = SKILLS / "practice-answer" / "SKILL.md"
ASKING = SKILLS / "practice-asking" / "SKILL.md"
INSTRUCTIONS = [CLAUDE_MD, ANALYZE, PRACTICE, ASKING]


def _instructions() -> str:
    """Every instruction the model is ever given, as one string."""
    return "\n".join(path.read_text(encoding="utf-8") for path in INSTRUCTIONS)


@pytest.mark.parametrize("path", INSTRUCTIONS, ids=lambda p: p.parent.name)
def test_every_instruction_file_is_there(path):
    """A skill that doesn't exist is a mode with no rules: the trigger phrase
    still works and the session runs on whatever the model remembers."""
    assert path.exists(), f"{path} is missing"


@pytest.mark.parametrize("path", [ANALYZE, PRACTICE, ASKING],
                         ids=lambda p: p.parent.name)
def test_every_skill_declares_itself(path):
    """Without the frontmatter the skill is never offered, and the mode is
    unreachable however well the rules inside it are written."""
    text = path.read_text(encoding="utf-8")

    assert text.startswith("---\n"), f"{path} has no frontmatter"
    head = text.split("---", 2)[1]
    assert f"name: {path.parent.name}" in head, f"{path} is named after another directory"
    assert "description:" in head, f"{path} has no description, so nothing triggers it"


def test_claude_md_dispatches_to_every_mode():
    """CLAUDE.md is the only thing always in context; if it doesn't name the
    skills, nothing routes a request to them."""
    text = CLAUDE_MD.read_text(encoding="utf-8")

    for skill in ("analyze-recording", "practice-answer", "practice-asking"):
        assert skill in text, f"CLAUDE.md never mentions the {skill} skill"


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
    text = ANALYZE.read_text(encoding="utf-8")
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
    text = _instructions()
    highest = max(_numbered_rules())

    referenced = {int(n) for n in re.findall(r"(?:General rule|rule) (\d+)", text)}

    dangling = {n for n in referenced if not 1 <= n <= highest}
    assert not dangling, f"the instructions reference rules that don't exist: {sorted(dangling)}"


def test_the_practice_rules_preamble_states_the_right_range():
    """
    The P-rules block explains that it's numbered that way so it can't collide
    with the general rules `1`-`N`. That N was already stale once (it said 13
    when there were 14), which is exactly the confusion the note exists to
    prevent — and now that the rule sets are in separate files, nothing but this
    check ever puts the two numbers side by side.
    """
    text = PRACTICE.read_text(encoding="utf-8")
    highest = max(_numbered_rules())

    match = re.search(r"run `1`–`(\d+)`", text)
    assert match, "the P-rules preamble no longer states a general-rules range"
    assert int(match.group(1)) == highest, (
        f"the preamble says the general rules run to {match.group(1)}, but there are {highest}"
    )


@pytest.mark.parametrize("filename", ["transcript_clean.txt", "transcript_annotated.txt",
                                      "lines.json", "fluency.json"])
def test_the_instructions_know_about_every_file_the_pipeline_writes(filename):
    """The workflow archives and reads these by name; a file the pipeline
    produces but nothing mentions won't be archived, and the session can't be
    re-measured later."""
    assert filename in _instructions(), (
        f"nothing in the instructions mentions {filename}, which run_pipeline writes"
    )


def test_the_workflow_is_told_to_read_the_drill_history():
    """
    Same reasoning as the fluency columns below: a measurement nothing instructs
    the analysis to look at may as well not exist. Drills are the only score
    here with a known denominator, and a workflow that never opens them would
    keep ranking mistakes on rates alone.
    """
    text = ANALYZE.read_text(encoding="utf-8")

    assert "voxlib.drill" in text, "the workflow is never told to read a drill"
    assert "drills.csv" in text, "the workflow is never told to read drill results"


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
def test_the_workflow_is_told_to_read_every_measured_column(column):
    """
    A measurement nothing instructs the analysis to look at may as well not
    exist: the pipeline would keep writing it to fluency_history.csv every
    session and no report would ever mention it. Step 4 is where the workflow
    is told which columns to read, so a new metric has to reach that list.
    """
    from voxlib.fluency import HISTORY_COLUMNS

    assert column in HISTORY_COLUMNS, f"{column} is no longer a measured column"
    assert column in ANALYZE.read_text(encoding="utf-8"), (
        f"the pipeline measures {column} but the workflow is never told to read it"
    )


def test_practice_mode_is_told_to_record_the_session_it_just_ran():
    """
    Same reasoning as the drill history above, one rung down. Typed practice is
    the only measurement of attended production, and a file nothing instructs the
    model to write stays empty — which is how the mode ran for two weeks
    recording only the date it had run on.
    """
    text = PRACTICE.read_text(encoding="utf-8")

    assert "voxlib.practice" in text, "practice mode is never told to record a session"
    assert "practice_history.csv" in text, "the practice history is never named"


def test_the_personal_data_files_are_all_gitignored():
    """
    Every history under analysis/ is the owner's own speech data, and this repo
    may be public. A new one is easy to add to CLAUDE.md and forget here.
    """
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    for name in ("memory.md", "mistakes.csv", "scores_history.csv", "fluency_history.csv",
                 "lexis_history.csv", "level_history.csv",
                 "drills.csv", "drill_items.csv", "practice_history.csv",
                 "conversation_focus_log.md", "asking_memory.md", "asking_archive.md",
                 "asking_drills.csv", "asking_drill_items.csv", "asking_pending.json",
                 "asking_scenarios.csv"):
        assert f"analysis/{name}" in ignored, f"analysis/{name} would be committed"


def test_the_content_directories_built_from_the_owners_mistakes_are_gitignored():
    """
    `drills/` and `asking/` are not code with the user's data beside it — the
    content *is* the data. A drill's prompts are reconstructions of sentences the
    owner said; a scenario's `trap` is a reconstruction of an error they make, and
    its situations are the ones that actually happened to them. Both directories
    were nearly committed on the grounds that the content "looked generic", which
    is a judgement that does not survive the next file added to them.

    Only each README is committed, because it documents the format.
    """
    ignored = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")

    for directory in ("drills", "asking"):
        assert f"{directory}/*" in ignored, f"{directory}/ would be committed"
        assert f"!{directory}/README.txt" in ignored, (
            f"{directory}/README.txt is ignored too, so the format is documented nowhere"
        )


def _question_rules() -> list[int]:
    text = ASKING.read_text(encoding="utf-8")
    return [int(n) for n in re.findall(r"^Q(\d+)\. ", text, flags=re.M)]


def test_question_rules_are_numbered_contiguously():
    """Same guard as the general rules: inserting a Q rule mid-list is exactly
    where the numbering breaks, and every cross-reference in that section is by
    number."""
    numbers = _question_rules()

    assert numbers, "no Q rules found — did the section heading change?"
    assert numbers == list(range(1, len(numbers) + 1)), f"Q numbering is not 1..N: {numbers}"


def test_the_practice_preamble_states_the_right_question_rule_range():
    """The P-rule preamble tells the reader which other rule sets exist so a bare
    number is never ambiguous. It was already stale once for the general rules."""
    text = PRACTICE.read_text(encoding="utf-8")
    highest = max(_question_rules())

    match = re.search(r"runs `Q1`–`Q(\d+)`", text)
    assert match, "the P-rules preamble no longer states a question-rules range"
    assert int(match.group(1)) == highest, (
        f"the preamble says the question rules run to {match.group(1)}, but there are {highest}"
    )


def test_question_practice_mode_is_told_to_record_the_session_it_just_ran():
    """Same reasoning as the drill and practice histories: a mode that measures
    something and writes it nowhere leaves no trend, and this one is the only
    measurement of questions the owner produced."""
    text = ASKING.read_text(encoding="utf-8")

    for name in ("asking/drills", "asking/scenarios", "asking_memory.md",
                 "asking_drills.csv", "asking_pending.json", "asking_scenarios.csv"):
        assert name in text, f"the mode is never told about {name}, which it needs"

    # Without this flag the row lands in the answering-mode denominator, where a
    # dozen short questions understate every typed rate. The column can only be
    # right if the command that writes it says so.
    assert "--mode ask" in text, "Q14 never passes --mode ask, so asking rows would pool"
