"""
The practice history — the middle rung, and the one that was missing.

Three things can be true of a grammar pattern, and until this file existed only
the outer two were measured:

1. **Known.** A drill asks for it directly, one structure in mind, unlimited
   thinking time. `drills.csv` answers this, and by 2026-08-17 it answered "yes"
   for every category on record: four attempts, all 100%.
2. **Produced when attending.** A typed conversation where the topic is real and
   the structure isn't announced — harder than a drill, far easier than speech.
   Nothing measured this at all. `conversation_focus_log.md` recorded that a
   pattern had been practised and on what date, never how it went.
3. **Produced unmonitored.** A recording. `mistakes.csv` answers this, and it
   kept answering "no" for the same categories the drills scored 100% on.

The gap between 1 and 3 is where the whole loop was stuck, and it has two very
different explanations that the two files together cannot distinguish: either the
pattern isn't really known and the drill is too easy, or it is known and simply
not automatic. Rung 2 separates them. A category that survives attended
production and still fails in speech needs volume, not explanation — and a
category that fails already under attention needs the explanation after all.

Two other things this makes possible, both asked for by CLAUDE.md and neither
answerable before:

**A denominator on the practice side.** Errors are counted against the words the
learner actually produced, per 1,000, the same normalization `mistakes.csv` uses
— so the two rates sit in the same units and can be read against each other.
That is the reason a practice session is asked for a couple of long turns rather
than a run of one-line answers: without a few hundred words there is nothing to
divide by.

**The treatment/instrument budget.** General rule 19 says a recording measures
and only corrected repetitions train, and asks for the two counts to be compared
each session. Nothing counted the repetitions, so the comparison was done from
memory or not at all. `reproductions` counts them, and the table prints the two
side by side.

Written by hand, via `python -m voxlib.practice add`, at the end of a practice
session — the same arrangement as `mistakes.csv`: append-only, one row per
session, and nothing edits a row once it is written. Unlike `mistakes.csv` a
repeated date is allowed, because two practice sessions in one day are two
sessions.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import date as date_type
from datetime import timedelta
from pathlib import Path
from typing import Optional

from voxlib import csvfile

logger = logging.getLogger(__name__)

HISTORY_COLUMNS = [
    "date",
    "focus",
    "learner_words",
    "errors",
    "error_breakdown",
    "reproductions",
    "long_turns",
    "notes",
    # Appended after `notes` rather than beside the other counts: a column added
    # to an append-only file can only go on the end, or the rows already in it
    # would have to be rewritten to stay aligned. See `voxlib.csvfile`.
    "vocabulary",
    "mode",
    "reproductions_missed",
]

# Errors and words are separated by a colon in the breakdown, sessions by a
# semicolon: "Article Errors:3;Redundant Reflexive Pronoun:1". A CSV cell rather
# than its own file because nothing joins on it — it is read whole or not at all.
# The vocabulary cell works the same way with one more field: the banned phrase,
# how many times it slipped out anyway, and how many times a replacement was
# produced instead — "you know:2:0;super:0:3".
_CATEGORY_SEPARATOR = ";"
_COUNT_SEPARATOR = ":"

# How many consecutive sessions a banned phrase has to survive untouched before
# it has stopped being a habit. Three, matching the absence streak `mistakes.csv`
# uses to promote a grammar category — the same claim about the same speaker
# deserves the same evidence.
CLEAN_SESSIONS_TO_RETIRE = 3

# The window the budget line covers. Two weeks, because rule 19 budgets in weeks
# ("roughly two recordings a week") and a single week is short enough that one
# quiet weekend reads as a collapse.
BUDGET_DAYS = 14

# The two kinds of practice session. They are not the same denominator, which is
# the whole reason this is a column: an answering session is a few long turns and
# runs to hundreds of words, while an asking session is a dozen questions and may
# run to eighty. Pooling them deflates every per-1,000-word rate in the file by
# however much asking happened that fortnight — a number nobody chose and nobody
# could see.
ANSWER_MODE = "answer"
ASK_MODE = "ask"
MODES = (ANSWER_MODE, ASK_MODE)

# A form corrected in the session that no tracked category covers — "help me to
# get", "I am out of context", "give me it". These used to go into `notes` as
# prose, which meant the second occurrence looked exactly like the first and
# nothing could count them. They go in the breakdown from the first correction
# instead, under a name carrying this prefix.
#
# The prefix is what keeps them honest. They are excluded from `errors` and from
# every rate, because the rows already in the file predate the convention and a
# denominator that changes meaning halfway down a column is worse than a missing
# number. What they get instead is their own count of sessions, which is the only
# thing being asked of them: has this happened before.
PROVISIONAL_PREFIX = "?"

# How many sessions a provisional form has to appear in before it stops being
# one. Two: once is a slip, and the same slip in two separate sessions is a
# pattern — at which point it earns a real category name and a drill, and from
# there the spaced-repetition schedule picks it up like any other.
SESSIONS_TO_PROMOTE = 2

# Question Practice Mode ran twice before this column existed and tagged its rows
# with a notes prefix, because `notes` was the only field available at the time
# (CLAUDE.md Q14). Reading that prefix back is what keeps those two rows from
# counting as answering sessions forever. New rows declare the mode properly;
# this is a fallback for the ones written before they could.
_ASK_NOTES_PREFIX = "question practice"

# How many recent practice sessions the attended-vs-unmonitored comparison pools.
# Three, matching the recency window the mistake history uses: one session is too
# few words to divide by, and the whole history would average away the present.
COMPARISON_SESSIONS = 3

# When a side of the loop stops being current. Rule 19 budgets in weeks
# ("roughly two recordings a week"), so a week is the point at which a side is
# behind and a fortnight the point at which it has stopped — `BUDGET_DAYS` is
# already the window the rule's own counts are read over.
#
# Stated here rather than in the page that draws them, because a threshold in a
# stylesheet is a threshold nobody can argue with: these two numbers decide
# whether the dashboard opens saying the loop is running or saying it is not.
LOOP_WARN_DAYS = 7
LOOP_STALE_DAYS = BUDGET_DAYS


def _elapsed(since: Optional[str], today: str) -> Optional[int]:
    if not since:
        return None
    try:
        return (date_type.fromisoformat(today) - date_type.fromisoformat(since)).days
    except ValueError:
        return None


def _state(days: Optional[int]) -> str:
    """`ok` / `warn` / `stale` / `never`, from one elapsed count."""
    if days is None:
        return "never"
    if days <= LOOP_WARN_DAYS:
        return "ok"
    return "warn" if days <= LOOP_STALE_DAYS else "stale"


@dataclass
class LoopSide:
    """One half of the loop: when it last happened and how that reads."""
    key: str
    label: str
    last: str                     # "" when it has never happened
    days: Optional[int]
    state: str
    detail: str = ""

    @property
    def running(self) -> bool:
        return self.state == "ok"


@dataclass
class LoopState:
    """
    Whether the loop this project is built around is actually turning.

    Rule 19 splits the work in two: the recording is the instrument and the
    corrected repetitions are the treatment. Both counts already existed — the
    recording dates in `mistakes.csv`, the repetitions in this file — and
    `budget_line` has printed them side by side for a fortnight at a time. What
    neither said is how long it has been since each last happened, which is the
    form the question actually takes when you open a page after three weeks:
    not "how many in the last fortnight" but "is this still going".

    The third side is the spaced-repetition schedule, because a review that is
    late is the one kind of work here that has a date attached and can therefore
    be *late* rather than merely undone.

    No streak. A streak counts consecutive days and would reward whichever side
    is easiest to do daily — which here is the recording, the side that is
    already over-supplied. An elapsed count says the same thing without turning
    a quiet fortnight into a failure.
    """
    today: str
    measure: LoopSide
    train: LoopSide
    review: LoopSide
    recordings_in_window: int
    sessions_in_window: int
    repetitions_in_window: int
    missed_in_window: int
    window_days: int

    @property
    def sides(self) -> list[LoopSide]:
        return [self.measure, self.train, self.review]

    @property
    def instrument_ahead(self) -> bool:
        """Rule 19's failure mode: measuring more than treating."""
        return self.recordings_in_window > self.sessions_in_window

    @property
    def worst(self) -> LoopSide:
        order = {"stale": 0, "never": 1, "warn": 2, "ok": 3}
        return sorted(self.sides, key=lambda s: (order[s.state], -(s.days or 0)))[0]


def loop_state(sessions: list[PracticeSession], recording_dates: list[str],
               overdue: Optional[list[tuple[str, str]]] = None,
               today: Optional[str] = None) -> LoopState:
    """
    The three sides of the loop, as of `today`.

    `overdue` is `(category, next_due)` for every schedule row already past its
    date — passed in rather than read here, because `focus_log` owns that file
    and this module has never imported it.

    "Trained" means a session that produced at least one corrected repetition,
    not merely a session that happened. A practice session with no repetitions
    in it is the failure rule 19 describes, so counting it as treatment would
    report the loop as turning on exactly the evidence that it is not.
    """
    today = today or date_type.today().isoformat()
    start = (date_type.fromisoformat(today) - timedelta(days=BUDGET_DAYS)).isoformat()

    # Bounded at both ends. A date after `today` is not evidence that anything
    # has happened recently — it is a typo, a clock that was wrong, or a
    # simulated history — and counting it reports a loop running hard while
    # nothing has been done at all.
    recorded = sorted(d for d in recording_dates if d and d <= today)
    trained = sorted(s.date for s in sessions if s.reproductions > 0 and s.date <= today)
    recent = [s for s in sessions if start < s.date <= today]
    overdue = sorted(overdue or [], key=lambda o: o[1])

    measure_days = _elapsed(recorded[-1] if recorded else None, today)
    train_days = _elapsed(trained[-1] if trained else None, today)

    measure = LoopSide(
        key="measure", label="Measure", last=recorded[-1] if recorded else "",
        days=measure_days, state=_state(measure_days),
        detail=f"{len(recorded)} recording{'' if len(recorded) == 1 else 's'} analysed",
    )
    train = LoopSide(
        key="train", label="Train", last=trained[-1] if trained else "",
        days=train_days, state=_state(train_days),
        detail=("no corrected repetition on record" if not trained else
                f"{len(trained)} session{'' if len(trained) == 1 else 's'} with a repetition "
                "in them"),
    )
    review_days = _elapsed(overdue[0][1] if overdue else None, today)
    review = LoopSide(
        key="review", label="Review", last=overdue[0][1] if overdue else "",
        days=review_days,
        # An empty schedule is nothing to be late for, not a late thing.
        state="ok" if not overdue else _state(review_days),
        detail=("nothing overdue" if not overdue else
                f"{len(overdue)} overdue, oldest {overdue[0][0]}"),
    )

    return LoopState(
        today=today, measure=measure, train=train, review=review,
        recordings_in_window=sum(1 for d in recorded if d > start),
        sessions_in_window=len(recent),
        repetitions_in_window=sum(s.reproductions for s in recent),
        missed_in_window=sum(s.reproductions_missed for s in recent),
        window_days=BUDGET_DAYS,
    )


def is_provisional(category: str) -> bool:
    """Whether a breakdown entry names an untracked form rather than a tracked
    grammar category."""
    return category.strip().startswith(PROVISIONAL_PREFIX)


@dataclass
class PracticeSession:
    date: str
    focus: str
    learner_words: int
    errors_by_category: dict[str, int] = field(default_factory=dict)
    reproductions: int = 0
    long_turns: int = 0
    vocabulary: dict[str, "WordResult"] = field(default_factory=dict)
    notes: str = ""
    mode: str = ANSWER_MODE
    reproductions_missed: int = 0

    @property
    def errors(self) -> int:
        """Tracked categories only — see `PROVISIONAL_PREFIX`."""
        return sum(n for c, n in self.errors_by_category.items() if not is_provisional(c))

    @property
    def provisional(self) -> dict[str, int]:
        return {c: n for c, n in self.errors_by_category.items() if is_provisional(c)}

    @property
    def reproductions_attempted(self) -> int:
        """Re-productions asked for, landed or not. `reproductions` counts the
        ones that landed; a session with three attempts and none landing is a
        different session from one with three that held, and until this column
        existed the two wrote the same row."""
        return self.reproductions + self.reproductions_missed

    @property
    def rate_per_1000(self) -> Optional[float]:
        """Errors per 1,000 words the learner produced — the same unit as
        `mistakes.csv`, so the two can be read against each other."""
        if self.learner_words <= 0:
            return None
        return round(self.errors * 1000 / self.learner_words, 2)


@dataclass
class WordResult:
    """One banned phrase's session: how often it slipped out, and how often
    something better was produced in its place.

    Both numbers, because either alone is misleading. Zero slips with zero
    replacements is usually avoidance — the sentence was rebuilt to dodge the
    slot rather than filled with a better word — and that is not the same result
    as zero slips with five replacements, which is the habit actually changing.
    """
    slips: int = 0
    uses: int = 0

    @property
    def clean(self) -> bool:
        return self.slips == 0


def _format_vocabulary(words: dict[str, WordResult]) -> str:
    return _CATEGORY_SEPARATOR.join(
        f"{phrase}{_COUNT_SEPARATOR}{r.slips}{_COUNT_SEPARATOR}{r.uses}"
        for phrase, r in sorted(words.items())
    )


def _parse_vocabulary(raw: str) -> dict[str, WordResult]:
    words: dict[str, WordResult] = {}
    for entry in raw.split(_CATEGORY_SEPARATOR):
        entry = entry.strip()
        if not entry:
            continue
        # Split from the right, twice: the phrase comes first and may contain
        # anything, including the separator.
        head, _, uses = entry.rpartition(_COUNT_SEPARATOR)
        phrase, _, slips = head.rpartition(_COUNT_SEPARATOR)
        try:
            words[phrase.strip()] = WordResult(slips=int(slips), uses=int(uses))
        except ValueError:
            logger.warning("Ignoring unreadable vocabulary entry %r", entry)
    return words


def _format_breakdown(errors: dict[str, int]) -> str:
    return _CATEGORY_SEPARATOR.join(
        f"{category}{_COUNT_SEPARATOR}{count}" for category, count in sorted(errors.items())
    )


def _parse_breakdown(raw: str) -> dict[str, int]:
    errors: dict[str, int] = {}
    for entry in raw.split(_CATEGORY_SEPARATOR):
        entry = entry.strip()
        if not entry:
            continue
        category, _, count = entry.rpartition(_COUNT_SEPARATOR)
        try:
            errors[category.strip()] = int(count)
        except ValueError:
            logger.warning("Ignoring unreadable error count %r", entry)
    return errors


def _read_mode(raw: dict) -> str:
    """The declared mode, or the one the notes prefix implies for a row written
    before the column existed."""
    declared = (raw.get("mode") or "").strip().lower()
    if declared in MODES:
        return declared
    if (raw.get("notes") or "").strip().lower().startswith(_ASK_NOTES_PREFIX):
        return ASK_MODE
    return ANSWER_MODE


def load(path: Path) -> list[PracticeSession]:
    if not path.exists():
        return []
    sessions = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            sessions.append(PracticeSession(
                date=raw["date"].strip(),
                focus=(raw.get("focus") or "").strip(),
                learner_words=int(raw["learner_words"]),
                errors_by_category=_parse_breakdown(raw.get("error_breakdown") or ""),
                reproductions=int(raw.get("reproductions") or 0),
                reproductions_missed=int(raw.get("reproductions_missed") or 0),
                long_turns=int(raw.get("long_turns") or 0),
                vocabulary=_parse_vocabulary(raw.get("vocabulary") or ""),
                notes=(raw.get("notes") or "").strip(),
                mode=_read_mode(raw),
            ))
    sessions.sort(key=lambda s: s.date)
    return sessions


def record_session(path: Path, *, date: str, focus: str, learner_words: int,
                   errors_by_category: dict[str, int], reproductions: int = 0,
                   long_turns: int = 0, vocabulary: Optional[dict[str, WordResult]] = None,
                   notes: str = "", mode: str = ANSWER_MODE,
                   reproductions_missed: int = 0) -> None:
    """
    Appends one practice session.

    A date that already has a row is fine — two practice sessions in a day are
    two sessions, and unlike a recording there is no transcript to merge twice.
    What is refused is a session with no words in it: an error count without a
    denominator is the thing this file exists to stop producing.
    """
    if learner_words <= 0:
        raise ValueError(
            f"learner_words must be positive, got {learner_words}. Errors without a word "
            f"count cannot be normalized, which makes them uncomparable with mistakes.csv "
            f"and with every other practice session."
        )
    if reproductions < 0 or long_turns < 0 or reproductions_missed < 0:
        raise ValueError("reproductions, reproductions_missed and long_turns cannot "
                         "be negative.")
    negative = sorted(c for c, n in errors_by_category.items() if n < 0)
    if negative:
        raise ValueError(f"Negative error counts for: {negative}")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}.")

    tracked = sum(n for c, n in errors_by_category.items() if not is_provisional(c))
    csvfile.append(path, HISTORY_COLUMNS, [{
        "date": date,
        "focus": focus,
        "learner_words": learner_words,
        # Tracked categories only. The provisional ones are in the breakdown
        # beside them but out of this total, so the column means the same thing
        # in the rows written before they could be recorded at all.
        "errors": tracked,
        "error_breakdown": _format_breakdown(errors_by_category),
        "reproductions": reproductions,
        "long_turns": long_turns,
        "vocabulary": _format_vocabulary(vocabulary or {}),
        "notes": notes,
        "mode": mode,
        "reproductions_missed": reproductions_missed,
    }])

    logger.info("Recorded a practice session for %s: %d words, %d errors", date,
                learner_words, tracked)


# --- closing a session --------------------------------------------------------
#
# Three things have to happen at the end of a practice session, and they were
# three separate manual steps: score the drill block, append the row below, and
# move every drilled pattern on in `conversation_focus_log.md`. All three land at
# the point where the session is already over — the moment at which a step is
# most likely to be skipped, and skipping any one of them is silent. An unscored
# block leaves `drill_pending.json` to be overwritten by the next session; an
# unwritten row makes a session that happened indistinguishable from one that
# didn't; a focus log left alone brings every pattern back on the wrong day.
#
# They also share their inputs, which is the real argument for doing them
# together: whether a pattern held up this session is the drill result *and* the
# conversation errors, and neither step could see both.

@dataclass
class SessionOutcome:
    session: PracticeSession
    scored: dict[str, object] = field(default_factory=dict)    # drill name -> DrillResult
    changes: list = field(default_factory=list)                # focus_log.Change
    scenarios: list = field(default_factory=list)              # asking.ScenarioRun
    notes: list[str] = field(default_factory=list)


def close_session(*, date: str, focus: str, learner_words: int,
                  errors_by_category: dict[str, int], reproductions: int = 0,
                  long_turns: int = 0, vocabulary: Optional[dict[str, WordResult]] = None,
                  notes: str = "", mode: str = ANSWER_MODE, reproductions_missed: int = 0,
                  history_path: Path,
                  focus_log_path: Path, pending: Path, drills_dir: Path,
                  drill_history: Path, drill_item_history: Path,
                  scenarios: Optional[list[str]] = None,
                  scenarios_dir: Optional[Path] = None,
                  scenario_history: Optional[Path] = None,
                  asking_memory: Optional[Path] = None,
                  dry_run: bool = False) -> SessionOutcome:
    """
    Score the block, write the row, move the schedule on.

    The order is deliberate: everything that can be refused is refused before
    anything is written. A session rejected for having no word count after its
    drill scores were already recorded would leave two files disagreeing about
    whether the session happened.
    """
    from voxlib import drill as drill_module
    from voxlib import focus_log

    if learner_words <= 0:
        raise ValueError(
            f"learner_words must be positive, got {learner_words}. Errors without a word "
            f"count cannot be normalized, which makes them uncomparable with mistakes.csv "
            f"and with every other practice session."
        )

    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}.")

    runs = []
    if scenarios:
        from voxlib import asking as asking_module

        if mode != ASK_MODE:
            raise ValueError(
                "Scenario results only come from Question Practice Mode — pass --mode ask, "
                "or drop the --scenario arguments."
            )
        pool = {s.name: s for s in asking_module.load_scenarios(scenarios_dir)} \
            if scenarios_dir else {}
        runs = [asking_module.parse_run(spec, pool, date) for spec in scenarios]

    outcome = SessionOutcome(session=PracticeSession(
        date=date, focus=focus, learner_words=learner_words,
        errors_by_category=dict(errors_by_category), reproductions=reproductions,
        long_turns=long_turns, vocabulary=dict(vocabulary or {}), notes=notes, mode=mode,
        reproductions_missed=reproductions_missed))

    # 1. The block. `missed` is per category, because that is what the schedule
    #    is keyed on — a drill is an implementation of a category, not a peer.
    missed: dict[str, bool] = {}
    block = drill_module.read_block(pending)
    if block is None:
        outcome.notes.append("No drill block was pending — nothing to score.")
    elif not block.answers:
        outcome.notes.append(
            f"A block of {len(block.items)} prompts was drawn but no answers were recorded, "
            f"so it can't be scored. Record them as they are given next time "
            f"(`python -m voxlib.drill answer \"...\"`). Leaving it pending.")
    else:
        drills = {d.name: d for d in drill_module.load_all(drills_dir)}
        outcome.scored = drill_module.score_block(block, drills)
        if not block.complete:
            outcome.notes.append(
                f"Only {len(block.answers)} of {len(block.items)} prompts were answered — "
                f"the rest count as unattempted, not as errors.")
        for name, result in outcome.scored.items():
            category = drills[name].category
            wrong = any(r.attempted and not r.correct for r in result.items)
            missed[category] = missed.get(category, False) or wrong
            if not dry_run:
                drill_module.record_result(drill_history, drill_item_history, date=date,
                                           result=result, notes=notes, condition=block.mode)
        if not dry_run:
            pending.unlink(missing_ok=True)

    # 2. The schedule. P18: a pattern the block asked about was tested, whether
    #    or not it came up anywhere else, and a miss in the block counts the same
    #    as one made mid-conversation.
    drilled = {category: not wrong for category, wrong in missed.items()}
    if focus:
        drilled.setdefault(focus, True)
    for category in list(drilled):
        if errors_by_category.get(category, 0) > 0:
            drilled[category] = False

    untested = sorted(c for c in set(errors_by_category) - set(drilled)
                      if not is_provisional(c))
    if untested:
        outcome.notes.append(
            f"Not tested by the block and not this session's focus, so their schedule is "
            f"unchanged (P18): {', '.join(untested)}.")

    if not dry_run:
        outcome.changes = focus_log.record(focus_log_path, drilled, date)
    else:
        _, outcome.changes = focus_log.apply(focus_log.load(focus_log_path), drilled, date)

    # 3. The row.
    if not dry_run:
        record_session(history_path, date=date, focus=focus, learner_words=learner_words,
                       errors_by_category=errors_by_category, reproductions=reproductions,
                       long_turns=long_turns, vocabulary=vocabulary, notes=notes, mode=mode,
                       reproductions_missed=reproductions_missed)

    #    Provisional forms are checked against the whole history rather than this
    #    session alone: the point of recording them at all is that the second
    #    occurrence should be impossible to miss, and it is a second occurrence
    #    only in the context of the first.
    if any(is_provisional(c) for c in errors_by_category):
        history = load(history_path) if history_path.exists() else []
        if dry_run:
            history = history + [outcome.session]
        # `ProvisionalForm.name` has the prefix stripped; the breakdown keys
        # still carry it.
        this_session = {c.strip().lstrip(PROVISIONAL_PREFIX).strip()
                        for c in errors_by_category if is_provisional(c)}
        for form in provisional_trends(history):
            if form.ready_to_promote and form.name in this_session:
                outcome.notes.append(
                    f'{form.name} has now come up in {form.sessions} sessions '
                    f'({form.first_seen} → {form.last_seen}). Give it a real category '
                    f'name and a drill, and record it under that name from now on.')

    # 4. The scenarios (Q10, Q16). Last, because it is the step that can be
    #    absent: an answering session has none, and an asking session that ended
    #    after the block has none either.
    if runs:
        from voxlib import asking as asking_module

        outcome.scenarios = runs
        total = sum(r.criteria_total for r in runs)
        met = sum(r.criteria_met for r in runs)
        outcome.notes.append(f"{len(runs)} scenario(s), {met}/{total} criteria met.")
        if not dry_run and scenario_history:
            asking_module.record_runs(scenario_history, runs)
        if not dry_run and asking_memory:
            attempted = sum(r.attempted for r in outcome.scored.values())
            correct = sum(r.correct for r in outcome.scored.values())
            written = asking_module.append_log_rows(
                asking_memory, date=date, runs=runs,
                drill_score=f"{correct}/{attempted}" if attempted else "—",
                biggest_problem=focus)
            outcome.notes.append(
                f"Log tables in {asking_memory.name} updated — the prose above them is still "
                f"yours to write (Q16)." if written else
                f"{asking_memory} has no scenario log to append to, so its tables are "
                f"unchanged. The history in {scenario_history} is written either way.")

    return outcome


def format_outcome(outcome: SessionOutcome, *, dry_run: bool = False) -> str:
    from voxlib import drill as drill_module

    session = outcome.session
    lines = [f"{'Would close' if dry_run else 'Closed'} {session.date} ({session.mode})"
             f"{f' — focus: {session.focus}' if session.focus else ''}", ""]

    for name, result in outcome.scored.items():
        lines.append(drill_module.format_result(result))
        lines.append("")

    rate = "—" if session.rate_per_1000 is None else f"{session.rate_per_1000:.2f}/1k"
    repro = f"{session.reproductions} re-production(s) landed"
    if session.reproductions_missed:
        repro += f" of {session.reproductions_attempted} asked for"
    lines.append(f"{session.learner_words} words · {session.errors} errors ({rate}) · "
                 f"{repro} · {session.long_turns} long turns")
    tracked = {c: n for c, n in session.errors_by_category.items() if not is_provisional(c)}
    if tracked:
        lines.append("  " + ", ".join(f"{c} {n}" for c, n in sorted(tracked.items())))
    if session.provisional:
        lines.append("  untracked: " + ", ".join(
            f"{c.lstrip(PROVISIONAL_PREFIX)} {n}"
            for c, n in sorted(session.provisional.items())))
    if not session.reproductions_attempted:
        lines.append("  No corrected repetitions this session — that is the failure rule 19 "
                     "describes (P22), not a clean run.")
    elif not session.reproductions:
        lines.append(f"  {session.reproductions_missed} re-production(s) asked for and none "
                     f"landed. The treatment was offered and not taken, which is a different "
                     f"result from a session that never offered it — and it does not count "
                     f"towards rule 19's budget.")

    if session.vocabulary:
        lines.append("  " + ", ".join(
            f"{phrase}: {r.slips} slip(s), {r.uses} replacement(s)"
            for phrase, r in sorted(session.vocabulary.items())))

    if outcome.scenarios:
        lines.append("")
        lines.append("Scenarios:")
        lines += [f"  {run.scenario:<28} {run.score:>5}  "
                  f"{('failed: ' + ', '.join(run.failed)) if run.failed else 'clean'}"
                  for run in outcome.scenarios]

    if outcome.changes:
        lines.append("")
        lines.append("Schedule:")
        lines += [f"  {change}" for change in outcome.changes]

    if outcome.notes:
        lines.append("")
        lines += [f"! {note}" for note in outcome.notes]
    return "\n".join(lines)


# --- the word constraints (P24) ----------------------------------------------
#
# The largest measured problem in this speaker's English has never been a grammar
# category — a single connector can outrun every tracked pattern in `mistakes.csv`
# put together, and evaluative vocabulary collapses into two or three
# intensifiers. P24 answers that by banning two or three phrases per session and
# requiring replacements, which is production rather than the suggestion a report
# can only make.
#
# What it had no way to answer is whether the constraint held. A banned word was
# announced and then nothing counted it, so "you know" could be banned in six
# consecutive sessions with no way to tell whether that was working, and the list
# in `memory.md` could only ever grow: nothing said when a phrase had stopped
# being a habit and could come off it.

@dataclass
class WordTrend:
    phrase: str
    sessions: int          # sessions this phrase was banned in
    slips: int
    uses: int
    clean_streak: int      # consecutive most recent banned sessions with no slip
    last_banned: str

    @property
    def ready_to_retire(self) -> bool:
        """Clean for long enough to come off `Vocabulary To Replace`.

        Replacements are required as well as slips being absent: a phrase avoided
        by never going near the slot is a phrase still in charge of the sentence.
        """
        return self.clean_streak >= CLEAN_SESSIONS_TO_RETIRE and self.uses > 0


def vocabulary_trends(sessions: list[PracticeSession]) -> list[WordTrend]:
    """Per-phrase totals, worst first — most slips, then least practised."""
    banned: dict[str, list[tuple[str, WordResult]]] = {}
    for session in sessions:
        for phrase, result in session.vocabulary.items():
            banned.setdefault(phrase, []).append((session.date, result))

    trends = []
    for phrase, history in banned.items():
        streak = 0
        for _, result in reversed(history):
            if not result.clean:
                break
            streak += 1
        trends.append(WordTrend(
            phrase=phrase,
            sessions=len(history),
            slips=sum(r.slips for _, r in history),
            uses=sum(r.uses for _, r in history),
            clean_streak=streak,
            last_banned=history[-1][0],
        ))

    trends.sort(key=lambda t: (-t.slips, t.uses, t.phrase))
    return trends


# --- untracked forms ---------------------------------------------------------
#
# Every correction that is not one of the tracked categories used to leave the
# session in prose, in the `notes` cell, if it left it at all. That is where
# "help me to get", "I am out of context" and "give me it" went, and the cost is
# specific: nothing could tell the second occurrence of a form from the first, so
# a recurring error stayed invisible for as long as it took someone to reread the
# notes column and notice a phrase twice. The correction happened each time and
# the pattern behind it was never named.
#
# Recording them in the breakdown under a "?" name fixes only that one thing:
# whether this has happened before, and in how many sessions. Two is enough to
# stop guessing (`SESSIONS_TO_PROMOTE`) — at that point the form gets a real
# category name and a drill, and the ordinary machinery takes it from there.

@dataclass
class ProvisionalForm:
    name: str              # without the prefix
    sessions: int
    total: int
    first_seen: str
    last_seen: str

    @property
    def ready_to_promote(self) -> bool:
        return self.sessions >= SESSIONS_TO_PROMOTE


def provisional_trends(sessions: list[PracticeSession],
                       mode: Optional[str] = None) -> list[ProvisionalForm]:
    """Untracked forms across the history, the most-repeated first.

    Both modes by default. A form that came out wrong while answering and again
    while asking is the same form twice, and splitting the count by mode would
    be the one reading that hides it.
    """
    seen: dict[str, list[tuple[str, int]]] = {}
    for session in sessions:
        if mode is not None and session.mode != mode:
            continue
        for category, count in session.provisional.items():
            name = category.strip().lstrip(PROVISIONAL_PREFIX).strip()
            if name:
                seen.setdefault(name, []).append((session.date, count))

    forms = [ProvisionalForm(name=name, sessions=len(history),
                             total=sum(n for _, n in history),
                             first_seen=min(d for d, _ in history),
                             last_seen=max(d for d, _ in history))
             for name, history in seen.items()]
    forms.sort(key=lambda f: (-f.sessions, -f.total, f.name))
    return forms


def format_provisional(forms: list[ProvisionalForm]) -> str:
    if not forms:
        return ""
    lines = ["Untracked forms — corrected in a session, not covered by any category yet:",
             f"  {'Form':<40} {'Sessions':>9} {'Times':>6} {'Last':>12}"]
    for f in forms:
        star = " *" if f.ready_to_promote else ""
        lines.append(f"  {f.name[:40]:<40} {f.sessions:>9} {f.total:>6} "
                     f"{f.last_seen:>12}{star}")
    due = [f.name for f in forms if f.ready_to_promote]
    if due:
        lines.append(f"  * seen in {SESSIONS_TO_PROMOTE}+ separate sessions — not a slip. "
                     f"Give it a category name and write a drill: {', '.join(due)}")
    return "\n".join(lines)


def provisional_line(sessions: list[PracticeSession]) -> str:
    """One line for the session briefs: what is waiting to be promoted, and what
    is on its first sighting. Empty when there is nothing to say."""
    forms = provisional_trends(sessions)
    if not forms:
        return ""
    due = [f.name for f in forms if f.ready_to_promote]
    if due:
        return (f"needs a category and a drill ({SESSIONS_TO_PROMOTE}+ sessions): "
                + ", ".join(due))
    return "seen once, watch for a repeat: " + ", ".join(f.name for f in forms[:4])


def practice_rates(sessions: list[PracticeSession],
                   window: int = COMPARISON_SESSIONS,
                   mode: Optional[str] = ANSWER_MODE) -> dict[str, float]:
    """
    Per-category error rate per 1,000 learner words, over the last `window`
    sessions of one mode.

    Pooled rather than averaged per session: a 90-word session and a 400-word one
    are not two equal observations, and averaging their rates would let the short
    one swing the result. One numerator over one denominator.

    One mode, though, and by default the answering one. The comparison this feeds
    is typed grammar production against the same categories in speech, and an
    asking session contributes words to the denominator while contributing
    nothing those categories could appear in — so pooling the two understates
    every typed rate. Pass `mode=None` to pool anyway.
    """
    pool = [s for s in sessions if mode is None or s.mode == mode]
    recent = pool[-window:] if window else pool
    words = sum(s.learner_words for s in recent)
    if not words:
        return {}
    totals: dict[str, int] = {}
    for session in recent:
        for category, count in session.errors_by_category.items():
            if is_provisional(category):
                continue
            totals[category] = totals.get(category, 0) + count
    return {category: round(count * 1000 / words, 2) for category, count in totals.items()}


def format_table(sessions: list[PracticeSession], *,
                 recording_dates: Optional[list[str]] = None,
                 speech_rates: Optional[dict[str, float]] = None,
                 today: Optional[str] = None) -> str:
    if not sessions:
        # Still print the budget: "no practice sessions, six recordings" is the
        # rule-19 signal at its loudest, and suppressing it here would hide it in
        # exactly the state that most needs saying.
        return ("No practice sessions recorded yet. Say \"let's practice\" to run one.\n\n"
                + budget_line([], recording_dates or [], today))

    header = (f"{'Date':<12} {'Mode':<7} {'Focus':<32} {'Words':>7} {'Errors':>7} "
              f"{'Per 1k':>7} {'Repro':>6} {'Miss':>5} {'Long':>5}")
    lines = [header, "-" * len(header)]
    for s in sessions:
        rate = "—" if s.rate_per_1000 is None else f"{s.rate_per_1000:.2f}"
        lines.append(f"{s.date:<12} {s.mode:<7} {s.focus[:32]:<32} {s.learner_words:>7} "
                     f"{s.errors:>7} {rate:>7} {s.reproductions:>6} "
                     f"{s.reproductions_missed:>5} {s.long_turns:>5}")
    lines.append("Repro: re-productions that landed. Miss: asked for and not produced — "
                 "a missed repair or my own")
    lines.append("sentence copied back. Only the landed ones are treatment (P22).")

    if speech_rates:
        practice = practice_rates(sessions, mode=ANSWER_MODE)
        shared = sorted(set(practice) & set(speech_rates),
                        key=lambda c: -speech_rates[c])
        if shared:
            lines.append("")
            lines.append(f"Attended vs unmonitored, errors per 1,000 words "
                         f"(last {COMPARISON_SESSIONS} answering sessions against the latest "
                         f"recording — asking sessions are a different denominator):")
            lines.append(f"  {'Category':<42} {'Typed':>7} {'Spoken':>7}")
            for category in shared:
                lines.append(f"  {category[:42]:<42} {practice[category]:>7.2f} "
                             f"{speech_rates[category]:>7.2f}")
            lines.append("  Worse typed than spoken: the pattern isn't reliably known yet — "
                         "explain it. Clean typed and failing spoken: it's known and not "
                         "automatic — that needs volume, not another explanation.")

    vocabulary = format_vocabulary(vocabulary_trends(sessions))
    if vocabulary:
        lines += ["", vocabulary]

    untracked = format_provisional(provisional_trends(sessions))
    if untracked:
        lines += ["", untracked]

    lines.append("")
    lines.append(budget_line(sessions, recording_dates or [], today))
    return "\n".join(lines)


def format_vocabulary(trends: list[WordTrend]) -> str:
    """The banned-word record: whether the constraint held, and whether anything
    replaced the phrase rather than the sentence simply being rebuilt around it."""
    if not trends:
        return ""

    lines = ["Word constraints (P24) — how often the ban held, and whether anything "
             "replaced the phrase:",
             f"  {'Phrase':<28} {'Banned':>7} {'Slips':>6} {'Used':>6} {'Clean':>6}"]
    for t in trends:
        star = " *" if t.ready_to_retire else ""
        lines.append(f"  {t.phrase[:28]:<28} {t.sessions:>8} {t.slips:>6} {t.uses:>6} "
                     f"{t.clean_streak:>6}{star}")

    retired = [t.phrase for t in trends if t.ready_to_retire]
    if retired:
        lines.append(f"  * clean for {CLEAN_SESSIONS_TO_RETIRE} banned sessions running with "
                     f"replacements actually produced — candidates to drop from "
                     f"`Vocabulary To Replace`: {', '.join(retired)}")
    avoided = [t.phrase for t in trends if t.clean_streak and not t.uses]
    if avoided:
        lines.append(f"  Clean but with no replacement produced, which is usually the slot "
                     f"being dodged rather than filled: {', '.join(avoided)}")
    return "\n".join(lines)


def budget_line(sessions: list[PracticeSession], recording_dates: list[str],
                today: Optional[str]) -> str:
    """
    Rule 19's two counts, side by side. Public because the session brief
    (`voxlib.brief`) opens with it: the fortnight that contained six recordings
    and no practice is the first thing a practice session should see.

    The recording is the instrument and the corrected repetitions are the
    treatment, and the failure mode the rule was written for is a report that
    recommends five things to notice into a fortnight containing no corrected
    repetitions at all.
    """
    end = date_type.fromisoformat(today) if today else date_type.today()
    start = (end - timedelta(days=BUDGET_DAYS)).isoformat()

    recent = [s for s in sessions if s.date > start]
    recordings = [d for d in recording_dates if d > start]
    repetitions = sum(s.reproductions for s in recent)
    missed = sum(s.reproductions_missed for s in recent)

    line = (f"Last {BUDGET_DAYS} days: {len(recordings)} recording(s), {len(recent)} practice "
            f"session(s), {repetitions} corrected repetition(s)"
            + (f" ({missed} more asked for and not produced)." if missed else "."))
    if len(recordings) > len(recent):
        line += (" The instrument is running ahead of the treatment — rule 19: more "
                 "recordings don't improve the measurement, they consume the time the "
                 "practice needed.")
    elif not repetitions and recent:
        line += (" Practice sessions with no corrected repetitions in them are the failure "
                 "rule 19 describes (P22)."
                 + (" The repairs were asked for and none came back — the form isn't "
                    "available for production yet, whatever is known about it." if missed
                    else ""))
    return line


def _default_path() -> Path:
    return Path(__file__).parent.parent / "analysis" / "practice_history.csv"


def main(argv: list[str] | None = None) -> int:
    """`python -m voxlib.practice` — the practice history, and a way to append to
    it without hand-editing an append-only file."""
    import argparse

    analysis = _default_path().parent
    parser = argparse.ArgumentParser(
        prog="python -m voxlib.practice",
        description="Read or extend the conversation-practice history.",
    )
    parser.add_argument("--path", type=Path, default=_default_path(),
                        help="History CSV (default: analysis/practice_history.csv)")
    parser.add_argument("--mistakes", type=Path, default=analysis / "mistakes.csv",
                        help="Recording history, for the comparison and the budget line")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("show", help="Print the history (default)")

    start = sub.add_parser(
        "start",
        help="Open a practice session: level, focus, banned words, drill block (P14-P24)")
    start.add_argument("--date", default=date_type.today().isoformat())
    start.add_argument("--memory", type=Path, default=analysis / "memory.md")
    start.add_argument("--focus-log", type=Path,
                       default=analysis / "conversation_focus_log.md")
    start.add_argument("--drills-dir", type=Path, default=analysis.parent / "drills")
    start.add_argument("--item-history", type=Path, default=analysis / "drill_items.csv")
    start.add_argument("--pending", type=Path, default=analysis / "drill_pending.json")
    start.add_argument("--focus-category", metavar="NAME",
                       help="Override P15's choice — use the exact `## <Mistake Name>` heading")
    start.add_argument("--count", type=int, default=None,
                       help="Prompts in the opening block")
    start.add_argument("--patterns", type=int, default=None,
                       help="How many patterns the block spans")
    start.add_argument("--mode", choices=MODES, default=ANSWER_MODE,
                       help='Which practice mode is opening. "answer" builds the grammar '
                            'brief from memory.md (P14); "ask" builds Question Practice '
                            "Mode's brief instead — the budget, the warm-up block from "
                            "asking/drills, and this session's scenarios already selected "
                            "(Q2, Q12). They read different files and pick different things, "
                            "so the mode has to be declared rather than inferred.")
    start.add_argument("--scenarios-dir", type=Path, default=analysis.parent / "asking" /
                       "scenarios", help="Ask mode: where the scenario packs live")
    start.add_argument("--scenario-history", type=Path,
                       default=analysis / "asking_scenarios.csv",
                       help="Ask mode: which scenarios have run, and how they scored")
    start.add_argument("--asking-memory", type=Path, default=analysis / "asking_memory.md",
                       help="Ask mode: the question-practice tracker (Q16)")
    start.add_argument("--scenarios", type=int, default=None,
                       help="Ask mode: how many scenarios to draw (Q12: four to six)")
    start.add_argument("--no-drill", action="store_true",
                       help="Brief only — don't draw a block or touch the pending file")

    end = sub.add_parser(
        "end", help="Close a session: score the block, write the row, move the schedule on")
    end.add_argument("--date", default=date_type.today().isoformat())
    end.add_argument("--focus", default="",
                     help="The `## <Mistake Name>` heading drilled, or free text if none")
    end.add_argument("--words", type=int, required=True,
                     help="Words the learner produced this session — the denominator")
    end.add_argument("--reproductions", type=int, default=0,
                     help="P22 re-productions that LANDED — a copy-back is never one")
    end.add_argument("--reproductions-missed", type=int, default=0,
                     help="Re-productions asked for that did not land: the repair missed, "
                          "the structure was dodged, or my own sentence came back. Kept "
                          "apart from --reproductions because only the landed ones are "
                          "treatment, and a session that offered three and got none is not "
                          "a session that offered none.")
    end.add_argument("--long-turns", type=int, default=0, help="P23 long turns")
    end.add_argument("--word", action="append", default=[], metavar="PHRASE:SLIPS:USED",
                     help="One per banned phrase (P24): how many times it slipped out, and "
                          'how many times a replacement was produced. e.g. "you know:2:0". '
                          "Repeatable.")
    end.add_argument("--notes", default="")
    end.add_argument("--mode", choices=MODES, default=ANSWER_MODE, help='Which practice mode ran: "answer" for Conversation Practice Mode (Claude asks, you answer) or "ask" for Question Practice Mode (Claude gives a situation, you ask). They are different denominators and are never pooled into one rate.')
    end.add_argument("--focus-log", type=Path, default=analysis / "conversation_focus_log.md")
    end.add_argument("--drills-dir", type=Path, default=analysis.parent / "drills")
    end.add_argument("--drill-history", type=Path, default=analysis / "drills.csv")
    end.add_argument("--drill-items", type=Path, default=analysis / "drill_items.csv")
    end.add_argument("--pending", type=Path, default=analysis / "drill_pending.json")
    end.add_argument("--scenario", action="append", default=[],
                     metavar="NAME:MET/TOTAL:FAILED",
                     help="Ask mode (Q10): one scenario's result, e.g. "
                          "'standup-migration:2/4:register,followup'. Repeatable. Writes the "
                          "scenario history and adds the rows to asking_memory.md's two "
                          "tables, so the log stops being retyped by hand at the end of a "
                          "session. /TOTAL may be left off for a scenario in the pool.")
    end.add_argument("--scenarios-dir", type=Path,
                     default=analysis.parent / "asking" / "scenarios",
                     help="Ask mode: where the scenario packs live")
    end.add_argument("--scenario-history", type=Path, default=analysis / "asking_scenarios.csv",
                     help="Ask mode: the scenario history to append to")
    end.add_argument("--asking-memory", type=Path, default=analysis / "asking_memory.md",
                     help="Ask mode: the tracker whose log tables get this session's rows")
    end.add_argument("--dry-run", action="store_true",
                     help="Print what would be written without writing it")
    end.add_argument("errors", nargs="*", metavar="CATEGORY:COUNT",
                     help='One per category that produced an error, e.g. "Article Errors:3". '
                          "Nothing at all means a clean session.")

    add = sub.add_parser("add", help="Append one practice session")
    add.add_argument("--date", default=date_type.today().isoformat())
    add.add_argument("--focus", default="",
                     help="The `## <Mistake Name>` heading drilled, or free text if none")
    add.add_argument("--words", type=int, required=True,
                     help="Words the learner produced this session — the denominator")
    add.add_argument("--reproductions-missed", type=int, default=0,
                     help="Re-productions asked for that did not land (see `end`)")
    add.add_argument("--reproductions", type=int, default=0,
                     help="P22 re-productions they completed")
    add.add_argument("--long-turns", type=int, default=0,
                     help="P23 long turns they gave")
    add.add_argument("--notes", default="")
    add.add_argument("--mode", choices=MODES, default=ANSWER_MODE, help='Which practice mode ran: "answer" for Conversation Practice Mode (Claude asks, you answer) or "ask" for Question Practice Mode (Claude gives a situation, you ask). They are different denominators and are never pooled into one rate.')
    add.add_argument("errors", nargs="*", metavar="CATEGORY:COUNT",
                    help='One per category that produced an error, e.g. "Article Errors:3". '
                         "Nothing at all means a clean session.")

    args = parser.parse_args(argv)

    if args.command == "start":
        from voxlib import brief as brief_module

        if args.mode == ASK_MODE:
            # Ask mode's defaults live in this branch rather than in the flags:
            # a default of `drills/` on --drills-dir is right for the answering
            # brief and wrong here, and a mode that silently drew a grammar
            # prompt into a question block is the collision `asking/` exists to
            # prevent. Explicit flags still win.
            from voxlib import asking as asking_module

            defaults = _default_path().parent
            print(asking_module.render(
                today=args.date,
                scenarios_dir=args.scenarios_dir,
                drills_dir=(args.drills_dir if args.drills_dir != defaults.parent / "drills"
                            else defaults.parent / "asking" / "drills"),
                memory_path=args.asking_memory,
                history_path=args.scenario_history,
                practice_path=args.path,
                mistakes_path=args.mistakes,
                item_history=(args.item_history if args.item_history != defaults /
                              "drill_items.csv" else defaults / "asking_drill_items.csv"),
                pending=(args.pending if args.pending != defaults / "drill_pending.json"
                         else defaults / "asking_pending.json"),
                count=args.scenarios or asking_module.DEFAULT_SCENARIOS,
                with_block=not args.no_drill,
                block_size=args.count or brief_module.DEFAULT_BLOCK,
                patterns=args.patterns or brief_module.DEFAULT_PATTERNS,
            ))
            return 0

        print(brief_module.render(
            today=args.date,
            memory_path=args.memory,
            focus_log_path=args.focus_log,
            mistakes_path=args.mistakes,
            practice_path=args.path,
            drills_dir=args.drills_dir,
            item_history=args.item_history,
            pending=args.pending,
            with_block=not args.no_drill,
            block_size=args.count or brief_module.DEFAULT_BLOCK,
            patterns=args.patterns or brief_module.DEFAULT_PATTERNS,
            focus_override=args.focus_category,
        ))
        return 0

    if args.command in {"add", "end"}:
        errors: dict[str, int] = {}
        for raw in args.errors:
            category, _, count = raw.rpartition(_COUNT_SEPARATOR)
            if not category or not count.strip().isdigit():
                parser.error(f'Expected "Category:count", got {raw!r}')
            if category in errors:
                parser.error(f"{category!r} is listed twice — add the counts up instead.")
            if is_provisional(category) and not category.lstrip(PROVISIONAL_PREFIX).strip():
                parser.error(f'{raw!r} has no name after the "{PROVISIONAL_PREFIX}" — an '
                             f'untracked form is recorded as "?help me to X:1", quoting the '
                             f'form itself.')
            errors[category] = int(count)

    if args.command == "end":
        if args.mode == ASK_MODE:
            # The same switch `start --mode ask` makes, and for the same reason:
            # every drill default here points at the grammar pool, and a question
            # block scored into `drills.csv` would land in the trend the
            # recording workflow reads at step 4b. Q14 used to pass four flags to
            # avoid that, which is four chances to forget one.
            defaults = _default_path().parent
            for attribute, default, replacement in (
                    ("drills_dir", defaults.parent / "drills", defaults.parent / "asking" / "drills"),
                    ("drill_history", defaults / "drills.csv", defaults / "asking_drills.csv"),
                    ("drill_items", defaults / "drill_items.csv",
                     defaults / "asking_drill_items.csv"),
                    ("pending", defaults / "drill_pending.json",
                     defaults / "asking_pending.json")):
                if getattr(args, attribute) == default:
                    setattr(args, attribute, replacement)

        words: dict[str, WordResult] = {}
        for raw in args.word:
            head, _, used = raw.rpartition(_COUNT_SEPARATOR)
            phrase, _, slips = head.rpartition(_COUNT_SEPARATOR)
            if not phrase or not slips.strip().isdigit() or not used.strip().isdigit():
                parser.error(f'Expected "phrase:slips:used", got {raw!r}')
            if phrase in words:
                parser.error(f"{phrase!r} is listed twice — add the counts up instead.")
            words[phrase] = WordResult(slips=int(slips), uses=int(used))

        try:
            outcome = close_session(
                date=args.date, focus=args.focus, learner_words=args.words,
                errors_by_category=errors, reproductions=args.reproductions,
                long_turns=args.long_turns, vocabulary=words, notes=args.notes,
                mode=args.mode, reproductions_missed=args.reproductions_missed,
                history_path=args.path, focus_log_path=args.focus_log,
                pending=args.pending, drills_dir=args.drills_dir,
                drill_history=args.drill_history, drill_item_history=args.drill_items,
                scenarios=args.scenario, scenarios_dir=args.scenarios_dir,
                scenario_history=args.scenario_history, asking_memory=args.asking_memory,
                dry_run=args.dry_run)
        except ValueError as error:
            parser.error(str(error))
        print(format_outcome(outcome, dry_run=args.dry_run))
        return 0

    if args.command == "add":
        try:
            record_session(args.path, date=args.date, focus=args.focus,
                           learner_words=args.words, errors_by_category=errors,
                           reproductions=args.reproductions, long_turns=args.long_turns,
                           notes=args.notes, mode=args.mode,
                           reproductions_missed=args.reproductions_missed)
        except ValueError as error:
            parser.error(str(error))
        print(f"Recorded {args.date} in {args.path}: {args.words} words, "
              f"{sum(errors.values())} errors, {args.reproductions} re-productions.")
        return 0

    recording_dates: list[str] = []
    speech_rates: dict[str, float] = {}
    try:
        from voxlib import mistakes as mistakes_module

        rows = mistakes_module.load(args.mistakes)
        recording_dates = mistakes_module.session_dates(rows)
        speech_rates = {
            trend.category: trend.latest_rate
            for trend in mistakes_module.summarize(rows)
            if trend.latest_rate is not None
        }
    except Exception:  # missing or malformed — the practice table still stands alone
        logger.warning("Could not read %s; printing the practice history without the "
                       "comparison", args.mistakes)

    print(format_table(load(args.path), recording_dates=recording_dates,
                       speech_rates=speech_rates))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
