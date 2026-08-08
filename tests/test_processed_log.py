"""
The log exists to stop the same audio being merged into two different
"sessions". `analysis/memory.md` is a running tally, not something recomputed
from source, so a double-counted session never washes out of it.
"""

import json
import os
from pathlib import Path

import pytest

from voxlib import processed


def _recording(tmp_path: Path, name: str, content: bytes = b"audio bytes") -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def test_nothing_is_known_before_the_first_run(tmp_path: Path):
    log = processed.load(tmp_path / "processed.json")
    assert processed.previously_processed(log, [_recording(tmp_path, "a.webm")]) == {}


def test_a_recorded_file_is_recognized_on_the_next_run(tmp_path: Path):
    log_path = tmp_path / "processed.json"
    recording = _recording(tmp_path, "part_01.webm")

    processed.record(log_path, [recording], when="2026-08-06")
    seen = processed.previously_processed(processed.load(log_path), [recording])

    assert list(seen) == [recording]
    assert seen[recording]["last_processed"] == "2026-08-06"
    assert seen[recording]["runs"] == 1


def test_files_are_matched_by_content_not_by_name(tmp_path: Path):
    """
    The decisive case for this project: the recordings folder is emptied and
    refilled every session, so `part_01.webm` is a different recording each
    time while the name stays put. Matching by name would silently skip every
    new session's first file.
    """
    log_path = tmp_path / "processed.json"
    old = _recording(tmp_path, "part_01.webm", b"last week's audio")
    processed.record(log_path, [old], when="2026-08-01")

    # Same name, new content — this is a new recording.
    old.write_bytes(b"this week's audio, a different length entirely")

    assert processed.previously_processed(processed.load(log_path), [old]) == {}


def test_reprocessing_bumps_the_run_count_and_date(tmp_path: Path):
    log_path = tmp_path / "processed.json"
    recording = _recording(tmp_path, "a.webm")

    processed.record(log_path, [recording], when="2026-08-06")
    processed.record(log_path, [recording], when="2026-08-08")

    entry = next(iter(processed.previously_processed(processed.load(log_path), [recording]).values()))
    assert entry["runs"] == 2
    assert entry["first_processed"] == "2026-08-06"
    assert entry["last_processed"] == "2026-08-08"


def test_only_the_repeated_files_are_reported(tmp_path: Path):
    log_path = tmp_path / "processed.json"
    old = _recording(tmp_path, "old.webm", b"old audio")
    processed.record(log_path, [old], when="2026-08-06")
    new = _recording(tmp_path, "new.webm", b"brand new audio, longer")

    seen = processed.previously_processed(processed.load(log_path), [old, new])

    assert list(seen) == [old]


def test_a_corrupt_log_is_ignored_rather_than_fatal(tmp_path: Path):
    log_path = tmp_path / "processed.json"
    log_path.write_text("{not json at all", encoding="utf-8")

    assert processed.load(log_path)["files"] == {}


def test_a_log_of_the_wrong_shape_is_ignored(tmp_path: Path):
    log_path = tmp_path / "processed.json"
    log_path.write_text(json.dumps({"version": 1, "files": ["not", "a", "dict"]}), encoding="utf-8")

    assert processed.load(log_path)["files"] == {}


def test_record_leaves_no_temp_file_behind(tmp_path: Path):
    log_path = tmp_path / "nested" / "processed.json"

    processed.record(log_path, [_recording(tmp_path, "a.webm")])

    assert log_path.exists()
    assert list(log_path.parent.glob("*.tmp")) == []


def test_warning_names_the_files_and_when_they_were_seen(tmp_path: Path):
    seen = {Path("part_01.webm"): {"name": "part_01.webm", "last_processed": "2026-08-06"}}

    message = processed.describe(seen, only_new=False)

    assert "part_01.webm" in message
    assert "2026-08-06" in message
    # Says what the consequence is, not just that it noticed.
    assert "double-count" in message
    assert "--only-new" in message


def test_warning_says_it_is_skipping_when_only_new_is_set(tmp_path: Path):
    seen = {Path("a.webm"): {"name": "a.webm", "last_processed": "2026-08-06"}}

    message = processed.describe(seen, only_new=True)

    assert "Skipping" in message
    assert "double-count" not in message


def test_describe_groups_several_files_under_their_dates():
    seen = {
        Path("a.webm"): {"name": "a.webm", "last_processed": "2026-08-06"},
        Path("b.webm"): {"name": "b.webm", "last_processed": "2026-08-06"},
        Path("c.webm"): {"name": "c.webm", "last_processed": "2026-08-04"},
    }

    message = processed.describe(seen, only_new=False)

    assert "3 recording(s)" in message
    assert "a.webm, b.webm on 2026-08-06" in message
    assert "c.webm on 2026-08-04" in message


def test_an_unreadable_file_does_not_break_the_lookup(tmp_path: Path):
    """The pipeline reports missing/unreadable inputs properly on its own —
    this log must not be the thing that crashes first."""
    log = processed.load(tmp_path / "processed.json")

    assert processed.previously_processed(log, [tmp_path / "does_not_exist.webm"]) == {}


def test_record_skips_files_that_vanished_mid_run(tmp_path: Path):
    log_path = tmp_path / "processed.json"

    processed.record(log_path, [tmp_path / "gone.webm"])

    assert processed.load(log_path)["files"] == {}


@pytest.mark.parametrize("only_new", [True, False])
def test_describe_never_returns_an_empty_message(only_new):
    seen = {Path("a.webm"): {"name": "a.webm", "last_processed": "2026-08-06"}}
    assert processed.describe(seen, only_new).strip()


def test_same_size_and_mtime_are_not_treated_as_the_same_recording(tmp_path: Path):
    """
    The bug the first version of this module shipped with. A session split
    into fixed-size chunks and written in one go gives every part identical
    size AND identical mtime — keying on that pair collapsed 15 real
    recordings into 7 entries, so two thirds of them were silently reported
    as "already transcribed" the moment one of them was.
    """
    log_path = tmp_path / "processed.json"
    same_size = [tmp_path / f"part_{i:02d}.webm" for i in range(1, 6)]
    for index, path in enumerate(same_size):
        path.write_bytes(bytes([index]) * 4096)  # equal length, different content
    mtime = same_size[0].stat().st_mtime
    for path in same_size:
        os.utime(path, (mtime, mtime))

    assert len({p.stat().st_size for p in same_size}) == 1
    assert len({p.stat().st_mtime for p in same_size}) == 1

    processed.record(log_path, same_size, when="2026-08-06")

    assert len(processed.load(log_path)["files"]) == 5
    assert len(processed.previously_processed(processed.load(log_path), same_size)) == 5


def test_identical_content_under_two_names_is_one_recording(tmp_path: Path):
    """The flip side, and the correct behaviour: the same audio copied twice
    is the same audio, whatever it's called."""
    log_path = tmp_path / "processed.json"
    original = _recording(tmp_path, "session.webm", b"identical bytes")
    copy = _recording(tmp_path, "session_copy.webm", b"identical bytes")

    processed.record(log_path, [original], when="2026-08-06")

    assert list(processed.previously_processed(processed.load(log_path), [copy])) == [copy]


def test_a_v1_log_is_discarded_rather_than_misread(tmp_path: Path):
    """v1 keyed on size+mtime; those keys can never match a content hash, so
    reading them would report every file as new while looking authoritative."""
    log_path = tmp_path / "processed.json"
    log_path.write_text(json.dumps({
        "version": 1,
        "files": {"4829633:1786182616.0": {"name": "part_01.webm", "last_processed": "2026-08-06"}},
    }), encoding="utf-8")

    assert processed.load(log_path)["files"] == {}
    assert processed.load(log_path)["version"] == processed.VERSION
