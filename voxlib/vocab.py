"""
Whether the words the coach retired are actually going away.

`memory.md` carries a "Vocabulary To Replace" table: a phrase the speaker
overuses, and what to say instead. It is written every session, read every
session, and until now nothing ever checked it. The whole table was a standing
instruction with no feedback loop — which is the one kind of advice that can be
wrong for months without anyone noticing.

The check is cheap, because the evidence is already on disk. Every session's
annotated transcript is archived, so both sides of each substitution can be
counted across the whole history: the phrase that was supposed to disappear, and
the replacement that was supposed to take its place.

Three things make the count worth trusting:

**Reliable lines only**, read through `fluency.reliable_lines_from_annotated`,
so a phrase whisper invented is never counted against the speaker.

**Word boundaries, not substrings.** Counting "great" as a substring also counts
"greater" and "greatest"; counting "cool" also counts "cooling". The phrases in
that table are short and common, which is exactly where substring matching goes
wrong most often.

**Both sides, as one story.** A retired phrase falling is only half of it — the
question is whether a replacement arrived or whether another crutch did. Where
the table names alternatives, each is counted, and the panel that reads this
shows the pair together.

What it cannot do: tell a word used well from a word used badly. A phrase can be
on the list for being vague rather than forbidden, and a session that uses it
well reads the same as one that leans on it. The count is a prompt to look, not
a verdict.
"""

from __future__ import annotations

import csv
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import brief, fluency

logger = logging.getLogger(__name__)

HISTORY_COLUMNS = [
    "date",
    "phrase",
    "kind",
    "occurrences",
    "words",
    "per_1000",
]

# A parenthetical in the table is a gloss for the reader — "cool (for everything
# positive)" — not part of the phrase to look for.
_GLOSS = re.compile(r"\([^)]*\)")
# The table offers alternatives with slashes, on both sides: a row may retire
# "estimate / estimation" and suggest "judge / assess / evaluate".
_ALTERNATIVES = re.compile(r"\s*/\s*")
# Some replacements open with an instruction rather than a phrase — "name the
# actual noun: this exercise / these expressions". Only what follows is sayable.
_INSTRUCTION = re.compile(r"^[^:]{0,40}:\s*")
# Anything that is not a letter or an internal apostrophe separates words.
_NON_WORD = re.compile(r"[^a-z']+")

# How many times a phrase has to have been said before its direction means
# anything. A phrase used once in the whole archive has no trend to report, and
# calling it "rising" is the same mistake the mistake history makes when it
# labels a difference of one instance — see `mistakes.SEPARABILITY_Z`.
MIN_FOR_MOVEMENT = 5


@dataclass
class Substitution:
    """One row of the table: what to stop saying, and what to say instead."""
    phrase: str
    replacements: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        # A one- or two-letter fragment matches far too much to mean anything.
        return len(self.phrase) >= 3


@dataclass
class Count:
    date: str
    phrase: str
    kind: str            # "retired" or "replacement"
    occurrences: int
    words: int

    @property
    def per_1000(self) -> Optional[float]:
        return round(self.occurrences / self.words * 1000, 2) if self.words else None


def clean_phrase(raw: str) -> str:
    """The searchable core of a table entry."""
    text = _GLOSS.sub(" ", (raw or "")).lower()
    text = text.replace("“", " ").replace("”", " ").replace('"', " ")
    text = _NON_WORD.sub(" ", text)
    return " ".join(text.split()).strip("' ")


def parse_substitutions(memory_path: Path) -> list[Substitution]:
    """The table, as pairs to count. Reads it through `brief.parse_memory` so the
    shape of memory.md is understood in one place."""
    memory = brief.parse_memory(memory_path)
    out = []
    for item in memory.vocabulary:
        # The gloss comes off before the alternatives are split, not after: a
        # parenthetical can itself contain a slash, and splitting first leaves
        # half a bracket on each side and turns the remains into phrases.
        suggested = _INSTRUCTION.sub("", _GLOSS.sub(" ", item.replacement or "").strip())
        replacements = [clean_phrase(part) for part in _ALTERNATIVES.split(suggested)]
        replacements = [r for r in replacements if r and len(r) >= 3]
        # A row can retire more than one phrase at once. Each is counted on its
        # own, because "estimate" and "estimation" do not have to move together.
        for part in _ALTERNATIVES.split(_GLOSS.sub(" ", item.phrase or "")):
            phrase = clean_phrase(part)
            if not phrase:
                continue
            substitution = Substitution(phrase=phrase, replacements=replacements)
            if substitution.usable:
                out.append(substitution)
    return out


def count_in(words: list[str], phrase: str) -> int:
    """How many times a phrase appears in a word sequence, on word boundaries.

    Word-by-word rather than by regex over the raw text, because the phrases are
    short and common: a substring search for "cool" also finds "cooling", and
    for "great" also "greater" — which is the difference between a phrase the
    speaker is leaning on and one they never said.
    """
    needle = phrase.split()
    if not needle:
        return 0
    span = len(needle)
    return sum(1 for i in range(len(words) - span + 1) if words[i:i + span] == needle)


def words_of(text: str) -> list[str]:
    """The reliable words of a session, lowercased, in order."""
    joined = " ".join(fluency.reliable_lines_from_annotated(text)).lower()
    return [w for w in _NON_WORD.split(joined) if w.strip("'")]


def measure_history(sessions_dir: Path,
                    substitutions: list[Substitution]) -> list[Count]:
    """Every archived session against every substitution, oldest first."""
    if not substitutions or not sessions_dir.is_dir():
        return []

    counts: list[Count] = []
    for archive in sorted(sessions_dir.glob("*.annotated.txt")):
        date = archive.name.split(".")[0]
        if len(date) != 10 or date.count("-") != 2:
            continue
        try:
            words = words_of(archive.read_text(encoding="utf-8"))
        except OSError:
            logger.warning("Could not read %s; skipping it", archive)
            continue
        for substitution in substitutions:
            counts.append(Count(date, substitution.phrase, "retired",
                                count_in(words, substitution.phrase), len(words)))
            for replacement in substitution.replacements:
                counts.append(Count(date, replacement, "replacement",
                                    count_in(words, replacement), len(words)))
    return counts


@dataclass
class Trend:
    """One phrase across the history."""
    phrase: str
    kind: str
    counts: list[int]
    dates: list[str]
    words: list[int]

    @property
    def total(self) -> int:
        return sum(self.counts)

    @property
    def early(self) -> float:
        half = max(1, len(self.counts) // 2)
        return _rate(self.counts[:half], self.words[:half])

    @property
    def late(self) -> float:
        half = max(1, len(self.counts) // 2)
        return _rate(self.counts[-half:], self.words[-half:])

    @property
    def movement(self) -> str:
        """Which way it went, over halves of the history.

        Halves rather than last-versus-previous for the same reason the mistake
        history tests its trends over a window: a single session of a short
        phrase is a coin flip. And below `MIN_FOR_MOVEMENT` there is no
        direction to report at all — a phrase said twice has not started
        rising, it has been said twice.
        """
        if not self.total:
            return "never said"
        if self.total < MIN_FOR_MOVEMENT:
            return "too few to tell"
        if self.late < self.early * 0.75:
            return "falling"
        if self.late > self.early * 1.25:
            return "rising"
        return "level"


def _rate(counts: list[int], words: list[int]) -> float:
    total_words = sum(words)
    return round(sum(counts) / total_words * 1000, 3) if total_words else 0.0


def summarize(counts: list[Count]) -> list[Trend]:
    """Per phrase, oldest session first, most-used first."""
    grouped: dict[tuple[str, str], list[Count]] = {}
    for count in counts:
        grouped.setdefault((count.phrase, count.kind), []).append(count)

    trends = []
    for (phrase, kind), rows in grouped.items():
        rows.sort(key=lambda c: c.date)
        trends.append(Trend(phrase=phrase, kind=kind,
                            counts=[r.occurrences for r in rows],
                            dates=[r.date for r in rows],
                            words=[r.words for r in rows]))
    trends.sort(key=lambda t: (-t.total, t.phrase))
    return trends


def write_history(path: Path, counts: list[Count]) -> None:
    """Rewritten, not appended: every row is recomputed from the archive and the
    table, so there is no observation here to preserve."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=HISTORY_COLUMNS)
        writer.writeheader()
        for count in counts:
            writer.writerow({
                "date": count.date,
                "phrase": count.phrase,
                "kind": count.kind,
                "occurrences": count.occurrences,
                "words": count.words,
                "per_1000": "" if count.per_1000 is None else count.per_1000,
            })
    logger.info("Wrote %d vocabulary counts to %s", len(counts), path)


def load_history(path: Path) -> list[Count]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            rows.append(Count(
                date=(raw.get("date") or "").strip(),
                phrase=(raw.get("phrase") or "").strip(),
                kind=(raw.get("kind") or "").strip(),
                occurrences=int(raw["occurrences"]),
                words=int(raw["words"]),
            ))
    rows.sort(key=lambda c: (c.date, c.phrase))
    return rows


def format_table(trends: list[Trend], substitutions: list[Substitution]) -> str:
    if not trends:
        return ("Nothing to count: memory.md has no 'Vocabulary To Replace' table, or "
                "no sessions are archived yet.")
    by_phrase = {(t.phrase, t.kind): t for t in trends}
    lines = ["Phrases the coach retired, and what replaced them.", ""]
    for substitution in substitutions:
        retired = by_phrase.get((substitution.phrase, "retired"))
        if not retired or not retired.total:
            continue
        lines.append(f"  {substitution.phrase}  —  {retired.movement}")
        lines.append(f"      said   {retired.counts}  (total {retired.total})")
        for replacement in substitution.replacements:
            arrived = by_phrase.get((replacement, "replacement"))
            if arrived and arrived.total:
                lines.append(f"      → {replacement}: {arrived.counts} "
                             f"(total {arrived.total}, {arrived.movement})")
    unsaid = [s.phrase for s in substitutions
              if not (by_phrase.get((s.phrase, "retired")) or Trend("", "", [], [], [])).total]
    if unsaid:
        lines.append("")
        lines.append("Never said in any archived session (nothing to retire): "
                     + ", ".join(unsaid))
    lines.append("")
    lines.append("Counts are per session, oldest first, over reliable lines only. A count "
                 "is a prompt to look, not a verdict: it cannot tell a word used well "
                 "from one leaned on.")
    return "\n".join(lines)


def _repo_root() -> Path:
    return Path(__file__).parent.parent


def main(argv: list[str] | None = None) -> int:
    """`python -m voxlib.vocab` — are the retired phrases actually going away?"""
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m voxlib.vocab",
        description="Count memory.md's retired phrases and their replacements over the "
                    "archived transcripts.",
    )
    parser.add_argument("--analysis", type=Path, default=_repo_root() / "analysis",
                        help="Directory holding memory.md and sessions/ (default: analysis/)")
    parser.add_argument("--write", action="store_true",
                        help="Write analysis/vocab_history.csv (rewritten, not appended)")
    args = parser.parse_args(argv)

    substitutions = parse_substitutions(args.analysis / "memory.md")
    counts = measure_history(args.analysis / "sessions", substitutions)
    print(format_table(summarize(counts), substitutions))
    if args.write and counts:
        write_history(args.analysis / "vocab_history.csv", counts)
        print(f"\nWrote {args.analysis / 'vocab_history.csv'}")
    return 0 if counts else 1


if __name__ == "__main__":
    raise SystemExit(main())
