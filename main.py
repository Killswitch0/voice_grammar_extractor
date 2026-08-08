#!/usr/bin/env python3
"""
Console app: extracts only YOUR lines from a video/audio file (including webm),
separating them from other voices by comparing against a reference sample of
your voice, and writes them to a document ready for grammar analysis via AI.

Examples:
    python main.py call.webm --reference my_voice.wav --hf-token hf_xxx -o out/

    python main.py recordings_folder/ --reference my_voice.wav \\
        --hf-token hf_xxx --whisper-model medium -o out/

    # If the recording is just you (solo, no diarization):
    python main.py monologue.mp4 --no-diarization -o out/

    # Using a config file instead of a long list of flags:
    python main.py recordings_folder/ --config my_config.yaml

    # Check what you'll get first, without running the slow transcription:
    python main.py call.webm --reference my_voice.wav --dry-run

    # Not sure which reference sample to cut? There's a dedicated helper:
    python identify_speaker.py call.webm --hf-token hf_xxx -o output/
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from rich.markup import escape
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent))

from voxlib.console import configure_logging, console, print_error  # noqa: E402
from voxlib import validation  # noqa: E402
from voxlib.diarization import DEFAULT_MERGE_GAP_SEC  # noqa: E402


def _fluency_log_path() -> Path | None:
    """
    Where to append this run's fluency measurement, or None to skip it.

    `analysis/` is this project's coaching workspace (memory.md, session
    reports, score history) and is absent for anyone using the extractor on its
    own — so the history file is only kept when that folder already exists,
    rather than conjuring a directory nobody asked for. Resolved against the
    script's own location, not the current directory, so it lands in the same
    place whether you run `python main.py` from the project root or `./run.sh`
    from anywhere.
    """
    candidate = Path(__file__).parent / "analysis"
    return candidate / "fluency_history.csv" if candidate.is_dir() else None


def _checked(validator, name: str):
    """
    Turns one of voxlib.validation's checks into an argparse `type=`.

    The checks live there, not here, because a `--config` file reaches the same
    settings without passing through argparse at all — one definition is what
    keeps the two entry points from disagreeing. This only adapts the error
    type, so argparse prints the message instead of swallowing it behind its
    own generic "invalid value".
    """
    def parse(raw: str):
        try:
            return validator(raw, name)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from exc

    parse.__name__ = name.lstrip("-").replace("-", "_")
    return parse


def build_arg_parser(config_defaults: dict | None = None) -> argparse.ArgumentParser:
    config_defaults = config_defaults or {}

    parser = argparse.ArgumentParser(
        prog="voice-grammar-extractor",
        description="Extracts your lines from a video/audio file for later grammar analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "input",
        type=Path,
        help="Path to a video/audio file, or a folder with several files",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to a YAML settings file (see config.example.yaml). "
             "Command-line flags explicitly passed take priority over the config.",
    )
    parser.add_argument(
        "-r", "--reference",
        type=Path,
        default=config_defaults.get("reference"),
        help="Path to a reference sample of your voice (10-30 sec of clean speech). "
             "Required unless --no-diarization is set. "
             "Not sure what to cut — use identify_speaker.py.",
    )
    parser.add_argument(
        "-o", "--output-dir",
        type=Path,
        default=config_defaults.get("output_dir", Path("output")),
        help="Folder for the final documents (default: ./output)",
    )
    parser.add_argument(
        "--hf-token",
        type=str,
        default=config_defaults.get("hf_token", os.environ.get("HF_TOKEN")),
        help="HuggingFace token for the diarization models (or the HF_TOKEN env var)",
    )
    parser.add_argument(
        "--whisper-model",
        type=str,
        default=config_defaults.get("whisper_model", "small"),
        choices=["tiny", "base", "small", "medium", "large-v3"],
        help="Whisper model size (default: small). Bigger = more accurate but slower.",
    )
    parser.add_argument(
        "--language",
        type=str,
        default=config_defaults.get("language", "en"),
        help="Speech language code for whisper (en, ru, etc.). "
             "Use 'auto' for auto-detection (useful for mixed-language speech).",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=config_defaults.get("device", "cpu"),
        choices=["cpu", "cuda"],
        help="Device to run computation on (default: cpu)",
    )
    parser.add_argument(
        "--threshold",
        type=_checked(validation.cosine_threshold, "--threshold"),
        default=config_defaults.get("threshold"),
        help="Cosine similarity threshold for recognizing your voice. If not given, it's "
             "auto-calibrated per recording from the gap between speakers' similarity to "
             "your reference voice (falls back to 0.75 if no speaker confidently matches). "
             "Raise it if the system confuses you with others; lower it if it misses your lines.",
    )
    parser.add_argument(
        "--no-diarization",
        action="store_true",
        default=config_defaults.get("no_diarization", False),
        help="Disable speaker separation: the whole file is treated as your solo speech.",
    )
    parser.add_argument(
        "--merge-gap",
        type=_checked(validation.non_negative_float, "--merge-gap"),
        default=config_defaults.get("merge_gap", DEFAULT_MERGE_GAP_SEC),
        help=f"Stitch consecutive turns by the same speaker back together when less than this "
             f"many seconds apart (default: {DEFAULT_MERGE_GAP_SEC}). Diarization cuts at every "
             f"pause, including mid-sentence ones, and whisper recognizes a whole phrase far "
             f"better than the fragments. Use 0 to keep the raw segments.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Don't use the progress cache — recompute everything from scratch, "
             "even if saved results already exist for this file.",
    )
    parser.add_argument(
        "--split-chars",
        type=_checked(validation.positive_int, "--split-chars"),
        default=config_defaults.get("split_chars"),
        help="If set, additionally splits transcript_clean.txt into parts no "
             "longer than the given number of characters (output/parts/part_N.txt) — "
             "useful when the whole text doesn't fit into a single AI prompt.",
    )
    parser.add_argument(
        "--low-confidence-threshold",
        type=_checked(validation.logprob_threshold, "--low-confidence-threshold"),
        default=config_defaults.get("low_confidence_threshold", -0.5),
        help="avg_logprob threshold (usually between 0 and -1.5) below which a line "
             "in the annotated document is marked as low-confidence [?] (default: -0.5).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only run diarization + identification of 'your' segments, no transcription. "
             "Shows how many speakers were found and what share of the speech is yours, "
             "before spending time on full processing. Requires diarization (not compatible with --no-diarization).",
    )
    parser.add_argument(
        "--remove-fillers",
        action="store_true",
        default=config_defaults.get("remove_fillers", False),
        help="Remove pure filler sounds (um, uh, erm) from the transcript. "
             "Meaningful filler words (like, you know, etc.) are left untouched — "
             "they can't be reliably told apart from real words without risking broken sentences.",
    )
    parser.add_argument(
        "--batch-size",
        type=_checked(validation.positive_int, "--batch-size"),
        default=config_defaults.get("batch_size"),
        help="Enable batched transcription (BatchedInferencePipeline) with the given "
             "batch size — speeds up processing of long lines, especially on GPU. "
             "Off by default (uses the regular sequential mode).",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=config_defaults.get("log_file"),
        help="Path to a file to additionally write the run log to "
             "(useful for long unattended runs).",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose logging",
    )
    return parser


def _print_dry_run_result(result: dict) -> None:
    console.print()
    console.print("[bold cyan]=== Dry run result (no transcription) ===[/]")

    table = Table(show_edge=True)
    table.add_column("File")
    # Merged rather than given a column of its own: a separate column pushed
    # the table past a standard terminal width and started truncating file
    # names, which are the one thing you need to read to act on this.
    table.add_column("Speakers (you)", justify="right")
    table.add_column("Your lines", justify="right")
    table.add_column("Your speech", justify="right")
    table.add_column("Share", justify="right")

    ambiguous = False
    for s in result["per_file"]:
        mins_mine = s["duration_mine_sec"] / 60
        # The whole point of the document is that it holds one person's speech.
        # 0 speakers matched means an empty transcript; 2+ means someone else's
        # sentences mixed into yours. Both are worth colouring, because both
        # are cheap to fix here and expensive to notice later.
        matched = s["num_speakers_mine"]
        speakers_cell = f"{s['num_speakers']} ({matched})"
        if matched != 1:
            ambiguous = True
            speakers_cell = f"[bold red]{speakers_cell}[/]"
        table.add_row(
            escape(s["file"]),
            speakers_cell,
            f"{s['num_segments_mine']}/{s['num_segments_total']}",
            f"~{mins_mine:.1f} min",
            f"[bold]{s['mine_share_pct']:.0f}%[/]",
        )
    console.print(table)

    console.print()
    if ambiguous:
        console.print(
            "[bold red]Check the bracketed number in 'Speakers (you)' above[/] — that's how many "
            "speakers were matched as you, and anything other than 1 means the split is wrong: "
            "0 would give you an empty transcript, 2+ mixes another person's speech into yours. "
            "Adjust [bold]--threshold[/] before running the full processing."
        )
        console.print()
    console.print("If the numbers look off — adjust [bold]--threshold[/] and try [bold]--dry-run[/] again.")
    console.print("Once you're happy with it — drop --dry-run and run the full processing.")


def _print_full_result(result: dict) -> None:
    console.print()
    console.print("[bold green]Done![/]")
    console.print(f"  Annotated document: [cyan]{escape(str(result['annotated']))}[/]")
    console.print(f"  Clean text for AI:  [cyan]{escape(str(result['clean']))}[/]")
    if result.get("parts"):
        console.print(f"  Parts for AI ({len(result['parts'])}): [cyan]{escape(str(result['parts'][0].parent))}/[/]")
    stats = result.get("stats", {})
    if stats:
        mins = stats["total_duration_sec"] / 60
        console.print(
            f"  Stats: {stats['total_lines']} lines, ~{mins:.1f} min of speech, "
            f"~{stats['total_words']} words"
        )
    if result.get("fluency") is not None:
        from voxlib.fluency import describe
        console.print(f"  Fluency: {escape(describe(result['fluency']))}")
    if result.get("low_confidence_warning"):
        console.print()
        console.print(f"[bold yellow]Recording quality:[/] {escape(result['low_confidence_warning'])}")


def _print_failed_files(failed_files: list[dict]) -> None:
    console.print()
    console.print(f"[bold yellow]{len(failed_files)} file(s) failed and were skipped:[/]")
    for f in failed_files:
        console.print(f"  [yellow]{escape(f['file'])}[/]: {escape(f['error'])}")
    console.print("Output above was still produced from the files that succeeded. "
                  "Fix the files above and re-run — already-processed files are cached and won't be redone.")


def main() -> int:
    # First, a light pass just for --config, so its values can be used as
    # defaults for the full parser (CLI flags will still override them).
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument("--config", type=Path, default=None)
    pre_args, _ = pre_parser.parse_known_args()

    config_defaults = {}
    if pre_args.config:
        from voxlib.config import load_config
        config_defaults = load_config(pre_args.config)

    parser = build_arg_parser(config_defaults)
    args = parser.parse_args()

    configure_logging(args.verbose, args.log_file)

    language = None if args.language.lower() == "auto" else args.language

    # Import the heavy dependencies (torch, pyannote, whisper) only here,
    # not at the top of the module — so --help and argument parsing work
    # even if the ML libraries aren't installed yet.
    from voxlib.pipeline import run_pipeline

    try:
        result = run_pipeline(
            input_path=args.input,
            reference_voice=args.reference,
            output_dir=args.output_dir,
            hf_token=args.hf_token,
            whisper_model=args.whisper_model,
            language=language,
            device=args.device,
            threshold=args.threshold,
            use_diarization=not args.no_diarization,
            use_cache=not args.no_cache,
            split_chars=args.split_chars,
            low_confidence_threshold=args.low_confidence_threshold,
            dry_run=args.dry_run,
            remove_fillers=args.remove_fillers,
            batch_size=args.batch_size,
            fluency_log=_fluency_log_path(),
            merge_gap=args.merge_gap,
        )
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/]")
        return 130
    except Exception as exc:  # noqa: BLE001
        print_error(str(exc), log_file=args.log_file, exc=exc, verbose=args.verbose)
        return 1

    if result.get("dry_run"):
        _print_dry_run_result(result)
    else:
        _print_full_result(result)

    if result.get("failed_files"):
        _print_failed_files(result["failed_files"])
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
