from pathlib import Path

import pytest

from voxlib import audio_utils


class FakeCompletedProcess:
    """Stand-in for subprocess.CompletedProcess — no real ffmpeg/ffprobe needed."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_check_ffmpeg_available_raises_when_not_on_path(monkeypatch):
    monkeypatch.setattr(audio_utils.shutil, "which", lambda name: None)
    with pytest.raises(audio_utils.AudioExtractionError):
        audio_utils.check_ffmpeg_available()


def test_check_ffmpeg_available_passes_when_on_path(monkeypatch):
    monkeypatch.setattr(audio_utils.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    audio_utils.check_ffmpeg_available()  # no exception


def test_extract_audio_raises_for_missing_input(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_utils.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    missing = tmp_path / "does_not_exist.mp4"
    with pytest.raises(audio_utils.AudioExtractionError):
        audio_utils.extract_audio(missing, tmp_path)


def test_extract_audio_builds_correct_ffmpeg_command(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_utils.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    input_file = tmp_path / "call.webm"
    input_file.write_bytes(b"fake recording bytes")
    output_dir = tmp_path / "out"

    captured = {}

    def fake_run(cmd, capture_output, text):
        captured["cmd"] = cmd
        # Simulate ffmpeg actually producing the output file, since
        # extract_audio checks output_path.exists() after the call.
        output_path = Path(cmd[-1])
        output_path.write_bytes(b"fake wav bytes")
        return FakeCompletedProcess(returncode=0)

    monkeypatch.setattr(audio_utils.subprocess, "run", fake_run)

    result_path = audio_utils.extract_audio(input_file, output_dir)

    assert result_path == output_dir / "call.wav"
    cmd = captured["cmd"]
    assert cmd[0] == "ffmpeg"
    assert str(input_file) in cmd
    assert cmd[cmd.index("-ac") + 1] == "1"
    assert cmd[cmd.index("-ar") + 1] == str(audio_utils.TARGET_SAMPLE_RATE)
    assert cmd[cmd.index("-sample_fmt") + 1] == "s16"
    assert cmd[cmd.index("-acodec") + 1] == "pcm_s16le"


def test_extract_audio_raises_on_nonzero_returncode(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_utils.shutil, "which", lambda name: "/usr/bin/ffmpeg")
    input_file = tmp_path / "call.webm"
    input_file.write_bytes(b"fake recording bytes")

    def fake_run(cmd, capture_output, text):
        return FakeCompletedProcess(returncode=1, stderr="ffmpeg exploded")

    monkeypatch.setattr(audio_utils.subprocess, "run", fake_run)

    with pytest.raises(audio_utils.AudioExtractionError, match="ffmpeg exploded"):
        audio_utils.extract_audio(input_file, tmp_path / "out")


def test_get_audio_duration_seconds_parses_ffprobe_output(tmp_path, monkeypatch):
    def fake_run(cmd, capture_output, text):
        return FakeCompletedProcess(returncode=0, stdout="12.345\n")

    monkeypatch.setattr(audio_utils.subprocess, "run", fake_run)

    duration = audio_utils.get_audio_duration_seconds(tmp_path / "x.wav")
    assert duration == pytest.approx(12.345)


def test_get_audio_duration_seconds_raises_on_ffprobe_error(tmp_path, monkeypatch):
    def fake_run(cmd, capture_output, text):
        return FakeCompletedProcess(returncode=1, stderr="no such file")

    monkeypatch.setattr(audio_utils.subprocess, "run", fake_run)

    with pytest.raises(audio_utils.AudioExtractionError):
        audio_utils.get_audio_duration_seconds(tmp_path / "x.wav")
