"""
The one thing an append-only CSV cannot do on its own: gain a column.

Every history in `analysis/` is append-only in the sense that matters — no row's
values are ever revised — and every one of them has eventually needed a field
nobody thought of when it was created. That cannot be appended around. Writing
nine fields under an eight-field header shifts every value in the new rows one
place left, and the file reads as corrupt rather than as incomplete; writing
eight under nine silently drops the new field on every read, which is worse
because nothing looks wrong.

So the header is rewritten once, in place, and the rows already in the file gain
an empty cell — which every loader here already reads as "not measured", the
same thing it meant before the column existed.

**A new column goes on the end.** Not beside the fields it belongs with, however
much better that reads: the existing rows are only still valid because
everything before the new column is untouched, and inserting one in the middle
means rewriting every row that was supposed to be immutable. `widen_header`
refuses a header that isn't a prefix of the new one, which is that rule enforced
rather than remembered.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def widen_header(path: Path, columns: list[str]) -> None:
    """
    Add columns to an existing history file, padding the rows already in it.

    Refuses anything that isn't an older version of the same file. A header this
    doesn't recognise is not a file to pad — padding it would shift its columns
    and destroy whatever it actually was.
    """
    if not path.exists():
        return
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    if not rows or rows[0] == columns:
        return
    if rows[0] != columns[:len(rows[0])]:
        raise ValueError(
            f"{path} has an unexpected header {rows[0]} — refusing to migrate it. Expected "
            f"the first {len(rows[0])} of {columns}."
        )
    width = len(columns)
    padded = [row + [""] * (width - len(row)) for row in rows[1:]]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(padded)
    logger.info("Added %d column(s) to %s", width - len(rows[0]), path)


def append(path: Path, columns: list[str], rows: list[dict]) -> None:
    """Append rows, writing the header if the file is new and widening it if it
    is an older version of itself."""
    path.parent.mkdir(parents=True, exist_ok=True)
    widen_header(path, columns)
    is_new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)
