"""
A record of which recordings have already been turned into a transcript.

The failure this guards against is specific. A session is recorded in parts and
the whole folder is processed at once, so merging many files into one
transcript is normal and must keep working. What isn't normal is the same
audio being merged in twice — because the folder wasn't cleared before the
next session, or because a run was repeated and archived under a second date.
Either way the occurrence counters in `analysis/memory.md` end up counting the
same sentences twice, and since that file is a running tally rather than
something recomputed from source, the error never washes out.

Recordings are identified by a hash of their contents, never by name: this
project's folder is emptied and refilled every session, so `part_01.webm` is a
different recording each time while the filename stays put. The names are
stored anyway, but only so the warning can say something a human recognizes.

Not size+mtime, which is what voxlib/cache.py uses. That pair is enough there
(it only has to answer "did THIS path change", and the cache is already keyed
per path) but it is not an identity: a session split into fixed-size chunks
and written in one go gives every part the same size and the same mtime. The
first version of this module used it and collapsed 15 real recordings into 7
entries. Hashing costs one pass over the file, against the minutes the same
file then spends in whisper.

Warning is the default rather than skipping, because "already processed" is
ambiguous on its own — deliberately re-running a session to try a different
--threshold is a perfectly good reason to see the same files again. `--only-new`
is there for when the intent really is "just the new ones".
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from pathlib import Path

logger = logging.getLogger(__name__)

VERSION = 2  # v1 keyed on size+mtime, which collided across same-size chunks

_HASH_CHUNK_BYTES = 1024 * 1024


def content_key(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def load(path: Path) -> dict:
    if not path.exists():
        return {"version": VERSION, "files": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read the processed-recordings log %s: %s. Ignoring it.", path, exc)
        return {"version": VERSION, "files": {}}
    if not isinstance(data.get("files"), dict):
        logger.warning("Processed-recordings log %s is not in the expected shape. Ignoring it.", path)
        return {"version": VERSION, "files": {}}
    if data.get("version") != VERSION:
        # v1 keyed on size+mtime, so its entries can't be matched against
        # content hashes at all. Start over rather than report nonsense: the
        # cost is one spurious-free run with no warnings.
        logger.info(
            "Processed-recordings log %s uses an older format (v%s) — starting a fresh one.",
            path, data.get("version"),
        )
        return {"version": VERSION, "files": {}}
    return data


def previously_processed(log: dict, files: list[Path]) -> dict[Path, dict]:
    """Which of `files` this log has seen before, mapped to what it knows."""
    known = log.get("files", {})
    seen: dict[Path, dict] = {}
    for file_path in files:
        try:
            entry = known.get(content_key(file_path))
        except OSError:
            continue  # unreadable file — the pipeline will report it properly
        if entry is not None:
            seen[file_path] = entry
    return seen


def describe(seen: dict[Path, dict], only_new: bool) -> str:
    """The message shown when a run includes recordings already transcribed."""
    by_date: dict[str, list[str]] = {}
    for file_path, entry in seen.items():
        by_date.setdefault(entry.get("last_processed", "an earlier run"), []).append(file_path.name)

    when = "; ".join(
        f"{', '.join(sorted(names))} on {day}" for day, names in sorted(by_date.items())
    )
    head = f"{len(seen)} recording(s) in this run were already transcribed before ({when})."

    if only_new:
        return head + " Skipping them, as --only-new was given."
    return (
        head + " Processing them again anyway — that's right if you're re-running a session "
        "on purpose (a different --threshold, say). But if you meant to analyze only new "
        "audio, this run will merge old speech into the new transcript, and the mistake "
        "counts in memory.md will double-count it. Clear the folder, or pass --only-new."
    )


def record(path: Path, files: list[Path], when: str | None = None) -> None:
    """Adds (or refreshes) an entry per file. Called only after a run that
    actually produced documents — a crashed run has nothing to remember."""
    log = load(path)
    today = when or date.today().isoformat()

    for file_path in files:
        try:
            key = content_key(file_path)
        except OSError:
            continue
        entry = log["files"].get(key)
        if entry is None:
            log["files"][key] = {
                "name": file_path.name,
                "first_processed": today,
                "last_processed": today,
                "runs": 1,
            }
        else:
            entry["name"] = file_path.name
            entry["last_processed"] = today
            entry["runs"] = entry.get("runs", 1) + 1

    log["version"] = VERSION
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(path)  # atomic, so an interrupted write can't corrupt the log
