"""
Discourse markers — the verbal tics that a hesitation counter can't see.

`fluency.py` counts pure pause sounds (um/uh/erm). Those are not this speaker's
problem: the measured rate has sat between 0.00 and 0.12 per 100 words for four
sessions running. What actually makes the speech sound unpolished is a phrase
doing the same job a hesitation sound does for other people — on 2026-08-08,
"you know" appeared 101 times in 2,292 words, which is roughly forty times the
filler rate for the same session.

That number was found by hand and written into `analysis/memory.md` as prose
("Any future fluency judgment should look at this by hand"). Counting the single
most important fluency signal by hand every session is exactly what
`fluency.py`'s own docstring argues against: the rule being applied lives
nowhere executable, so nothing stops the next session from drawing the line
somewhere slightly different. Hence this module.

**What is deliberately NOT counted, and why.**

"like" and "so" are the two other obvious candidates, and both are excluded.
They are genuinely ambiguous — "I like it", "something like that", "so I went
home", "it was so good" are all ordinary uses, and no word-level rule separates
them from the filler ones reliably. A metric whose definition can't be pinned
down can't be compared against itself six months later, which is the only thing
this number is for. "like" is frequent enough in this project's transcripts (61
uses on 2026-08-08) to be worth watching, but it has to be watched by eye, and
the report should say so rather than quietly folding a guess into the series.

The markers below are counted in **every** use, including the occasional
legitimate one ("basically" as a real qualifier). That's on purpose too: the
point of the measurement is the tic, and a genuine "basically" repeated thirty
times in a conversation is the tic. The alternative — trying to judge intent per
occurrence — is the ambiguity problem again.
"""

from __future__ import annotations

import re

# Ordered roughly by how much they've mattered in this project's transcripts, so
# the breakdown in fluency.json reads top-down. Each pattern is anchored on word
# boundaries and matched case-insensitively.
#
# Multi-word markers allow any run of whitespace between the words: whisper
# sometimes splits them across a line break inside a merged segment.
_MARKER_SOURCES: dict[str, str] = {
    "you know": r"\byou\s+know\b|\by'?know\b",
    "i mean": r"\bi\s+mean\b",
    "kind of": r"\bkind\s+of\b|\bkinda\b",
    "sort of": r"\bsort\s+of\b|\bsorta\b",
    "basically": r"\bbasically\b",
    "actually": r"\bactually\b",
    "literally": r"\bliterally\b",
    "you see": r"\byou\s+see\b",
    "or something": r"\bor\s+something\b",
    "and stuff": r"\band\s+stuff\b",
    "how to say": r"\bhow\s+to\s+say\b",
    "let's say": r"\blet'?s\s+say\b",
}

DISCOURSE_MARKERS: dict[str, re.Pattern] = {
    name: re.compile(pattern, re.IGNORECASE) for name, pattern in _MARKER_SOURCES.items()
}

# Named so a reader of this module doesn't have to reconstruct the reasoning in
# the docstring from the absence of two entries above.
DELIBERATELY_NOT_COUNTED = ("like", "so")


def count_markers(text: str) -> dict[str, int]:
    """
    Per-marker counts for one piece of text. Markers with no hits are omitted,
    so a breakdown stays readable instead of being mostly zeros.

    "you know" is matched before nothing else needs to be: no pattern here is a
    prefix of another, so the counts can't double-count a single phrase.
    """
    counts = {}
    for name, pattern in DISCOURSE_MARKERS.items():
        hits = len(pattern.findall(text))
        if hits:
            counts[name] = hits
    return counts


def count_all(text: str) -> int:
    """Total marker occurrences — the number the tracked rate is built from."""
    return sum(count_markers(text).values())


def merge_counts(per_line: list[dict[str, int]]) -> dict[str, int]:
    """
    Folds per-line breakdowns into one, keeping the declaration order of
    DISCOURSE_MARKERS rather than the order the lines happened to hit them in —
    two sessions' breakdowns should be readable side by side.
    """
    totals: dict[str, int] = {}
    for name in DISCOURSE_MARKERS:
        total = sum(counts.get(name, 0) for counts in per_line)
        if total:
            totals[name] = total
    return totals
