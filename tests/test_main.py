from pathlib import Path

from main import _print_dry_run_result, _print_full_result


def test_print_dry_run_result_preserves_bracketed_filename(capsys):
    _print_dry_run_result({
        "per_file": [
            {
                "file": "call [draft].webm",
                "num_speakers": 2,
                "num_segments_total": 40,
                "num_segments_mine": 22,
                "duration_mine_sec": 185.0,
                "mine_share_pct": 61.0,
            },
        ],
    })

    out = capsys.readouterr().out
    assert "call [draft].webm" in out


def test_print_full_result_preserves_bracketed_paths(capsys):
    # Short, hand-built paths (rather than tmp_path's long OS-generated
    # prefix) so the line stays well under the console's wrap width — a
    # wrapped line is a display artifact unrelated to what's under test here.
    annotated = Path("out [draft]/transcript_annotated.txt")
    clean = Path("out [draft]/transcript_clean.txt")

    _print_full_result({"annotated": annotated, "clean": clean})

    out = capsys.readouterr().out
    assert str(annotated) in out
    assert str(clean) in out
