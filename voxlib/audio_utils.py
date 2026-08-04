"""
Extracts and normalizes audio from any video/audio container (mp4, webm, mkv,
mp3, m4a, wav, ogg, etc.) using ffmpeg.

Everything is converted to a single format that both pyannote (diarization)
and whisper (transcription) understand equally well: WAV, 16kHz, mono, PCM16.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

TARGET_SAMPLE_RATE = 16000

# Extensions worth trying directly (informational only; ffmpeg actually detects
# the format from file content, not from the extension).
KNOWN_EXTENSIONS = {
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".wmv",
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".flac",
}


class AudioExtractionError(RuntimeError):
    pass


def check_ffmpeg_available() -> None:
    if shutil.which("ffmpeg") is None:
        raise AudioExtractionError(
            "ffmpeg not found in PATH. Install it: "
            "https://ffmpeg.org/download.html "
            "(Ubuntu/Debian: `sudo apt install ffmpeg`, macOS: `brew install ffmpeg`)"
        )


def extract_audio(input_path: Path, output_dir: Path) -> Path:
    """
    Extracts the audio track from an arbitrary video/audio file (including webm)
    and saves it as WAV 16kHz mono PCM16.

    Returns the path to the resulting wav file.
    """
    check_ffmpeg_available()

    if not input_path.exists():
        raise AudioExtractionError(f"File not found: {input_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{input_path.stem}.wav"

    cmd = [
        "ffmpeg",
        "-y",                       # overwrite without prompting
        "-i", str(input_path),
        "-vn",                      # drop the video stream if present
        "-ac", "1",                 # mono
        "-ar", str(TARGET_SAMPLE_RATE),
        "-sample_fmt", "s16",
        "-acodec", "pcm_s16le",
        str(output_path),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0 or not output_path.exists():
        raise AudioExtractionError(
            f"ffmpeg failed to extract audio from {input_path.name}.\n"
            f"stderr:\n{result.stderr[-2000:]}"
        )

    return output_path


def get_audio_duration_seconds(wav_path: Path) -> float:
    """Returns the duration of a wav file in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(wav_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise AudioExtractionError(f"ffprobe error: {result.stderr}")
    return float(result.stdout.strip())
