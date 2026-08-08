"""
Shared validation for the numeric settings, used by BOTH the command line and
the config file.

There are two ways into every setting — argparse `type=` and a YAML key — and
only the first one used to check anything. A config file bypassed argparse's
conversion entirely, so a value that the CLI would reject outright could still
reach the pipeline through `--config`. Keeping the rules in one place is what
makes the two paths agree by construction rather than by remembering to update
both.

Each function accepts a raw string (from the CLI) or an already-typed value
(from YAML) and raises ValueError with a message meant for a human. main.py
adapts that into argparse's own error type; config.py lets it surface as-is.
"""

from __future__ import annotations

# Cosine similarity is mathematically bounded to this range (see
# DiarizationEngine.cosine_similarity), so anything outside it can only be a
# typo — "8.0" meant as "0.8" would otherwise silently misidentify every
# speaker rather than failing.
COSINE_MIN, COSINE_MAX = -1.0, 1.0

# Whisper's avg_logprob is always <= 0 and realistically sits between 0 and
# about -1.5. A positive threshold would mark EVERY line as low-confidence,
# and since the analysis workflow excludes [?] lines from grammar judgment
# entirely, that quietly empties the review instead of erroring.
LOGPROB_MIN, LOGPROB_MAX = -10.0, 0.0


def _as_float(value, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a number, got {value!r}") from None


def cosine_threshold(value, name: str = "threshold") -> float:
    parsed = _as_float(value, name)
    if not (COSINE_MIN <= parsed <= COSINE_MAX):
        raise ValueError(
            f"{name} must be between {COSINE_MIN} and {COSINE_MAX} "
            f"(it's a cosine similarity), got {parsed}"
        )
    return parsed


def logprob_threshold(value, name: str = "low_confidence_threshold") -> float:
    parsed = _as_float(value, name)
    if not (LOGPROB_MIN <= parsed <= LOGPROB_MAX):
        raise ValueError(
            f"{name} must be between {LOGPROB_MIN} and {LOGPROB_MAX} "
            f"(it's whisper's avg_logprob, always <= 0 and usually above -1.5), got {parsed}"
        )
    return parsed


def non_negative_float(value, name: str) -> float:
    parsed = _as_float(value, name)
    if parsed < 0:
        raise ValueError(f"{name} must be 0 or greater, got {parsed} (0 turns the feature off)")
    return parsed


def positive_int(value, name: str) -> int:
    # int(str(...)) rather than int(...) on purpose: int(8.5) would silently
    # truncate a fractional YAML value to 8 instead of rejecting it.
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be a whole number, got {value!r}") from None
    if parsed <= 0:
        raise ValueError(
            f"{name} must be greater than 0, got {parsed} "
            f"(leave it unset to turn the feature off)"
        )
    return parsed
