"""
Spoken drills — the one place in this project where a number has a denominator.

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
finds intact. So a drill is spoken out loud, in one take, and transcribed by the
same pipeline as everything else.

Four things follow from that last sentence, and each is a place where a drill
can quietly lie about the speaker:

**The transcriber is part of the instrument.** An article is a short unstressed
function word — precisely what speech-to-text drops and inserts. Scoring an
article drill against a raw transcript measures the recogniser as much as the
speaker, so lines the recogniser flagged as low-confidence are excluded from
scoring entirely rather than counted as mistakes. That is rule 1 of this
project's analysis workflow, applied where it matters most. `--calibrate` is the
other half: read the answers aloud deliberately correctly, and whatever still
comes back wrong is the instrument's error rate rather than yours.

**Accuracy without pace is half a measurement.** Fifteen correct with four
seconds of thinking before each one and fifteen correct at conversational speed
are different states of the same skill, and only the second is automaticity.
Timings already exist per line, so seconds-per-item is recorded next to the
score.

**A fixed list stops testing the pattern and starts testing the list.** After a
few runs a drill of fifteen items is memorised, and 15/15 means nothing. The
file therefore holds a pool and a run draws a sample from it, weighted toward
items that were missed or that haven't come up in a while.

**A changed drill breaks its own trend.** If items are added or reworded, an old
score and a new one are not the same measurement. Every attempt records a
fingerprint of the pool it was drawn from — the pool, not the sample, since the
sample is meant to differ every run — so the history can say "this is a
different drill now" instead of drawing one line through both.
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import statistics
from dataclasses import dataclass, field
from datetime import date as date_type
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# One row per attempt — what step 4b of the analysis workflow reads.
HISTORY_COLUMNS = [
    "date", "drill", "category", "fingerprint", "mode", "items",
    "attempted", "correct", "median_seconds", "unscorable_lines", "notes",
]

# One row per item per attempt — what sampling reads, and the only place that
# can answer "which item keeps failing", which is usually the actual lesson.
ITEM_COLUMNS = ["date", "drill", "mode", "item_id", "prompt", "attempted", "correct", "seconds"]

DRILL_MODE = "drill"
CALIBRATION_MODE = "calibration"

# Punctuation is the transcriber's guess, not the speaker's, so it can't be
# allowed to decide whether an item passed. Apostrophes are the exception:
# "he's" and "he is" are both fine but "hes" is not a word, and the patterns are
# written against contractions.
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
    `correct` matches only the right form. Both, not one: a line that matches
    neither means the item was skipped or misheard, which is a different fact
    from getting it wrong and is never counted as an error.

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
        changing between runs is not that — it is the design — so a fingerprint
        taken over the sample would raise the alarm every single run and teach
        the reader to ignore it.
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
class SpokenLine:
    """A transcript line with everything scoring needs to know about it."""
    text: str
    start: Optional[float] = None
    end: Optional[float] = None
    low_confidence: bool = False

    @property
    def normalized(self) -> str:
        return normalize(self.text)


@dataclass
class ItemResult:
    item: DrillItem
    attempted: bool
    correct: bool
    heard: Optional[str]         # the transcript line matched to this item, if any
    seconds: Optional[float]     # from the end of the previous answer to the end of this one


@dataclass
class DrillResult:
    drill: Drill
    mode: str = DRILL_MODE
    unscorable_lines: int = 0    # lines the recogniser wasn't sure about, so not matched
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

    @property
    def median_seconds(self) -> Optional[float]:
        """Per item, end of the previous answer to the end of this one — so it
        includes the pause spent thinking, which is where automaticity actually
        shows. None when the transcript carried no timings."""
        timed = [r.seconds for r in self.items if r.seconds is not None]
        return round(statistics.median(timed), 2) if timed else None


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


def load_spoken_lines(path: Path) -> list[SpokenLine]:
    """
    Reads `lines.json` when given one, a plain transcript otherwise.

    lines.json is strongly preferred and is the default, because it carries the
    two things a bare transcript throws away: which lines the recogniser wasn't
    sure about, and when each line was said. Without the first, a dropped "a" is
    scored as a grammar mistake; without the second there is no pace at all.
    """
    if path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        return [
            SpokenLine(
                text=line["text"],
                start=line.get("start"),
                end=line.get("end"),
                low_confidence=bool(line.get("low_confidence")),
            )
            for line in data.get("lines", [])
            if line.get("text", "").strip()
        ]

    return [SpokenLine(text=raw) for raw in path.read_text(encoding="utf-8").splitlines()
            if raw.strip()]


# --- scoring -----------------------------------------------------------------

def score(drill: Drill, lines: list[SpokenLine], *, mode: str = DRILL_MODE) -> DrillResult:
    """
    Match the transcript against the drill, in order.

    In order, and never re-using a line, because the prompts are spoken in the
    order they were printed and several items in one drill deliberately share a
    frame. Scanning the whole transcript for each item independently would let a
    single well-said sentence satisfy three items at once and score 20/20 on
    seven attempts.

    Lines the recogniser flagged as low-confidence are not eligible to match
    anything. An article is exactly the kind of short unstressed word a
    recogniser drops, so scoring such a line would put its uncertainty on the
    speaker's record as a grammar error. Excluded, the item reads as "not heard",
    which is what actually happened. They are counted and reported, because a
    drill where half the lines were unscorable is a recording problem, not a
    result.

    A line that matches nothing is simply passed over: false starts, "let me try
    that again" and the recogniser's own misfires all land there, and none of
    them is evidence about grammar.
    """
    result = DrillResult(drill=drill, mode=mode,
                         unscorable_lines=sum(1 for l in lines if l.low_confidence))
    cursor = 0
    previous_end: Optional[float] = None

    for item in drill.items:
        match_at = None
        for index in range(cursor, len(lines)):
            line = lines[index]
            if line.low_confidence:
                continue
            if item.attempted.search(line.normalized):
                match_at = index
                break

        if match_at is None:
            result.items.append(ItemResult(item, attempted=False, correct=False,
                                           heard=None, seconds=None))
            continue

        line = lines[match_at]
        cursor = match_at + 1

        seconds = None
        if line.end is not None:
            reference = previous_end if previous_end is not None else line.start
            if reference is not None:
                seconds = round(line.end - reference, 2)
            previous_end = line.end

        result.items.append(ItemResult(
            item,
            attempted=True,
            correct=bool(item.correct.search(line.normalized)),
            heard=line.text,
            seconds=seconds,
        ))

    return result


# --- history -----------------------------------------------------------------

@dataclass
class HistoryRow:
    date: str
    drill: str
    category: str
    fingerprint: str
    mode: str
    items: int
    attempted: int
    correct: int
    median_seconds: Optional[float]
    unscorable_lines: int
    notes: str

    @property
    def accuracy(self) -> Optional[float]:
        return None if not self.attempted else round(self.correct / self.attempted, 3)


@dataclass
class ItemRow:
    date: str
    drill: str
    mode: str
    item_id: str
    prompt: str
    attempted: bool
    correct: bool
    seconds: Optional[float]


def _optional_float(raw: str) -> Optional[float]:
    raw = (raw or "").strip()
    return float(raw) if raw else None


def record_result(history_path: Path, items_path: Path, *, date: str,
                  result: DrillResult, notes: str = "") -> None:
    """
    Appends one attempt, plus one row per item.

    Unlike the session history this does not refuse a date it already holds:
    running the same drill twice in a day is the entire point of a drill, and
    each run is a separate observation rather than one counted twice.
    """
    for path, columns, rows in (
        (history_path, HISTORY_COLUMNS, [{
            "date": date,
            "drill": result.drill.name,
            "category": result.drill.category,
            "fingerprint": result.drill.pool_fingerprint,
            "mode": result.mode,
            "items": result.drill.size,
            "attempted": result.attempted,
            "correct": result.correct,
            # Blank, never 0, when the transcript carried no timings: "not
            # measured" and "instant" are not the same claim.
            "median_seconds": "" if result.median_seconds is None else result.median_seconds,
            "unscorable_lines": result.unscorable_lines,
            "notes": notes,
        }]),
        (items_path, ITEM_COLUMNS, [{
            "date": date,
            "drill": result.drill.name,
            "mode": result.mode,
            "item_id": r.item.item_id,
            "prompt": r.item.prompt,
            "attempted": int(r.attempted),
            "correct": int(r.correct),
            "seconds": "" if r.seconds is None else r.seconds,
        } for r in result.items]),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not path.exists()
        with path.open("a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            if is_new:
                writer.writeheader()
            writer.writerows(rows)

    logger.info("Recorded %s (%s): %d/%d", result.drill.name, result.mode,
                result.correct, result.attempted)


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
                mode=(raw.get("mode") or DRILL_MODE).strip(),
                items=int(raw["items"]),
                attempted=int(raw["attempted"]),
                correct=int(raw["correct"]),
                median_seconds=_optional_float(raw.get("median_seconds", "")),
                unscorable_lines=int(raw.get("unscorable_lines") or 0),
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
                mode=(raw.get("mode") or DRILL_MODE).strip(),
                item_id=raw["item_id"].strip(),
                prompt=raw["prompt"].strip(),
                attempted=raw["attempted"].strip() == "1",
                correct=raw["correct"].strip() == "1",
                seconds=_optional_float(raw.get("seconds", "")),
            ))
    rows.sort(key=lambda r: r.date)
    return rows


# --- sampling ----------------------------------------------------------------

# What a run draws when the pool is bigger than one take. Fifteen items is
# roughly two minutes spoken, which is the length that still gets done.
DEFAULT_SAMPLE = 15


def select_items(drill: Drill, item_rows: list[ItemRow], sample: int) -> list[DrillItem]:
    """
    Which items this run should ask for.

    Priority, and the reasoning behind the order: items missed last time come
    first, because closing those is what a drill is for and because a miss that
    only comes back after every unseen item in the pool has been through is not
    being drilled at all — with a pool twice the sample size it would wait weeks.
    Then items never attempted, which carry the most information about the parts
    of the frame nobody has tested yet. Then items whose last outing wasn't heard
    at all. Then the ones answered correctly, oldest first, so the pool rotates
    instead of narrowing to a favourite fifteen.

    Deliberately deterministic. A random sample would make two runs on the same
    day incomparable for no benefit, and the rotation already comes from the
    history moving under it.

    Calibration runs are ignored here: reading the answer sheet aloud says
    nothing about which items the speaker finds hard, and letting a clean
    calibration mark an item as mastered would retire exactly the items that are
    hardest to say.
    """
    if sample >= drill.size:
        return list(drill.items)

    last_by_item: dict[str, ItemRow] = {}
    for row in item_rows:
        if row.drill == drill.name and row.mode == DRILL_MODE:
            last_by_item[row.item_id] = row          # rows are date-sorted; last wins

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
# `show --sample` and `score` are separated by however long it takes to speak the
# prompts and run the pipeline, and the selection depends on a history that the
# scoring itself changes. Recomputing it at scoring time would therefore be
# reproducible only by luck, and a mismatch is not a small error: the speaker
# would be scored against fifteen prompts they were never shown, and almost
# every item would read as "not heard". So the selection is written down.

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
    lines = [f"{result.drill.name} — {result.drill.target}"]
    if result.mode == CALIBRATION_MODE:
        lines.append("CALIBRATION RUN — anything wrong below is the instrument, not you.")
    lines.append("")

    for i, r in enumerate(result.items, 1):
        pace = "" if r.seconds is None else f"   [{r.seconds:.1f}s]"
        if not r.attempted:
            mark, detail = "·", "not heard — skipped, or the recogniser missed it"
        elif r.correct:
            mark, detail = "✓", r.heard
        else:
            mark, detail = "✗", f"{r.heard}   → {r.item.example}"
        lines.append(f"{mark} {i:>2}. {detail}{pace}")

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
        if result.median_seconds is not None:
            lines.append(f"Median {result.median_seconds:.1f}s per item — accuracy at "
                         f"conversational pace is the goal, not accuracy alone.")
        skipped = result.drill.size - result.attempted
        if skipped:
            lines.append(f"{skipped} not heard — those are not counted as errors.")

    if result.unscorable_lines:
        lines.append(f"{result.unscorable_lines} line(s) excluded as low-confidence: the "
                     f"recogniser wasn't sure what it heard, so they can't score grammar.")
    if result.mode == CALIBRATION_MODE and accuracy is not None and accuracy < 1:
        lines.append("")
        lines.append("These misses are the drill's own error rate. Treat that many misses "
                     "in a real run as noise rather than as mistakes.")
    return "\n".join(lines)


def format_history(rows: list[HistoryRow]) -> str:
    if not rows:
        return "No drills recorded yet. `python -m voxlib.drill list` to see what's available."

    header = (f"{'Date':<12} {'Drill':<24} {'Score':>9} {'Acc':>5} {'Pace':>7} "
              f"{'Set':>8} {'Mode':>12}")
    lines = [header, "-" * len(header)]
    seen_fingerprints: dict[str, set[str]] = {}
    for r in rows:
        accuracy = "—" if r.accuracy is None else f"{r.accuracy:.0%}"
        pace = "—" if r.median_seconds is None else f"{r.median_seconds:.1f}s"
        lines.append(f"{r.date:<12} {r.drill[:24]:<24} {r.correct:>4}/{r.attempted:<4} "
                     f"{accuracy:>5} {pace:>7} {r.fingerprint or '—':>8} {r.mode:>12}")
        seen_fingerprints.setdefault(r.drill, set()).add(r.fingerprint)

    changed = [name for name, prints in seen_fingerprints.items() if len(prints) > 1]
    lines.append("")
    if changed:
        lines.append(f"Item set changed at some point for: {', '.join(changed)} — scores "
                     f"either side of a new fingerprint are different measurements, so "
                     f"don't read one trend through both.")
    lines.append("Accuracy is over items attempted, not items printed — a prompt the "
                 "recogniser never heard is not an error.")
    lines.append("Pace is the median seconds per item, thinking pause included.")
    return "\n".join(lines)


# --- CLI ---------------------------------------------------------------------

def _repo_root() -> Path:
    return Path(__file__).parent.parent


def main(argv: list[str] | None = None) -> int:
    """`python -m voxlib.drill` — print the history, list drills, show one to
    read aloud, or score a transcript against one."""
    import argparse

    analysis = _repo_root() / "analysis"
    parser = argparse.ArgumentParser(
        prog="python -m voxlib.drill",
        description="Spoken drills: say the prompts out loud, record, transcribe, score.",
    )
    parser.add_argument("--drills-dir", type=Path, default=_repo_root() / "drills")
    parser.add_argument("--history", type=Path, default=analysis / "drills.csv")
    parser.add_argument("--item-history", type=Path, default=analysis / "drill_items.csv")
    parser.add_argument("--pending", type=Path, default=analysis / "drill_pending.json")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="Available drills")

    show = sub.add_parser("show", help="Print the prompts to read aloud")
    show.add_argument("drill")
    show.add_argument("--sample", type=int, default=DEFAULT_SAMPLE,
                      help=f"How many items to draw from the pool (default {DEFAULT_SAMPLE}); "
                           f"0 for the whole drill")
    show.add_argument("--answers", action="store_true",
                      help="Reveal the model answers (read these AFTER speaking, not before)")

    score_cmd = sub.add_parser("score", help="Score a transcript against a drill")
    score_cmd.add_argument("drill")
    score_cmd.add_argument("--transcript", type=Path,
                           default=_repo_root() / "output" / "lines.json",
                           help="lines.json (preferred — carries confidence and timings) "
                                "or a plain transcript")
    score_cmd.add_argument("--date", default=date_type.today().isoformat())
    score_cmd.add_argument("--notes", default="")
    score_cmd.add_argument("--calibrate", action="store_true",
                           help="This recording was the answers read aloud deliberately "
                                "correctly — score the instrument, not the speaker")
    score_cmd.add_argument("--whole-drill", action="store_true",
                           help="Ignore the pending sample and score every item")
    score_cmd.add_argument("--dry-run", action="store_true",
                           help="Print the result without recording it")

    item_cmd = sub.add_parser("items", help="Per-item record for one drill")
    item_cmd.add_argument("drill")

    args = parser.parse_args(argv)

    if args.command in {"show", "score", "items"}:
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
        sample = args.sample if args.sample > 0 else drill.size
        chosen = select_items(drill, load_item_history(args.item_history), sample)
        running = drill.subset([i.item_id for i in chosen])
        write_pending(args.pending, drill, [i.item_id for i in chosen])

        print(f"{drill.name} — {drill.target}")
        print(f"{running.size} of {drill.size} items. Say each one out loud, in order, "
              f"in one take.")
        if running.size < drill.size:
            print("Drawn from the pool: anything missed last time, then whatever hasn't "
                  "come up in a while.")
        if drill.instructions:
            print()
            print(drill.instructions)
        print()
        for i, item in enumerate(running.items, 1):
            print(f"{i:>2}. {item.prompt}")
            if args.answers:
                print(f"    ✓ {item.example}")
                print(f"    ✗ {item.wrong}")
        print()
        if not args.answers:
            print("Answers: re-run with --answers, after you've recorded — reading them "
                  "first turns production practice back into recognition practice.")
        print(f"This selection is saved; `score {drill.name}` will use it.")
        return 0

    if args.command == "items":
        rows = [r for r in load_item_history(args.item_history)
                if r.drill == drill.name and r.mode == DRILL_MODE]
        if not rows:
            print(f"No item history for {drill.name} yet.")
            return 0
        by_item: dict[str, list[ItemRow]] = {}
        for row in rows:
            by_item.setdefault(row.item_id, []).append(row)
        print(f"{'Prompt':<44} {'Runs':>5} {'Right':>6} {'Last':>12}")
        print("-" * 70)
        for item in drill.items:
            history = by_item.get(item.item_id, [])
            attempts = [r for r in history if r.attempted]
            right = sum(1 for r in attempts if r.correct)
            last = history[-1].date if history else "never"
            print(f"{item.prompt[:44]:<44} {len(attempts):>5} {right:>6} {last:>12}")
        print()
        print("Runs counts only the times the item was actually heard. The prompts at "
              "the top of the next sample are the ones missed or not yet seen.")
        return 0

    if args.command == "score":
        if not args.transcript.exists():
            parser.error(f"No transcript at {args.transcript}. Run the pipeline first.")
        lines = load_spoken_lines(args.transcript)
        if args.transcript.suffix != ".json":
            print("Scoring a plain transcript: no confidence flags and no timings, so a "
                  "word the recogniser guessed can be scored as your mistake. Prefer "
                  "output/lines.json.")
            print()

        pending = read_pending(args.pending, drill.name)
        running = drill.subset(pending) if pending and not args.whole_drill else drill

        result = score(running, lines,
                       mode=CALIBRATION_MODE if args.calibrate else DRILL_MODE)
        print(format_result(result))

        if not args.dry_run:
            record_result(args.history, args.item_history, date=args.date,
                          result=result, notes=args.notes)
            # Cleared whether or not it was used: a sample left lying around
            # would silently narrow the next run to prompts nobody was shown.
            if pending:
                args.pending.unlink(missing_ok=True)
            print()
            print(f"Recorded in {args.history}.")
        return 0

    print(format_history(load_history(args.history)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
