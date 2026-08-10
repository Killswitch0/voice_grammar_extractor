"""
Drills — the one place in this project where a number has a denominator.

Everything else here counts errors: so many article mistakes in so many words.
What that cannot say is *out of how many chances*, because nothing knows how
many singular countable nouns were spoken. The missing denominator is not a
detail. A speaker who moves from short conversational turns to a long monologue
produces far more noun phrases per hundred words, so their error rate can rise
while their accuracy improves — and in a per-1,000-words series the two are
indistinguishable. A rising rate can therefore send a category to the top of the
priority list for weeks on evidence that never supported it.

A drill asks the question the other way round. The prompts are fixed in advance,
so the denominator is fixed in advance: N attempts, and the only open question is
how many came out right. 19/20 against 12/20 is comparable across weeks in a way
a rate per 1,000 words is not.

The second thing it fixes is the kind of exercise. A recurring mistake at this
level is usually understood as a rule and still produced under time pressure,
which is exactly the knowledge a written fill-in-the-blank exercise tests and
finds intact. A drill gives the content words and asks for the whole sentence,
so the grammar has to be produced rather than recognised.

Drills run inside Conversation Practice Mode: the prompts are asked one at a
time, corrected immediately, and the answers are scored at the end. An earlier
version also supported speaking a drill into a recording and scoring the
transcript — it measured pace and real speech production, and it cost a recorder
app, a file to move and a transcription run for two minutes of exercise. A
measurement nobody performs is worth nothing, so it was removed rather than left
to rot in the docs. Recordings remain the instrument for free speech; drills are
what happens in dialogue.

Two things the scoring is careful about, both of which survive that change:

**A fixed list stops testing the pattern and starts testing the list.** After a
few sessions a small drill is memorised and the score means nothing. The file
holds a pool, and each session draws a few items from it, leading with whatever
was missed last time.

**A changed drill breaks its own trend.** If items are added or reworded, an old
score and a new one are not the same measurement. Every attempt records a
fingerprint of the pool it was drawn from — the pool, not the sample, since the
sample is meant to differ every session — so the history can say "this is a
different drill now" instead of drawing one line through both.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date as date_type
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# One row per attempt — what step 4b of the analysis workflow reads.
HISTORY_COLUMNS = ["date", "drill", "category", "fingerprint", "items",
                   "attempted", "correct", "notes"]

# One row per item per attempt — what sampling reads, and the only place that
# can answer "which item keeps failing", which is usually the actual lesson.
ITEM_COLUMNS = ["date", "drill", "item_id", "prompt", "attempted", "correct"]

# How many items a practice session opens with. Small on purpose: the block is a
# warm-up that puts the session's focus pattern in front of the learner, and the
# value of the session is the conversation after it.
DEFAULT_ITEMS = 5

# Punctuation is noise here, not signal — an answer typed without a full stop is
# not a grammar mistake. Apostrophes are the exception: "he's" and "he is" are
# both fine but "hes" is not a word, and the patterns are written against
# contractions.
_PUNCTUATION = re.compile(r"[^\w\s']+")
_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "´": "'"})


def normalize(line: str) -> str:
    """Lowercased, punctuation-free, single-spaced — what patterns match against."""
    line = line.translate(_APOSTROPHES).lower()
    return " ".join(_PUNCTUATION.sub(" ", line).split())


def _short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


@dataclass
class DrillItem:
    """
    One thing to say, and how to tell what came back.

    `attempted` matches the target structure however it came out, right or wrong;
    `correct` matches only the right form. Both, not one: an answer that matches
    neither means the item was dodged or answered with a different construction
    entirely, which is a different fact from getting it wrong.

    `example` and `wrong` are the model answers. They are also the test: a
    pattern that doesn't match its own example, or that accepts its own
    counter-example, is a broken pattern, and the suite refuses it.
    """
    prompt: str
    example: str
    wrong: str
    attempted: re.Pattern
    correct: re.Pattern

    @property
    def item_id(self) -> str:
        """Derived from the model answer rather than from position in the file,
        so inserting an item doesn't silently re-label every item after it — and
        so that rewording an answer correctly reads as a *different* item, which
        it is."""
        return _short_hash(normalize(self.example))


@dataclass
class Drill:
    name: str
    category: str            # the `## <Mistake Name>` heading in memory.md this drills
    target: str              # one line, what structure is being trained
    instructions: str
    items: list[DrillItem]
    # Set only on a subset, to remember the pool it was drawn from — see
    # `pool_fingerprint`.
    drawn_from: Optional[str] = None

    @property
    def size(self) -> int:
        return len(self.items)

    @property
    def pool_fingerprint(self) -> str:
        """
        Identifies the item pool, not the sample.

        What the history needs to detect is "the drill was edited", because a
        score before and after that is not the same measurement. A sample
        changing between sessions is not that — it is the design — so a
        fingerprint taken over the sample would raise the alarm every single
        session and teach the reader to ignore it.
        """
        return self.drawn_from or _short_hash("|".join(sorted(i.item_id for i in self.items)))

    def subset(self, item_ids: list[str]) -> "Drill":
        """The same drill narrowed to a sample, keeping file order."""
        wanted = set(item_ids)
        return Drill(name=self.name, category=self.category, target=self.target,
                     instructions=self.instructions,
                     items=[i for i in self.items if i.item_id in wanted],
                     drawn_from=self.pool_fingerprint)


@dataclass
class ItemResult:
    item: DrillItem
    attempted: bool
    correct: bool
    answer: Optional[str]        # what they actually wrote, if anything matched


@dataclass
class DrillResult:
    drill: Drill
    items: list[ItemResult] = field(default_factory=list)

    @property
    def attempted(self) -> int:
        return sum(1 for r in self.items if r.attempted)

    @property
    def correct(self) -> int:
        return sum(1 for r in self.items if r.correct)

    @property
    def accuracy(self) -> Optional[float]:
        """Of the items actually attempted. None when nothing was — an empty
        drill has no accuracy, and reporting 0% would read as total failure."""
        if not self.attempted:
            return None
        return round(self.correct / self.attempted, 3)


# --- loading -----------------------------------------------------------------

def load_drill(path: Path) -> Drill:
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    missing = {"name", "category", "target", "items"} - set(raw or {})
    if missing:
        raise ValueError(f"{path} is missing: {sorted(missing)}")

    items = []
    for i, entry in enumerate(raw["items"], 1):
        missing = {"prompt", "example", "wrong", "attempted", "correct"} - set(entry)
        if missing:
            raise ValueError(f"{path} item {i} is missing: {sorted(missing)}")
        items.append(DrillItem(
            prompt=entry["prompt"],
            example=entry["example"],
            wrong=entry["wrong"],
            attempted=re.compile(entry["attempted"]),
            correct=re.compile(entry["correct"]),
        ))
    if not items:
        raise ValueError(f"{path} has no items.")

    duplicates = {i.item_id for i in items if [x.item_id for x in items].count(i.item_id) > 1}
    if duplicates:
        raise ValueError(
            f"{path} has two items with the same model answer, so their histories would "
            f"merge into one: {sorted(i.example for i in items if i.item_id in duplicates)}"
        )

    return Drill(
        name=raw["name"],
        category=raw["category"],
        target=raw["target"],
        instructions=(raw.get("instructions") or "").strip(),
        items=items,
    )


def load_all(directory: Path) -> list[Drill]:
    return sorted((load_drill(p) for p in directory.glob("*.yaml")), key=lambda d: d.name)


def load_answers(path: Path) -> list[str]:
    """One answer per line, in the order the prompts were asked."""
    return [raw for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip()]


# --- scoring -----------------------------------------------------------------

def score(drill: Drill, answers: list[str]) -> DrillResult:
    """
    Match the answers against the drill, in order.

    In order, and never re-using an answer, because the prompts are asked in the
    order they were printed and several items in one drill deliberately share a
    frame. Scanning the whole list for each item independently would let a single
    well-formed sentence satisfy three items at once and score 20/20 on seven
    attempts.

    An answer that matches nothing is simply passed over. That is not a grammar
    failure — it is a question that got answered with some other construction, or
    not really answered at all — so it counts towards neither side.
    """
    normalized = [(raw, normalize(raw)) for raw in answers]
    result = DrillResult(drill=drill)
    cursor = 0

    for item in drill.items:
        match_at = None
        for index in range(cursor, len(normalized)):
            if item.attempted.search(normalized[index][1]):
                match_at = index
                break

        if match_at is None:
            result.items.append(ItemResult(item, attempted=False, correct=False, answer=None))
            continue

        raw, text = normalized[match_at]
        cursor = match_at + 1
        result.items.append(ItemResult(
            item,
            attempted=True,
            correct=bool(item.correct.search(text)),
            answer=raw,
        ))

    return result


# --- history -----------------------------------------------------------------

@dataclass
class HistoryRow:
    date: str
    drill: str
    category: str
    fingerprint: str
    items: int
    attempted: int
    correct: int
    notes: str

    @property
    def accuracy(self) -> Optional[float]:
        return None if not self.attempted else round(self.correct / self.attempted, 3)


@dataclass
class ItemRow:
    date: str
    drill: str
    item_id: str
    prompt: str
    attempted: bool
    correct: bool


def record_result(history_path: Path, items_path: Path, *, date: str,
                  result: DrillResult, notes: str = "") -> None:
    """
    Appends one attempt, plus one row per item.

    Unlike the session history this does not refuse a date it already holds:
    drilling the same pattern twice in a day is the entire point, and each run is
    a separate observation rather than one counted twice.
    """
    for path, columns, rows in (
        (history_path, HISTORY_COLUMNS, [{
            "date": date,
            "drill": result.drill.name,
            "category": result.drill.category,
            "fingerprint": result.drill.pool_fingerprint,
            "items": result.drill.size,
            "attempted": result.attempted,
            "correct": result.correct,
            "notes": notes,
        }]),
        (items_path, ITEM_COLUMNS, [{
            "date": date,
            "drill": result.drill.name,
            "item_id": r.item.item_id,
            "prompt": r.item.prompt,
            "attempted": int(r.attempted),
            "correct": int(r.correct),
        } for r in result.items]),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not path.exists()
        with path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            if is_new:
                writer.writeheader()
            writer.writerows(rows)

    logger.info("Recorded %s: %d/%d", result.drill.name, result.correct, result.attempted)


def load_history(path: Path) -> list[HistoryRow]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            rows.append(HistoryRow(
                date=raw["date"].strip(),
                drill=raw["drill"].strip(),
                category=raw["category"].strip(),
                fingerprint=(raw.get("fingerprint") or "").strip(),
                items=int(raw["items"]),
                attempted=int(raw["attempted"]),
                correct=int(raw["correct"]),
                notes=(raw.get("notes") or "").strip(),
            ))
    rows.sort(key=lambda r: r.date)
    return rows


def load_item_history(path: Path) -> list[ItemRow]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            rows.append(ItemRow(
                date=raw["date"].strip(),
                drill=raw["drill"].strip(),
                item_id=raw["item_id"].strip(),
                prompt=raw["prompt"].strip(),
                attempted=raw["attempted"].strip() == "1",
                correct=raw["correct"].strip() == "1",
            ))
    rows.sort(key=lambda r: r.date)
    return rows


# --- sampling ----------------------------------------------------------------

def select_items(drill: Drill, item_rows: list[ItemRow], sample: int) -> list[DrillItem]:
    """
    Which items this session should ask for.

    Priority, and the reasoning behind the order: items missed last time come
    first, because closing those is what a drill is for and because a miss that
    only comes back after every unseen item in the pool has been through is not
    being drilled at all — with a pool many times the sample size it would wait
    weeks. Then items never attempted, which carry the most information about
    the parts of the frame nobody has tested yet. Then items whose last outing
    matched nothing. Then the ones answered correctly, oldest first, so the pool
    rotates instead of narrowing to a favourite handful.

    Deliberately deterministic. A random sample would make two sessions on the
    same day incomparable for no benefit, and the rotation already comes from the
    history moving under it.
    """
    if sample >= drill.size:
        return list(drill.items)

    last_by_item = {row.item_id: row for row in item_rows if row.drill == drill.name}

    def rank(indexed: tuple[int, DrillItem]) -> tuple[int, str, int]:
        index, item = indexed
        last = last_by_item.get(item.item_id)
        if last is not None and last.attempted and not last.correct:
            bucket = 0
        elif last is None:
            bucket = 1
        elif not last.attempted:
            bucket = 2
        else:
            bucket = 3
        return (bucket, last.date if last else "", index)

    ordered = sorted(enumerate(drill.items), key=rank)[:sample]
    return [item for _, item in sorted(ordered, key=lambda pair: pair[0])]


# --- the pending sample ------------------------------------------------------
#
# `next` and `score` are separated by the whole practice session, and the
# selection depends on a history that the scoring itself changes. Recomputing it
# at scoring time would therefore be reproducible only by luck, and a mismatch is
# not a small error: the answers would be scored against prompts nobody was
# asked. So the selection is written down.

def write_pending(path: Path, drill: Drill, item_ids: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"drill": drill.name, "item_ids": item_ids}, indent=2),
                    encoding="utf-8")


def read_pending(path: Path, drill_name: str) -> Optional[list[str]]:
    """The sample waiting to be scored, if it belongs to this drill."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Ignoring unreadable pending sample at %s", path)
        return None
    if data.get("drill") != drill_name:
        return None
    return data.get("item_ids") or None


# --- rendering ---------------------------------------------------------------

def format_result(result: DrillResult) -> str:
    lines = [f"{result.drill.name} — {result.drill.target}", ""]

    for i, r in enumerate(result.items, 1):
        if not r.attempted:
            mark, detail = "·", "no answer using this structure"
        elif r.correct:
            mark, detail = "✓", r.answer
        else:
            mark, detail = "✗", f"{r.answer}   → {r.item.example}"
        lines.append(f"{mark} {i:>2}. {detail}")

    lines.append("")
    accuracy = result.accuracy
    if accuracy is None:
        lines.append(
            f"0 of {result.drill.size} items attempted — nothing to score. Check the "
            f"answers are in the order the prompts were asked."
        )
    else:
        lines.append(f"{result.correct}/{result.attempted} correct ({accuracy:.0%}) "
                     f"of {result.drill.size} items attempted.")
        skipped = result.drill.size - result.attempted
        if skipped:
            lines.append(f"{skipped} answered with some other construction — not counted "
                         f"either way.")
    return "\n".join(lines)


def format_history(rows: list[HistoryRow]) -> str:
    if not rows:
        return "No drills recorded yet. `python -m voxlib.drill list` to see what's available."

    header = f"{'Date':<12} {'Drill':<28} {'Score':>9} {'Accuracy':>9} {'Set':>9}"
    lines = [header, "-" * len(header)]
    seen_fingerprints: dict[str, set[str]] = {}
    for r in rows:
        accuracy = "—" if r.accuracy is None else f"{r.accuracy:.0%}"
        lines.append(f"{r.date:<12} {r.drill[:28]:<28} {r.correct:>4}/{r.attempted:<4} "
                     f"{accuracy:>9} {r.fingerprint or '—':>9}")
        seen_fingerprints.setdefault(r.drill, set()).add(r.fingerprint)

    changed = [name for name, prints in seen_fingerprints.items() if len(prints) > 1]
    lines.append("")
    if changed:
        lines.append(f"Item set changed at some point for: {', '.join(changed)} — scores "
                     f"either side of a new fingerprint are different measurements, so "
                     f"don't read one trend through both.")
    lines.append("Accuracy is over items attempted, not items asked — a prompt answered "
                 "with a different construction is not an error.")
    return "\n".join(lines)


# --- CLI ---------------------------------------------------------------------

def _repo_root() -> Path:
    return Path(__file__).parent.parent


def main(argv: list[str] | None = None) -> int:
    """`python -m voxlib.drill` — print the history, list drills, draw the next
    prompts, or score the answers to them."""
    import argparse

    analysis = _repo_root() / "analysis"
    parser = argparse.ArgumentParser(
        prog="python -m voxlib.drill",
        description="Drills: prompts asked in conversation, scored against a known key.",
    )
    parser.add_argument("--drills-dir", type=Path, default=_repo_root() / "drills")
    parser.add_argument("--history", type=Path, default=analysis / "drills.csv")
    parser.add_argument("--item-history", type=Path, default=analysis / "drill_items.csv")
    parser.add_argument("--pending", type=Path, default=analysis / "drill_pending.json")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="Available drills")

    nxt = sub.add_parser("next", help="The prompts to ask this session")
    nxt.add_argument("drill")
    nxt.add_argument("--count", type=int, default=DEFAULT_ITEMS)

    score_cmd = sub.add_parser("score", help="Score the answers to the last prompts")
    score_cmd.add_argument("drill")
    score_cmd.add_argument("--answers", type=Path, required=True,
                           help="Their answers, one per line, in the order asked")
    score_cmd.add_argument("--date", default=date_type.today().isoformat())
    score_cmd.add_argument("--notes", default="")
    score_cmd.add_argument("--whole-drill", action="store_true",
                           help="Ignore the pending sample and score every item")
    score_cmd.add_argument("--dry-run", action="store_true",
                           help="Print the result without recording it")

    item_cmd = sub.add_parser("items", help="Per-item record for one drill")
    item_cmd.add_argument("drill")

    args = parser.parse_args(argv)

    if args.command in {"next", "score", "items"}:
        drills = {d.name: d for d in load_all(args.drills_dir)}
        drill = drills.get(args.drill)
        if drill is None:
            parser.error(f"No drill named {args.drill!r}. Available: {', '.join(drills) or 'none'}")

    if args.command == "list":
        found = load_all(args.drills_dir)
        if not found:
            print(f"No drills in {args.drills_dir}.")
            return 1
        for d in found:
            print(f"{d.name:<26} {d.size:>2} items  [{d.category}]")
            print(f"{'':<26} {d.target}")
        return 0

    if args.command == "next":
        chosen = select_items(drill, load_item_history(args.item_history), args.count)
        write_pending(args.pending, drill, [i.item_id for i in chosen])
        print(f"{drill.name} — {drill.target}")
        print(f"{len(chosen)} of {drill.size} items, hardest first. Ask them one at a time.")
        print()
        for i, item in enumerate(chosen, 1):
            print(f"{i:>2}. {item.prompt}")
        print()
        print("Answers are deliberately not printed: this output is visible to the "
              "person answering.")
        print(f"Afterwards: score {drill.name} --answers <their answers, one per line>")
        return 0

    if args.command == "items":
        rows = [r for r in load_item_history(args.item_history) if r.drill == drill.name]
        if not rows:
            print(f"No item history for {drill.name} yet.")
            return 0
        by_item: dict[str, list[ItemRow]] = {}
        for row in rows:
            by_item.setdefault(row.item_id, []).append(row)
        print(f"{'Prompt':<44} {'Asked':>6} {'Right':>6} {'Last':>12}")
        print("-" * 71)
        for item in drill.items:
            history = by_item.get(item.item_id, [])
            attempts = [r for r in history if r.attempted]
            right = sum(1 for r in attempts if r.correct)
            last = history[-1].date if history else "never"
            print(f"{item.prompt[:44]:<44} {len(attempts):>6} {right:>6} {last:>12}")
        print()
        print("Asked counts only the times the item was actually answered with this "
              "structure. The prompts at the top of the next sample are the ones missed "
              "or not yet seen.")
        return 0

    if args.command == "score":
        if not args.answers.exists():
            parser.error(f"No answers file at {args.answers}.")

        pending = read_pending(args.pending, drill.name)
        running = drill.subset(pending) if pending and not args.whole_drill else drill

        result = score(running, load_answers(args.answers))
        print(format_result(result))

        if not args.dry_run:
            record_result(args.history, args.item_history, date=args.date,
                          result=result, notes=args.notes)
            # Cleared whether or not it was used: a sample left lying around
            # would silently narrow the next session to prompts nobody was asked.
            if pending:
                args.pending.unlink(missing_ok=True)
            print()
            print(f"Recorded in {args.history}.")
        return 0

    print(format_history(load_history(args.history)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
