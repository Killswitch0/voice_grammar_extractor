"""
Cache of intermediate progress for processing a single file.

Diarization and transcription are the most expensive steps in terms of time.
If the script crashes 50 minutes into a one-hour recording (network issue, out
of memory, Ctrl+C), without a cache everything would have to be redone from
scratch. Here, the result of each step is saved to disk right after it's
computed, and on a re-run of the same file the already-done steps are picked
up from the cache instead of being recomputed.

The cache is invalidated in layers, each narrower than the last:
  - the input file itself changed (size/mtime) -> everything is reset.
  - the mode changed ("diarization" vs "solo") -> everything is reset (solo
    transcribes the whole file, diarization transcribes only "your" segments
    — the two are not interchangeable).
  - the reference voice sample changed -> identification and transcription
    are reset, but diarization (segmentation of the recording itself) is
    kept, since it never depended on the reference voice.
  - the segment-merging gap changed -> identification and transcription are
    reset, but diarization is kept: merging is applied to pyannote's raw
    output every run, so a different gap reshapes the segments without
    needing the expensive model pass again. Everything computed per segment
    afterwards is keyed to those boundaries, though, and has to go.
  - the transcription-affecting settings changed (whisper model, language,
    batch size) -> only transcription is reset; diarization/identification
    are untouched.
Without this, changing --threshold, --reference, or --whisper-model on a
file you've already processed would silently keep using stale results.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _cache_path(cache_dir: Path, input_file: Path) -> Path:
    """
    Cache file name for an input recording.

    The stem alone is not unique: `part_01.webm` and `part_01.m4a` sitting in
    the same folder would share one cache file, and since each one's
    fingerprint check fails against the other's, they'd take turns wiping each
    other's diarization on every run. Appending a short hash of the full
    resolved path keeps the name readable while making it actually identify
    one file.
    """
    digest = hashlib.sha1(str(input_file.resolve()).encode("utf-8")).hexdigest()[:8]
    return cache_dir / f"{input_file.stem}_{digest}.json"


def file_fingerprint(path: Path) -> dict:
    """Cheap identity check for a file (size + mtime) — used both for the
    input recording and, separately, for the reference voice sample."""
    stat = path.stat()
    return {"size": stat.st_size, "mtime": stat.st_mtime}


def load_cache(
    cache_dir: Path,
    input_file: Path,
    mode: str,
    reference_fingerprint: dict | None = None,
    transcription_params: dict | None = None,
    segmentation_params: dict | None = None,
) -> dict[str, Any]:
    """
    Returns the cache for this file, narrowed down by whichever of the
    checks below apply (see the module docstring for the full cascade).
    """
    path = _cache_path(cache_dir, input_file)
    empty = {"diarization": None, "identification": None, "transcription": []}

    if not path.exists():
        return empty

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read cache %s: %s. Ignoring cache.", path, exc)
        return empty

    if data.get("file_fingerprint") != file_fingerprint(input_file):
        logger.info("File %s has changed since the last run — its cache was reset.", input_file.name)
        return empty

    if data.get("mode") != mode:
        logger.info(
            "File %s was previously processed in a different mode (%s vs %s now) — "
            "its cache was reset to avoid mixing lines from the two modes.",
            input_file.name, data.get("mode"), mode,
        )
        return empty

    result = {
        "diarization": data.get("diarization"),
        "identification": data.get("identification"),
        "transcription": data.get("transcription", []),
    }

    if mode == "diarization" and reference_fingerprint is not None:
        if data.get("reference_fingerprint") != reference_fingerprint:
            logger.info(
                "Reference voice sample has changed since the last run on %s — "
                "identification and transcription were reset (diarization is kept).",
                input_file.name,
            )
            result["identification"] = None
            result["transcription"] = []

    if mode == "diarization" and segmentation_params is not None:
        if data.get("segmentation_params") != segmentation_params:
            logger.info(
                "Segment merging changed since the last run on %s — identification and "
                "transcription were reset (raw diarization is kept and re-merged).",
                input_file.name,
            )
            result["identification"] = None
            result["transcription"] = []

    if transcription_params is not None and data.get("transcription_params") != transcription_params:
        logger.info(
            "Transcription settings (model/language/batch size) changed since the last "
            "run on %s — its cached transcription was reset.",
            input_file.name,
        )
        result["transcription"] = []

    return result


def save_cache(
    cache_dir: Path,
    input_file: Path,
    mode: str,
    cache_data: dict[str, Any],
    reference_fingerprint: dict | None = None,
    transcription_params: dict | None = None,
    segmentation_params: dict | None = None,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir, input_file)
    payload = {
        "file_fingerprint": file_fingerprint(input_file),
        "mode": mode,
        **cache_data,
    }
    if reference_fingerprint is not None:
        payload["reference_fingerprint"] = reference_fingerprint
    if transcription_params is not None:
        payload["transcription_params"] = transcription_params
    if segmentation_params is not None:
        payload["segmentation_params"] = segmentation_params

    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(path)  # atomic replace — won't leave a corrupt file on a write interruption


def segments_to_dicts(segments: list) -> list[dict]:
    return [asdict(s) for s in segments]
