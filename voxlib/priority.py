"""
What to work on — the crossing, done once, in one place.

Four files each answer part of "what should I do next" and none of them answers
it alone. `mistakes.summarize` ranks by impact but has no idea whether the
pattern has ever been drilled. `drills.csv` says whether the form is known but
not whether it survives speech. `conversation_focus_log.md` says what is late
but not what is important. `practice_history.csv` says whether anything is being
treated at all. The crossing was being done three times — by the coach in prose
each session, by `brief.choose_focus` when a practice session opens, and by a
hardcoded `if`-chain inside the dashboard — and the three could disagree.

**Why this is a sort and not a score.** The obvious design is
`priority = w1*frequency + w2*severity + w3*trend + w4*lateness`, and it is the
wrong one. Weights nobody chose are weights nobody can argue with, and this
project has already been burned once by exactly that: `impact` began life as
`severity * rate` and turned out to be a frequency ranking wearing a severity
costume, which nobody could see until the ranking was read back against the
data. A weighted sum of four judgments would hide four such mistakes instead of
one.

So the order is lexicographic and every step is nameable:

  0. **Loop blockers.** A recording transcribed but never analysed, or a
     treatment side that has stopped. These outrank every pattern because they
     invalidate the ranking rather than appearing in it — a ranking computed
     from an out-of-date history is answering a question about last month, and a
     perfect ranking acted on by nobody is not a plan.

  1. **Treatability.** The rung a pattern fails on decides whether any action
     exists and which one, so it sorts before how much the pattern costs. This
     is the part that cannot be expressed as a number at all: "knows it and
     still says it wrong" and "never drilled" are not two values of one
     quantity, they are different problems, and the response to the first
     (produce it) is the opposite of the response to the second (drill it).

  2. **Impact**, within a class. `severity * sqrt(recency-weighted rate)`,
     unchanged, straight from `mistakes.summarize`.

  3. **The portfolio**, per rule 17: at least two clarity-tier items, at most
     two polish-tier, one slot held for fluency or vocabulary. Applied to the
     slate rather than to the ranking, because it is a constraint on what to
     *show* — a frequent survivable error legitimately owns several top slots
     and would otherwise crowd out everything the listener actually loses.

  4. **Annotations.** Stalled, overdue, thin, frozen, not-separable. These
     explain a row; they never move one. The distinction matters more than it
     looks: if lateness multiplied the score, the ranking would become a
     function of how long since you last practised rather than of what is wrong
     with your English, and a fortnight off would silently reorder the whole
     table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from . import mistakes

# What it takes for "the form is known" to be a claim about the speaker rather
# than about a small sample. A drill is five items by design; a perfect score
# over one item is not evidence, and a mixed block can carry a single item of a
# pattern — which would otherwise read as a perfect score on the harder
# condition.
MIN_DRILL_ITEMS = 5
FORM_KNOWN_ACCURACY = 0.8

# The rungs, in the order a pattern climbs them. The names are the ones
# CLAUDE.md gives the files: drills.csv is what the owner knows,
# practice_history.csv is what they produce while attending, mistakes.csv is
# what they produce when they have forgotten they are being measured.
LADDER_STATES = {
    "no-drill": "No drill yet",
    "thin-evidence": "Too few drill items to tell",
    "form-unreliable": "Form not reliable yet",
    "automaticity-gap": "Knows it, still says it wrong",
    "clean": "Clean in the last measured session",
    "retiring": "Ready to retire",
}

# What to do about each. The short form is what a to-do line needs — one verb,
# readable at a glance — and the long form is the reason, which matters most for
# the state at the top, where the obvious response (drill it) is the wrong one.
LADDER_ACTIONS = {
    "automaticity-gap": ("Produce it in dialogue",
                         "the form is known and more drilling will not fix it"),
    "form-unreliable": ("Keep drilling it",
                        "the form itself is not reliable yet"),
    "no-drill": ("Write a drill for it",
                 "nothing above rung 3 can be measured until one exists"),
    "thin-evidence": ("Drill it again",
                      "one item is not a score"),
    "clean": ("Watch it",
              "one clean session is not a streak"),
    "retiring": ("Retire it",
                 "move it to Improvements in memory.md"),
}

# Treatability order. Lower sorts first. A state carrying a clear, different
# action outranks one whose action is "find out more", which outranks one with
# nothing to do.
TREATABILITY = {
    "automaticity-gap": 0,
    "form-unreliable": 1,
    "no-drill": 2,
    "thin-evidence": 3,
    "clean": 4,
    "retiring": 5,
}

# Rule 17's portfolio, as numbers.
MIN_CLARITY = 2
MAX_POLISH = 2
SLATE = 5


def ladder_state(*, ready_for_improvements: bool, latest_rate: Optional[float],
                 drill: Optional[dict]) -> str:
    """Which rung a pattern is stuck on.

    The order matters. A pattern clean for three sessions is resolved whether or
    not it was ever drilled, so that is checked first; and "knows it, still says
    it wrong" is only claimed once there is enough drill evidence to support the
    first half of the sentence.
    """
    if ready_for_improvements:
        return "retiring"
    if not drill or not drill.get("attempted"):
        return "no-drill"
    if drill["attempted"] < MIN_DRILL_ITEMS:
        return "thin-evidence"
    if (drill.get("accuracy") or 0) < FORM_KNOWN_ACCURACY:
        return "form-unreliable"
    if latest_rate:
        return "automaticity-gap"
    return "clean"


@dataclass
class Blocker:
    """Something that has to happen before the ranking below it means anything."""
    kind: str
    title: str
    detail: str
    anchor: str = "loop"


@dataclass
class Target:
    """One pattern, ranked, with everything needed to say why it is here."""
    category: str
    slug: str
    state: str
    action: str                    # the short imperative
    action_why: str                # and the reason behind it
    tier: str
    severity: int
    impact: float
    latest_rate: Optional[float]
    latest_count: Optional[int]
    drill: Optional[dict]
    flags: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    slot: str = ""                 # "clarity" / "polish" — which rule-17 slot it filled

    @property
    def why(self) -> str:
        return "; ".join(self.reasons)


def blockers(*, unanalysed: list[str], loop, attended_sessions: int,
             asking_sessions: int,
             dialogue_overdue: Optional[list[tuple[str, str]]] = None) -> list[Blocker]:
    """Stage 0 — the things that outrank every pattern.

    `loop` is a `practice.LoopState`. Passed in rather than built here because
    it needs the focus-log schedule, which this module has no business reading.
    """
    out: list[Blocker] = []
    dialogue_overdue = dialogue_overdue or []

    for pending in unanalysed[:1]:
        out.append(Blocker(
            kind="unanalysed",
            title=f"Analyse the {pending} recording",
            detail="the pipeline has transcribed it, but no session has read it — so it is "
                   "in the timeline and the speech panel and in none of the grammar "
                   "sections, and every ranking here predates it",
            anchor="timeline",
        ))

    # One blocker, not two. "Nothing is being treated" and "no conversation
    # practice has ever been recorded" are the same instruction from two
    # directions, and printing both as separate to-dos is how a list of five
    # becomes a list of two facts — the failure rule 20 describes, committed by
    # the page that is supposed to enforce it.
    # The instrument has to be running for "the instrument is ahead of the
    # treatment" to be the finding. A project where nothing has happened at all
    # is dormant or new, and telling it its loop is broken is telling a fresh
    # clone it is failing — which is the page's worst available failure mode.
    stopped = (loop is not None and loop.train.state in ("stale", "never")
               and loop.measure.state in ("ok", "warn"))
    unbridged = not attended_sessions and asking_sessions

    if stopped or unbridged:
        if stopped:
            elapsed = ("nothing has ever been treated" if loop.train.state == "never"
                       else f"{loop.train.days} days since the last corrected repetition")
            detail = (f"{elapsed}, against {loop.recordings_in_window} recording(s) in the "
                      f"last {loop.window_days} days. The recording measures and only "
                      f"corrected repetitions train (rule 19), so every target below is "
                      f"being described rather than worked on")
        else:
            detail = ("the recordings are current, but nothing bridges them and the drills")
        if unbridged:
            detail += (f". It has to be conversation practice specifically: all "
                       f"{asking_sessions} sessions on record were question practice, so "
                       f"rung 2 is empty for every grammar pattern")
        out.append(Blocker(
            kind="treatment-stopped",
            title="Run a practice session",
            detail=detail,
        ))

    # Patterns the recording cannot measure at all — question-asking is not a
    # grammar category, so these have a rung 1 and a rung 2 and no rung 3. They
    # are kept out of the ranked table for that reason, and being off the table
    # must not mean being off the list: nothing else on this page would ever
    # mention them again.
    if dialogue_overdue:
        oldest = min(dialogue_overdue, key=lambda o: o[1])
        names = ", ".join(c for c, _ in sorted(dialogue_overdue, key=lambda o: o[1])[:3])
        out.append(Blocker(
            kind="overdue-dialogue",
            title=f"{len(dialogue_overdue)} question-practice slot(s) are overdue",
            detail=f"the oldest since {oldest[1]} — {names}"
                   + (", …" if len(dialogue_overdue) > 3 else "")
                   + ". The recording cannot measure these, so the schedule is the only "
                     "thing that tracks them",
            anchor="askpatterns",
        ))

    return out


def _reasons(trend: mistakes.CategoryTrend, state: str, drill: Optional[dict],
             overdue_days: Optional[int], frozen: bool) -> tuple[list[str], list[str]]:
    """The flags a row carries, and the sentence fragments that justify its place.

    Kept together because they come from the same facts, and kept out of the
    sort because none of them moves a row.
    """
    flags, reasons = [], []

    if state == "automaticity-gap" and drill:
        reasons.append(f"{round((drill['accuracy'] or 0) * 100)}% correct over "
                       f"{drill['attempted']} drill items, still "
                       f"{trend.latest_rate} per 1,000 words in speech")
    if trend.stalled:
        flags.append("stalled")
        reasons.append(f"no better than {mistakes.STALL_WINDOW} measured sessions ago — "
                       "change the approach, don't restate the goal (rule 18)")
    if trend.thin:
        flags.append("thin")
        reasons.append(f"ranked on {trend.evidence} instances in total, so the ranking is a "
                       f"guess about a rare event")
    if trend.reported_direction == "not separable yet":
        flags.append("not-separable")
    if overdue_days is not None:
        flags.append("overdue")
        reasons.append(f"review {overdue_days} days late")
    if frozen:
        flags.append("frozen")
        reasons.append(f"no chance to make it in the last {mistakes.STALL_WINDOW} sessions, "
                       "so its absence streak is frozen rather than earned")
    return flags, reasons


def rank(trends: list[mistakes.CategoryTrend], *, drills: dict[str, dict],
         slugs: dict[str, str], overdue: Optional[dict[str, int]] = None,
         frozen: Optional[set[str]] = None) -> list[Target]:
    """Every tracked pattern, in the order stages 1-2 put them."""
    overdue = overdue or {}
    frozen = frozen or set()
    evidence_by_category = {t.category: t.evidence for t in trends}

    targets = []
    for trend in trends:
        drill = drills.get(trend.category)
        state = ladder_state(ready_for_improvements=trend.ready_for_improvements,
                             latest_rate=trend.latest_rate, drill=drill)
        flags, reasons = _reasons(trend, state, drill, overdue.get(trend.category),
                                  trend.category in frozen)
        targets.append(Target(
            category=trend.category,
            slug=slugs.get(trend.category, ""),
            state=state,
            action=LADDER_ACTIONS[state][0],
            action_why=LADDER_ACTIONS[state][1],
            tier=trend.tier,
            severity=trend.severity,
            impact=trend.impact,
            latest_rate=trend.latest_rate,
            latest_count=trend.latest_count,
            drill=drill,
            flags=flags,
            reasons=reasons,
        ))

    # Thin evidence demotes within a class, and never across one. Impact will
    # happily nominate a severity-5 category observed three times in one
    # session, and the action attached to a `no-drill` row is "build something"
    # — an investment, spent on a guess about a rare event. The class still
    # sorts first, because what to do about a pattern does not depend on how
    # many instances are behind it; only which one to do it to first does.
    targets.sort(key=lambda t: (TREATABILITY[t.state], "thin" in t.flags,
                                -t.impact, t.category))

    # "The highest-impact one with enough instances to build a drill from" is
    # true of exactly one row, and it is the sentence that explains why the
    # ranking skipped the rarer, more serious category above it. Attached after
    # the sort, because before it nothing knows which row that is — written into
    # every no-drill row instead, it said the same superlative five times.
    first = next((t for t in targets
                  if t.state == "no-drill" and "thin" not in t.flags), None)
    if first is not None:
        evidence = evidence_by_category.get(first.category)
        first.reasons.insert(0, "the highest-impact pattern with no drill and enough "
                                "instances on record to build one from"
                             + (f" — {evidence} of them" if evidence else ""))
    return targets


def slate(targets: list[Target], size: int = SLATE) -> list[Target]:
    """
    Rule 17's portfolio: the ranked list narrowed to what to actually show.

    At least `MIN_CLARITY` clarity-tier items and at most `MAX_POLISH` polish
    ones, filled in ranked order. A tier with nothing in it leaves its slot
    empty rather than being padded — the rule says so, and a padded slate is how
    a category with no evidence behind it ends up looking like a priority.

    Patterns with nothing to do about them (`clean`, `retiring`) never take a
    slot: they belong in what's working, not in what to work on.
    """
    actionable = [t for t in targets if t.state not in ("clean", "retiring")]
    clarity = [t for t in actionable if t.tier == "clarity"]

    chosen: list[Target] = []
    for target in clarity[:min(MIN_CLARITY, size)]:
        target.slot = "clarity"
        chosen.append(target)

    # Then by rank, respecting the polish ceiling.
    for target in actionable:
        if len(chosen) >= size:
            break
        if target in chosen:
            continue
        if target.tier == "polish" and sum(1 for c in chosen if c.tier == "polish") >= MAX_POLISH:
            continue
        target.slot = target.tier
        chosen.append(target)

    # The same key `rank` used, thin demotion included. Sorting on impact alone
    # here put the demoted row straight back on top — and since `_actions` takes
    # the slate in order, a category seen three times in one session became the
    # single bolded "one thing to do", which is the exact investment-on-a-guess
    # the demotion exists to prevent. The superlative `rank` attached to the
    # best-evidenced row then appeared underneath it, contradicting it.
    chosen.sort(key=lambda t: (TREATABILITY[t.state], "thin" in t.flags,
                               -t.impact, t.category))
    return chosen
