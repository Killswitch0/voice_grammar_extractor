"""
Spoken drills — the one place in this project where a number has a denominator.

Everything else here counts errors: so many article mistakes in so many words.
What that cannot say is *out of how many chances*, because nothing knows how
many singular countable nouns were spoken. The missing denominator is not a
detail. A speaker who moves from short conversational turns to a long monologue
produces far more noun phrases per hundred words, so their error rate can rise
while their accuracy improves — and in a per-1,000-words series the two are
indistinguishable. A rising rate can therefore send a category to the top of
the priority list for weeks on evidence that never supported it.

A drill asks the question the other way round. The prompts are fixed in advance,
so the denominator is fixed in advance: N attempts, and the only open question
is how many came out right. 19/20 against 12/20 is comparable across weeks in a
way that a rate per 1,000 words is not.

The second thing it fixes is the kind of exercise. A recurring mistake at this
level is usually understood as a rule and still produced under time pressure,
which is precisely the knowledge a written fill-in-the-blank exercise tests and
finds intact. So a drill is spoken out loud, in one take, and transcribed by the
same pipeline as everything else.

Scoring never asks whether the sentence was *correct English*. It asks two
narrower questions per item — was the target structure attempted at all, and did
it come out right — because a speech-to-text transcript is not reliable enough
to mark a whole sentence, and because an item that was skipped or misheard must
not be scored as a grammar failure. Attempts and hits are reported separately
for that reason.
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from datetime import date as date_type
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

HISTORY_COLUMNS = ["date", "drill", "category", "items", "attempted", "correct", "notes"]

# Punctuation is whisper's guess, not the speaker's, so it can't be allowed to
# decide whether a drill item passed. Apostrophes are the exception: "he's" and
# "he is" are both fine but "hes" is not a word, and patterns are written
# against contractions.
_PUNCTUATION = re.compile(r"[^\w\s']+")
_APOSTROPHES = str.maketrans({"’": "'", "ʼ": "'", "´": "'"})


def normalize(line: str) -> str:
    """Lowercased, punctuation-free, single-spaced — what patterns match against."""
    line = line.translate(_APOSTROPHES).lower()
    return " ".join(_PUNCTUATION.sub(" ", line).split())


@dataclass
class DrillItem:
    """
    One thing to say, and how to tell what came back.

    `attempted` matches the target structure however it came out, right or
    wrong; `correct` matches only the right form. Both, not one: a line that
    matches neither means the item was skipped or misheard, which is a different
    fact from getting it wrong and is never counted as an error.

    `example` and `wrong` are the model answers. They are also the test: a
    pattern that doesn't match its own example, or that accepts its own
    counter-example, is a broken pattern, and the suite refuses it.
    """
    prompt: str
    example: str
    wrong: str
    attempted: re.Pattern
    correct: re.Pattern


@dataclass
class Drill:
    name: str
    category: str            # the `## <Mistake Name>` heading in memory.md this drills
    target: str              # one line, what structure is being trained
    instructions: str
    items: list[DrillItem]

    @property
    def size(self) -> int:
        return len(self.items)


@dataclass
class ItemResult:
    item: DrillItem
    attempted: bool
    correct: bool
    heard: Optional[str]     # the transcript line matched to this item, if any


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

    return Drill(
        name=raw["name"],
        category=raw["category"],
        target=raw["target"],
        instructions=(raw.get("instructions") or "").strip(),
        items=items,
    )


def load_all(directory: Path) -> list[Drill]:
    return sorted((load_drill(p) for p in directory.glob("*.yaml")), key=lambda d: d.name)


def score(drill: Drill, lines: list[str]) -> DrillResult:
    """
    Match the transcript against the drill, in order.

    In order, and never re-using a line, because the prompts are spoken in the
    order they were printed and several items in one drill deliberately share a
    frame. Scanning the whole transcript for each item independently would let a
    single well-said sentence satisfy three items at once and score 20/20 on
    seven attempts.

    A line that matches nothing is simply passed over: false starts, "wait, let
    me try that again" and whisper's misfires all land there, and none of them
    is evidence about grammar.
    """
    normalized = [(raw, normalize(raw)) for raw in lines]
    result = DrillResult(drill=drill)
    cursor = 0

    for item in drill.items:
        match_at = None
        for index in range(cursor, len(normalized)):
            if item.attempted.search(normalized[index][1]):
                match_at = index
                break

        if match_at is None:
            result.items.append(ItemResult(item, attempted=False, correct=False, heard=None))
            continue

        raw, text = normalized[match_at]
        cursor = match_at + 1
        result.items.append(ItemResult(
            item,
            attempted=True,
            correct=bool(item.correct.search(text)),
            heard=raw,
        ))

    return result


def record_result(path: Path, *, date: str, result: DrillResult, notes: str = "") -> None:
    """
    Appends one attempt.

    Unlike `mistakes.csv` this does not refuse a date it already holds: running
    the same drill twice in a day is the entire point of a drill, and each run
    is a separate observation rather than a double count of one.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS)
        if is_new:
            writer.writeheader()
        writer.writerow({
            "date": date,
            "drill": result.drill.name,
            "category": result.drill.category,
            "items": result.drill.size,
            "attempted": result.attempted,
            "correct": result.correct,
            "notes": notes,
        })
    logger.info("Recorded %s: %d/%d", result.drill.name, result.correct, result.attempted)


@dataclass
class HistoryRow:
    date: str
    drill: str
    category: str
    items: int
    attempted: int
    correct: int
    notes: str

    @property
    def accuracy(self) -> Optional[float]:
        return None if not self.attempted else round(self.correct / self.attempted, 3)


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
                items=int(raw["items"]),
                attempted=int(raw["attempted"]),
                correct=int(raw["correct"]),
                notes=(raw.get("notes") or "").strip(),
            ))
    rows.sort(key=lambda r: r.date)
    return rows


def format_result(result: DrillResult) -> str:
    lines = [f"{result.drill.name} — {result.drill.target}", ""]
    for i, r in enumerate(result.items, 1):
        if not r.attempted:
            mark, detail = "·", "not heard — skipped, or whisper missed it"
        elif r.correct:
            mark, detail = "✓", r.heard
        else:
            mark, detail = "✗", f"{r.heard}   → {r.item.example}"
        lines.append(f"{mark} {i:>2}. {detail}")

    lines.append("")
    accuracy = result.accuracy
    if accuracy is None:
        lines.append(
            f"0 of {result.drill.size} items attempted — nothing to score. Check the "
            f"transcript is the right one, and that the sentences were said in order."
        )
    else:
        lines.append(f"{result.correct}/{result.attempted} correct ({accuracy:.0%}) "
                     f"of {result.drill.size} items attempted.")
        skipped = result.drill.size - result.attempted
        if skipped:
            lines.append(f"{skipped} not heard — those are not counted as errors.")
    return "\n".join(lines)


def format_history(rows: list[HistoryRow]) -> str:
    if not rows:
        return "No drills recorded yet. `python -m voxlib.drill list` to see what's available."

    header = f"{'Date':<12} {'Drill':<26} {'Score':>9} {'Accuracy':>9} {'Attempted':>10}"
    lines = [header, "-" * len(header)]
    for r in rows:
        accuracy = "—" if r.accuracy is None else f"{r.accuracy:.0%}"
        lines.append(f"{r.date:<12} {r.drill[:26]:<26} {r.correct:>4}/{r.attempted:<4} "
                     f"{accuracy:>9} {f'{r.attempted}/{r.items}':>10}")
    lines.append("")
    lines.append("Accuracy is over items attempted, not items printed — a prompt whisper "
                 "never heard is not an error.")
    return "\n".join(lines)


def _repo_root() -> Path:
    return Path(__file__).parent.parent


def main(argv: list[str] | None = None) -> int:
    """`python -m voxlib.drill` — print the history, list drills, show one to
    read aloud, or score a transcript against one."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m voxlib.drill",
        description="Spoken drills: say the prompts out loud, record, transcribe, score.",
    )
    parser.add_argument("--drills-dir", type=Path, default=_repo_root() / "drills")
    parser.add_argument("--history", type=Path,
                        default=_repo_root() / "analysis" / "drills.csv")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="Available drills")

    show = sub.add_parser("show", help="Print the prompts to read aloud")
    show.add_argument("drill")
    show.add_argument("--answers", action="store_true",
                      help="Reveal the model answers (read these AFTER speaking, not before)")

    score_cmd = sub.add_parser("score", help="Score a transcript against a drill")
    score_cmd.add_argument("drill")
    score_cmd.add_argument("--transcript", type=Path,
                           default=_repo_root() / "output" / "transcript_clean.txt")
    score_cmd.add_argument("--date", default=date_type.today().isoformat())
    score_cmd.add_argument("--notes", default="")
    score_cmd.add_argument("--dry-run", action="store_true",
                           help="Print the result without recording it")

    args = parser.parse_args(argv)

    if args.command in {"show", "score"}:
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

    if args.command == "show":
        print(f"{drill.name} — {drill.target}")
        print(f"{drill.size} items. Say each one out loud, in order, in one take.")
        if drill.instructions:
            print()
            print(drill.instructions)
        print()
        for i, item in enumerate(drill.items, 1):
            print(f"{i:>2}. {item.prompt}")
            if args.answers:
                print(f"    ✓ {item.example}")
                print(f"    ✗ {item.wrong}")
        if not args.answers:
            print()
            print("Answers: re-run with --answers, after you've recorded — reading them "
                  "first turns production practice back into recognition practice.")
        return 0

    if args.command == "score":
        if not args.transcript.exists():
            parser.error(f"No transcript at {args.transcript}. Run the pipeline first.")
        lines = [l for l in args.transcript.read_text(encoding="utf-8").splitlines() if l.strip()]
        result = score(drill, lines)
        print(format_result(result))
        if not args.dry_run:
            record_result(args.history, date=args.date, result=result, notes=args.notes)
            print()
            print(f"Recorded in {args.history}.")
        return 0

    print(format_history(load_history(args.history)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
