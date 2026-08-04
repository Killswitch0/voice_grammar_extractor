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
leaving a few extra fillers untouched. "um"/"uh"/"erm" are safe because
they're pure pause sounds with no meaningful use whatsoever.
"""

from __future__ import annotations

import re

# Safe to remove — have no meaningful use in the English language.
_FILLER_SOUND_PATTERN = re.compile(r"\b(um+|uh+|erm+)\b[,]?", re.IGNORECASE)


def remove_fillers(text: str) -> str:
    """
    Removes pure filler sounds (um, uh, erm) from the text.
    Does not touch meaningful filler words (like, you know, I mean, etc.) —
    see the module docstring for why this is a deliberate choice.
    """
    cleaned = _FILLER_SOUND_PATTERN.sub("", text)

    # collapse extra whitespace and duplicate punctuation left behind after removal
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([,.!?])", r"\1", cleaned)
    cleaned = re.sub(r"([,.!?])\s*\1+", r"\1", cleaned)
    return cleaned.strip()
