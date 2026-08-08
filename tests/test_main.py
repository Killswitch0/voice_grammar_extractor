import sys
from pathlib import Path

import main


def test_threshold_defaults_to_none_without_config_or_flag():
    args = main.build_arg_parser().parse_args(["call.webm"])
    assert args.threshold is None


def test_explicit_threshold_flag_is_used():
    args = main.build_arg_parser().parse_args(["call.webm", "--threshold", "0.6"])
    assert args.threshold == 0.6


def test_config_threshold_is_used_when_flag_not_given():
    args = main.build_arg_parser({"threshold": 0.6}).parse_args(["call.webm"])
    assert args.threshold == 0.6


def test_explicit_flag_overrides_config():
    args = main.build_arg_parser({"threshold": 0.6}).parse_args(["call.webm", "--threshold", "0.9"])
    assert args.threshold == 0.9


def test_print_dry_run_result_preserves_bracketed_filename(capsys):
    main._print_dry_run_result({
        "per_file": [
            {
                "file": "call [draft].webm",
                "num_speakers": 2,
                "num_speakers_mine": 1,
                "num_segments_total": 40,
                "num_segments_mine": 22,
                "duration_mine_sec": 185.0,
                "mine_share_pct": 61.0,
                "threshold": 0.75,
            },
        ],
    })

    out = capsys.readouterr().out
    assert "call [draft].webm" in out


def _dry_run_stats(**overrides) -> dict:
    stats = {
        "file": "call.webm",
        "num_speakers": 2,
        "num_speakers_mine": 1,
        "num_segments_total": 40,
        "num_segments_mine": 22,
        "duration_mine_sec": 185.0,
        "mine_share_pct": 61.0,
        "threshold": 0.75,
    }
    stats.update(overrides)
    return stats


def test_dry_run_flags_when_more_than_one_speaker_matched(capsys):
    """Exactly one speaker matching is the only healthy outcome — 2+ means
    another person's speech joins yours in a document whose whole premise is
    that it holds only yours."""
    main._print_dry_run_result({"per_file": [_dry_run_stats(num_speakers_mine=2)]})

    out = capsys.readouterr().out
    assert "Speakers (you)" in out
    assert "mixes another person's speech" in out


def test_dry_run_flags_when_no_speaker_matched(capsys):
    main._print_dry_run_result({"per_file": [_dry_run_stats(num_speakers_mine=0)]})

    out = capsys.readouterr().out
    assert "empty transcript" in out


def test_dry_run_stays_quiet_when_exactly_one_speaker_matched(capsys):
    main._print_dry_run_result({"per_file": [_dry_run_stats(num_speakers_mine=1)]})

    out = capsys.readouterr().out
    assert "mixes another person's speech" not in out
    assert "empty transcript" not in out


def test_print_full_result_preserves_bracketed_paths(capsys):
    # Short, hand-built paths (rather than tmp_path's long OS-generated
    # prefix) so the line stays well under the console's wrap width — a
    # wrapped line is a display artifact unrelated to what's under test here.
    annotated = Path("out [draft]/transcript_annotated.txt")
    clean = Path("out [draft]/transcript_clean.txt")

    main._print_full_result({"annotated": annotated, "clean": clean})

    out = capsys.readouterr().out
    assert str(annotated) in out
    assert str(clean) in out


def test_main_handles_keyboard_interrupt_gracefully(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "dummy.mp4", "--no-diarization"])

    def raise_interrupt(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr("voxlib.pipeline.run_pipeline", raise_interrupt)

    exit_code = main.main()

    assert exit_code == 130
    assert "Cancelled" in capsys.readouterr().out
