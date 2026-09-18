"""
Counting the chances a mistake had.

Every other measurement in this project is a numerator. These cover the
denominator: what counts as a chance, when a count is too thin to divide by, and
— most importantly — the gate that stops a frame being adopted just because
somebody wrote one.
"""

from pathlib import Path

import pytest

from voxlib import exposure, mistakes, opportunity


def _frames(directory: Path, entries: list[tuple[str, str]], name: str = "f.yaml") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    body = "frames:\n"
    for category, trigger in entries:
        body += f"  - category: {category!r}\n    trigger: |\n      {trigger}\n"
    (directory / name).write_text(body, encoding="utf-8")
    return directory


def _archive(directory: Path, date: str, lines: list[tuple[str, bool]]) -> None:
    """One annotated transcript, in the shape `formatter` writes: a timestamp,
    an optional `[?]` marker, then the text. `(text, reliable)` per line."""
    directory.mkdir(parents=True, exist_ok=True)
    body = ["=== part_01.webm ==="]
    for i, (text, ok) in enumerate(lines):
        stamp = f"[00:{i // 60:02d}:{i % 60:02d}]"
        body.append(f"{stamp}{'' if ok else ' [?]'} {text}")
    (directory / f"{date}.annotated.txt").write_text("\n".join(body) + "\n", encoding="utf-8")


def _mistakes(path: Path, rows: list[tuple[str, int, str, int, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "date,category,severity,occurrences,reliable_words,source,notes\n"
    for date, severity, category, words, occurrences in rows:
        shown = "" if occurrences is None else occurrences
        body += f'{date},"{category}",{severity},{shown},{words},test,\n'
    path.write_text(body, encoding="utf-8")


# --- what counts as a chance ---------------------------------------------------

def test_a_line_whisper_was_unsure_of_is_not_a_chance(tmp_path: Path):
    """The same population every other measurement uses. A line that may not
    have been said cannot be evidence that the structure came up."""
    _archive(tmp_path / "sessions", "2026-08-01", [
        ("I listen music every day", True),
        ("I listen music again", False),        # [?] — not counted either way
    ])
    frames = opportunity.load_frames(_frames(tmp_path / "frames", [("Prep", r"\blisten\b")]))
    counts = opportunity.count(tmp_path / "sessions", frames)

    assert [c.opportunities for c in counts] == [1]


def test_a_line_is_one_chance_however_often_the_frame_appears(tmp_path: Path):
    """A line saying it twice is one moment of speaking. Counting matches
    instead would inflate the denominator, which is the direction that
    flatters."""
    _archive(tmp_path / "sessions", "2026-08-01", [
        ("I listen music and he listen music", True),
    ])
    frames = opportunity.load_frames(_frames(tmp_path / "frames", [("Prep", r"\blisten\b")]))

    assert opportunity.count(tmp_path / "sessions", frames)[0].opportunities == 1


def test_a_trigger_can_be_written_across_lines(tmp_path: Path):
    """A category's frame is a long alternation and unreviewable on one line, so
    triggers compile VERBOSE — which is also why a literal space has to be \\s."""
    _archive(tmp_path / "sessions", "2026-08-01", [("a lot of energy", True),
                                                   ("many things", True)])
    frames = opportunity.load_frames(_frames(tmp_path / "frames", [
        ("Quant", "\\b(many\n      |a\\s+lot\\s+of)\\b")]))

    assert opportunity.count(tmp_path / "sessions", frames)[0].opportunities == 2


def test_an_unusable_trigger_names_the_category_it_came_from(tmp_path: Path):
    directory = _frames(tmp_path / "frames", [("Prep", r"\b(unclosed")])

    with pytest.raises(ValueError, match="Prep"):
        opportunity.load_frames(directory)


def test_two_frames_cannot_claim_the_same_category(tmp_path: Path):
    """Both would silently write to the same key and one would win by file
    order, which is not a thing anyone would ever debug."""
    directory = _frames(tmp_path / "frames", [("Prep", r"\ba\b"), ("Prep", r"\bb\b")])

    with pytest.raises(ValueError, match="same category"):
        opportunity.load_frames(directory)


def test_no_frames_is_an_empty_answer_not_an_error(tmp_path: Path):
    """frames/ is personal content like drills/ and a fresh clone has none.
    Everything downstream falls back to the per-word rate."""
    assert opportunity.load_frames(tmp_path / "nothing") == []
    assert opportunity.count(tmp_path / "nothing", []) == []


# --- when a count is too thin to divide by -------------------------------------

def test_a_session_with_too_few_chances_reports_no_accuracy(tmp_path: Path):
    """One error against three chances is 67%, and that is not a measurement —
    at these counts the figure moves further on one instance than any real
    change would move it."""
    _archive(tmp_path / "sessions", "2026-08-01",
             [("x listen y", True)] * (opportunity.MIN_OPPORTUNITIES - 1))
    _mistakes(tmp_path / "mistakes.csv", [("2026-08-01", 4, "Prep", 1000, 1)])
    frames = opportunity.load_frames(_frames(tmp_path / "frames", [("Prep", r"\blisten\b")]))

    counts = opportunity.count(tmp_path / "sessions", frames)
    scored = opportunity.accuracy(counts, mistakes.load(tmp_path / "mistakes.csv"), frames)

    assert scored[0].series[0]["accuracy"] is None
    assert scored[0].series[0]["opportunities"] == opportunity.MIN_OPPORTUNITIES - 1


def test_thin_sessions_still_pool_into_a_real_denominator(tmp_path: Path):
    """The per-session threshold is not the pooled one. A frame yielding three
    chances a session across twelve sessions has thirty-six of them, and the
    first version of this module reported that as zero."""
    for day in range(1, 7):
        _archive(tmp_path / "sessions", f"2026-08-0{day}", [("I listen", True)] * 3)
    _mistakes(tmp_path / "mistakes.csv",
              [(f"2026-08-0{d}", 4, "Prep", 1000, 1) for d in range(1, 7)])
    frames = opportunity.load_frames(_frames(tmp_path / "frames", [("Prep", r"\blisten\b")]))

    scored = opportunity.accuracy(opportunity.count(tmp_path / "sessions", frames),
                                  mistakes.load(tmp_path / "mistakes.csv"), frames)[0]

    assert scored.opportunities == 18
    assert scored.errors == 6
    assert scored.accuracy == pytest.approx(1 - 6 / 18, abs=0.001)
    # Every per-session figure is withheld, and the pooled one is not.
    assert all(point["accuracy"] is None for point in scored.series)


def test_a_session_the_coach_never_judged_is_not_scored(tmp_path: Path):
    """A blank in mistakes.csv means the structure was not looked for. Whatever
    the regex found, scoring it would invent an accuracy from a session nobody
    read."""
    _archive(tmp_path / "sessions", "2026-08-01", [("I listen", True)] * 20)
    _mistakes(tmp_path / "mistakes.csv", [("2026-08-01", 4, "Prep", 1000, None)])
    frames = opportunity.load_frames(_frames(tmp_path / "frames", [("Prep", r"\blisten\b")]))

    scored = opportunity.accuracy(opportunity.count(tmp_path / "sessions", frames),
                                  mistakes.load(tmp_path / "mistakes.csv"), frames)[0]

    assert scored.sessions == 0
    assert scored.accuracy is None


# --- the absence streak that was never earned ----------------------------------

def test_no_chances_at_all_is_a_frozen_streak_not_a_clean_run(tmp_path: Path):
    """Comparative adjectives sat at "2 of 3 toward promotion" for five sessions
    because no short adjective ever came up. Read off mistakes.csv alone that is
    indistinguishable from clean production, and this is the difference."""
    for day in (1, 2, 3, 4):
        lines = [("nothing here", True)] if day > 1 else [("it is easier than that", True)] * 9
        _archive(tmp_path / "sessions", f"2026-08-0{day}", lines)
    _mistakes(tmp_path / "mistakes.csv",
              [(f"2026-08-0{d}", 2, "Comparative", 1000, 0) for d in (1, 2, 3, 4)])
    frames = opportunity.load_frames(_frames(tmp_path / "frames", [("Comparative", r"\bthan\b")]))

    scored = opportunity.accuracy(opportunity.count(tmp_path / "sessions", frames),
                                  mistakes.load(tmp_path / "mistakes.csv"), frames)[0]

    assert scored.frozen
    assert scored.series[0]["opportunities"] == 9


def test_a_low_frequency_frame_is_not_frozen(tmp_path: Path):
    """Two or three chances a session is a fact about the structure, not the
    structure failing to arise. Only zero is frozen."""
    for day in (1, 2, 3):
        _archive(tmp_path / "sessions", f"2026-08-0{day}", [("because of this", True)] * 2)
    _mistakes(tmp_path / "mistakes.csv",
              [(f"2026-08-0{d}", 2, "Because", 1000, 0) for d in (1, 2, 3)])
    frames = opportunity.load_frames(_frames(tmp_path / "frames",
                                             [("Because", r"\bbecause\s+of\b")]))

    scored = opportunity.accuracy(opportunity.count(tmp_path / "sessions", frames),
                                  mistakes.load(tmp_path / "mistakes.csv"), frames)[0]

    assert not scored.frozen


# --- the gate ------------------------------------------------------------------

# Session lengths that do not rise with anything. The word count has to be
# uncorrelated with the errors for the comparison to be a comparison — with a
# monotonic one both denominators score 1.0 and the gate has nothing to choose
# between, which is the shape of the real question rather than a fixture detail.
_WORDS = [2100, 1500, 2400, 1800, 2550, 1600, 2300, 1900]


def _linear_history(tmp_path: Path, pairs: list[tuple[int, int]]) -> tuple[list, list]:
    """Sessions where `chances` lines contain the frame and `errors` are recorded."""
    rows = []
    for i, (chances, errors) in enumerate(pairs, 1):
        date = f"2026-08-{i:02d}"
        _archive(tmp_path / "sessions", date, [("I listen", True)] * chances or [("x", True)])
        rows.append((date, 4, "Prep", _WORDS[(i - 1) % len(_WORDS)], errors))
    _mistakes(tmp_path / "mistakes.csv", rows)
    frames = opportunity.load_frames(_frames(tmp_path / "frames", [("Prep", r"\blisten\b")]))
    return (mistakes.load(tmp_path / "mistakes.csv"),
            opportunity.count(tmp_path / "sessions", frames))


def test_a_frame_that_predicts_the_errors_earns_the_denominator(tmp_path: Path):
    """Errors rising with chances is the whole claim the per-word rate makes and
    cannot support. Where a frame delivers it, it is the better divisor."""
    rows, counts = _linear_history(tmp_path, [(10, 1), (20, 2), (30, 3), (40, 4), (50, 5),
                                              (60, 6)])
    verdict = exposure.compare_denominators(rows, counts)[0]

    assert verdict.prefer_opportunities
    assert verdict.r_opportunities > verdict.r_words


def test_a_frame_that_predicts_nothing_keeps_the_per_word_rate(tmp_path: Path):
    """The point of the gate. A frame nobody validated must not quietly become
    the denominator under months of recorded numbers."""
    rows, counts = _linear_history(tmp_path, [(10, 5), (20, 1), (30, 6), (40, 2), (50, 4),
                                              (60, 1)])
    verdict = exposure.compare_denominators(rows, counts)[0]

    assert not verdict.prefer_opportunities
    assert "does not predict" in verdict.verdict or "no better" in verdict.verdict


def test_a_frame_is_not_judged_on_too_few_sessions(tmp_path: Path):
    """Two points make a perfect correlation and mean nothing."""
    rows, counts = _linear_history(tmp_path, [(10, 1), (20, 2), (30, 3)])
    verdict = exposure.compare_denominators(rows, counts)[0]

    assert not verdict.prefer_opportunities
    assert "too few sessions" in verdict.verdict


def test_both_denominators_are_scored_over_the_same_sessions(tmp_path: Path):
    """Scored over different session sets the comparison is between two
    different questions, and whichever had the friendlier sessions wins."""
    _archive(tmp_path / "sessions", "2026-08-01", [("I listen", True)] * 10)
    _mistakes(tmp_path / "mistakes.csv", [
        ("2026-08-01", 4, "Prep", 1000, 1),
        # No transcript for this date at all, so it has no chance count.
        ("2026-08-02", 4, "Prep", 1000, 9),
    ])
    frames = opportunity.load_frames(_frames(tmp_path / "frames", [("Prep", r"\blisten\b")]))
    rows = mistakes.load(tmp_path / "mistakes.csv")

    verdict = exposure.compare_denominators(rows, opportunity.count(tmp_path / "sessions",
                                                                   frames))[0]
    assert verdict.pairs == 1


# --- the history file ----------------------------------------------------------

def test_the_history_is_rewritten_and_carries_its_fingerprint(tmp_path: Path):
    """Derived, like the level line: the rows hold no observation of their own,
    only the archive read through the frames. A file mixing rows from two
    different triggers would draw a trend that is part speaker, part regex."""
    _archive(tmp_path / "sessions", "2026-08-01", [("I listen", True)] * 3)
    frames = opportunity.load_frames(_frames(tmp_path / "frames", [("Prep", r"\blisten\b")]))
    counts = opportunity.count(tmp_path / "sessions", frames)

    path = tmp_path / "opportunity_history.csv"
    opportunity.record(path, counts)
    first = path.read_text(encoding="utf-8")
    opportunity.record(path, counts)

    assert path.read_text(encoding="utf-8") == first            # rewritten, not appended
    assert frames[0].fingerprint in first

    changed = opportunity.load_frames(_frames(tmp_path / "frames2", [("Prep", r"\bhear\b")]))
    assert changed[0].fingerprint != frames[0].fingerprint


def test_more_errors_than_chances_withholds_the_accuracy(tmp_path: Path):
    """A chance is a line and an error is an occurrence, and one line can hold
    several — so the subtraction has no floor. Left alone it rendered as
    "-133.3%", which reads as a claim about the speaker. Errors outrunning
    chances is a fact about the *frame*: the trigger is missing the lines the
    errors were made in.
    """
    for day in range(1, 6):
        _archive(tmp_path / "sessions", f"2026-08-0{day}", [("I listen", True)] * 3)
    _mistakes(tmp_path / "mistakes.csv",
              [(f"2026-08-0{d}", 4, "Prep", 1000, 7) for d in range(1, 6)])
    frames = opportunity.load_frames(_frames(tmp_path / "frames", [("Prep", r"\blisten\b")]))

    scored = opportunity.accuracy(opportunity.count(tmp_path / "sessions", frames),
                                  mistakes.load(tmp_path / "mistakes.csv"), frames)[0]

    assert scored.errors > scored.opportunities
    assert scored.undercounted
    assert scored.accuracy is None
    assert all(point["accuracy"] is None for point in scored.series)


def test_an_ordinary_frame_is_not_flagged_as_undercounting(tmp_path: Path):
    for day in range(1, 6):
        _archive(tmp_path / "sessions", f"2026-08-0{day}", [("I listen", True)] * 10)
    _mistakes(tmp_path / "mistakes.csv",
              [(f"2026-08-0{d}", 4, "Prep", 1000, 2) for d in range(1, 6)])
    frames = opportunity.load_frames(_frames(tmp_path / "frames", [("Prep", r"\blisten\b")]))

    scored = opportunity.accuracy(opportunity.count(tmp_path / "sessions", frames),
                                  mistakes.load(tmp_path / "mistakes.csv"), frames)[0]

    assert not scored.undercounted
    assert scored.accuracy == pytest.approx(0.8, abs=0.001)
