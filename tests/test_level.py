"""
Checks on the level scale.

A sub-band level is the most over-claimable number this project produces: it
looks like a measurement, it will be quoted as one, and nobody reading "B2.1"
can see what it rested on. So these tests are mostly about the scale refusing to
say more than the evidence supports — one dimension not being allowed to carry
the reading, a bad session not being allowed to move the line, and an
unmeasurable session saying so.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from voxlib import level
from voxlib.mistakes import MistakeCount
from voxlib import fluency, lexis, mistakes


def _rungs(**kwargs) -> dict:
    """Dimension rungs by name, for the rule under test."""
    return {"accuracy": None, "fluency": None, "range": None, "interaction": None, **kwargs}


def test_a_single_strong_dimension_cannot_carry_the_level():
    """
    The failure CEFR profiling exists to prevent. Fluency at the top of the
    scale beside accuracy at the bottom is not an advanced speaker; averaging
    the two would say it was.
    """
    assert level.session_rung(_rungs(accuracy=0, fluency=7, range=0, interaction=0)) == 0


def test_one_lagging_dimension_does_not_freeze_the_line():
    """The opposite failure. Requiring every dimension to reach a rung lets the
    single slowest measure hold a speaker still for months."""
    # Three dimensions at B2.2, one a rung behind: the rung is still B2.2.
    assert level.session_rung(_rungs(accuracy=3, fluency=3, range=2, interaction=3)) == 3
    # Two behind, and it is not.
    assert level.session_rung(_rungs(accuracy=3, fluency=3, range=2, interaction=2)) == 2


def test_a_laggard_more_than_one_rung_down_pulls_the_reading_to_it():
    assert level.session_rung(_rungs(accuracy=5, fluency=5, range=1, interaction=5)) == 2


def test_an_unmeasured_dimension_is_not_a_zero():
    """Coherence is absent by design and Interaction is absent whenever no
    question practice has happened. Scoring either as nil would report a
    speaker who cannot interact at all."""
    assert level.session_rung(_rungs(accuracy=3, fluency=3, range=3)) == 3
    assert level.session_rung(_rungs()) is None


def test_the_polish_tier_is_ungated_until_the_band_starts():
    """
    The split that makes the whole scale work. The total mistake rate on record
    triples while the clarity rate falls, because almost all of it is
    severity-2 article errors. A B1+ reading must not be dragged down by
    errors a listener understands instantly.
    """
    polish = level.MEASURES["polish"]

    assert level.rung_for(19.4, polish) == 1        # ungated below B2.1, capped there
    assert level.rung_for(3.0, polish) == 7
    clarity = level.MEASURES["clarity"]
    # The same rate of clarity errors clears no rung at all, which is a reading
    # in its own right and not the absence of one.
    assert level.rung_for(19.4, clarity) == level.BELOW_SCALE
    assert level.rung_for(None, clarity) is None
    assert level.label(level.BELOW_SCALE) == "below B1"


def test_a_measure_is_scored_in_the_direction_it_improves():
    assert level.rung_for(0.440, level.MEASURES["mattr"]) == 7      # higher is better
    # Below every rung is BELOW_SCALE, not None: None is reserved for "nobody
    # measured it", and the two must not be confusable.
    assert level.rung_for(0.100, level.MEASURES["mattr"]) == level.BELOW_SCALE
    assert level.rung_for(0.05, level.MEASURES["fillers"]) == 7     # lower is better


def _word(session: int, index: int) -> str:
    """A unique pronounceable token. Letters only: the tokenizer counts words,
    so anything with a digit in it reduces to its letters and collides."""
    letters = "abcdefghijklmnopqrstuvwxyz"
    return (letters[session % 26] + letters[index // 26 % 26] + letters[index % 26])


def _write_lexis(directory: Path, dates: list[str], *, mattr: float) -> None:
    """A lexical history with a chosen MATTR, so Range is measured.

    Built by hand rather than from transcripts: these tests are about the scale,
    and `test_lexis.py` covers the measurement.
    """
    rows = [",".join(lexis.HISTORY_COLUMNS)]
    for index, date in enumerate(dates):
        rows.append(f"{date},500,200,{mattr},50,100.0,{index},40,80.0,"
                    f"{min(index, lexis.RECENT_BASELINE_SESSIONS)}")
    (directory / "lexis_history.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")


def _write_history(directory: Path, sessions: list[tuple], *, mattr: float = 0.40) -> None:
    """Sessions of (date, clarity_count, polish_count, words, filler_rate, marker_rate)."""
    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for date, clarity, polish, words, fillers, markers in sessions:
        mistakes.record_session(
            directory / "mistakes.csv", date=date, reliable_words=words,
            counts=[MistakeCount("A clarity mistake", 4, clarity),
                    MistakeCount("A polish mistake", 2, polish)])
        rows.append(
            f"{date}T10:00:00,{date},pipeline,solo,1,100,2,0.05,0.02,{words + 50},{words},"
            f"10.0,95.0,segment,1,{fillers},30,{markers},0.3,20")
    (directory / "fluency_history.csv").write_text(
        ",".join(fluency.HISTORY_COLUMNS) + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    _write_lexis(directory, [s[0] for s in sessions], mattr=mattr)


def test_one_good_session_does_not_promote(tmp_path: Path):
    """
    Consecutive sessions here differ by a factor of three on how long the owner
    happened to talk. Without hysteresis the level would follow that around,
    and a "level" that moves weekly is not a level.
    """
    directory = tmp_path / "analysis"
    # Two ordinary sessions, then one strong one.
    _write_history(directory, [
        ("2026-08-01", 6, 4, 1000, 1.0, 3.5),
        ("2026-08-02", 6, 4, 1000, 1.0, 3.5),
        ("2026-08-03", 0, 0, 1000, 0.05, 1.2),
    ])
    readings = level.gather(directory)

    assert readings[-1].rung > readings[-1].level     # the session beats the level
    assert readings[-1].level == readings[0].level    # and the level has not moved


def test_three_consecutive_qualifying_sessions_do_promote(tmp_path: Path):
    """The counterpart: sustained change is what a level is supposed to track."""
    directory = tmp_path / "analysis"
    _write_history(directory, [
        ("2026-08-01", 6, 4, 1000, 1.0, 3.5),
        ("2026-08-02", 0, 0, 1000, 0.05, 1.2),
        ("2026-08-03", 0, 0, 1000, 0.05, 1.2),
        ("2026-08-04", 0, 0, 1000, 0.05, 1.2),
    ])
    readings = level.gather(directory)

    assert readings[0].level < readings[-1].level
    # Promotion takes the minimum of the qualifying window, never the best of it.
    assert readings[-1].level == min(r.rung for r in readings[1:])


def test_a_session_the_pipeline_calls_unreliable_moves_nothing(tmp_path: Path):
    """
    A session that lost a large share of its words to low-confidence recognition
    is not a measurement of the speaker. Counting it would let a bad microphone
    demote someone.
    """
    directory = tmp_path / "analysis"
    _write_history(directory, [("2026-08-01", 1, 1, 1000, 0.1, 2.0)])
    text = (directory / "fluency_history.csv").read_text(encoding="utf-8")
    # Same row, but with almost half the words unusable.
    (directory / "fluency_history.csv").write_text(
        text.replace(",0.05,0.02,", ",0.5,0.45,"), encoding="utf-8")

    reading = level.gather(directory)[0]

    assert reading.reliable is False
    assert reading.level is None          # nothing reliable yet, so no level is claimed


def test_a_session_with_too_little_measured_is_provisional(tmp_path: Path):
    """Better to print the word than a decimal nobody can support."""
    directory = tmp_path / "analysis"
    directory.mkdir()
    mistakes.record_session(directory / "mistakes.csv", date="2026-08-01",
                            reliable_words=1000,
                            counts=[MistakeCount("A clarity mistake", 4, 2)])
    # No fluency history and no lexical history: accuracy alone.
    reading = level.gather(directory)[0]

    assert sum(1 for r in reading.dimension_rungs.values() if r is not None) == 1
    assert reading.provisional is True
    assert reading.level is None          # and it never becomes the level


def test_question_practice_stops_counting_once_it_is_stale(tmp_path: Path):
    """
    Scenario evidence describes the speaker at the time. Carried forward
    indefinitely, a good afternoon in August would still be propping up the
    interaction score at Christmas.
    """
    from voxlib import asking

    directory = tmp_path / "analysis"
    _write_history(directory, [
        ("2026-08-20", 2, 2, 1000, 0.3, 2.5),
        ("2026-10-20", 2, 2, 1000, 0.3, 2.5),
    ])
    asking.record_runs(directory / "asking_scenarios.csv", [
        asking.ScenarioRun(date="2026-08-19", scenario="s", criteria_met=3, criteria_total=4)])

    readings = level.gather(directory)

    assert readings[0].values["scenarios"] == 0.75          # one day old
    assert readings[1].values["scenarios"] is None          # two months old
    assert readings[0].dimension_rungs["interaction"] is not None
    assert readings[1].dimension_rungs["interaction"] is None


def test_the_recorded_history_can_be_rebuilt_rather_than_appended(tmp_path: Path):
    """
    The one file here that is rewritten. Appending would leave rows computed
    under different thresholds with only the date to tell them apart, and a
    trend drawn through them would be part speaker, part calibration change.
    """
    directory = tmp_path / "analysis"
    _write_history(directory, [("2026-08-01", 2, 2, 1000, 0.3, 2.5)])
    readings = level.gather(directory)
    path = directory / "level_history.csv"

    level.record(path, readings)
    level.record(path, readings)
    rows = level.load_history(path)

    assert len(rows) == 1                                   # not two
    assert rows[0]["calibration"] == level.CALIBRATION
    assert rows[0]["date"] == "2026-08-01"


def test_every_measure_has_a_threshold_for_every_rung():
    """A short thresholds list would silently score the top rungs as unreachable
    — or worse, as cleared."""
    for measure in level.MEASURES.values():
        assert len(measure.thresholds) == len(level.SCALE), measure.key
    assert level.SCALE[1] == "B1+"                           # the anchor rung


def test_the_lexical_novelty_gate_waits_for_a_full_baseline(tmp_path: Path):
    """
    The first sessions measure novelty against one and two sessions of
    vocabulary and read far higher for that reason alone, before the figure
    settles. Gating on them would hand out a free promotion at the start of
    every history.
    """
    directory = tmp_path / "analysis"
    _write_history(directory, [
        (f"2026-08-0{d}", 2, 2, 1000, 0.3, 2.5) for d in range(1, 6)])
    sessions = directory / "sessions"
    sessions.mkdir()
    for day in range(1, 6):
        body = " ".join(_word(day, n) for n in range(500))
        (sessions / f"2026-08-0{day}.annotated.txt").write_text(
            f"[00:00:01] {body}", encoding="utf-8")
    lexis.append_history(directory / "lexis_history.csv",
                         lexis.measure_history(sessions))

    readings = {r.date: r for r in level.gather(directory)}

    assert readings["2026-08-02"].values["novelty"] is None   # baseline of one
    assert readings["2026-08-05"].values["novelty"] == pytest.approx(1000.0)
