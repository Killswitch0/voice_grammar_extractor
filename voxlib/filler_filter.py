"""
Optional cleanup of meaningless filler sounds (um, uh, erm) from the
transcript — enabled with the --remove-fillers flag.

Important design decision: phrases like "like", "you know", "I mean", "kind
of", "basically", "actually" are deliberately NOT included here. Even though
they're often used as conversational fillers, they're also fully meaningful
words in other contexts ("I like it", "I mean what I say", "actually, I
disagree"). A regex can't reliably tell one usage apart from the other, and
for a tool whose purpose is GRAMMAR analysis, the risk of accidentally
breaking a real sentence (and thereby introducing a fake error) is worse than
leaving a few extra fillers untouched.

"um"/"uh"/"erm" are safe to remove *as standalone sounds* — but only then.
"uh" is also the first half of "uh-huh", which is not hesitation at all: it
means "yes", the spoken equivalent of a nod. Matching it there used to turn
"Uh-huh, I agree" into "-huh, I agree", inventing a broken line in a document
whose whole purpose is grammar review. Hence the backchannel guard below.
"mm-hmm" never matched in the first place, and is left alone for the same
reason.
"""

from __future__ import annotations

import re

# Hesitation sounds, and only those. The (?![-\s]huh) guard is what keeps
# "uh-huh" and "uh huh" — backchannel agreement, not hesitation — out of both
# the removal and the count.
#
# Public because voxlib/fluency.py counts fillers with this exact pattern: one
# definition means the number reported as a fluency metric can never disagree
# with what --remove-fillers actually strips, and the metric inherits the same
# backchannel exclusion the analysis workflow has always applied by hand.
FILLER_SOUND_PATTERN = re.compile(r"\b(um+|uh+|erm+)\b(?![-\s]huh)[,]?", re.IGNORECASE)


def remove_fillers(text: str) -> str:
    """
    Removes pure filler sounds (um, uh, erm) from the text.
    Does not touch meaningful filler words (like, you know, I mean, etc.) —
    see the module docstring for why this is a deliberate choice.
    """
    cleaned = FILLER_SOUND_PATTERN.sub("", text)

    # collapse extra whitespace and duplicate punctuation left behind after removal
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([,.!?])", r"\1", cleaned)
    cleaned = re.sub(r"([,.!?])\s*\1+", r"\1", cleaned)
    return cleaned.strip()
