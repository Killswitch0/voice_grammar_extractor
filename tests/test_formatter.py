import json
from pathlib import Path

from voxlib.formatter import (
    SourcedLine,
    write_annotated_document,
    write_clean_document,
    write_lines_json,
    write_split_documents,
)


def _sample_lines() -> list[SourcedLine]:
    return [
        SourcedLine(source_file="a.webm", start=0.0, end=2.0, text="Hello there", avg_logprob=-0.1),
        SourcedLine(source_file="a.webm", start=2.0, end=4.0, text="This is unclear", avg_logprob=-0.9),
        SourcedLine(source_file="b.webm", start=0.0, end=1.5, text="Second file line", avg_logprob=None),
    ]


def test_write_clean_document_is_just_the_text(tmp_path: Path):
    out = tmp_path / "clean.txt"
    write_clean_document(_sample_lines(), out)
    assert out.read_text() == "Hello there\nThis is unclear\nSecond file line\n"


def test_write_annotated_document_groups_by_source_and_marks_low_confidence(tmp_path: Path):
    out = tmp_path / "ann.txt"
    write_annotated_document(_sample_lines(), out, low_confidence_threshold=-0.5)
    text = out.read_text()

    assert "=== a.webm ===" in text
    assert "=== b.webm ===" in text
    assert "[00:00:00] Hello there" in text
    # avg_logprob -0.9 is below the -0.5 threshold -> marked low-confidence.
    assert "[00:00:02] [?] This is unclear" in text
    # avg_logprob -0.1 is above the threshold -> no marker.
    assert "[?] Hello there" not in text
    # avg_logprob=None can never be marked low-confidence.
    assert "[?] Second file line" not in text


def test_write_split_documents_respects_max_chars_and_never_splits_a_line(tmp_path: Path):
    lines = _sample_lines()
    # Small enough that each line becomes its own part, given the sample texts.
    paths = write_split_documents(lines, tmp_path, max_chars=15)

    assert [p.name for p in paths] == ["part_1.txt", "part_2.txt", "part_3.txt"]
    assert paths[0].read_text() == "Hello there\n"
    assert paths[1].read_text() == "This is unclear\n"
    assert paths[2].read_text() == "Second file line\n"


def test_write_split_documents_packs_multiple_short_lines_per_part(tmp_path: Path):
    lines = _sample_lines()
    # Generous enough for all three lines to fit in a single part.
    paths = write_split_documents(lines, tmp_path, max_chars=1000)

    assert len(paths) == 1
    assert paths[0].read_text() == "Hello there\nThis is unclear\nSecond file line\n"


def test_write_split_documents_clears_stale_parts_from_previous_runs(tmp_path: Path):
    parts_dir = tmp_path / "parts"
    parts_dir.mkdir()
    stale = parts_dir / "part_7.txt"
    stale.write_text("leftover from a bigger previous run")

    write_split_documents(_sample_lines(), tmp_path, max_chars=1000)

    assert not stale.exists()


def _mixed_confidence_lines() -> list[SourcedLine]:
    return [
        SourcedLine("a.webm", 0.0, 5.0, "a clear sentence with words", avg_logprob=-0.2),
        SourcedLine("a.webm", 6.0, 7.0, "mumbled", avg_logprob=-0.9),
        SourcedLine("b.webm", 0.0, 4.0, "another clear one", avg_logprob=None),
    ]


def test_lines_json_flags_confidence_per_line(tmp_path: Path):
    """
    The point of the file: the [?] information and the sentences live
    together, so "never judge grammar on a mis-recognized line" doesn't depend
    on aligning two text files by eye every session.
    """
    path = tmp_path / "lines.json"

    write_lines_json(_mixed_confidence_lines(), path, low_confidence_threshold=-0.5)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert [line["low_confidence"] for line in payload["lines"]] == [False, True, False]
    assert [line["text"] for line in payload["lines"]][1] == "mumbled"


def test_lines_json_agrees_with_the_annotated_document(tmp_path: Path):
    """Both come from formatter.is_low_confidence, and this pins that they
    can't drift: whatever carries a [?] marker is flagged in the JSON."""
    lines = _mixed_confidence_lines()
    annotated_path = tmp_path / "annotated.txt"
    json_path = tmp_path / "lines.json"

    write_annotated_document(lines, annotated_path, low_confidence_threshold=-0.5)
    write_lines_json(lines, json_path, low_confidence_threshold=-0.5)

    marked_in_text = [
        "[?]" in raw for raw in annotated_path.read_text(encoding="utf-8").splitlines()
        if raw.startswith("[")
    ]
    flagged_in_json = [
        line["low_confidence"] for line in json.loads(json_path.read_text(encoding="utf-8"))["lines"]
    ]
    assert marked_in_text == flagged_in_json


def test_lines_json_precomputes_totals(tmp_path: Path):
    path = tmp_path / "lines.json"

    write_lines_json(_mixed_confidence_lines(), path, low_confidence_threshold=-0.5)

    totals = json.loads(path.read_text(encoding="utf-8"))["totals"]
    assert totals["lines"] == 3
    assert totals["low_confidence_lines"] == 1
    assert totals["words"] == 9
    assert totals["reliable_words"] == 8  # "mumbled" excluded


def test_lines_json_keeps_source_file_and_timing(tmp_path: Path):
    """Line 3 restarts at 0.0 because it comes from a different recording —
    the source has to travel with it or the timeline reads as going backwards."""
    path = tmp_path / "lines.json"

    write_lines_json(_mixed_confidence_lines(), path, low_confidence_threshold=-0.5)

    third = json.loads(path.read_text(encoding="utf-8"))["lines"][2]
    assert third["source_file"] == "b.webm"
    assert (third["start"], third["end"]) == (0.0, 4.0)
    assert third["timestamp"] == "00:00:00"  # matches what the annotated file prints
    assert third["index"] == 2


def test_lines_json_records_the_threshold_it_applied(tmp_path: Path):
    path = tmp_path / "lines.json"

    write_lines_json(_mixed_confidence_lines(), path, low_confidence_threshold=-0.8)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["low_confidence_threshold"] == -0.8
    # A looser threshold means fewer lines flagged — readable from the file itself.
    assert payload["totals"]["low_confidence_lines"] == 1


def test_lines_json_handles_non_ascii_text(tmp_path: Path):
    path = tmp_path / "lines.json"

    write_lines_json(
        [SourcedLine("a.webm", 0.0, 1.0, "naïve café — déjà vu", avg_logprob=-0.1)],
        path, low_confidence_threshold=-0.5,
    )

    assert json.loads(path.read_text(encoding="utf-8"))["lines"][0]["text"] == "naïve café — déjà vu"
