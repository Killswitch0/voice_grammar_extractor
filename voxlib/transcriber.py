"""
Transcribes specific time segments of audio via faster-whisper.

We don't transcribe the whole file at once — only the chunks that
diarization.py marked as "mine" — this saves time and keeps other people's
lines out of the document.

Audio is decoded into a numpy array once per file (not on every transcribe()
call), otherwise faster-whisper would re-read the file from disk for every
single segment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from .console import track

logger = logging.getLogger(__name__)


@dataclass
class TranscribedLine:
    start: float
    end: float
    text: str
    avg_logprob: Optional[float] = None  # whisper's average log-probability; closer to 0 = more confident


class Transcriber:
    def __init__(
        self,
        model_size: str = "small",
        device: str = "cpu",
        compute_type: str = "int8",
        batch_size: int | None = None,
    ):
        from faster_whisper import WhisperModel

        logger.info("Loading whisper model '%s' (device=%s)...", model_size, device)
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

        # BatchedInferencePipeline speeds up long segments (it chunks them and
        # processes the chunks in batches), but some versions of faster-whisper
        # have known bugs with inner sub-segment timestamps. We only use
        # .text and .avg_logprob, not those inner timestamps, so the risk is
        # low — but we still keep this opt-in (--batch-size) rather than the
        # default behavior.
        self.batch_size = batch_size
        self.batched_pipeline = None
        if batch_size:
            from faster_whisper import BatchedInferencePipeline
            logger.info("Batched transcription enabled (batch_size=%d).", batch_size)
            self.batched_pipeline = BatchedInferencePipeline(model=self.model)

    def detect_language(self, audio: np.ndarray) -> str | None:
        """
        Detects the spoken language ONCE for a whole file.

        Needed because transcribe_my_segments feeds whisper one short segment
        at a time. With language=None, whisper would then re-detect per segment
        — off one or two seconds of audio, which is far too little to be
        reliable, so a single English clip could come back transcribed as
        Russian and land in the document looking like a grammar mistake the
        speaker never made.

        Returns None if detection fails, which restores the old per-segment
        behavior rather than aborting a long run over a diagnostic.
        """
        try:
            language, probability, _ = self.model.detect_language(
                audio=audio, language_detection_segments=4,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Could not detect the language for this file (%s) — falling back to "
                "per-segment detection, which is unreliable on short segments. "
                "Pass --language explicitly to avoid this.", exc,
            )
            return None

        logger.info("Detected language for this file: %s (confidence %.2f)", language, probability)
        return language

    def transcribe_segment(
        self, audio: np.ndarray, start: float, end: float, language: str | None = "en"
    ) -> tuple[str, float | None]:
        """
        Transcribes a single [start, end] time range from already-decoded audio.
        language=None enables whisper's language auto-detection (useful for mixed-language speech).

        Returns (text, avg_logprob). avg_logprob is the minimum across
        sub-segments (worst case), None if the segment turned out empty (no
        words recognized).
        """
        # faster-whisper expects clip_timestamps as a flat list of numbers
        # [start, end, ...], not a list of dicts. When clip_timestamps is
        # used, the vad_filter parameter is ignored by the library anyway,
        # so we don't pass it here.
        if self.batched_pipeline is not None:
            segments, _info = self.batched_pipeline.transcribe(
                audio,
                language=language,
                clip_timestamps=[start, end],
                batch_size=self.batch_size,
                beam_size=5,
            )
        else:
            segments, _info = self.model.transcribe(
                audio,
                language=language,
                clip_timestamps=[start, end],
                beam_size=5,
            )
        segments = list(segments)
        text_parts = [seg.text.strip() for seg in segments]
        text = " ".join(part for part in text_parts if part)

        logprobs = [seg.avg_logprob for seg in segments if seg.avg_logprob is not None]
        avg_logprob = min(logprobs) if logprobs else None

        return text, avg_logprob

    def transcribe_full_file(
        self,
        wav_path: Path,
        language: str | None = "en",
        already_done: set[tuple[float, float]] | None = None,
        on_segment_done: Callable[[TranscribedLine], None] | None = None,
    ) -> list[TranscribedLine]:
        """
        Transcribes the whole file WITHOUT diarization (solo mode): unlike
        transcribe_my_segments, there are no predefined line boundaries here,
        so each line that whisper itself split by pauses in speech is kept as
        a separate line — instead of being merged into one continuous block
        of text for the whole file.
        """
        from faster_whisper.audio import decode_audio

        already_done = already_done or set()
        lines: list[TranscribedLine] = []

        logger.info("Decoding audio for transcription...")
        audio = decode_audio(str(wav_path), sampling_rate=16000)

        if self.batched_pipeline is not None:
            raw_segments, _info = self.batched_pipeline.transcribe(
                audio, language=language, batch_size=self.batch_size, beam_size=5,
            )
        else:
            raw_segments, _info = self.model.transcribe(audio, language=language, beam_size=5)

        for seg in track(raw_segments, "Transcribing lines"):
            text = seg.text.strip()
            if not text:
                continue
            if (seg.start, seg.end) in already_done:
                continue
            line = TranscribedLine(start=seg.start, end=seg.end, text=text, avg_logprob=seg.avg_logprob)
            lines.append(line)
            if on_segment_done is not None:
                on_segment_done(line)

        return lines

    def transcribe_my_segments(
        self,
        wav_path: Path,
        identified_segments,
        language: str | None = "en",
        min_duration: float = 0.3,
        already_done: set[tuple[float, float]] | None = None,
        on_segment_done: Callable[[TranscribedLine], None] | None = None,
    ) -> list[TranscribedLine]:
        """
        already_done: set of (start, end) segments already transcribed in a
        previous run (from the cache) — skipped again.
        on_segment_done: called right after each successfully transcribed
        segment — used for incremental cache saving.
        """
        from faster_whisper.audio import decode_audio

        already_done = already_done or set()
        lines: list[TranscribedLine] = []
        mine = [s for s in identified_segments if s.is_me]
        my_segments = [s for s in mine if (s.end - s.start) >= min_duration]

        # Reported before the early return below: if EVERY one of your segments
        # is too short, that's the case where silently returning nothing is
        # most confusing.
        skipped_short = len(mine) - len(my_segments)
        if skipped_short:
            logger.info(
                'Skipped %d of your segments shorter than %.1fs (too short to transcribe '
                'reliably). Short replies like "yes, I do" can be lost this way.',
                skipped_short, min_duration,
            )

        pending = [s for s in my_segments if (s.start, s.end) not in already_done]
        skipped = len(my_segments) - len(pending)
        if skipped:
            logger.info("Skipping %d lines already transcribed earlier (from cache).", skipped)

        if not pending:
            return lines

        logger.info("Decoding audio for transcription (once per file)...")
        audio = decode_audio(str(wav_path), sampling_rate=16000)

        # --language auto arrives here as None. Resolve it once against the
        # whole file rather than letting each short segment be guessed at
        # separately — see detect_language.
        if language is None:
            language = self.detect_language(audio)

        for seg in track(pending, "Transcribing lines", total=len(pending)):
            text, avg_logprob = self.transcribe_segment(audio, seg.start, seg.end, language=language)
            if text:
                line = TranscribedLine(start=seg.start, end=seg.end, text=text, avg_logprob=avg_logprob)
                lines.append(line)
                if on_segment_done is not None:
                    on_segment_done(line)

        return lines
