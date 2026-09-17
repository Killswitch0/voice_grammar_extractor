"""
Checks on the lexical range measurement.

Range was the one CEFR dimension this project measured nowhere, so it is new
code with no history to fall back on. Both of its measures have an obvious
version that is wrong, and these pin the difference:

  * distinct-words-over-total falls as a transcript lengthens, so it reports
    how long someone talked rather than how widely;
  * novelty against the whole archive decays whatever the speaker does, because
    the thing a word has to be new against keeps growing.
"""

from __future__ import annotations

from pathlib import Path

from voxlib import lexis


def _annotated(*lines: str) -> str:
    """The archived annotated format: a timestamp, an optional [?] marker."""
    return "\n".join(lines)


def test_only_the_lines_whisper_was_sure_about_are_counted():
    """
    The same rule every other metric in analysis/ uses, and it is not a detail:
    a mis-recognised line says nothing about the speaker's vocabulary, and
    counting it would credit them with words whisper invented.
    """
    text = _annotated(
        "=== part1.webm ===",
        "[00:00:01] a genuinely spoken sentence",
        "[00:00:05] [?] hallucinated gibberish xylophone",
        "",
    )

    assert lexis.words_from_annotated(text) == [
        "a", "genuinely", "spoken", "sentence"]


def test_a_contraction_is_one_word():
    assert lexis.words_in("don't  it's  well-made") == [
        "don't", "it's", "well", "made"]


def test_variety_does_not_fall_just_because_the_session_was_longer():
    """
    The reason MATTR is here rather than a type-token ratio. Two sessions of
    identical variety, one twice as long: TTR punishes the longer one, MATTR
    does not: a distinct-word count tracks session length almost exactly.
    """
    block = [f"word{n}" for n in range(200)] * 2          # 400 words, 200 types
    short = block
    long = block * 2                                       # 800 words, same 200 types

    naive_short = len(set(short)) / len(short)
    naive_long = len(set(long)) / len(long)
    assert naive_long < naive_short / 1.9                  # halves, purely on length

    assert lexis.mattr(short, window=200, step=50) == lexis.mattr(long, window=200, step=50)


def test_a_session_shorter_than_one_window_has_no_ratio():
    """Not a ratio of zero — a ratio nobody could compute."""
    assert lexis.mattr(["a", "b", "c"], window=400) is None


def test_novelty_is_measured_against_a_fixed_number_of_sessions(tmp_path: Path):
    """
    The trap this measure was rebuilt to avoid. Every session here uses exactly
    the same words, so a speaker who has learned nothing: counted against the
    whole archive novelty collapses to zero and reads as a vocabulary drying
    up, which is a fact about the archive. Counted against a fixed window it
    stays flat, which is the truth.
    """
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    for day in range(1, 7):
        # 500 words so MATTR is computable, and identical every session.
        body = " ".join(f"word{n}" for n in range(500))
        (sessions / f"2026-08-0{day}.annotated.txt").write_text(
            f"[00:00:01] {body}", encoding="utf-8")

    history = lexis.measure_history(sessions)

    assert [m.date for m in history] == [f"2026-08-0{d}" for d in range(1, 7)]
    assert history[0].new_words is None            # nothing to be new against yet
    assert history[1].new_words == 0               # and nothing new after that
    assert history[-1].new_vs_recent == 0
    # The rolling baseline is full from the fourth session on.
    assert history[3].recent_baseline_sessions == lexis.RECENT_BASELINE_SESSIONS
    assert history[1].recent_baseline_sessions == 1


def test_new_words_are_counted_against_the_past_not_the_whole_corpus(tmp_path: Path):
    """"New" means new at the time. Measured against the whole archive, a word's
    first appearance would depend on sessions recorded after it."""
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "2026-08-01.annotated.txt").write_text(
        "[00:00:01] " + " ".join(["alpha"] * 500), encoding="utf-8")
    (sessions / "2026-08-02.annotated.txt").write_text(
        "[00:00:01] " + " ".join(["alpha", "beta"] * 250), encoding="utf-8")

    history = lexis.measure_history(sessions)

    assert history[1].new_words == 1               # "beta", new on the day
    assert history[1].new_per_1000 == 2.0          # 1 in 500 words


def test_the_history_round_trips_through_its_csv(tmp_path: Path):
    """Blanks have to survive as None: the first session's novelty is unmeasured
    and must not read back as zero."""
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    for day in (1, 2):
        (sessions / f"2026-08-0{day}.annotated.txt").write_text(
            "[00:00:01] " + " ".join(f"w{n}" for n in range(500)), encoding="utf-8")

    history = lexis.measure_history(sessions)
    path = tmp_path / "lexis_history.csv"
    lexis.append_history(path, history)
    reloaded = lexis.load_history(path)

    assert reloaded[0].new_words is None
    assert reloaded[0].new_per_1000 is None
    assert [m.mattr for m in reloaded] == [m.mattr for m in history]
    assert [m.words for m in reloaded] == [m.words for m in history]
