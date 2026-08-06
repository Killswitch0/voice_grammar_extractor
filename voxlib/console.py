"""
Single shared terminal style for the whole app — logging and progress bars
in main.py, identify_speaker.py, and everywhere in voxlib go through here, so
different modules can't drift into different looks.

Not in scope: pyannote's own progress bars during diarization (the
segmentation/embeddings/... bars) — those are drawn by pyannote.audio itself
via its ProgressHook, a separate library's own display we don't control.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, TypeVar

from rich.console import Console
from rich.logging import RichHandler
from rich.markup import escape
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

console = Console()

T = TypeVar("T")


def print_error(message: str, log_file: Path | None = None) -> None:
    """
    The one shared look for a user-facing error: a red panel on the console.

    Deliberately doesn't go through the logging module — the root logger's
    RichHandler is always attached, so a logger.error() call here would also
    print a second, plain-text copy of the same message right next to this
    panel. If a --log-file is configured, the message is appended to it
    directly instead, in the same plain format configure_logging's
    FileHandler already uses.

    The message is escaped before rendering: exception text routinely looks
    like "[Errno 2] No such file or directory: ..." and Rich would otherwise
    silently swallow the "[Errno 2]" part, mistaking it for a markup tag.
    """
    console.print()
    console.print(Panel(escape(message), title="[bold red]Error[/]", border_style="red"))
    if log_file:
        with log_file.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%H:%M:%S} [ERROR] {message}\n")


def configure_logging(verbose: bool = False, log_file: Path | None = None) -> None:
    """
    One consistent logging setup for the whole app: colored, aligned level
    tags on the console; plain timestamped text in --log-file, if given
    (color codes don't belong in a log file).
    """
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [
        RichHandler(console=console, show_path=False, markup=False, rich_tracebacks=True)
    ]

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
        handlers.append(file_handler)

    logging.basicConfig(level=level, format="%(message)s", datefmt="[%X]", handlers=handlers, force=True)


def make_progress() -> Progress:
    """The one progress-bar look used everywhere in this app."""
    return Progress(
        SpinnerColumn(style="cyan"),
        TextColumn("[bold cyan]{task.description}"),
        BarColumn(bar_width=40, complete_style="green", finished_style="bold green"),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
    )


def track(iterable: Iterable[T], description: str, total: int | None = None) -> Iterator[T]:
    """
    Drop-in replacement for tqdm(iterable, desc=..., total=...) that renders
    in this app's single consistent progress-bar style instead of tqdm's.
    """
    with make_progress() as progress:
        task_id = progress.add_task(description, total=total)
        for item in iterable:
            yield item
            progress.advance(task_id)
