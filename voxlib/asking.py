"""
Question Practice Mode's content, its session brief, and its scenario history.

The mode had the same problem `voxlib.brief` was written for, one mode over.
Before a single question could be asked, three files were read by hand — a
memory document that had grown past 270 lines, and every scenario pack in
`asking/scenarios/`, in full, to pick four to six of them against a selection
rule (Q12) and a scenario log kept as prose. That is several thousand tokens and
several minutes spent on selection, in a mode whose entire value is the exchange
afterwards. The friction sits at the *start*, which is exactly where rule 19's
budget gets lost: a session that takes minutes to open is a session that doesn't
happen.

So this module does for asking what the brief does for answering — reads the
sources once, applies Q12 arithmetically, and prints everything the first
message needs.

It also gives the mode the one thing it never had: a machine-readable record of
which scenarios have run and how they scored. Q12 says to prefer scenarios never
run before and then the ones whose criteria failed last time, and both facts
lived in a markdown table that had to be read and matched by eye. A CSV answers
it in one pass, and the markdown table becomes a rendering of the CSV rather than
the record itself — the same division `mistakes.csv` and `memory.md` already
have, and for the same reason: prose rewritten from its own previous prose loses
things.

What this deliberately does not do is score anything. A scenario's answer space
is open — that is why Q10 scores against written criteria rather than patterns —
so the yes/no calls are made in the conversation and passed in. This only records
them.
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from voxlib import csvfile

logger = logging.getLogger(__name__)

# One row per scenario run. `failed` holds the criterion ids that were missed,
# semicolon-separated, because that is what Q12 reads to bring a scenario back.
HISTORY_COLUMNS = ["date", "scenario", "pack", "register", "function",
                   "criteria_met", "criteria_total", "failed"]

_FAILED_SEPARATOR = ";"

# Q12: four to six scenarios a session, mixed by register — drawn at the bottom
# of that range rather than the middle. Every session on record ran two, so a
# fifth scenario printed in full is a scenario nobody reaches, and the brief pays
# about a kilobyte for it. Four leaves slack over what has ever been used and
# `--scenarios 6` is there for a session with time in it.
#
# Below four is a different thing and not an economy: three registers is the
# least that trains the calibration this mode exists for, and eight criteria is
# already a thin denominator to read a session by.
DEFAULT_SCENARIOS = 4

# How much of a pattern's `Notes:` prose the digest carries. Enough for the note
# to mean something, short enough that the digest stays a digest — the full text
# is one file read away when a correction needs it.
NOTE_CHARS = 240


# --- the content --------------------------------------------------------------

@dataclass
class Criterion:
    id: str
    check: str


@dataclass
class Scenario:
    name: str
    pack: str
    setting: str
    register: str
    function: str
    situation: str
    ask_for: str
    reply: str
    holds_back: str
    criteria: list[Criterion]
    trap: str

    @property
    def criteria_total(self) -> int:
        return len(self.criteria)


def load_pack(path: Path) -> list[Scenario]:
    """One YAML file — a pack — as scenarios carrying their pack's own fields."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    pack = data.get("pack") or path.stem
    setting = data.get("setting", "")
    out = []
    for entry in data.get("scenarios") or []:
        out.append(Scenario(
            name=entry.get("name", ""),
            pack=pack,
            setting=setting,
            register=entry.get("register", ""),
            function=entry.get("function", ""),
            situation=(entry.get("situation") or "").strip(),
            ask_for=(entry.get("ask_for") or "").strip(),
            reply=(entry.get("reply") or "").strip(),
            holds_back=(entry.get("holds_back") or "").strip(),
            criteria=[Criterion(c.get("id", ""), (c.get("check") or "").strip())
                      for c in entry.get("criteria") or []],
            trap=(entry.get("trap") or "").strip(),
        ))
    return out


def load_scenarios(directory: Path) -> list[Scenario]:
    """Every pack in a directory. A pack that won't parse is skipped, not fatal —
    a session should still run on the rest (the same rule the brief follows for
    a missing file)."""
    if not directory.is_dir():
        return []
    found: list[Scenario] = []
    for path in sorted(directory.glob("*.yaml")):
        try:
            found.extend(load_pack(path))
        except Exception:
            logger.warning("Could not read the scenario pack %s; skipping it", path,
                           exc_info=True)
    return found


# --- the run history ----------------------------------------------------------

@dataclass
class ScenarioRun:
    date: str
    scenario: str
    pack: str = ""
    register: str = ""
    function: str = ""
    criteria_met: int = 0
    criteria_total: int = 0
    failed: list[str] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.failed

    @property
    def score(self) -> str:
        return f"{self.criteria_met}/{self.criteria_total}"


def load_history(path: Path) -> list[ScenarioRun]:
    """Every scenario run on record, oldest first."""
    if not path.exists():
        return []
    runs = []
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        try:
            runs.append(ScenarioRun(
                date=row["date"],
                scenario=row["scenario"],
                pack=row.get("pack", ""),
                register=row.get("register", ""),
                function=row.get("function", ""),
                criteria_met=int(row.get("criteria_met") or 0),
                criteria_total=int(row.get("criteria_total") or 0),
                failed=[f for f in (row.get("failed") or "").split(_FAILED_SEPARATOR) if f],
            ))
        except (KeyError, ValueError):
            logger.warning("Skipping an unreadable row in %s: %r", path, row)
    runs.sort(key=lambda r: r.date)
    return runs


def record_runs(path: Path, runs: list[ScenarioRun]) -> None:
    """Append this session's scenarios. Append-only, like every history here."""
    csvfile.append(path, HISTORY_COLUMNS, [{
        "date": run.date,
        "scenario": run.scenario,
        "pack": run.pack,
        "register": run.register,
        "function": run.function,
        "criteria_met": run.criteria_met,
        "criteria_total": run.criteria_total,
        "failed": _FAILED_SEPARATOR.join(run.failed),
    } for run in runs])


def parse_run(spec: str, scenarios: dict[str, Scenario], date: str) -> ScenarioRun:
    """
    `name:met/total:failed,ids` as typed on the command line.

    `total` may be omitted when the scenario is one this repo can see — it knows
    how many criteria the scenario has, and a hand-typed denominator that
    disagrees with the YAML is a number nobody can interpret later.
    """
    parts = spec.split(":")
    if len(parts) < 2:
        raise ValueError(
            f"{spec!r} is not a scenario result. Write it as "
            f"'<scenario>:<met>/<total>:<failed,criterion,ids>', e.g. "
            f"'standup-migration:2/4:register,followup'."
        )

    name = parts[0].strip()
    score = parts[1].strip()
    failed = [f.strip() for f in (parts[2] if len(parts) > 2 else "").split(",") if f.strip()]

    scenario = scenarios.get(name)
    met_text, _, total_text = score.partition("/")
    try:
        met = int(met_text)
        total = int(total_text) if total_text else (scenario.criteria_total if scenario else 0)
    except ValueError as error:
        raise ValueError(f"{spec!r}: {score!r} is not a score like '3/4'.") from error

    if not total:
        raise ValueError(
            f"{spec!r} has no criteria count, and {name!r} isn't a scenario in this pool, so "
            f"there is nothing to take it from. Write the total: '{name}:{met}/4'."
        )
    if met > total:
        raise ValueError(f"{spec!r}: {met} criteria met out of {total} is not possible.")
    if scenario and total != scenario.criteria_total:
        logger.warning("%s has %d criteria in the YAML but the result says %d",
                       name, scenario.criteria_total, total)

    return ScenarioRun(
        date=date, scenario=name,
        pack=scenario.pack if scenario else "",
        register=scenario.register if scenario else "",
        function=scenario.function if scenario else "",
        criteria_met=met, criteria_total=total, failed=failed,
    )


# --- selection (Q12) ----------------------------------------------------------
#
# Never run before, then the ones that failed last time, then the rest — and
# varying `register` rather than `setting`, because five peer-level work
# scenarios train less than one peer, one manager and one stranger. The grammar
# is the same in all five; the social calibration is what differs.

# Rank bands. Lower is picked first.
_NEVER_RUN = 0
_FAILED_LAST = 1
_CLEAN = 2


@dataclass
class Choice:
    scenario: Scenario
    reason: str


def choose_scenarios(scenarios: list[Scenario], history: list[ScenarioRun],
                     count: int = DEFAULT_SCENARIOS) -> list[Choice]:
    """
    Q12's rule, applied arithmetically.

    Register variety is a first-class constraint rather than a preference to
    apply by eye: the pass below takes the best candidate from each register
    before it takes a second from any of them, so a pool dominated by peer-level
    work scenarios cannot quietly produce a peer-only session.
    """
    if not scenarios:
        return []

    last: dict[str, ScenarioRun] = {}
    for run in history:
        last[run.scenario] = run          # history is oldest first, so this is the latest
    latest_session = max((r.date for r in history), default="")

    ranked: list[tuple[tuple, Scenario, str]] = []
    for scenario in scenarios:
        run = last.get(scenario.name)
        if run is None:
            band, reason = _NEVER_RUN, "never run"
            recency = ""
        elif run.failed:
            band = _FAILED_LAST
            reason = f"failed {', '.join(run.failed)} on {run.date}"
            recency = run.date
        else:
            band = _CLEAN
            reason = f"clean {run.score} on {run.date}"
            recency = run.date

        # Q12: don't repeat a scenario from the previous session unless a
        # criterion failed there. Ranking it last rather than dropping it keeps a
        # small pool usable — a pool of six cannot afford a hard exclusion.
        if run is not None and run.date == latest_session and not run.failed:
            band = _CLEAN + 1
            reason = f"ran last session, clean ({run.score})"

        ranked.append(((band, recency, scenario.name), scenario, reason))

    ranked.sort(key=lambda entry: entry[0])

    chosen: list[Choice] = []
    seen_registers: set[str] = set()
    for _, scenario, reason in ranked:
        if len(chosen) >= count:
            break
        if scenario.register in seen_registers:
            continue
        seen_registers.add(scenario.register)
        chosen.append(Choice(scenario, reason))

    if len(chosen) < count:
        taken = {c.scenario.name for c in chosen}
        for _, scenario, reason in ranked:
            if len(chosen) >= count:
                break
            if scenario.name not in taken:
                chosen.append(Choice(scenario, reason))

    return chosen


# --- what `asking_memory.md` is read for --------------------------------------
#
# Q16's tracker is prose, and prose is right for it: what a register error costs
# a listener is not a number. But two thirds of what a session needs from it is
# structured — which patterns are active, when each last failed, and what has
# already been run. Parsing that part is what lets the file be read once at the
# end of a session instead of in full at the start of every one.

@dataclass
class Pattern:
    name: str
    status: str = ""
    sessions_with_error: str = ""
    last_error: str = ""
    note: str = ""


@dataclass
class AskingMemory:
    patterns: list[Pattern] = field(default_factory=list)
    register_notes: list[str] = field(default_factory=list)
    usable: bool = True

    @property
    def worst(self) -> Optional[Pattern]:
        """The pattern to keep an eye on: most sessions with an error, ties
        broken by the most recent failure."""
        active = [p for p in self.patterns if p.status.lower().startswith("active")]
        if not active:
            return None

        def key(pattern: Pattern) -> tuple:
            try:
                sessions = int(pattern.sessions_with_error)
            except ValueError:
                sessions = 0
            return (-sessions, pattern.last_error or "")

        return sorted(active, key=key)[0]


def _section(text: str, heading: str) -> str:
    match = re.search(rf"^{re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text,
                      flags=re.M | re.S)
    return match.group(1) if match else ""


def parse_memory(path: Path) -> AskingMemory:
    """The structured half of `asking_memory.md`, for the brief."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return AskingMemory(usable=False)

    memory = AskingMemory()

    patterns_text = _section(text, "## Patterns")
    for block in re.split(r"^### ", patterns_text, flags=re.M)[1:]:
        lines = block.splitlines()
        pattern = Pattern(name=lines[0].strip())
        note = ""
        for i, line in enumerate(lines[1:]):
            if line.startswith("Status:"):
                pattern.status = line.split(":", 1)[1].strip()
            elif line.startswith("Sessions with an error:"):
                pattern.sessions_with_error = line.split(":", 1)[1].strip()
            elif line.startswith("Last error:"):
                pattern.last_error = line.split(":", 1)[1].strip()
            elif line.startswith("Notes:"):
                note = " ".join(lines[i + 1:]).replace("Notes:", "", 1)
                note = re.sub(r"\s+", " ", re.sub(r"\*\*", "", note)).strip()
        pattern.note = note[:NOTE_CHARS] + ("…" if len(note) > NOTE_CHARS else "")
        memory.patterns.append(pattern)

    # The register notes are written as paragraphs led by a bolded verdict —
    # "**Stranger, in writing — the worst result so far (0/4).**" — and those
    # leads are the digest. Anything without one is prose that has to be read in
    # full to mean anything, and is left for the file itself.
    for paragraph in _section(text, "## Register notes").split("\n\n"):
        lead = re.match(r"\s*\*\*(.+?)\*\*", paragraph, flags=re.S)
        if lead:
            memory.register_notes.append(re.sub(r"\s+", " ", lead.group(1)).strip())

    return memory


# --- writing the log back (Q16) -----------------------------------------------
#
# The two tables at the bottom of `asking_memory.md` are the mechanical part of
# the end-of-session write, and they were being retyped by hand at the point in
# the session where a step is most likely to be skipped. They are generated from
# the same results the CSV row is built from, so they cannot disagree with it.
#
# The prose above them is still written by hand, because that is the part with
# judgment in it.

_SCENARIO_LOG = "## Scenario log"
_SESSION_HISTORY = "## Session history"


def _append_to_table(text: str, heading: str, rows: list[str]) -> str:
    """
    Put `rows` after the last row of the table under `heading`.

    The table may be empty (header and separator only), which is what a freshly
    created tracker looks like — so the insertion point is the last line that
    starts with a pipe, not the last data row.
    """
    match = re.search(rf"^{re.escape(heading)}\s*$(.*?)(?=^## |\Z)", text, flags=re.M | re.S)
    if not match:
        return text

    body = match.group(1)
    lines = body.splitlines()
    last_pipe = max((i for i, line in enumerate(lines) if line.lstrip().startswith("|")),
                    default=None)
    if last_pipe is None:
        return text

    lines[last_pipe + 1:last_pipe + 1] = rows
    return text[:match.start(1)] + "\n".join(lines) + "\n" + text[match.end(1):]


def append_log_rows(path: Path, *, date: str, runs: list[ScenarioRun],
                    drill_score: str = "—", biggest_problem: str = "") -> bool:
    """
    Add this session's rows to the scenario log and the session history.

    Returns False when the file has neither table — a tracker that doesn't exist
    yet, or one whose headings were renamed. The caller says so rather than
    creating a document of its own: Q16 owns this file's shape.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False

    if _SCENARIO_LOG not in text or _SESSION_HISTORY not in text:
        return False

    scenario_rows = [
        f"| {run.date} | {run.scenario} | {run.score} | "
        f"{', '.join(run.failed) if run.failed else '—'} |"
        for run in runs
    ]
    met = sum(r.criteria_met for r in runs)
    total = sum(r.criteria_total for r in runs)
    session_row = (f"| {date} | {len(runs)} | {met}/{total} | {drill_score} | "
                   f"{biggest_problem or '—'} |")

    text = _append_to_table(text, _SCENARIO_LOG, scenario_rows)
    text = _append_to_table(text, _SESSION_HISTORY, [session_row])
    path.write_text(text, encoding="utf-8")
    return True


# --- the brief ----------------------------------------------------------------

@dataclass
class AskBrief:
    date: str
    scenarios: list[Choice]
    block: Optional[object] = None            # brief.Block
    memory: AskingMemory = field(default_factory=AskingMemory)
    last_session: str = ""
    budget: str = ""
    notes: list[str] = field(default_factory=list)


def build(*, today: str, scenarios_dir: Path, drills_dir: Path, memory_path: Path,
          history_path: Path, practice_path: Path, mistakes_path: Path,
          item_history: Path, pending: Path, count: int = DEFAULT_SCENARIOS,
          with_block: bool = True, block_size: int = 6, patterns: int = 3) -> AskBrief:
    """Everything Q2 used to read by hand, in one pass."""
    from voxlib import brief as brief_module
    from voxlib import mistakes as mistakes_module
    from voxlib import practice as practice_module

    notes: list[str] = []

    pool = load_scenarios(scenarios_dir)
    if not pool:
        notes.append(f"No scenario packs in {scenarios_dir} — write them as you go "
                     f"(asking/README.txt has the format) and skip the block (Q13).")

    history = load_history(history_path)
    chosen = choose_scenarios(pool, history, count=count)

    memory = parse_memory(memory_path)
    if not memory.usable:
        notes.append(f"No tracker at {memory_path} — this is the first session, so create it "
                     f"at the end (Q16) rather than inventing a history.")

    recording_dates: list[str] = []
    try:
        recording_dates = mistakes_module.session_dates(mistakes_module.load(mistakes_path))
    except Exception:
        logger.warning("Could not read %s for the budget line", mistakes_path)

    sessions = practice_module.load(practice_path)
    asking = [s for s in sessions if s.mode == practice_module.ASK_MODE]
    if asking:
        last = asking[-1]
        last_session = (f"{last.date} · {last.focus or 'no focus'} · {last.learner_words} words · "
                        f"{last.errors} errors · {last.reproductions} re-productions")
    else:
        last_session = "none recorded yet"

    block = None
    if with_block:
        block = brief_module.draw_block(
            drills_dir=drills_dir, item_history=item_history, mistakes=mistakes_path,
            pending=pending, focus_drill=None, count=block_size, patterns=patterns)
        if block is None:
            notes.append(f"No drills in {drills_dir} — run the scenarios without a block "
                         f"rather than improvising prompts and scoring them by hand (Q13).")
        elif block.replaced_pending:
            notes.append("An unscored block from an earlier session was replaced. Its answers "
                         "can no longer be scored.")

    return AskBrief(date=today, scenarios=chosen, block=block, memory=memory,
                    last_session=last_session,
                    budget=practice_module.budget_line(sessions, recording_dates, today),
                    notes=notes)


def _field(label: str, value: str, width: int = 12) -> str:
    """`label: value`, with the wrapped lines of a YAML block hanging under it —
    a scenario's situation runs to three lines and is unreadable flush left."""
    indent = " " * (width + 2)
    body = ("\n" + indent).join(line.strip() for line in value.splitlines() if line.strip())
    return f"  {label + ':':<{width}}{body}"


def format_brief(brief: AskBrief) -> str:
    """
    Plain text, and — unlike the answering brief — **not** safe to have on screen
    while answering.

    Every scenario prints its `trap` and its criteria, which are the two things
    Q12 and Q10 say not to read out: a trap announced is an error that can no
    longer be made, and criteria read out in advance are a checklist to write
    against rather than a question to ask. Same for `holds_back`. This output is
    for the person running the session, not the person in it.
    """
    label = "{:<13}".format
    lines = [f"ASKING BRIEF — {brief.date}", "=" * 72, "",
             label("Budget") + brief.budget,
             label("Last asking") + brief.last_session]

    worst = brief.memory.worst
    if worst:
        lines.append(label("Watch") + f"{worst.name} — {worst.sessions_with_error} session(s) "
                                      f"with an error, last {worst.last_error or 'never'}")
        if worst.note:
            lines.append(label("") + worst.note)

    others = [p for p in brief.memory.patterns if worst is None or p.name != worst.name]
    if others:
        lines.append(label("Also tracked") + " · ".join(
            f"{p.name} ({p.status.lower()})" for p in others))

    if brief.memory.register_notes:
        lines += ["", "Register, from last time:"]
        lines += [f"  - {note}" for note in brief.memory.register_notes]

    if brief.block:
        lines += ["", f"Warm-up block — {len(brief.block.prompts)} prompts, "
                      f"{brief.block.patterns} patterns, interleaved (Q13).",
                  "Hand them over in one message and take the answers back in one "
                  "(they are written and scored", "against a key either way), then correct "
                  "the misses together. Which pattern each prompt tests",
                  "is deliberately not shown — naming it restores the priming the "
                  "interleaving removes.", ""]
        lines += [f"  {i:>2}. {prompt}" for i, prompt in enumerate(brief.block.prompts, 1)]
        lines += ["", "  Record them, in prompt order, before correcting:",
                  '    python -m voxlib.drill --drills-dir asking/drills \\',
                  '      --pending analysis/asking_pending.json answer "a1" "a2" "a3" ...']

    if brief.scenarios:
        lines += ["", "=" * 72,
                  f"{len(brief.scenarios)} scenarios (Q12), varied by register. "
                  f"NOT to be shown as written:",
                  "the trap, the criteria and what the reply holds back are all for you.", ""]
        # `form` is deliberately one string in every scenario
        # (asking/README.txt), and it is a long one — printed per scenario it is
        # most of the block and says the same thing five times over. Any check
        # shared by more than one scenario is printed once, here.
        counts: dict[str, int] = {}
        for choice in brief.scenarios:
            for criterion in choice.scenario.criteria:
                counts[criterion.check] = counts.get(criterion.check, 0) + 1

        shared = {}
        for choice in brief.scenarios:
            for criterion in choice.scenario.criteria:
                if counts[criterion.check] > 1 and criterion.check not in shared:
                    shared[criterion.check] = criterion.id
        if shared:
            lines.append("Scored in every scenario below:")
            lines += [f"  [{name}] {check}" for check, name in shared.items()]
            lines.append("")

        for i, choice in enumerate(brief.scenarios, 1):
            s = choice.scenario
            lines.append(f"--- {i}. {s.name}  [{s.register} · {s.function} · {s.pack}]"
                         f"  ({choice.reason})")
            for field_label, value in (("Situation", s.situation), ("Ask for", s.ask_for),
                                       ("Reply", s.reply), ("Holds back", s.holds_back),
                                       ("Trap", s.trap)):
                lines.append(_field(field_label, value))
            for criterion in s.criteria:
                if criterion.check in shared:
                    lines.append(f"  [{criterion.id}] (as above)")
                else:
                    lines.append(f"  [{criterion.id}] {criterion.check}")
            lines.append("")

    if brief.notes:
        lines += [f"! {note}" for note in brief.notes]

    lines += ["", "-" * 72,
              "At the end — scores the block, writes the practice row, the scenario history "
              "and the log tables (Q14):",
              f"  python -m voxlib.practice end --date {brief.date} --mode ask \\",
              "      --focus '<the question pattern that failed most>' --words <their words> \\",
              "      --reproductions <Q8> --long-turns 0 \\",
              "      --scenario 'name:3/4:register,followup' --scenario 'name:4/4' \\",
              "      'Pattern Name:1'"]
    return "\n".join(lines)


def render(**kwargs) -> str:
    """`build` and `format_brief` in one call — what the CLI runs."""
    return format_brief(build(**kwargs))
