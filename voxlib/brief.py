"""
The session brief — everything Conversation Practice Mode needs before its first
question, in one command.

P14 asks for five sources to be read at the start of every practice session:
`memory.md` (several hundred lines of prose), `conversation_focus_log.md`, the
drill list, the practice history and the mistake ranking. P15 then applies a
selection rule to them — most overdue first, unlogged patterns ahead of logged
ones, ties broken by impact and then by tier, a stalled pattern pulled forward —
and P24 picks two or three words to ban out of a markdown table.

None of that needs judgment. All of it was being done by hand, every session,
before a single question could be asked, and it cost more than the practice it
was setting up. That matters more than it sounds: rule 19's budget line exists
because recordings routinely outnumber practice sessions, and the friction that
produces sits at the *start* — a ten-minute session is impossible when the setup
alone takes several minutes.

So the reading and the selecting happen here, once, and the output is a brief:
level, focus, why that focus, the words to ban, how the last session went, and
the mixed drill block already drawn and written to the pending file.

Two things this deliberately does not do:

**It does not decide anything a person should.** Everything here is a rule from
CLAUDE.md carried out arithmetically, the same way `voxlib.mistakes` carries out
rule 15 instead of leaving the multiplication to be done by eye. Where a rule
says "prefer" rather than "always", the preference is encoded as a weight that
can be outvoted, not as a hard override.

**It does not write to `memory.md` or the focus log.** Practice mode reads the
first and owns the second, but the log is updated at the *end* of a session
(P18), and this runs at the beginning. Everything here is read-only apart from
the drill pending file, which is machine state `voxlib.drill` already owns.
"""

from __future__ import annotations

import logging
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# How many prompts the opening block asks, and across how many patterns. Both
# match `voxlib.drill`'s own defaults for a mixed block; named here so the brief
# can say what it drew without importing them as magic numbers.
DEFAULT_BLOCK = 6
DEFAULT_PATTERNS = 3

# Words banned per session (P24). Three is the cap the rule sets, for the same
# reason general rule 20 allows one target in a recording: a constraint has to be
# holdable while talking.
VOCABULARY_SLOTS = 3

# P15 says to break a tie on impact, and where impact is close to prefer the
# clarity tier — a typed dialogue is the one place a meaning-breaking pattern can
# be caught mid-sentence. "Close" has to be a number to be a sort order, and this
# is it: clarity wins any comparison it loses by less than 15%, and loses any it
# loses by more. Deliberately small. It is a tie-break, not a second ranking.
CLARITY_BONUS = 1.15


# --- what gets parsed out of memory.md ---------------------------------------

@dataclass
class VocabularyItem:
    """One row of `Vocabulary To Replace`."""
    phrase: str          # the left cell as written, e.g. 'nice (for anything positive)'
    replacement: str     # the right cell, trimmed to the suggestion itself

    @property
    def word(self) -> str:
        """The phrase without its parenthetical gloss — what actually gets
        banned, and what a priority line is matched against."""
        return self.phrase.split("(")[0].strip() or self.phrase


@dataclass
class Memory:
    cefr: str = ""
    persistent: list[str] = field(default_factory=list)   # `## <Mistake Name>` headings
    priorities: list[str] = field(default_factory=list)   # the numbered lines, as written
    vocabulary: list[VocabularyItem] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return bool(self.persistent or self.vocabulary or self.cefr)


def _section(text: str, heading: str) -> str:
    """The body under a top-level `# heading`, up to the next one.

    Top-level only: `# Improvements` also contains `## <Mistake Name>` entries,
    and a parser that scanned the whole document for them would offer patterns
    that have already been resolved as candidates to drill."""
    match = re.search(rf"^#\s+{re.escape(heading)}\s*$", text, flags=re.M)
    if not match:
        return ""
    rest = text[match.end():]
    following = re.search(r"^#\s+\S", rest, flags=re.M)
    return rest[: following.start()] if following else rest


def _table_rows(section: str) -> list[list[str]]:
    """Markdown table rows, minus the header and the `|---|` separator."""
    rows = []
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells or all(set(c) <= {"-", ":"} for c in cells if c):
            continue
        rows.append(cells)
    return rows[1:] if rows else []


def _trim_note(cell: str) -> str:
    """The suggestion without the running commentary after it.

    The right-hand column carries counts and dates as well as alternatives —
    "a silent pause — N uses last session, down from M" — which is useful in the
    document and unusable as an instruction to hold while speaking."""
    return re.sub(r"\*+", "", cell.split(" — ")[0]).strip()


def parse_memory(path: Path) -> Memory:
    """
    The four things practice mode needs out of `memory.md`.

    Everything else in that file is written for a person to read, and this
    deliberately leaves it alone: the point is not to turn `memory.md` into a
    data format, it is to stop re-reading 300 lines of prose to recover a CEFR
    estimate, a list of headings and two columns of a table.

    Returns an empty `Memory` rather than raising if the file is missing or
    shaped differently — P14 says never to block on it.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        logger.warning("No readable memory at %s; the brief will fall back to topics", path)
        return Memory()

    cefr = ""
    level = re.search(r"^Estimated CEFR:\s*(.+)$", _section(text, "Current English Level"),
                      flags=re.M)
    if level:
        cefr = level.group(1).strip()

    persistent = re.findall(r"^##\s+(.+?)\s*$",
                            _section(text, "Persistent Grammar Mistakes"), flags=re.M)

    priorities = [line.strip() for line in
                  re.findall(r"^\d+\.\s+(.+)$", _section(text, "Current Priorities"), flags=re.M)]

    vocabulary = [
        VocabularyItem(phrase=re.sub(r"\*+", "", row[0]).strip(), replacement=_trim_note(row[1]))
        for row in _table_rows(_section(text, "Vocabulary To Replace"))
        if len(row) >= 2 and row[0]
    ]

    return Memory(cefr=cefr, persistent=persistent, priorities=priorities,
                  vocabulary=vocabulary)


# --- the focus log ------------------------------------------------------------

@dataclass
class FocusRow:
    category: str
    last_drilled: str
    streak: int
    next_due: str


def parse_focus_log(path: Path) -> dict[str, FocusRow]:
    """`conversation_focus_log.md`'s table, keyed by category.

    Still markdown, still written by hand at the end of a session (P18). Read
    here rather than migrated, because this command only needs to *read* it —
    turning it into data belongs with whatever ends up writing it."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    rows: dict[str, FocusRow] = {}
    for cells in _table_rows(text):
        if len(cells) < 4 or not cells[0]:
            continue
        try:
            streak = int(cells[2])
        except ValueError:
            streak = 0
        rows[cells[0]] = FocusRow(category=cells[0], last_drilled=cells[1],
                                  streak=streak, next_due=cells[3])
    return rows


# --- choosing the focus (P15) -------------------------------------------------

@dataclass
class FocusChoice:
    category: str
    reason: str                       # why this one, in one line
    tier: str = ""
    impact: Optional[float] = None
    streak: int = 0
    last_drilled: str = ""
    stalled: bool = False
    drill: Optional[str] = None       # the drill training it, if one exists
    drill_target: str = ""
    runners_up: list[str] = field(default_factory=list)


def choose_focus(candidates: list[str], log: dict[str, FocusRow],
                 trends: dict, today: str) -> Optional[FocusChoice]:
    """
    P15, carried out rather than re-argued.

    The order, and where each part comes from:

    1. **Most overdue first**, by `Next due`. A category with no logged row is
       more overdue than any category that has one — it has never been drilled
       here at all, so nothing says it holds up.
    2. **A stalled pattern is pulled forward** to today if its `Next due` is
       later. Rule 18 calls drilling it here the changed approach, and P15 makes
       it a strong candidate "regardless of its Next due" — but a *strong
       candidate* is not an override, so it enters the running rather than
       winning outright.
    3. **Ties break on impact**, with the clarity tier weighted by
       `CLARITY_BONUS`.

    `trends` is `{category: CategoryTrend}` from `voxlib.mistakes.summarize`.
    A candidate missing from it is still eligible — it is a tracked pattern
    nobody has counted yet — it simply sorts last among equally due ones.
    """
    if not candidates:
        return None

    def sort_key(category: str) -> tuple:
        row = log.get(category)
        trend = trends.get(category)
        stalled = bool(trend and trend.stalled)

        if row is None:
            due = ""                                     # never drilled: most overdue
        elif stalled and row.next_due > today:
            due = today                                  # pulled forward
        else:
            due = row.next_due

        impact = trend.impact if trend else 0.0
        if trend and trend.tier == "clarity":
            impact *= CLARITY_BONUS
        return (due, -impact, category)

    ordered = sorted(candidates, key=sort_key)
    category = ordered[0]
    row = log.get(category)
    trend = trends.get(category)
    stalled = bool(trend and trend.stalled)

    if row is None:
        reason = "never drilled in practice mode — unlogged patterns go first (P15)"
    elif row.next_due <= today:
        reason = f"due {row.next_due}, last drilled {row.last_drilled}"
    elif stalled:
        reason = (f"not due until {row.next_due}, pulled forward: no better than 3 measured "
                  f"sessions ago in speech, so drilling it here is the changed approach "
                  f"(rule 18)")
    else:
        reason = f"nothing is overdue — this is the next one up ({row.next_due})"

    return FocusChoice(
        category=category,
        reason=reason,
        tier=trend.tier if trend else "",
        impact=trend.impact if trend else None,
        streak=row.streak if row else 0,
        last_drilled=row.last_drilled if row else "",
        stalled=stalled,
        runners_up=ordered[1:3],
    )


# --- choosing the words (P24) -------------------------------------------------

def choose_vocabulary(items: list[VocabularyItem], priorities: list[str],
                      rotation: int = 0, slots: int = VOCABULARY_SLOTS) -> list[VocabularyItem]:
    """
    Which words to ban this session.

    One slot is pinned to whatever `Current Priorities` already names, because
    rule 17 reserves a place in that ranking for fluency or vocabulary and the
    analysis has therefore already decided which word is costing the most — at
    this level a single intensifier or connector can outrun every grammar
    category in the table. Re-deciding it here would be a second, worse ranking
    of the same thing.

    The remaining slots rotate through the table. Without rotation the same two
    or three rows would be banned every session forever and the other dozen
    would never be practised; with it, the list is a rota rather than a fossil.
    The offset is the number of practice sessions already recorded, so it
    advances on its own and two runs of this command on the same day agree.
    """
    if not items or slots <= 0:
        return []

    priority_text = " ".join(priorities).lower()
    pinned = next((i for i in items if len(i.word) > 2 and i.word.lower() in priority_text), None)

    rest = [i for i in items if i is not pinned]
    offset = rotation % len(rest) if rest else 0
    rotated = rest[offset:] + rest[:offset]

    chosen = ([pinned] if pinned else []) + rotated
    return chosen[:slots]


# --- the opening drill block (P19) -------------------------------------------

@dataclass
class Block:
    prompts: list[str]
    patterns: int
    replaced_pending: bool = False


def draw_block(*, drills_dir: Path, item_history: Path, mistakes: Path, pending: Path,
               focus_drill: Optional[str], count: int = DEFAULT_BLOCK,
               patterns: int = DEFAULT_PATTERNS) -> Optional[Block]:
    """
    The mixed block, drawn and written to the pending file exactly as
    `drill next --mixed --include <focus>` would.

    `focus_drill` is optional on purpose. P19 used to be read as "no drill for
    the focus, no block", which skipped the block entirely and left those
    sessions without a single scored item. The block runs either way; the focus
    is pinned into it when it has a drill.
    """
    from voxlib import drill as drill_module

    try:
        pool = drill_module.load_all(drills_dir)
    except Exception:
        logger.warning("Could not load drills from %s; the session runs as conversation",
                       drills_dir, exc_info=True)
        return None
    if not pool:
        return None

    included = [d for d in pool if d.name == focus_drill]
    ranked = included + [d for d in drill_module.priority_order(pool, mistakes)
                         if d.name != focus_drill]
    chosen = drill_module.select_mixed(
        ranked, drill_module.load_item_history(item_history), count, patterns=patterns)
    if not chosen:
        return None

    replaced = pending.exists()
    drill_module.write_mixed_pending(pending, chosen)
    return Block(prompts=[item.prompt for _, item in chosen],
                 patterns=len({d.name for d, _ in chosen}),
                 replaced_pending=replaced)


# --- the brief ----------------------------------------------------------------

@dataclass
class Brief:
    date: str
    cefr: str
    focus: Optional[FocusChoice]
    vocabulary: list[VocabularyItem]
    block: Optional[Block]
    last_session: str
    budget: str
    typed_vs_spoken: str = ""
    notes: list[str] = field(default_factory=list)


def build(*, today: str, memory_path: Path, focus_log_path: Path, mistakes_path: Path,
          practice_path: Path, drills_dir: Path, item_history: Path, pending: Path,
          with_block: bool = True, block_size: int = DEFAULT_BLOCK,
          patterns: int = DEFAULT_PATTERNS, focus_override: Optional[str] = None) -> Brief:
    """Read all five sources, apply P15 and P24, draw the block."""
    from voxlib import mistakes as mistakes_module
    from voxlib import practice as practice_module

    memory = parse_memory(memory_path)
    log = parse_focus_log(focus_log_path)
    notes: list[str] = []

    trends: dict = {}
    recording_dates: list[str] = []
    speech_rates: dict[str, float] = {}
    try:
        rows = mistakes_module.load(mistakes_path)
        recording_dates = mistakes_module.session_dates(rows)
        for trend in mistakes_module.summarize(rows):
            trends[trend.category] = trend
            if trend.latest_rate is not None:
                speech_rates[trend.category] = trend.latest_rate
    except Exception:
        logger.warning("Could not read %s; the focus falls back to the schedule alone",
                       mistakes_path)

    sessions = practice_module.load(practice_path)

    # P15: candidates are the `Persistent Grammar Mistakes` headings. Falling back
    # to the tracked categories keeps a missing memory.md from emptying the list
    # entirely — a pattern in mistakes.csv is a pattern worth drilling.
    candidates = memory.persistent or sorted(trends)
    if not memory.usable:
        notes.append(f"No readable memory at {memory_path} — running on the mistake history "
                     f"alone (P14: never block on it).")
    if not candidates:
        notes.append("Nothing tracked as persistent yet — pick a topic normally (P10) and "
                     "skip the focus announcement (P16).")

    if focus_override:
        # A deliberate override, not a bug: the schedule is a default, and there
        # are sessions where the person knows what they want to work on. Said out
        # loud so a brief that ignored the schedule never looks like one that
        # applied it.
        if focus_override not in candidates:
            notes.append(f"{focus_override!r} is not a tracked persistent pattern — drilling "
                         f"it anyway, but nothing will join it to mistakes.csv.")
        focus = choose_focus([focus_override], log, trends, today)
        if focus:
            focus.reason = "chosen by hand, overriding the P15 schedule"
    else:
        focus = choose_focus(candidates, log, trends, today)

    if focus:
        try:
            from voxlib import drill as drill_module

            for d in drill_module.load_all(drills_dir):
                if d.category == focus.category:
                    focus.drill, focus.drill_target = d.name, d.target
                    break
        except Exception:
            logger.warning("Could not match a drill to %s", focus.category, exc_info=True)

    vocabulary = choose_vocabulary(memory.vocabulary, memory.priorities, rotation=len(sessions))

    block = None
    if with_block:
        block = draw_block(drills_dir=drills_dir, item_history=item_history,
                           mistakes=mistakes_path, pending=pending,
                           focus_drill=focus.drill if focus else None,
                           count=block_size, patterns=patterns)
        if block is None:
            notes.append("No drills to draw from — run the session as a normal conversation "
                         "and don't improvise prompts to score by hand (P19).")
        elif block.replaced_pending:
            notes.append("An unscored block from an earlier session was replaced. Its answers "
                         "can no longer be scored.")
        elif focus and not focus.drill:
            notes.append(f"No drill trains {focus.category} — the block still runs, from the "
                         f"highest-impact patterns that do have one (P19). Writing one is the "
                         f"changed approach if this keeps recurring.")

    if sessions:
        last = sessions[-1]
        rate = "—" if last.rate_per_1000 is None else f"{last.rate_per_1000:.2f}/1k"
        last_session = (f"{last.date} · {last.focus or 'no focus'} · {last.learner_words} words · "
                        f"{last.errors} errors ({rate}) · {last.reproductions} re-productions")
    else:
        last_session = "none recorded yet"

    typed_vs_spoken = ""
    if focus:
        typed = practice_module.practice_rates(sessions).get(focus.category)
        spoken = speech_rates.get(focus.category)
        if typed is not None and spoken is not None:
            typed_vs_spoken = (
                f"{typed:.2f}/1k typed vs {spoken:.2f}/1k spoken — "
                + ("known but not automatic: this needs volume of corrected production, not "
                   "another explanation" if typed < spoken else
                   "failing under attention too: this one still needs teaching"))

    return Brief(
        date=today,
        cefr=memory.cefr,
        focus=focus,
        vocabulary=vocabulary,
        block=block,
        last_session=last_session,
        budget=practice_module.budget_line(sessions, recording_dates, today),
        typed_vs_spoken=typed_vs_spoken,
        notes=notes,
    )


def format_brief(brief: Brief) -> str:
    """
    Plain text, and safe to have on screen while answering.

    Nothing here is withheld from the learner except what `voxlib.drill` already
    withholds: the model answers, and which pattern each prompt belongs to. The
    focus is named because P16 announces it out loud anyway.
    """
    label = "{:<13}".format
    lines = [f"PRACTICE BRIEF — {brief.date}", "=" * 72, ""]

    lines.append(label("Level") + (brief.cefr or "unknown — start around B1+ (P8)"))

    if brief.focus:
        focus = brief.focus
        lines.append(label("Focus") + focus.category)
        detail = [focus.reason]
        if focus.impact is not None:
            detail.append(f"{focus.tier} tier, impact {focus.impact:.2f}")
        if focus.last_drilled:
            detail.append(f"streak {focus.streak}")
        lines.append(label("") + " · ".join(detail))
        if focus.drill:
            lines.append(label("") + f"drill: {focus.drill} — {focus.drill_target}")
        if brief.typed_vs_spoken:
            lines.append(label("") + brief.typed_vs_spoken)
        if focus.runners_up:
            lines.append(label("Also due") + " · ".join(focus.runners_up))
    else:
        lines.append(label("Focus") + "none — normal topic selection (P10, P15)")

    if brief.vocabulary:
        lines.append(label("Ban") + " · ".join(v.word for v in brief.vocabulary))
        for v in brief.vocabulary:
            lines.append(label("") + f"{v.word} → {v.replacement}")

    lines += ["", label("Last session") + brief.last_session, label("Budget") + brief.budget]

    if brief.block:
        lines += ["", f"Mixed block — {len(brief.block.prompts)} prompts, "
                      f"{brief.block.patterns} patterns, interleaved.",
                  "Ask them one at a time under P1-P6. Which pattern each prompt tests is "
                  "deliberately not shown —", "naming it restores the priming the block "
                  "exists to remove. Correct from your own English.", ""]
        lines += [f"  {i:>2}. {prompt}" for i, prompt in enumerate(brief.block.prompts, 1)]

    if brief.notes:
        lines.append("")
        lines += [f"! {note}" for note in brief.notes]

    lines += ["", "-" * 72, "At the end of the session:"]
    if brief.block:
        lines.append("  python -m voxlib.drill score --mixed --answers <their answers, one "
                     "per line>")
    # shlex, because half the category names contain double quotes of their own
    # — `Verb Complementation With "Propose"/"Allow"` pasted between quotes is a
    # broken command, and a copy-pasteable line that doesn't run is worse than no
    # line at all.
    focus_name = shlex.quote(brief.focus.category if brief.focus else "")
    lines.append(f"  python -m voxlib.practice add --date {brief.date} --focus {focus_name} "
                 f"\\\n      --words <their words> --reproductions <P22> --long-turns <P23> "
                 f"'Category:count'")
    lines.append("  then update analysis/conversation_focus_log.md for every pattern the "
                 "block asked about (P18).")
    return "\n".join(lines)


def render(**kwargs) -> str:
    """`build` and `format_brief` in one call — what the CLI runs."""
    return format_brief(build(**kwargs))
