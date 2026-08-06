"""
Diarization (who speaks when) + identification of "your" segments by comparing
voice embeddings against a reference sample.

Uses pyannote.audio:
  - pipeline "pyannote/speaker-diarization-community-1" to split speakers apart
  - Model "pyannote/embedding" to get a vector fingerprint of a voice

Loading these models requires a free HuggingFace token and a one-time
acceptance of the usage terms on the model pages (see README).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .console import track

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.75
# Below this, the best-matching speaker isn't a confident match at all (likely
# a mismatched reference sample or wrong file) — don't trust gap-based auto
# calibration in that case, since it would still confidently pick *someone*.
MIN_CONFIDENT_SIMILARITY = 0.3


@dataclass
class Segment:
    start: float
    end: float
    speaker_label: str  # pyannote's raw label (SPEAKER_00, etc.), not stable across files


@dataclass
class IdentifiedSegment:
    start: float
    end: float
    is_me: bool
    similarity: float


class DiarizationEngine:
    def __init__(self, hf_token: str, device: str = "cpu"):
        import torch
        from pyannote.audio import Pipeline, Model, Inference

        self.device = torch.device(device)

        logger.info("Loading diarization model (pyannote/speaker-diarization-community-1)...")
        self.diarization_pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-community-1", token=hf_token
        )
        self.diarization_pipeline.to(self.device)

        logger.info("Loading voice embedding model (pyannote/embedding)...")
        embedding_model = Model.from_pretrained("pyannote/embedding", token=hf_token)
        self.embedding_inference = Inference(embedding_model, window="whole")
        self.embedding_inference.to(self.device)

    def diarize(self, wav_path: Path) -> list[Segment]:
        """Returns the list of segments (start, end, speaker_label) for the whole file."""
        from pyannote.audio.pipelines.utils.hook import ProgressHook

        with ProgressHook() as hook:
            raw_output = self.diarization_pipeline(str(wav_path), hook=hook)

        # pyannote.audio 4.x wraps the result in a DiarizeOutput with a
        # .speaker_diarization attribute; 3.x returns an Annotation directly.
        # We support both.
        annotation = getattr(raw_output, "speaker_diarization", raw_output)

        segments: list[Segment] = []
        for turn, _, speaker in annotation.itertracks(yield_label=True):
            segments.append(Segment(start=turn.start, end=turn.end, speaker_label=speaker))
        segments.sort(key=lambda s: s.start)
        return segments

    def compute_embedding(self, wav_path: Path, start: float | None = None, end: float | None = None) -> np.ndarray:
        """
        Computes a voice embedding for the whole file (if start/end are not given)
        or for a specific time range.
        """
        if start is None and end is None:
            emb = self.embedding_inference(str(wav_path))
        else:
            from pyannote.core import Segment as PyannoteSegment
            emb = self.embedding_inference.crop(str(wav_path), PyannoteSegment(start, end))
        return np.asarray(emb).reshape(-1)

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        a_norm = a / (np.linalg.norm(a) + 1e-8)
        b_norm = b / (np.linalg.norm(b) + 1e-8)
        return float(np.dot(a_norm, b_norm))

    def identify_my_segments(
        self,
        wav_path: Path,
        segments: list[Segment],
        reference_embedding: np.ndarray,
        threshold: float | None = None,
        min_segment_duration: float = 0.3,
    ) -> list[IdentifiedSegment]:
        """
        For each unique speaker_label, computes an average embedding across all
        of that speaker's segments (more robust than a single short clip),
        compares it to the reference, and marks all of that speaker's segments
        as "mine" or not.
        """
        by_speaker: dict[str, list[Segment]] = {}
        for seg in segments:
            if seg.end - seg.start >= min_segment_duration:
                by_speaker.setdefault(seg.speaker_label, []).append(seg)

        speaker_similarity: dict[str, float] = {}
        for speaker, segs in track(by_speaker.items(), "Comparing speaker voices", total=len(by_speaker)):
            # Take up to 5 of this speaker's longest segments for a more robust embedding estimate
            longest = sorted(segs, key=lambda s: s.end - s.start, reverse=True)[:5]
            embeddings = []
            for seg in longest:
                try:
                    emb = self.compute_embedding(wav_path, seg.start, seg.end)
                    embeddings.append(emb)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Could not compute embedding for segment %s: %s", seg, exc)
            if not embeddings:
                speaker_similarity[speaker] = -1.0
                continue
            avg_embedding = np.mean(embeddings, axis=0)
            speaker_similarity[speaker] = self.cosine_similarity(avg_embedding, reference_embedding)

        logger.info("Speaker similarity to the reference voice: %s", speaker_similarity)
        effective_threshold = self.resolve_threshold(speaker_similarity, threshold)

        result: list[IdentifiedSegment] = []
        for seg in segments:
            sim = speaker_similarity.get(seg.speaker_label, -1.0)
            result.append(
                IdentifiedSegment(
                    start=seg.start,
                    end=seg.end,
                    is_me=sim >= effective_threshold,
                    similarity=sim,
                )
            )
        return result

    @staticmethod
    def _suggest_threshold_from_gap(speaker_similarity: dict[str, float]) -> tuple[float, float] | None:
        """
        If there are two or more speakers, finds the biggest gap between
        adjacent similarity values and returns (suggested_threshold, gap_size)
        for the middle of that gap — this is usually the point where
        "definitely you" ends and "definitely not you" begins. Returns None
        if there's nothing to compare (fewer than 2 speakers).
        """
        values = sorted(speaker_similarity.values(), reverse=True)
        if len(values) < 2:
            return None

        gaps = [(values[i] - values[i + 1], i) for i in range(len(values) - 1)]
        biggest_gap, idx = max(gaps)
        suggested = (values[idx] + values[idx + 1]) / 2
        return suggested, biggest_gap

    @staticmethod
    def resolve_threshold(speaker_similarity: dict[str, float], explicit_threshold: float | None) -> float:
        """
        Decides which threshold to actually use for "is this speaker me".

        If the caller gave an explicit threshold (from --threshold or a config
        file), it's used as-is — but a hint is still logged if the gap-based
        suggestion disagrees with it noticeably, so the user can fine-tune.

        Otherwise, auto-calibrates from the biggest gap between speakers'
        similarity to the reference voice. Falls back to DEFAULT_THRESHOLD if
        there's no gap to compute (fewer than 2 speakers) or the best match is
        too weak to trust (MIN_CONFIDENT_SIMILARITY) — a low best-similarity
        usually means a mismatched reference sample or file, and the gap logic
        would otherwise still confidently point at *someone*.
        """
        gap_result = DiarizationEngine._suggest_threshold_from_gap(speaker_similarity)

        if explicit_threshold is not None:
            if gap_result is not None:
                suggested, gap = gap_result
                if abs(suggested - explicit_threshold) > 0.03:
                    logger.info(
                        "Hint: based on the gap in voice similarity (%.2f), a threshold of ~%.2f "
                        "might separate you from the rest more precisely (currently using --threshold %.2f).",
                        gap, suggested, explicit_threshold,
                    )
            return explicit_threshold

        top_similarity = max(speaker_similarity.values(), default=-1.0)
        if gap_result is None or top_similarity < MIN_CONFIDENT_SIMILARITY:
            logger.warning(
                "Could not confidently auto-calibrate a threshold (best similarity to the "
                "reference voice was %.2f) — falling back to the default %.2f. Pass --threshold "
                "explicitly if this misidentifies your lines.",
                top_similarity, DEFAULT_THRESHOLD,
            )
            return DEFAULT_THRESHOLD

        suggested, _ = gap_result
        logger.info(
            "Auto-selected threshold %.2f based on the gap in voice similarity to the "
            "reference (no --threshold given).",
            suggested,
        )
        return suggested
