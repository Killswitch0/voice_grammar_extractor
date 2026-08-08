"""
Optional heavy end-to-end smoke test: requires torch/faster-whisper actually
installed (see requirements.txt) — deliberately NOT run in the default CI
job (see .github/workflows/tests.yml, which only installs the light runtime
deps the rest of the test suite needs). Run manually after upgrading
torch/pyannote.audio/faster-whisper to catch integration breakage the
mocked-out unit tests elsewhere in this suite can't see:

    pytest -m slow
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow


def _write_sine_wav(path: Path, duration_sec: float = 2.0, sample_rate: int = 16000) -> None:
    """
    A short synthetic tone — enough to exercise the full extract -> decode ->
    transcribe -> write pipeline without needing a real voice recording
    (personal recordings are deliberately not committed to this repo, see
    .gitignore). It won't produce meaningful transcribed text (there's no
    speech in it) — this test only asserts the pipeline runs to completion
    and produces well-formed output, not that whisper "understood" anything.
    """
    n_samples = int(duration_sec * sample_rate)
    with wave.open(str(path), "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)  # 16-bit PCM
        wav_file.setframerate(sample_rate)
        frames = bytearray()
        for i in range(n_samples):
            value = int(3000 * math.sin(2 * math.pi * 440 * i / sample_rate))
            frames += struct.pack("<h", value)
        wav_file.writeframes(bytes(frames))


def test_pipeline_runs_end_to_end_without_diarization(tmp_path):
    """
    Whisper's behavior on a non-speech tone is genuinely undefined: it may
    hallucinate a stray phrase or return nothing at all, and which one happens
    varies by model version. Both are correct pipeline outcomes, so this
    asserts the pair of them rather than picking one and becoming flaky:

      - lines came out  -> the documents exist and are well-formed
      - nothing came out -> the pipeline refuses to write empty documents
                            over whatever was there before

    What it's really guarding is that extract -> decode -> transcribe -> write
    holds together against the real libraries after a dependency bump.
    """
    from voxlib.pipeline import run_pipeline

    input_wav = tmp_path / "sample.wav"
    _write_sine_wav(input_wav)
    output_dir = tmp_path / "output"

    try:
        result = run_pipeline(
            input_path=input_wav,
            reference_voice=None,
            output_dir=output_dir,
            hf_token=None,
            whisper_model="tiny",
            use_diarization=False,
            use_cache=False,
        )
    except RuntimeError as exc:
        assert "Not a single line was extracted" in str(exc)
        assert not (output_dir / "transcript_clean.txt").exists()
        return

    assert result["annotated"].exists()
    assert result["clean"].exists()
    assert "stats" in result
    assert "failed_files" not in result
