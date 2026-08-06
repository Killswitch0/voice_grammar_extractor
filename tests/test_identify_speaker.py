import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

import identify_speaker as isp


@dataclass
class _FakeSegment:
    start: float
    end: float


def test_build_arg_parser_defaults(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    args = isp.build_arg_parser().parse_args(["call.webm"])
    assert args.input == Path("call.webm")
    assert args.output_dir == Path("output")
    assert args.reference_dir == Path("voice_reference")
    assert args.device == "cpu"
    assert args.hf_token is None
    assert args.verbose is False


def test_build_arg_parser_picks_up_hf_token_env_var(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_dummy_test_token")
    args = isp.build_arg_parser().parse_args(["call.webm"])
    assert args.hf_token == "hf_dummy_test_token"


def test_build_arg_parser_rejects_invalid_device(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        isp.build_arg_parser().parse_args(["call.webm", "--device", "quantum"])


def test_pick_sample_clip_selects_longest_segment_and_caps_duration():
    segments = [_FakeSegment(0.0, 2.0), _FakeSegment(5.0, 20.0), _FakeSegment(30.0, 33.0)]
    start, duration = isp._pick_sample_clip(segments, max_duration=12.0)
    assert start == 5.0
    assert duration == 12.0  # 15s longest segment capped to the 12s max


def test_pick_sample_clip_uses_full_duration_when_under_the_cap():
    segments = [_FakeSegment(0.0, 2.0), _FakeSegment(5.0, 20.0)]
    start, duration = isp._pick_sample_clip(segments, max_duration=30.0)
    assert start == 5.0
    assert duration == 15.0


def test_running_in_container_true_when_dockerenv_exists(monkeypatch):
    monkeypatch.setattr(isp.Path, "exists", lambda self: str(self) == "/.dockerenv")
    assert isp._running_in_container() is True


def test_running_in_container_false_when_dockerenv_missing(monkeypatch):
    monkeypatch.setattr(isp.Path, "exists", lambda self: False)
    assert isp._running_in_container() is False


def test_play_audio_stops_at_first_available_player(monkeypatch):
    monkeypatch.setattr(isp, "_running_in_container", lambda: False)
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd[0])
        if cmd[0] == "afplay":
            raise FileNotFoundError()
        return None  # ffplay "succeeds"

    with patch("subprocess.run", side_effect=fake_run):
        isp._play_audio(Path("sample.wav"))

    assert calls == ["afplay", "ffplay"]


def test_play_audio_falls_back_to_printing_the_path_when_no_player_exists(monkeypatch, capsys):
    monkeypatch.setattr(isp, "_running_in_container", lambda: False)
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        isp._play_audio(Path("sample.wav"))

    out = capsys.readouterr().out
    assert "sample.wav" in out
    assert "No audio player found" in out


def test_play_audio_skips_players_entirely_when_in_a_container(monkeypatch, capsys):
    # ffplay is normally present in the container (it ships with ffmpeg) and
    # exits 0 even with no audio device — a false "success" we can't detect
    # from the exit code. Must skip straight to the manual-open message.
    monkeypatch.setattr(isp, "_running_in_container", lambda: True)

    with patch("subprocess.run") as mock_run:
        isp._play_audio(Path("sample.wav"))
        mock_run.assert_not_called()

    out = capsys.readouterr().out
    assert "sample.wav" in out
    assert "container" in out.lower()


def test_confirm_overwrite_returns_true_without_prompting_when_nothing_exists(monkeypatch):
    monkeypatch.setattr(isp.Path, "exists", lambda self: False)
    with patch("identify_speaker.Confirm.ask") as mock_ask:
        assert isp._confirm_overwrite(Path("my_reference.wav")) is True
        mock_ask.assert_not_called()


def test_confirm_overwrite_returns_false_when_user_declines(monkeypatch):
    monkeypatch.setattr(isp.Path, "exists", lambda self: True)
    with patch("identify_speaker.Confirm.ask", return_value=False):
        assert isp._confirm_overwrite(Path("my_reference.wav")) is False


def test_confirm_overwrite_returns_true_when_user_accepts(monkeypatch):
    monkeypatch.setattr(isp.Path, "exists", lambda self: True)
    with patch("identify_speaker.Confirm.ask", return_value=True):
        assert isp._confirm_overwrite(Path("my_reference.wav")) is True


def test_confirm_overwrite_defaults_to_no(monkeypatch):
    # Overwriting the permanent reference sample is destructive — the prompt
    # must default to declining, not accepting, a blank Enter.
    monkeypatch.setattr(isp.Path, "exists", lambda self: True)
    with patch("identify_speaker.Confirm.ask", return_value=False) as mock_ask:
        isp._confirm_overwrite(Path("my_reference.wav"))
        assert mock_ask.call_args.kwargs.get("default") is False


def test_main_handles_keyboard_interrupt_gracefully(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        sys, "argv",
        ["identify_speaker.py", "dummy.mp4", "--hf-token", "dummy", "-o", str(tmp_path)],
    )

    def raise_interrupt(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr("voxlib.audio_utils.extract_audio", raise_interrupt)

    exit_code = isp.main()

    assert exit_code == 130
    assert "Cancelled" in capsys.readouterr().out
