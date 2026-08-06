#!/usr/bin/env python3
"""
Helper for picking a reference sample of your voice — no manual ffmpeg cutting needed.

Diarizes a single file, cuts a short sample from each speaker found, lets you
listen to them, and asks which one is you. The chosen sample is saved as a
ready-to-use .wav that you can pass straight to main.py via --reference.

Example:
    python identify_speaker.py call.webm --hf-token hf_xxx
    # -> voice_reference/my_reference.wav

    python main.py recordings_folder/ --reference voice_reference/my_reference.wav --hf-token hf_xxx
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from rich.markup import escape
from rich.prompt import Confirm, Prompt

sys.path.insert(0, str(Path(__file__).parent))

from voxlib.console import configure_logging, console, print_error  # noqa: E402

SAMPLE_DURATION_SEC = 12.0  # length of the listening sample for each speaker


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="identify-speaker",
        description="Diarizes a file, lets you listen to a sample of each speaker, and pick which one is you.",
        epilog=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("input", type=Path, help="Video/audio file that includes your voice among others")
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("output"),
                         help="Where to save the temporary speaker samples for listening (default: ./output). "
                              "This is disposable — the final chosen reference is saved elsewhere, see --reference-dir.")
    parser.add_argument("--reference-dir", type=Path, default=Path("voice_reference"),
                         help="Where to save the final chosen reference sample (default: ./voice_reference). "
                              "Unlike --output-dir, this is meant to be permanent — don't point it at a folder "
                              "you routinely wipe.")
    parser.add_argument("--hf-token", type=str, default=os.environ.get("HF_TOKEN"),
                         help="HuggingFace token (or the HF_TOKEN env var)")
    parser.add_argument("--device", type=str, default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def _pick_sample_clip(segments: list, max_duration: float) -> tuple[float, float]:
    """
    Picks one speaker's longest continuous segment and returns
    (clip_start, clip_duration), capped at max_duration — the simplest way
    to get a short, representative, listenable sample of that speaker's voice.
    """
    longest = max(segments, key=lambda s: s.end - s.start)
    duration = min(max_duration, longest.end - longest.start)
    return longest.start, duration


def _running_in_container() -> bool:
    return Path("/.dockerenv").exists()


def _play_audio(path: Path) -> None:
    """Tries to play the file through whatever player is available on the system.
    If none is found, just prints the path so you can open the file manually.

    Inside a container, ffplay is normally present (it ships with ffmpeg) and
    exits 0 even when there's no audio device to play through (ALSA just
    fails silently under the hood) — so we can't detect "no sound" from the
    exit code alone. Skip straight to the manual-open message in that case
    instead of falsely reporting success.
    """
    if _running_in_container():
        console.print(f"  [dim](Running in a container — no audio device to play through. Open the file manually: {escape(str(path))})[/]")
        return

    players = [
        ["afplay", str(path)],       # macOS
        ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)],  # Linux/Windows (ships with ffmpeg)
        ["aplay", str(path)],        # Linux (alsa, wav only)
    ]
    for cmd in players:
        try:
            subprocess.run(cmd, check=True, capture_output=True)
            return
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue
    console.print(f"  [dim](No audio player found on this system — open the file manually: {escape(str(path))})[/]")


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    configure_logging(args.verbose)

    if not args.hf_token:
        print_error("A HuggingFace token is required: --hf-token or the HF_TOKEN env var.")
        return 1

    from voxlib.audio_utils import extract_audio
    from voxlib.diarization import DiarizationEngine
    import tempfile
    import shutil

    args.output_dir.mkdir(parents=True, exist_ok=True)
    samples_dir = args.output_dir / "speaker_samples"
    samples_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="identify_speaker_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)

        console.print("Extracting audio and running diarization (this can take a few minutes)...")
        wav_path = extract_audio(args.input, tmp_dir)

        engine = DiarizationEngine(hf_token=args.hf_token, device=args.device)
        segments = engine.diarize(wav_path)

        by_speaker: dict[str, list] = {}
        for seg in segments:
            by_speaker.setdefault(seg.speaker_label, []).append(seg)

        if not by_speaker:
            print_error("Could not find a single speaker in the file.")
            return 1

        console.print(f"\n[bold cyan]Speakers found: {len(by_speaker)}[/]\n")

        # For each speaker, take their longest continuous segment (up to
        # SAMPLE_DURATION_SEC) and cut a sample out of it with ffmpeg — the
        # simplest way to let you hear the voice.
        speaker_samples: dict[str, Path] = {}
        for speaker, segs in sorted(by_speaker.items()):
            clip_start, clip_duration = _pick_sample_clip(segs, SAMPLE_DURATION_SEC)
            sample_path = samples_dir / f"{speaker}.wav"

            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(wav_path),
                    "-ss", str(clip_start), "-t", str(clip_duration),
                    str(sample_path),
                ],
                capture_output=True, check=True,
            )
            speaker_samples[speaker] = sample_path

        speaker_list = sorted(speaker_samples.keys())

        console.print("We'll now listen to a voice sample from each speaker, one by one.")
        console.print("You can answer as soon as you recognize your own voice "
                       "(or just listen through all of them and choose at the end).\n")

        for idx, speaker in enumerate(speaker_list, start=1):
            path = speaker_samples[speaker]
            console.print(f"[bold]({idx}/{len(speaker_list)})[/] {speaker} -> [cyan]{escape(str(path))}[/]")
            if Confirm.ask("    Play this sample?", default=True):
                _play_audio(path)
            console.print()

        console.print("[bold cyan]Speaker samples:[/]")
        for idx, speaker in enumerate(speaker_list, start=1):
            console.print(f"  {idx}. {speaker}  ([cyan]{escape(str(speaker_samples[speaker]))}[/])")

        choice = Prompt.ask(
            f"\nWhich number is you? (1-{len(speaker_list)}, or 'r' to replay all)",
            choices=[str(i) for i in range(1, len(speaker_list) + 1)] + ["r"],
            show_choices=False,
        )
        while choice == "r":
            for speaker in speaker_list:
                console.print(f"\n[bold]{speaker}[/]:")
                _play_audio(speaker_samples[speaker])
            choice = Prompt.ask(
                f"\nWhich number is you? (1-{len(speaker_list)}, or 'r' to replay all)",
                choices=[str(i) for i in range(1, len(speaker_list) + 1)] + ["r"],
                show_choices=False,
            )
        chosen_speaker = speaker_list[int(choice) - 1]

        reference_path = args.reference_dir / "my_reference.wav"
        args.reference_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(speaker_samples[chosen_speaker], reference_path)

    console.print(f"\n[bold green]Done![/] Reference sample saved: [cyan]{escape(str(reference_path))}[/]")
    if _running_in_container():
        console.print(f"Now run:\n  ./run.sh <files> --reference {escape(str(reference_path))}")
    else:
        console.print(f"Now run:\n  python main.py <files> --reference {escape(str(reference_path))} --hf-token ...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
