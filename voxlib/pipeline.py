"""
Orchestrates the full pipeline:
  extract audio -> diarize -> identify "my" segments -> transcribe -> build documents

Supports both a single file and a folder of several recordings (batch mode),
merging all "my" lines from all files into unified final documents.

Each file caches its progress (diarization, identification, transcription) in
output_dir/.cache/, so a re-run on the same file (or after a crash mid-way
through processing) does not recompute steps that are already done. The
cache is scoped to the parameters that affect each step (mode, reference
voice, transcription settings) — see voxlib/cache.py for the invalidation
rules that keep this safe across changed settings.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import asdict
from pathlib import Path

from rich.markup import escape

from . import cache
from .audio_utils import extract_audio, KNOWN_EXTENSIONS
from .console import console
from .diarization import DiarizationEngine, Segment, IdentifiedSegment
from .transcriber import Transcriber, TranscribedLine
from .filler_filter import remove_fillers as _remove_fillers
from .formatter import (
    SourcedLine,
    write_annotated_document,
    write_clean_document,
    write_split_documents,
    DEFAULT_LOW_CONFIDENCE_THRESHOLD,
)

logger = logging.getLogger(__name__)

# How often on_segment_done writes the full cache file to disk, in number of
# newly transcribed segments. Saving after every single segment is safest
# (least work lost on a crash) but means rewriting the whole accumulated
# transcription list each time — for a long recording with many segments,
# that adds up to a lot of redundant I/O. A final save always happens after
# the loop finishes, so at most this many segments are ever at risk on a crash.
SAVE_EVERY_N_SEGMENTS = 5


def collect_input_files(input_path: Path) -> list[Path]:
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        files = sorted(
            p for p in input_path.iterdir()
            if p.is_file() and p.suffix.lower() in KNOWN_EXTENSIONS
        )
        if not files:
            raise FileNotFoundError(
                f"No supported audio/video files found in folder {input_path}."
            )
        return files
    raise FileNotFoundError(f"Path not found: {input_path}")


def _diarize_and_identify(
    file_path: Path,
    wav_path: Path,
    cache_dir: Path,
    use_cache: bool,
    diarizer: DiarizationEngine,
    reference_embedding,
    threshold: float | None,
    reference_fingerprint: dict | None = None,
    transcription_params: dict | None = None,
) -> tuple[list[Segment], list[IdentifiedSegment], dict]:
    """Step shared by dry-run and normal mode: diarization + identification, with caching."""
    file_cache = cache.load_cache(
        cache_dir, file_path, mode="diarization",
        reference_fingerprint=reference_fingerprint, transcription_params=transcription_params,
    ) if use_cache else {
        "diarization": None, "identification": None, "transcription": [],
    }

    if file_cache["diarization"] is not None:
        segments = [Segment(**s) for s in file_cache["diarization"]]
        logger.info("Diarization loaded from cache (%d segments).", len(segments))
    else:
        segments = diarizer.diarize(wav_path)
        logger.info("Found speech segments: %d", len(segments))
        if use_cache:
            cache.save_cache(cache_dir, file_path, mode="diarization", cache_data={
                "diarization": cache.segments_to_dicts(segments),
                "identification": None,
                "transcription": file_cache.get("transcription", []),
            }, reference_fingerprint=reference_fingerprint, transcription_params=transcription_params)

    if file_cache["identification"] is not None:
        # similarity is cached (expensive: needs the embedding model), but
        # is_me is re-derived fresh from it every time — so changing
        # --threshold on an already-processed file takes effect immediately,
        # without needing to recompute embeddings.
        speaker_similarity = {
            seg.speaker_label: ident["similarity"]
            for seg, ident in zip(segments, file_cache["identification"])
        }
        effective_threshold = DiarizationEngine.resolve_threshold(speaker_similarity, threshold)
        identified = [
            IdentifiedSegment(
                start=s["start"], end=s["end"],
                similarity=s["similarity"], is_me=s["similarity"] >= effective_threshold,
            )
            for s in file_cache["identification"]
        ]
        logger.info(
            "'Mine' segment identification loaded from cache (re-checked against threshold=%.2f).",
            effective_threshold,
        )
    else:
        identified = diarizer.identify_my_segments(
            wav_path, segments, reference_embedding, threshold=threshold
        )
        my_count = sum(1 for s in identified if s.is_me)
        logger.info("Identified as 'mine': %d", my_count)
        if use_cache:
            cache.save_cache(cache_dir, file_path, mode="diarization", cache_data={
                "diarization": cache.segments_to_dicts(segments),
                "identification": cache.segments_to_dicts(identified),
                "transcription": file_cache.get("transcription", []),
            }, reference_fingerprint=reference_fingerprint, transcription_params=transcription_params)

    return segments, identified, file_cache


def _filter_cached_transcription(
    cached_transcription_dicts: list[dict],
    identified: list[IdentifiedSegment],
) -> list[dict]:
    """
    Keeps only cached transcription entries whose (start, end) matches a
    segment CURRENTLY identified as "mine". If threshold or the reference
    voice changed since these lines were cached, some previously-mine
    segments may no longer qualify — their stale lines must not leak into
    the output, and newly-mine segments must be (re)transcribed rather than
    treated as already done just because *some* cache entry exists for them.
    """
    my_segment_keys = {(s.start, s.end) for s in identified if s.is_me}
    return [t for t in cached_transcription_dicts if (t["start"], t["end"]) in my_segment_keys]


def _process_single_file(
    file_path: Path,
    tmp_dir: Path,
    cache_dir: Path,
    use_cache: bool,
    use_diarization: bool,
    diarizer: DiarizationEngine | None,
    reference_embedding,
    transcriber: Transcriber,
    language: str | None,
    threshold: float | None,
    remove_fillers: bool,
    reference_fingerprint: dict | None = None,
    transcription_params: dict | None = None,
) -> list[TranscribedLine]:
    wav_path = extract_audio(file_path, tmp_dir)

    if use_diarization:
        segments, identified, file_cache = _diarize_and_identify(
            file_path, wav_path, cache_dir, use_cache, diarizer, reference_embedding, threshold,
            reference_fingerprint=reference_fingerprint, transcription_params=transcription_params,
        )

        cached_transcription_dicts = _filter_cached_transcription(
            file_cache.get("transcription", []), identified
        )
        already_done = {(t["start"], t["end"]) for t in cached_transcription_dicts}
        cached_lines = [
            TranscribedLine(start=t["start"], end=t["end"], text=t["text"], avg_logprob=t.get("avg_logprob"))
            for t in cached_transcription_dicts
        ]

        def on_segment_done(line: TranscribedLine) -> None:
            cached_transcription_dicts.append(asdict(line))
            if use_cache and len(cached_transcription_dicts) % SAVE_EVERY_N_SEGMENTS == 0:
                cache.save_cache(cache_dir, file_path, mode="diarization", cache_data={
                    "diarization": cache.segments_to_dicts(segments),
                    "identification": cache.segments_to_dicts(identified),
                    "transcription": cached_transcription_dicts,
                }, reference_fingerprint=reference_fingerprint, transcription_params=transcription_params)

        new_lines = transcriber.transcribe_my_segments(
            wav_path, identified, language=language,
            already_done=already_done, on_segment_done=on_segment_done,
        )
        all_lines = cached_lines + new_lines

        if use_cache and new_lines:
            # Guarantee the last (< SAVE_EVERY_N_SEGMENTS) batch is persisted too.
            cache.save_cache(cache_dir, file_path, mode="diarization", cache_data={
                "diarization": cache.segments_to_dicts(segments),
                "identification": cache.segments_to_dicts(identified),
                "transcription": cached_transcription_dicts,
            }, reference_fingerprint=reference_fingerprint, transcription_params=transcription_params)
    else:
        # No diarization: the whole file is transcribed as-is, with whisper's
        # own natural line boundaries (based on pauses in speech) — not a
        # single "start to end" segment, which would turn the whole file into
        # one continuous block of text.
        file_cache = cache.load_cache(
            cache_dir, file_path, mode="solo", transcription_params=transcription_params,
        ) if use_cache else {
            "diarization": None, "identification": None, "transcription": [],
        }
        cached_transcription_dicts = list(file_cache.get("transcription", []))
        already_done = {(t["start"], t["end"]) for t in cached_transcription_dicts}
        cached_lines = [
            TranscribedLine(start=t["start"], end=t["end"], text=t["text"], avg_logprob=t.get("avg_logprob"))
            for t in cached_transcription_dicts
        ]

        def on_segment_done(line: TranscribedLine) -> None:
            cached_transcription_dicts.append(asdict(line))
            if use_cache and len(cached_transcription_dicts) % SAVE_EVERY_N_SEGMENTS == 0:
                cache.save_cache(cache_dir, file_path, mode="solo", cache_data={
                    "diarization": None,
                    "identification": None,
                    "transcription": cached_transcription_dicts,
                }, transcription_params=transcription_params)

        new_lines = transcriber.transcribe_full_file(
            wav_path, language=language,
            already_done=already_done, on_segment_done=on_segment_done,
        )
        all_lines = cached_lines + new_lines

        if use_cache and new_lines:
            cache.save_cache(cache_dir, file_path, mode="solo", cache_data={
                "diarization": None,
                "identification": None,
                "transcription": cached_transcription_dicts,
            }, transcription_params=transcription_params)

    if remove_fillers:
        for line in all_lines:
            line.text = _remove_fillers(line.text)

    return all_lines


def _dry_run_stats_for_file(
    file_path: Path,
    wav_path: Path,
    cache_dir: Path,
    use_cache: bool,
    diarizer: DiarizationEngine,
    reference_embedding,
    threshold: float | None,
    reference_fingerprint: dict | None = None,
) -> dict:
    segments, identified, _ = _diarize_and_identify(
        file_path, wav_path, cache_dir, use_cache, diarizer, reference_embedding, threshold,
        reference_fingerprint=reference_fingerprint,
    )
    speakers = {s.speaker_label for s in segments}
    total_duration = sum(s.end - s.start for s in segments)
    my_segments = [s for s in identified if s.is_me]
    my_duration = sum(s.end - s.start for s in my_segments)

    return {
        "file": file_path.name,
        "num_speakers": len(speakers),
        "num_segments_total": len(segments),
        "num_segments_mine": len(my_segments),
        "duration_total_sec": total_duration,
        "duration_mine_sec": my_duration,
        "mine_share_pct": (my_duration / total_duration * 100) if total_duration > 0 else 0.0,
    }


def _format_hms(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def _log_dry_run_summary(per_file_stats: list[dict]) -> None:
    logger.info("=" * 60)
    logger.info("DRY RUN — diarization results without transcription:")
    for s in per_file_stats:
        logger.info(
            "  %s: %d speakers, your lines=%d/%d, your speech=%s (%.0f%% of total speech in the file)",
            s["file"], s["num_speakers"], s["num_segments_mine"], s["num_segments_total"],
            _format_hms(s["duration_mine_sec"]), s["mine_share_pct"],
        )
    total_mine = sum(s["duration_mine_sec"] for s in per_file_stats)
    logger.info("Total of your speech across all files: %s", _format_hms(total_mine))
    logger.info(
        "If the share of 'your' segments looks implausible — adjust --threshold "
        "and run --dry-run again before spending time on the full transcription."
    )
    logger.info("=" * 60)


def _compute_and_log_stats(all_lines: list[SourcedLine]) -> dict:
    total_lines = len(all_lines)
    total_duration = sum(line.end - line.start for line in all_lines)
    total_words = sum(len(line.text.split()) for line in all_lines)
    avg_duration = total_duration / total_lines if total_lines else 0.0

    stats = {
        "total_lines": total_lines,
        "total_duration_sec": total_duration,
        "total_words": total_words,
        "avg_line_duration_sec": avg_duration,
    }

    logger.info(
        "Stats: lines=%d, total speech=%s, words=%d, average line length=%.1f sec",
        total_lines, _format_hms(total_duration), total_words, avg_duration,
    )
    return stats


def run_pipeline(
    input_path: Path,
    reference_voice: Path | None,
    output_dir: Path,
    hf_token: str | None,
    whisper_model: str = "small",
    language: str | None = "en",
    device: str = "cpu",
    threshold: float | None = None,
    use_diarization: bool = True,
    use_cache: bool = True,
    split_chars: int | None = None,
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
    dry_run: bool = False,
    remove_fillers: bool = False,
    batch_size: int | None = None,
) -> dict:
    """
    Returns a dict with paths to the final files and stats:
      {"annotated": Path, "clean": Path, "parts": [Path, ...], "stats": {...}}
    In dry_run=True mode, instead returns {"dry_run": True, "per_file": [...]}
    and does not run transcription at all.
    """
    input_files = collect_input_files(input_path)
    logger.info("Files found to process: %d", len(input_files))

    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = output_dir / ".cache"
    all_lines: list[SourcedLine] = []
    # Files that raised while being processed — kept separate from a hard
    # abort so a single bad recording (corrupt file, unsupported codec)
    # doesn't cost the output for every other file in the batch.
    failed_files: list[dict] = []

    # Settings that affect the resulting transcription TEXT (not just which
    # segments get transcribed) — a cached transcription is only trusted if
    # these still match what produced it (see voxlib/cache.py).
    transcription_params = {
        "whisper_model": whisper_model, "language": language, "batch_size": batch_size,
    }

    with tempfile.TemporaryDirectory(prefix="voice_extractor_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)

        diarizer = None
        reference_embedding = None
        reference_fingerprint = None
        if use_diarization:
            if not hf_token:
                raise ValueError(
                    "A HuggingFace token is required for diarization (--hf-token or the HF_TOKEN env var). "
                    "See the README, 'Installation' or 'Quickstart' section for how to get one."
                )
            if not reference_voice:
                raise ValueError(
                    "A reference sample of your voice is required (--reference), "
                    "since the recordings contain other voices that need to be separated out."
                )
            diarizer = DiarizationEngine(hf_token=hf_token, device=device)
            reference_fingerprint = cache.file_fingerprint(reference_voice)

            logger.info("Extracting audio from the reference sample and computing its embedding...")
            ref_wav = extract_audio(reference_voice, tmp_dir)
            reference_embedding = diarizer.compute_embedding(ref_wav)
        elif dry_run:
            raise ValueError(
                "--dry-run only makes sense together with diarization "
                "(with no other voices in the recording, it's already known that all lines are yours)."
            )

        if dry_run:
            per_file_stats = []
            for file_path in input_files:
                if len(input_files) > 1:
                    console.rule(escape(file_path.name))
                logger.info("=== Dry run: %s ===", file_path.name)
                try:
                    wav_path = extract_audio(file_path, tmp_dir)
                    stats = _dry_run_stats_for_file(
                        file_path, wav_path, cache_dir, use_cache, diarizer, reference_embedding, threshold,
                        reference_fingerprint=reference_fingerprint,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Failed to process %s: %s", file_path.name, exc)
                    failed_files.append({"file": file_path.name, "error": str(exc)})
                    continue
                per_file_stats.append(stats)
            _log_dry_run_summary(per_file_stats)
            result = {"dry_run": True, "per_file": per_file_stats}
            if failed_files:
                result["failed_files"] = failed_files
            return result

        # Full run: the transcriber is only needed here, not in dry-run,
        # so --dry-run runs faster and doesn't load whisper for nothing.
        transcriber = Transcriber(model_size=whisper_model, device=device, batch_size=batch_size)

        for file_path in input_files:
            if len(input_files) > 1:
                console.rule(escape(file_path.name))
            logger.info("=== Processing: %s ===", file_path.name)
            try:
                transcribed = _process_single_file(
                    file_path=file_path,
                    tmp_dir=tmp_dir,
                    cache_dir=cache_dir,
                    use_cache=use_cache,
                    use_diarization=use_diarization,
                    diarizer=diarizer,
                    reference_embedding=reference_embedding,
                    transcriber=transcriber,
                    language=language,
                    threshold=threshold,
                    remove_fillers=remove_fillers,
                    reference_fingerprint=reference_fingerprint,
                    transcription_params=transcription_params,
                )
            except Exception as exc:  # noqa: BLE001
                # A per-file failure (corrupt recording, unsupported codec, a
                # transient model error) shouldn't cost the output for every
                # other file already processed in this batch — already-cached
                # progress for THIS file is untouched, so a re-run picks up
                # right where it left off once the underlying issue is fixed.
                logger.exception("Failed to process %s: %s", file_path.name, exc)
                failed_files.append({"file": file_path.name, "error": str(exc)})
                continue

            for line in transcribed:
                all_lines.append(
                    SourcedLine(
                        source_file=file_path.name,
                        start=line.start,
                        end=line.end,
                        text=line.text,
                        avg_logprob=line.avg_logprob,
                    )
                )

    annotated_path = output_dir / "transcript_annotated.txt"
    clean_path = output_dir / "transcript_clean.txt"

    write_annotated_document(all_lines, annotated_path, low_confidence_threshold=low_confidence_threshold)
    write_clean_document(all_lines, clean_path)

    result: dict = {"annotated": annotated_path, "clean": clean_path}
    if failed_files:
        result["failed_files"] = failed_files

    if split_chars:
        part_paths = write_split_documents(all_lines, output_dir, max_chars=split_chars)
        result["parts"] = part_paths
        logger.info("Split into %d parts in %s/parts/", len(part_paths), output_dir)

    result["stats"] = _compute_and_log_stats(all_lines)

    logger.info("Done. Total lines: %d", len(all_lines))
    logger.info("Annotated document: %s", annotated_path)
    logger.info("Clean document (for AI): %s", clean_path)

    return result
