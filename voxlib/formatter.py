"""
Builds the final text documents from transcribed lines.

Generates:
  - annotated: with timestamps, source file name, and a marker on low-confidence
    lines — for your navigation/review
  - clean:     just the lines themselves, one per line — to feed into an AI
  - (optionally) parts of the clean document, if it's too large for a single
    AI prompt
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class SourcedLine:
    source_file: str
    start: float
    end: float
    text: str
    avg_logprob: Optional[float] = None


# Whisper's avg_logprob typically ranges from about 0 (maximally confident)
# down to -1.5 and below (not confident at all). -0.5 works reasonably well in
# practice to separate questionable recognitions from normal ones.
DEFAULT_LOW_CONFIDENCE_THRESHOLD = -0.5


def is_low_confidence(avg_logprob: Optional[float], threshold: float) -> bool:
    """
    The single definition of "whisper wasn't sure about this line".

    Shared with voxlib/fluency.py, which excludes these lines from the fluency
    metrics for the same reason the analysis workflow excludes them from
    grammar judgment: a mis-recognized line says nothing about how the speaker
    actually spoke. Two definitions of the same idea would let the [?] you see
    in the document drift apart from the [?] the metrics acted on.

    A missing avg_logprob counts as confident — that's how the annotated
    document has always treated it, and inventing doubt where whisper reported
    none would silently shrink the analyzable transcript.
    """
    return avg_logprob is not None and avg_logprob < threshold


def _format_timestamp(seconds: float) -> str:
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def write_annotated_document(
    lines: list[SourcedLine],
    output_path: Path,
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    low_confidence_count = 0

    with output_path.open("w", encoding="utf-8") as f:
        current_source = None
        for line in lines:
            if line.source_file != current_source:
                current_source = line.source_file
                f.write(f"\n=== {current_source} ===\n")
            ts = _format_timestamp(line.start)
            low_confidence = is_low_confidence(line.avg_logprob, low_confidence_threshold)
            marker = " [?]" if low_confidence else ""
            if low_confidence:
                low_confidence_count += 1
            f.write(f"[{ts}]{marker} {line.text}\n")

    if low_confidence_count:
        import logging
        logging.getLogger(__name__).info(
            "Marked as low-confidence ([?]): %d out of %d lines. "
            "This is usually unclear diction/background noise in the recording — "
            "when reviewing grammar, double-check these lines against the original.",
            low_confidence_count, len(lines),
        )


def write_lines_json(
    lines: list[SourcedLine],
    output_path: Path,
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
) -> None:
    """
    The same lines as the two text documents, in a form nothing has to parse.

    The text files each hold half of what the analysis needs: the clean one has
    the sentences to review, the annotated one has the `[?]` markers saying
    which of them can be trusted. Using both meant aligning them by hand across
    hundreds of lines — and they don't even align one-to-one, since the
    annotated file carries `=== file.webm ===` headers the clean one doesn't.
    A rule as important as "never judge grammar on a mis-recognized line"
    shouldn't depend on getting that right by eye every session.

    So each line here carries its own confidence flag, its source file and its
    timing, and the totals are precomputed. `timestamp` is redundant with
    `start` on purpose: it's what the annotated document prints, so a line can
    still be found there by eye when a human wants to look.
    """
    low_confidence_flags = [is_low_confidence(line.avg_logprob, low_confidence_threshold) for line in lines]

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "low_confidence_threshold": low_confidence_threshold,
        "totals": {
            "lines": len(lines),
            "low_confidence_lines": sum(low_confidence_flags),
            "words": sum(len(line.text.split()) for line in lines),
            "reliable_words": sum(
                len(line.text.split())
                for line, low in zip(lines, low_confidence_flags) if not low
            ),
        },
        "lines": [
            {
                "index": index,
                "source_file": line.source_file,
                "start": round(line.start, 3),
                "end": round(line.end, 3),
                "timestamp": _format_timestamp(line.start),
                "text": line.text,
                "avg_logprob": line.avg_logprob,
                "low_confidence": low,
            }
            for index, (line, low) in enumerate(zip(lines, low_confidence_flags))
        ],
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_clean_document(lines: list[SourcedLine], output_path: Path) -> None:
    """
    Clean text: one line per line, no timestamps or file names.
    This is the file you paste as-is into an AI prompt for grammar analysis.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(f"{line.text}\n")


def write_split_documents(lines: list[SourcedLine], output_dir: Path, max_chars: int) -> list[Path]:
    """
    Splits the lines into several files part_1.txt, part_2.txt, ... so that
    each file is no longer than max_chars characters (lines are never split
    in the middle). Useful when you've accumulated a lot of recordings and the
    whole transcript_clean.txt doesn't fit into a single AI prompt at once.
    """
    parts_dir = output_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)

    # Clear old parts from previous runs, so no stale files are left behind
    # if there are fewer lines this time.
    for old_file in parts_dir.glob("part_*.txt"):
        old_file.unlink()

    written_paths: list[Path] = []
    current_lines: list[str] = []
    current_len = 0
    part_number = 1

    def flush() -> None:
        nonlocal current_lines, current_len, part_number
        if not current_lines:
            return
        part_path = parts_dir / f"part_{part_number}.txt"
        part_path.write_text("\n".join(current_lines) + "\n", encoding="utf-8")
        written_paths.append(part_path)
        part_number += 1
        current_lines = []
        current_len = 0

    for line in lines:
        text = line.text
        # +1 for the newline
        if current_len + len(text) + 1 > max_chars and current_lines:
            flush()
        current_lines.append(text)
        current_len += len(text) + 1

    flush()
    return written_paths
