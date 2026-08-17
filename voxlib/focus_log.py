"""
`conversation_focus_log.md` — which patterns have been drilled in dialogue, and
when each is due back.

The schedule is spaced repetition: a pattern that holds up gets a longer gap
before it is checked again, and one that fails is checked tomorrow. P18 states
it as `Last drilled + min(2^Correct streak, 14)` days, which is a line of
arithmetic that was being done by hand, on a markdown table edited by hand, at
the end of a session — the point at which everything is already finished and the
temptation to skip a step is highest. A miscounted streak is invisible
afterwards: the file is the only record of it, so a wrong number simply becomes
the truth and the pattern comes back at the wrong time for weeks.

So the arithmetic lives here, and the table is rewritten rather than edited.

**Still markdown, deliberately.** The obvious move is a CSV like every other
history in `analysis/`, and it would be wrong: those files are append-only
records of what happened, whereas this one holds *current state* — four fields
that are overwritten every time a pattern is drilled. Nothing accumulates, there
is nothing to plot, and the whole file is short enough to read at a glance while
deciding what to practice. That is a document, not a dataset. What it needed was
not a different format but a writer that can do the arithmetic.

Everything outside the table is preserved on write, so notes can be kept in the
file without a session eating them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date as date_type
from datetime import timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TITLE = "# Conversation Focus Log"
COLUMNS = ["Mistake name", "Last drilled", "Correct streak", "Next due"]

# The ceiling on the gap, from P18. Two weeks is roughly the point past which a
# "pattern" being re-checked has stopped being practice and become an exam.
MAX_GAP_DAYS = 14


def table_rows(text: str) -> list[list[str]]:
    """
    Markdown table rows, minus the header and the `|---|` separator.

    Shared with `voxlib.brief`, which reads two hand-written documents of its
    own. Tolerant on purpose: these files are edited by a person, so a row with
    stray whitespace or a missing trailing pipe is normal input, not corruption.
    """
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells or all(set(c) <= {"-", ":"} for c in cells if c):
            continue
        rows.append(cells)
    return rows[1:] if rows else []


@dataclass
class FocusRow:
    category: str
    last_drilled: str
    streak: int
    next_due: str


@dataclass
class Change:
    """One row's before and after, for reporting back in chat."""
    category: str
    clean: bool
    streak: int
    next_due: str
    previous_streak: Optional[int] = None

    @property
    def is_new(self) -> bool:
        return self.previous_streak is None

    def __str__(self) -> str:
        held = "held up" if self.clean else "produced an error"
        return (f"{self.category}: {held} — streak "
                f"{'—' if self.is_new else self.previous_streak} → {self.streak}, "
                f"due {self.next_due}")


def load(path: Path) -> dict[str, FocusRow]:
    """The table, keyed by category. Missing file reads as an empty schedule —
    nothing has been drilled, which is a state, not an error."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    rows: dict[str, FocusRow] = {}
    for cells in table_rows(text):
        if len(cells) < 4 or not cells[0]:
            continue
        try:
            streak = int(cells[2])
        except ValueError:
            logger.warning("Unreadable streak %r for %r; treating it as 0", cells[2], cells[0])
            streak = 0
        rows[cells[0]] = FocusRow(category=cells[0], last_drilled=cells[1],
                                  streak=streak, next_due=cells[3])
    return rows


def due_date(streak: int, today: str) -> str:
    """P18's schedule: `today + min(2^streak, 14)` days.

    A failure is the same formula with the streak reset to 0, which lands on
    tomorrow — so there is one rule here rather than two, and the "reset to 0 and
    come back tomorrow" case is not a special case at all."""
    gap = min(2 ** max(streak, 0), MAX_GAP_DAYS)
    return (date_type.fromisoformat(today) + timedelta(days=gap)).isoformat()


def apply(rows: dict[str, FocusRow], drilled: dict[str, bool],
          today: str) -> tuple[dict[str, FocusRow], list[Change]]:
    """
    Move every drilled pattern's row on, and say what changed.

    `drilled` is `{category: held_up}`. A pattern that produced an error
    *anywhere* in the session is `False` — P18 counts a miss in the drill block
    the same as one made mid-conversation, because it is the same pattern
    failing under an easier condition.

    A pattern that was tested and came up clean gets `Last drilled` moved even
    if it never appeared elsewhere in the session: it was tested, and that is
    what the date records.
    """
    updated = dict(rows)
    changes: list[Change] = []

    for category, clean in drilled.items():
        previous = updated.get(category)
        streak = (previous.streak + 1) if (clean and previous) else (1 if clean else 0)
        due = due_date(streak, today)
        updated[category] = FocusRow(category=category, last_drilled=today,
                                     streak=streak, next_due=due)
        changes.append(Change(category=category, clean=clean, streak=streak, next_due=due,
                              previous_streak=previous.streak if previous else None))

    return updated, changes


def render(rows: dict[str, FocusRow], existing: str = "") -> str:
    """
    The document, with the table replaced and everything else kept.

    Row order follows the file, new patterns appended — so a diff between two
    sessions shows what actually changed rather than a reshuffle.
    """
    order = [cells[0] for cells in table_rows(existing) if cells and cells[0] in rows]
    order += [category for category in rows if category not in order]

    table = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    table += [f"| {rows[c].category} | {rows[c].last_drilled} | {rows[c].streak} "
              f"| {rows[c].next_due} |" for c in order]

    lines = existing.splitlines()
    first = next((i for i, line in enumerate(lines) if line.strip().startswith("|")), None)
    if first is None:
        prefix = lines or [TITLE, ""]
        return "\n".join([*prefix, *([""] if prefix[-1].strip() else []), *table]) + "\n"

    last = first
    while last + 1 < len(lines) and lines[last + 1].strip().startswith("|"):
        last += 1
    return "\n".join([*lines[:first], *table, *lines[last + 1:]]) + "\n"


def save(path: Path, rows: dict[str, FocusRow]) -> None:
    existing = ""
    if path.exists():
        existing = path.read_text(encoding="utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(rows, existing), encoding="utf-8")
    logger.info("Updated %s (%d patterns)", path, len(rows))


def record(path: Path, drilled: dict[str, bool], today: str) -> list[Change]:
    """`load`, `apply`, `save` — what the end of a practice session runs."""
    if not drilled:
        return []
    rows, changes = apply(load(path), drilled, today)
    save(path, rows)
    return changes
