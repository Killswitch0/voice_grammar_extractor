from pathlib import Path

from voxlib.formatter import (
    SourcedLine,
    write_annotated_document,
    write_clean_document,
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
