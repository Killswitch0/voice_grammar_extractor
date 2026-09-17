"""
Checks on the vocabulary-substitution counter.

The phrases in memory.md's table are short, common English words, which is
exactly where a naive count goes wrong: "cool" inside "cooling", "great" inside
"greater", a parenthetical gloss counted as part of the phrase. Each of those
turns a phrase the speaker never said into one they apparently lean on.
"""

from __future__ import annotations

from pathlib import Path

from voxlib import vocab

_MEMORY = """# Vocabulary To Replace

| Phrase | Say instead |
|---|---|
| cool (for everything positive) | that's helpful / I like that |
| estimate / estimation (of people) | judge / assess |
| stuff | name the actual noun: this exercise / these notes |
| a (too short to search) | something |

# Useful Vocabulary Learned
"""


def _memory(tmp_path: Path) -> Path:
    path = tmp_path / "memory.md"
    path.write_text(_MEMORY, encoding="utf-8")
    return path


def test_a_phrase_is_counted_on_word_boundaries():
    """
    The failure that would make this whole measure useless. Counted as a
    substring, "cool" also matches "cooling" and "cooler" — so a speaker who
    never said the retired word reads as still using it, and the table they are
    working from never looks any better.
    """
    words = vocab.words_of("[00:00:01] the cooling system is cooler but that is cool")

    assert vocab.count_in(words, "cool") == 1
    assert vocab.count_in(words, "cooling") == 1


def test_a_multi_word_phrase_has_to_appear_in_order():
    words = vocab.words_of("[00:00:01] of course it is course of study")

    assert vocab.count_in(words, "of course") == 1
    assert vocab.count_in(words, "course of") == 1
    assert vocab.count_in(words, "of course it") == 1


def test_only_the_lines_whisper_was_sure_about_are_counted():
    """A phrase whisper invented must never be counted against the speaker —
    the same population every other measurement in analysis/ uses."""
    text = "\n".join([
        "[00:00:01] this is genuinely cool",
        "[00:00:05] [?] cool cool cool",
    ])

    assert vocab.count_in(vocab.words_of(text), "cool") == 1


def test_the_gloss_is_not_part_of_the_phrase(tmp_path: Path):
    """
    The table is written for a person: "cool (for everything positive)" names
    one word and explains it. Searching for the whole cell finds nothing, and
    the row silently reports no progress forever.
    """
    subs = {s.phrase: s for s in vocab.parse_substitutions(_memory(tmp_path))}

    assert "cool" in subs
    assert subs["cool"].replacements == ["that's helpful", "i like that"]


def test_a_row_can_retire_more_than_one_phrase(tmp_path: Path):
    """"estimate / estimation" is two words to stop using, and they do not have
    to move together, so each is counted on its own."""
    subs = {s.phrase: s for s in vocab.parse_substitutions(_memory(tmp_path))}

    assert "estimate" in subs and "estimation" in subs
    assert subs["estimate"].replacements == ["judge", "assess"]


def test_an_instruction_is_not_a_phrase_to_count(tmp_path: Path):
    """Some replacements open with advice rather than words: "name the actual
    noun: this exercise". Only the sayable part is countable."""
    subs = {s.phrase: s for s in vocab.parse_substitutions(_memory(tmp_path))}

    assert subs["stuff"].replacements == ["this exercise", "these notes"]


def test_a_fragment_too_short_to_search_is_dropped(tmp_path: Path):
    """A one- or two-letter entry matches most sentences; counting it would
    swamp the panel with a number that means nothing."""
    assert "a" not in {s.phrase for s in vocab.parse_substitutions(_memory(tmp_path))}


def test_movement_is_judged_over_halves_not_the_last_session(tmp_path: Path):
    """
    A short phrase in one session is a coin flip, the same reason the mistake
    history tests its trends over a window. Halves of the history are the
    smallest honest unit here.
    """
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    # Said often early, rarely late — with the same number of words each time.
    for day, times in enumerate([5, 4, 5, 1, 0, 1], start=1):
        body = " ".join(["cool"] * times + ["filler"] * (100 - times))
        (sessions / f"2026-08-0{day}.annotated.txt").write_text(
            f"[00:00:01] {body}", encoding="utf-8")

    counts = vocab.measure_history(sessions, [vocab.Substitution("cool", [])])
    trend = next(t for t in vocab.summarize(counts) if t.phrase == "cool")

    assert trend.counts == [5, 4, 5, 1, 0, 1]
    assert trend.movement == "falling"
    assert trend.total == 16


def test_a_phrase_nobody_ever_said_is_not_reported_as_falling(tmp_path: Path):
    """Zero everywhere is not progress; it means the row describes something
    the archive has never seen."""
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "2026-08-01.annotated.txt").write_text(
        "[00:00:01] " + " ".join(["filler"] * 100), encoding="utf-8")

    counts = vocab.measure_history(sessions, [vocab.Substitution("never said", [])])

    assert vocab.summarize(counts)[0].movement == "never said"


def test_both_sides_of_a_substitution_are_counted(tmp_path: Path):
    """A retired phrase falling is only half the question — the other half is
    whether the replacement arrived or another crutch did."""
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "2026-08-01.annotated.txt").write_text(
        "[00:00:01] cool cool that's helpful", encoding="utf-8")

    counts = vocab.measure_history(
        sessions, [vocab.Substitution("cool", ["that's helpful"])])
    kinds = {(c.phrase, c.kind): c.occurrences for c in counts}

    assert kinds[("cool", "retired")] == 2
    assert kinds[("that's helpful", "replacement")] == 1


def test_the_history_round_trips_through_its_csv(tmp_path: Path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "2026-08-01.annotated.txt").write_text(
        "[00:00:01] cool words here", encoding="utf-8")

    counts = vocab.measure_history(sessions, [vocab.Substitution("cool", [])])
    path = tmp_path / "vocab_history.csv"
    vocab.write_history(path, counts)
    reloaded = vocab.load_history(path)

    assert [(c.phrase, c.occurrences, c.words) for c in reloaded] == [
        (c.phrase, c.occurrences, c.words) for c in counts]
    assert reloaded[0].per_1000 == counts[0].per_1000


def test_a_missing_table_or_archive_is_not_an_error(tmp_path: Path):
    """memory.md may have no such table, and a fresh clone has no sessions."""
    assert vocab.parse_substitutions(tmp_path / "nothing.md") == []
    assert vocab.measure_history(tmp_path / "nowhere", [vocab.Substitution("cool", [])]) == []


def test_a_phrase_said_twice_has_no_direction(tmp_path: Path):
    """
    The same restraint the mistake trends apply. A phrase that appears once or
    twice in a whole archive has not started rising — it has been said twice,
    and labelling that "still rising" is a verdict on a coin flip.
    """
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    for day, times in enumerate([0, 0, 1, 1], start=1):
        body = " ".join(["rare"] * times + ["filler"] * 100)
        (sessions / f"2026-08-0{day}.annotated.txt").write_text(
            f"[00:00:01] {body}", encoding="utf-8")

    counts = vocab.measure_history(sessions, [vocab.Substitution("rare", [])])
    trend = next(t for t in vocab.summarize(counts) if t.phrase == "rare")

    assert trend.total == 2
    assert trend.movement == "too few to tell"
    assert vocab.MIN_FOR_MOVEMENT > 2
