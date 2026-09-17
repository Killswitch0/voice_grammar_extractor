"""
Checks on the view layer.

The dashboard's whole design premise is that it computes nothing — every number
it shows comes from the module that owns the file it came from. So these tests
are not about arithmetic. They are about the three ways a chart drawn from this
data lies, each of which is a rendering decision rather than a calculation:

  * filling an untested cell with the clean colour,
  * plotting a category before it was ever tracked as a run of zeros,
  * and summing a growing set of categories into one line called "progress".

Each is cheap to reintroduce while tidying the template, and none of them would
fail any existing test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from voxlib import dashboard, fluency
from voxlib.mistakes import MistakeCount
from voxlib import mistakes


def _history(path: Path, sessions: list[tuple[str, int, list]]) -> None:
    for date, words, counts in sessions:
        mistakes.record_session(
            path, date=date, reliable_words=words,
            counts=[MistakeCount(*c) for c in counts],
        )


@pytest.fixture
def analysis(tmp_path: Path) -> Path:
    """Three sessions with one of every case: a mistake tracked throughout, one
    added later, an explicit zero, and a blank."""
    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [
        ("2026-08-01", 1000, [("Article Errors", 2, 4)]),
        ("2026-08-02", 2000, [("Article Errors", 2, 0),
                              ("Extra to After Modal", 3, 6)]),
        ("2026-08-03", 1000, [("Article Errors", 2, 2),
                              ("Extra to After Modal", 3, None)]),
    ])
    return directory


def test_an_untested_session_is_a_hole_in_the_series_not_a_zero(analysis: Path):
    """
    A blank in `mistakes.csv` means the structure never came up, so nothing was
    measured. Drawn as a zero it reads as a clean session — the page would
    report progress that was never observed, and the line through it would slope
    the wrong way.
    """
    model = dashboard.build_model(analysis_dir=analysis)
    extra = next(c for c in model["categories"] if c["category"] == "Extra to After Modal")
    last = extra["series"][-1]

    assert last["state"] == "untested"
    assert last["rate"] is None

    clean = next(c for c in model["categories"] if c["category"] == "Article Errors")
    assert clean["series"][1]["state"] == "clean"
    assert clean["series"][1]["rate"] == 0.0


def test_a_category_is_not_drawn_before_anyone_was_looking_for_it(analysis: Path):
    """
    Coaching adds categories as it finds them. A category first tracked in
    session two has no data for session one — not a zero, and not an untested
    session either: nobody was looking. Zero-filling it invents an improvement
    for every mistake ever added to the tracker.
    """
    model = dashboard.build_model(analysis_dir=analysis)
    extra = next(c for c in model["categories"] if c["category"] == "Extra to After Modal")

    assert [p["state"] for p in extra["series"]] == ["before", "seen", "untested"]
    assert extra["first_seen"] == "2026-08-02"


def test_the_comparable_line_counts_only_the_categories_tracked_throughout(analysis: Path):
    """
    The total rate rises when the tracker grows, whatever the speaker does.
    `cohort_rate` is the same categories at both ends, which is the only sum
    that can be compared across the whole history.
    """
    model = dashboard.build_model(analysis_dir=analysis)

    assert model["cohort"] == ["Article Errors"]
    second = model["sessions"][1]
    # Six of the session's occurrences belong to a category added that session.
    assert second["occurrences"] == 6
    assert second["rate"] == 3.0
    assert second["cohort_rate"] == 0.0


def test_the_ranking_is_the_one_the_cli_prints(analysis: Path):
    """
    Impact is severity x sqrt(recency-weighted rate), defined and tested in
    `mistakes`. If the page ever sorted by its own idea of importance, it and
    `python -m voxlib.mistakes` would disagree about what to practise next.
    """
    model = dashboard.build_model(analysis_dir=analysis)
    expected = [t.category for t in mistakes.summarize(mistakes.load(analysis / "mistakes.csv"))]

    assert [c["category"] for c in model["categories"]] == expected


def test_a_short_session_does_not_look_like_a_worse_one(analysis: Path):
    """The denominator is per session and already on every row; the page divides
    by it rather than plotting counts."""
    model = dashboard.build_model(analysis_dir=analysis)
    rates = {s["date"]: s["rate"] for s in model["sessions"]}

    # Four errors in 1,000 words and eight in 2,000 are the same density.
    assert rates["2026-08-01"] == 4.0


def test_the_headline_compares_against_an_average_not_the_last_session(analysis: Path):
    """
    Consecutive sessions here differ by a factor of three on how long the owner
    happened to talk. A delta against the single previous session is mostly
    noise about session length.
    """
    model = dashboard.build_model(analysis_dir=analysis)
    headline = model["headline"]

    assert headline["baseline_window"] == 2          # only two sessions precede the last
    assert headline["baseline_mean"] == 3.5          # (4.0 + 3.0) / 2
    assert headline["delta"] == pytest.approx(-1.5)  # 2.0 now: better


def test_missing_history_files_are_empty_sections_not_a_crash(tmp_path: Path):
    """A fresh clone has none of these files, and `--open` on day one should say
    so rather than raise."""
    model = dashboard.build_model(analysis_dir=tmp_path / "nothing")

    assert model["sessions"] == []
    assert model["categories"] == []
    assert dashboard.main(["--analysis", str(tmp_path / "nothing"),
                           "--out", str(tmp_path / "out.html")]) == 1


def test_the_page_carries_its_data_without_closing_its_own_script_tag(analysis: Path):
    """
    Category names come from a CSV the coach writes by hand and contain quotes
    already (`Conditional "will" In If-Clauses`). A name containing a literal
    `</script>` would otherwise end the JSON block and break the page.
    """
    model = dashboard.build_model(analysis_dir=analysis)
    model["categories"][0]["category"] = 'Bad </script><script>alert(1)</script>'
    page = dashboard.render(model)

    assert "</script><script>alert(1)" not in page
    assert "\\u003c/script" in page
    payload = page.split('<script id="model" type="application/json">')[1].split("</script>")[0]
    assert json.loads(payload)["categories"][0]["category"].startswith("Bad <")


def test_pace_is_not_comparable_across_a_change_of_measurement(tmp_path: Path):
    """
    Words per minute is measured against VAD-tight turns under diarization and
    against whisper's pause-inclusive segments without it. The recorded history
    crosses that line, and one line drawn through both shows a collapse in pace
    that is purely a change of instrument.
    """
    path = tmp_path / "fluency_history.csv"
    path.write_text(
        ",".join(fluency.HISTORY_COLUMNS) + "\n"
        # A backfilled row: counted words, never measured time.
        "2026-08-01T10:00:00,2026-08-01,backfill,,0,10,1,0.1,0.05,900,850,0.0,0.0,,1,0.1,5,0.5,,\n"
        "2026-08-02T10:00:00,2026-08-02,pipeline,diarization,2,20,2,0.1,0.05,"
        "1000,950,10.0,100.0,vad,1,0.1,5,0.5,,\n",
        encoding="utf-8")

    rows = fluency.load_history(path)

    assert rows[0].comparable_pace is False       # no basis: nothing to compare against
    assert rows[1].comparable_pace is True
    assert rows[0].median_pause_sec is None       # blank, not 0.0
    assert rows[0].long_pauses is None


def test_a_rerun_of_one_session_does_not_become_two_sessions(tmp_path: Path):
    """
    The history is append-only, so re-running a recording after a fix appends a
    second row for the same date. The later run is the current measurement; two
    points for one session would double-count it in every total on the page.
    """
    path = tmp_path / "fluency_history.csv"
    path.write_text(
        ",".join(fluency.HISTORY_COLUMNS) + "\n"
        "2026-08-02T10:00:00,2026-08-02,pipeline,solo,2,20,2,0.1,0.05,"
        "1000,950,10.0,95.0,segment,1,0.1,5,0.5,,\n"
        "2026-08-02T18:00:00,2026-08-02,pipeline,solo,3,30,1,0.03,0.01,"
        "1100,1080,11.0,100.0,segment,1,0.09,5,0.45,,\n",
        encoding="utf-8")

    latest = fluency.latest_per_date(fluency.load_history(path))

    assert len(latest) == 1
    assert latest[0].run_at == "2026-08-02T18:00:00"
    assert latest[0].reliable_words == 1080


def test_the_prose_for_a_resolved_mistake_is_not_offered_as_a_current_one(tmp_path: Path):
    """
    `# Improvements` carries `##` entries of exactly the same shape as the
    persistent ones. A parser that scanned the whole document would show a
    retired mistake's notes on a card for a live one.
    """
    from voxlib import brief

    path = tmp_path / "memory.md"
    path.write_text(
        "# Persistent Grammar Mistakes\n\n"
        "## Article Errors\nSeverity: 2\nSays \"the\" where none belongs.\n\n"
        "# Improvements\n\n"
        "## Redundant Reflexive Pronoun\nGone since 2026-08-15.\n",
        encoding="utf-8")

    notes = brief.persistent_notes(path)

    assert set(notes) == {"Article Errors"}
    assert "none belongs" in notes["Article Errors"]


# --- the ladder ---------------------------------------------------------------
#
# The ladder's only job is to say where a pattern breaks down, and every way it
# can be wrong is a way of claiming evidence that isn't there: a perfect score
# over one item, a drill that was never written reported as a failure, or an
# asking session's word count used as the denominator for grammar categories it
# never gave a chance to appear.


def _practice(path: Path, rows: list[dict]) -> None:
    from voxlib import practice
    for row in rows:
        practice.record_session(
            path, date=row["date"], focus=row.get("focus", "practice"),
            learner_words=row["words"], errors_by_category=row.get("errors", {}),
            mode=row.get("mode", practice.ANSWER_MODE),
        )


def _drill(path: Path, category: str, attempts: list[tuple]) -> None:
    """Rows straight into `drills.csv`.

    The writer takes a whole scored `DrillResult`; what the dashboard reads is
    `drill.load_history`, so the fixture writes what that loader parses and
    leaves the writer to its own tests.
    """
    from voxlib import csvfile, drill
    csvfile.append(path, drill.HISTORY_COLUMNS, [{
        "date": date, "drill": "a-drill", "category": category, "fingerprint": "abc",
        "items": attempted, "attempted": attempted, "correct": correct, "notes": "",
        "condition": condition,
    } for date, attempted, correct, condition in attempts])


def _ladder_row(model: dict, category: str) -> dict:
    return next(r for r in model["ladder"]["rows"] if r["category"] == category)


def test_one_perfect_item_is_not_evidence_that_the_form_is_known(tmp_path: Path):
    """
    Two of the three drills on record have exactly one mixed-condition item. A
    A perfect score over one item would promote the pattern to "knows it, still
    says it wrong" — a diagnosis that says to stop drilling — on a sample of one.
    """
    from voxlib import drill

    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [("2026-08-01", 1000, [("Article Errors", 2, 4)])])
    _drill(directory / "drills.csv", "Article Errors", [("2026-08-02", 1, 1, drill.MIXED)])

    row = _ladder_row(dashboard.build_model(analysis_dir=directory), "Article Errors")

    assert row["state"] == "thin-evidence"
    assert row["drill"]["attempted"] < dashboard.MIN_DRILL_ITEMS


def test_a_drill_that_was_never_written_is_not_a_failed_drill(tmp_path: Path):
    """
    Most tracked mistakes have no drill at all. Reported as 0% accuracy they
    would look like the worst-known forms in the collection, when in fact
    nothing about them has been tested.
    """
    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [("2026-08-01", 1000, [("Extra to After Modal", 3, 2)])])

    row = _ladder_row(dashboard.build_model(analysis_dir=directory), "Extra to After Modal")

    assert row["state"] == "no-drill"
    assert row["drill"] is None          # not a zero, and not an accuracy of 0.0


def test_knowing_the_form_and_still_saying_it_wrong_is_its_own_diagnosis(tmp_path: Path):
    """
    The state the whole view exists for: a form that drills perfectly over
    enough items to mean it, and is simultaneously among the worst mistakes in
    the recordings — which means more drilling is the one thing that will not
    help.
    """
    from voxlib import drill

    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [
        ("2026-08-01", 1000, [("Article Errors", 2, 12)]),
        ("2026-08-02", 1000, [("Article Errors", 2, 14)]),
    ])
    _drill(directory / "drills.csv", "Article Errors", [("2026-08-02", 10, 10, drill.BLOCKED)])

    row = _ladder_row(dashboard.build_model(analysis_dir=directory), "Article Errors")

    assert row["state"] == "automaticity-gap"
    assert row["drill"]["accuracy"] == 1.0
    assert row["speech_rate"] == 14.0


def test_a_resolved_mistake_is_retired_whether_or_not_it_was_ever_drilled(tmp_path: Path):
    """Three explicit clean sessions is the rule memory.md promotes on, and it
    outranks every rung below it: there is nothing left to practise."""
    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [
        ("2026-08-01", 1000, [("Redundant Reflexive Pronoun", 3, 3)]),
        ("2026-08-02", 1000, [("Redundant Reflexive Pronoun", 3, 0)]),
        ("2026-08-03", 1000, [("Redundant Reflexive Pronoun", 3, 0)]),
        ("2026-08-04", 1000, [("Redundant Reflexive Pronoun", 3, 0)]),
    ])

    row = _ladder_row(dashboard.build_model(analysis_dir=directory),
                      "Redundant Reflexive Pronoun")

    assert row["state"] == "retiring"
    assert row["absence_streak"] >= 3


def test_an_asking_session_does_not_become_an_attended_grammar_rate(tmp_path: Path):
    """
    Every practice session on record is a question-practice one. Those sessions
    contribute words to the denominator while giving most grammar categories no
    chance to appear, so pooling them understates every rate — `practice_rates`
    says so, and the ladder shows a count for them instead of inventing one.
    """
    from voxlib import practice

    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [("2026-08-01", 1000, [("Article Errors", 2, 4)])])
    _practice(directory / "practice_history.csv", [
        {"date": "2026-08-02", "words": 200, "errors": {"Article Errors": 2},
         "mode": practice.ASK_MODE},
    ])

    model = dashboard.build_model(analysis_dir=directory)
    row = _ladder_row(model, "Article Errors")

    assert row["attended_rate"] is None       # no conversation practice has been recorded
    assert row["attended_in_asking"] == 2     # but the errors happened, and are shown
    assert model["ladder"]["attended_sessions"] == 0
    assert model["ladder"]["asking_sessions"] == 1


def test_conversation_practice_is_read_as_the_middle_rung(tmp_path: Path):
    """The counterpart of the test above: an answering session is exactly what
    rung 2 measures, and it is reported as a rate in the same unit as speech."""
    from voxlib import practice

    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [("2026-08-01", 1000, [("Article Errors", 2, 4)])])
    _practice(directory / "practice_history.csv", [
        {"date": "2026-08-02", "words": 500, "errors": {"Article Errors": 1},
         "mode": practice.ANSWER_MODE},
    ])

    row = _ladder_row(dashboard.build_model(analysis_dir=directory), "Article Errors")

    assert row["attended_rate"] == 2.0        # 1 error in 500 words, per 1,000
    assert row["attended_in_asking"] is None


def test_a_pattern_the_recording_cannot_measure_is_kept_out_of_the_table(tmp_path: Path):
    """
    The focus log schedules question-asking patterns too, and those have no
    rung 3 at all — the recording cannot see whether a question was well asked.
    In the table they would be a row of permanent blanks.
    """
    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [("2026-08-01", 1000, [("Article Errors", 2, 4)])])
    (directory / "conversation_focus_log.md").write_text(
        "# Conversation Focus Log\n\n"
        "| Mistake name | Last drilled | Correct streak | Next due |\n|---|---|---|---|\n"
        "| Article Errors | 2026-08-02 | 1 | 2026-08-04 |\n"
        "| Question Register And Softening Frames | 2026-08-02 | 1 | 2026-08-04 |\n",
        encoding="utf-8")

    ladder = dashboard.build_model(analysis_dir=directory, today="2026-08-10")["ladder"]

    assert [d["category"] for d in ladder["dialogue_only"]] == [
        "Question Register And Softening Frames"]
    assert ladder["dialogue_only"][0]["overdue"] is True
    assert _ladder_row({"ladder": ladder}, "Article Errors")["overdue"] is True


def test_a_schedule_that_is_not_due_yet_is_not_flagged_as_overdue(tmp_path: Path):
    """`today` is a parameter so the page is reproducible; an off-by-one here
    would mark everything overdue the day it was drilled."""
    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [("2026-08-01", 1000, [("Article Errors", 2, 4)])])
    (directory / "conversation_focus_log.md").write_text(
        "# Conversation Focus Log\n\n"
        "| Mistake name | Last drilled | Correct streak | Next due |\n|---|---|---|---|\n"
        "| Article Errors | 2026-08-02 | 1 | 2026-08-04 |\n",
        encoding="utf-8")

    row = _ladder_row(dashboard.build_model(analysis_dir=directory, today="2026-08-04"),
                      "Article Errors")

    assert row["next_due"] == "2026-08-04"
    assert row["overdue"] is False        # due today is not overdue


def test_blocked_and_mixed_drill_conditions_are_reported_apart(tmp_path: Path):
    """
    A blocked drill names the pattern; a mixed block makes the owner notice which
    rule applies, and that is the condition that predicts unprompted speech.
    Summed into one score, a strong blocked run hides how little mixed evidence
    there is.
    """
    from voxlib import drill

    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [("2026-08-01", 1000, [("Article Errors", 2, 4)])])
    _drill(directory / "drills.csv", "Article Errors",
           [("2026-08-02", 5, 5, drill.BLOCKED), ("2026-08-03", 2, 1, drill.MIXED)])

    stat = _ladder_row(dashboard.build_model(analysis_dir=directory), "Article Errors")["drill"]

    assert stat["blocked"] == {"attempted": 5, "correct": 5, "accuracy": 1.0}
    assert stat["mixed"] == {"attempted": 2, "correct": 1, "accuracy": 0.5}
    assert stat["accuracy"] == round(6 / 7, 3)


# --- how it was spoken --------------------------------------------------------
#
# The speech panel's failure modes are all the same shape: a column that was
# never measured but is not empty. Two of them are already in the recorded
# history — the backfilled sessions wrote 0.0 for a pace nobody timed, and the
# pause columns are blank for every diarized run on purpose.


def _fluency_row(**over) -> str:
    row = {
        "run_at": "2026-08-02T10:00:00", "date": "2026-08-02", "origin": "pipeline",
        "mode": "solo", "files": 1, "total_lines": 100, "low_confidence_lines": 10,
        "low_confidence_share": 0.1, "low_confidence_word_share": 0.05,
        "total_words": 1000, "reliable_words": 950, "speech_minutes": 10.0,
        "words_per_minute": 95.0, "speech_time_basis": "segment", "filler_count": 1,
        "fillers_per_100_words": 0.1, "discourse_marker_count": 30,
        "discourse_markers_per_100_words": 3.0, "median_pause_sec": 0.3, "long_pauses": 20,
    }
    row.update(over)
    return ",".join("" if row[c] is None else str(row[c]) for c in fluency.HISTORY_COLUMNS)


def _fluency_csv(path: Path, rows: list[str]) -> None:
    path.write_text(",".join(fluency.HISTORY_COLUMNS) + "\n" + "\n".join(rows) + "\n",
                    encoding="utf-8")


def test_a_backfilled_session_is_not_a_session_of_total_silence(tmp_path: Path):
    """
    A backfilled row holds `0.0` for speech minutes and words per minute,
    because it was counted from an archived transcript with no clock to measure
    against. Plotted from the column as written, such a history opens with
    sessions of nobody speaking.
    """
    directory = tmp_path / "analysis"
    directory.mkdir()
    _fluency_csv(directory / "fluency_history.csv", [
        _fluency_row(date="2026-08-01", run_at="2026-08-01T10:00:00", origin="backfill",
                     mode=None, files=0, speech_minutes=0.0, words_per_minute=0.0,
                     speech_time_basis=None, median_pause_sec=None, long_pauses=None),
        _fluency_row(date="2026-08-02"),
    ])

    speech = dashboard.build_model(analysis_dir=directory)["speech"]

    assert speech["sessions"][0]["wpm"] is None          # not 0.0
    assert speech["pace"]["unmeasured"] == 1
    # And it appears in no pace series at all, rather than as a point at zero.
    assert all(row.get("wpm_segment") is None for row in speech["pace"]["rows"][:1])


def test_pace_is_split_into_one_series_per_measurement_basis(tmp_path: Path):
    """
    A session of each basis, and no row carries both keys: the line stops at the
    change of instrument instead of stepping across it. The two bases put the
    same speaker at very different figures, so one line through them reads as a
    collapse in fluency that never happened.
    """
    directory = tmp_path / "analysis"
    directory.mkdir()
    _fluency_csv(directory / "fluency_history.csv", [
        _fluency_row(date="2026-08-01", mode="diarization", words_per_minute=104.0,
                     speech_time_basis=fluency.VAD_BASIS, median_pause_sec=None,
                     long_pauses=None),
        _fluency_row(date="2026-08-02", words_per_minute=58.0,
                     speech_time_basis=fluency.SEGMENT_BASIS),
    ])

    pace = dashboard.build_model(analysis_dir=directory)["speech"]["pace"]

    assert [s["basis"] for s in pace["series"]] == [fluency.VAD_BASIS, fluency.SEGMENT_BASIS]
    assert pace["rows"][0] == {**pace["rows"][0], "wpm_vad": 104.0, "wpm_segment": None}
    assert pace["rows"][1] == {**pace["rows"][1], "wpm_vad": None, "wpm_segment": 58.0}


def test_the_pause_columns_are_blank_for_a_diarized_session_by_design(tmp_path: Path):
    """
    `fluency._pause_stats` records pauses for solo recordings only: in a diarized
    recording the gap between two of the owner's lines is mostly the other person
    talking. Charted as zeros, every diarized session would read as the most
    fluent one on record.
    """
    directory = tmp_path / "analysis"
    directory.mkdir()
    _fluency_csv(directory / "fluency_history.csv", [
        _fluency_row(date="2026-08-01", mode="diarization",
                     speech_time_basis=fluency.VAD_BASIS,
                     median_pause_sec=None, long_pauses=None),
        _fluency_row(date="2026-08-02"),
    ])

    speech = dashboard.build_model(analysis_dir=directory)["speech"]
    by_key = {m["key"]: m for m in speech["metrics"]}

    assert by_key["median_pause"]["solo_only"] is True
    assert by_key["median_pause"]["points"][0]["value"] is None      # not 0.0
    assert by_key["long_pause_rate"]["points"][0]["value"] is None
    assert by_key["long_pause_rate"]["points"][1]["value"] == 2.0    # 20 over 10 minutes
    assert by_key["filler_rate"]["solo_only"] is False


def test_a_pause_count_without_a_clock_is_not_divided_by_zero(tmp_path: Path):
    """A backfilled row carries 0.0 speech minutes; a rate per minute over that
    denominator is either a crash or an infinity."""
    directory = tmp_path / "analysis"
    directory.mkdir()
    _fluency_csv(directory / "fluency_history.csv", [
        _fluency_row(date="2026-08-01", origin="backfill", mode=None, speech_minutes=0.0,
                     words_per_minute=0.0, speech_time_basis=None, long_pauses=7),
    ])

    speech = dashboard.build_model(analysis_dir=directory)["speech"]

    assert speech["sessions"][0]["long_pauses"] == 7       # the count is still reported
    assert speech["sessions"][0]["long_pause_rate"] is None


def test_reliability_is_judged_on_the_word_share_not_the_line_share(tmp_path: Path):
    """
    `warn_if_unreliable` fires on the word share and deliberately not on the line
    share: a two-word "Yeah." weighs as much as a full sentence by line, and
    short backchannels are exactly where whisper is least confident. A history
    can show a line share far above its word share — judged by line, "fix your
    microphone" would outrank the speaker's English.
    """
    directory = tmp_path / "analysis"
    directory.mkdir()
    _fluency_csv(directory / "fluency_history.csv", [
        _fluency_row(date="2026-08-01", low_confidence_share=0.60,
                     low_confidence_word_share=0.23),
    ])

    speech = dashboard.build_model(analysis_dir=directory)["speech"]
    session = speech["sessions"][0]

    assert session["line_share"] == 0.60
    assert session["word_share"] == 0.23
    assert session["unreliable"] is False              # 23% is under the 40% threshold
    assert speech["any_unreliable"] is False
    assert speech["warn_share"] == fluency.LOW_CONFIDENCE_WARN_SHARE


def test_a_session_over_the_threshold_is_flagged(tmp_path: Path):
    """The counterpart: the threshold is the module's own, so raising it there
    moves the page with it."""
    directory = tmp_path / "analysis"
    directory.mkdir()
    _fluency_csv(directory / "fluency_history.csv", [
        _fluency_row(date="2026-08-01",
                     low_confidence_word_share=fluency.LOW_CONFIDENCE_WARN_SHARE),
    ])

    speech = dashboard.build_model(analysis_dir=directory)["speech"]

    assert speech["sessions"][0]["unreliable"] is True
    assert speech["any_unreliable"] is True


# --- asking questions, and the chronology -------------------------------------
#
# This panel has no unmonitored-speech rung and never will, so the thing to get
# wrong here is the denominator: twelve drill items were offered across two
# sessions and exactly one was ever answered, and seven scenario runs spread
# across seven registers give every register a sample of one.


def _scenarios(path: Path, runs: list[tuple]) -> None:
    from voxlib import asking
    asking.record_runs(path, [asking.ScenarioRun(
        date=date, scenario=scenario, pack=pack, register=register, function=function,
        criteria_met=met, criteria_total=total, failed=list(failed),
    ) for date, scenario, pack, register, function, met, total, failed in runs])


def test_a_criterion_that_fails_across_situations_is_counted_as_a_pattern(tmp_path: Path):
    """
    Register and function have one run each; the criteria are the one dimension
    that repeats. A criterion failing in four different scenarios is a property
    of the asker, not of any one situation, which is the only thing seven runs
    can actually support.
    """
    directory = tmp_path / "analysis"
    directory.mkdir()
    _scenarios(directory / "asking_scenarios.csv", [
        ("2026-08-18", "standup", "work", "peer", "verify", 4, 4, []),
        ("2026-08-18", "estimate", "work", "manager", "commit", 2, 4, ["form", "function"]),
        ("2026-08-19", "blocked-help", "work", "senior-peer", "ask", 2, 4, ["form"]),
    ])

    asking_model = dashboard.build_model(analysis_dir=directory)["asking"]

    assert asking_model["totals"] == {"runs": 3, "met": 8, "total": 12}
    assert asking_model["criteria"][0] == {
        "criterion": "form", "count": 2, "scenarios": ["estimate", "blocked-help"]}
    assert [d["date"] for d in asking_model["by_date"]] == ["2026-08-18", "2026-08-19"]


def test_a_register_with_one_run_is_not_reported_as_a_score(tmp_path: Path):
    """
    Seven runs across seven registers is one run each. Grouped and charted
    anyway, every bar has a denominator of one and the worst-performing register
    is whichever scenario happened to go badly once.
    """
    directory = tmp_path / "analysis"
    directory.mkdir()
    _scenarios(directory / "asking_scenarios.csv", [
        ("2026-08-18", "a", "work", "peer", "verify", 0, 4, ["form"]),
        ("2026-08-18", "b", "work", "manager", "commit", 4, 4, []),
        ("2026-08-19", "c", "work", "peer", "ask", 4, 4, []),
    ])

    asking_model = dashboard.build_model(analysis_dir=directory)["asking"]
    by_name = {g["name"]: g for g in asking_model["registers"]}

    assert by_name["manager"]["runs"] == 1
    assert by_name["manager"]["enough"] is False
    assert by_name["peer"]["runs"] == 2                  # still under the minimum
    assert by_name["peer"]["enough"] is False
    assert asking_model["min_runs_to_group"] == dashboard.MIN_RUNS_TO_GROUP


def test_items_offered_are_not_items_attempted(tmp_path: Path):
    """
    A question-practice block that is cut short or skipped offers far more items
    than it answers. An accuracy over the offered count understates it, and an
    accuracy that ignores the gap reads as perfect — the honest report is the
    two numbers side by side.
    """
    from voxlib import csvfile, drill

    directory = tmp_path / "analysis"
    directory.mkdir()
    # `items` is what the block offered, `attempted` what was answered — the two
    # come apart exactly when a block is cut short, which is both blocks here.
    csvfile.append(directory / "asking_drills.csv", drill.HISTORY_COLUMNS, [
        {"date": "2026-08-18", "drill": "do-support",
         "category": "Missing Do-Support In Questions", "fingerprint": "abc",
         "items": 2, "attempted": 1, "correct": 1, "notes": "", "condition": drill.MIXED},
        {"date": "2026-08-19", "drill": "embedded",
         "category": "Embedded Question Word Order", "fingerprint": "def",
         "items": 2, "attempted": 0, "correct": 0, "notes": "", "condition": drill.MIXED},
    ])

    asking_model = dashboard.build_model(analysis_dir=directory)["asking"]

    assert asking_model["drill_totals"] == {"items": 4, "attempted": 1, "correct": 1}
    skipped = next(d for d in asking_model["drills"]
                   if d["category"] == "Embedded Question Word Order")
    assert skipped["items"] == 2
    assert skipped["attempted"] == 0
    assert skipped["accuracy"] is None          # no denominator, so no score


def test_the_question_panel_shows_only_its_own_mode(tmp_path: Path):
    """The counterpart of the ladder's rule, from the other side: a conversation
    practice session is not evidence about asking questions."""
    from voxlib import practice

    directory = tmp_path / "analysis"
    directory.mkdir()
    _practice(directory / "practice_history.csv", [
        {"date": "2026-08-18", "words": 100, "mode": practice.ASK_MODE},
        {"date": "2026-08-20", "words": 500, "mode": practice.ANSWER_MODE},
    ])

    asking_model = dashboard.build_model(analysis_dir=directory)["asking"]

    assert [s["date"] for s in asking_model["practice"]] == ["2026-08-18"]
    assert asking_model["practice_totals"] == {
        "sessions": 1, "words": 100, "errors": 0, "reproductions": 0}


def test_a_form_seen_twice_stops_being_a_slip(tmp_path: Path):
    """
    CLAUDE.md's rule: an error no category covers is recorded under a
    `?`-prefixed name, and two sessions with the same one earns it a category
    and a drill. The page has to say which ones have got there.
    """
    from voxlib import practice

    directory = tmp_path / "analysis"
    directory.mkdir()
    _practice(directory / "practice_history.csv", [
        {"date": "2026-08-18", "words": 100, "errors": {"?look in X": 1},
         "mode": practice.ASK_MODE},
        {"date": "2026-08-19", "words": 100, "errors": {"?look in X": 2, "?once only": 1},
         "mode": practice.ASK_MODE},
    ])

    provisional = dashboard.build_model(analysis_dir=directory)["asking"]["provisional"]

    assert provisional[0]["name"] == "look in X"
    assert provisional[0]["sessions"] == 2
    assert provisional[0]["total"] == 3
    assert provisional[0]["ready"] is True
    assert provisional[1]["ready"] is False


def test_the_timeline_keeps_a_day_that_had_no_recording(tmp_path: Path):
    """
    Practice happens on days with no recording: scenarios and typed words with
    no audio at all. A chronology built from the recordings alone would show
    nothing happened that day.
    """
    from voxlib import practice

    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [("2026-08-18", 1000, [("Article Errors", 2, 4)])])
    _practice(directory / "practice_history.csv", [
        {"date": "2026-08-19", "words": 235, "mode": practice.ASK_MODE}])
    _scenarios(directory / "asking_scenarios.csv", [
        ("2026-08-19", "blocked-help", "work", "senior-peer", "ask", 2, 4, ["form"])])

    timeline = dashboard.build_model(analysis_dir=directory)["timeline"]

    assert [e["date"] for e in timeline] == ["2026-08-19", "2026-08-18"]   # newest first
    practice_day = timeline[0]
    assert practice_day["recording"] is False
    assert practice_day["rate"] is None            # no recording, so no mistake rate
    assert practice_day["practice_words"] == 235
    assert practice_day["scenario_met"] == 2
    assert timeline[1]["recording"] is True


def test_report_links_are_relative_to_wherever_the_page_is_written(tmp_path: Path):
    """
    Both the analysis directory and the output path are command-line arguments,
    so an absolute or assumed path would break as soon as either moved. Without
    an output directory there is nothing to be relative to, and the timeline
    carries no links rather than guessing.
    """
    directory = tmp_path / "analysis"
    (directory / "sessions").mkdir(parents=True)
    _history(directory / "mistakes.csv", [("2026-08-18", 1000, [("Article Errors", 2, 4)])])
    (directory / "sessions" / "2026-08-18.md").write_text("# Session Report", encoding="utf-8")
    out = tmp_path / "output"
    out.mkdir()

    linked = dashboard.build_model(analysis_dir=directory, out_dir=out)["timeline"]
    unlinked = dashboard.build_model(analysis_dir=directory)["timeline"]

    assert linked[0]["report"] == "../analysis/sessions/2026-08-18.md"
    assert unlinked[0]["report"] == ""


# --- the notes from memory.md -------------------------------------------------
#
# These sections are written for a person to read and carry inline markdown,
# worked examples and dated decisions. Printed as preformatted text they showed
# the syntax rather than the emphasis, buried the examples mid-paragraph, and
# repeated four header fields the card already had from the CSV. The parser's
# one hard requirement is that it never loses content: anything it does not
# recognise has to come back out in `rest`.

# An invented section in the shape memory.md uses — see tests/fixtures/ for the
# same convention elsewhere in this suite.
_NOTE = '''Status: Active (marked `!` for the **third** consecutive session)
Occurrences: 4 sessions (1, 2, 2, then 5 instances)
First seen: 2025-03-04
Last seen: 2025-03-25
Severity: 2
Typical examples:
- "she give me the book" -> "she gave me the book" (2025-03-25)
- "i must to finish it" -> "I must finish it" (2025-03-18, question practice)
- "he want you come early" -> "he wants you **to** come early" (2025-03-11, recording)
Notes: The most frequent category in this invented example, at a rate of **5.10**.

**Rule-18 changed approach, 2025-03-18 — retire the drill.** It returned a perfect score every time.

**Rule-18 changed approach, 2025-03-25 — the pattern comes off the focus list.** Four sessions.

A paragraph in no particular shape, which must survive anyway.
'''


def test_the_worked_examples_are_pulled_out_of_the_prose(tmp_path: Path):
    """
    The wrong sentence and its correction are the only part of a note you can
    practise from, and they sat in the middle of a long block of prose. The
    source qualifier — "(a date, question practice)" — is kept apart from the
    date because it says which mode caught it.
    """
    note = dashboard._parse_note(_NOTE)

    assert [e["wrong"] for e in note["examples"]] == [
        "she give me the book",
        "i must to finish it",
        "he want you come early",
    ]
    assert note["examples"][0] == {
        "wrong": "she give me the book", "right": "she gave me the book",
        "date": "2025-03-25", "source": "",
    }
    assert note["examples"][1]["source"] == "question practice"
    # Inline markdown is left in the text for the renderer to turn into elements.
    assert note["examples"][2]["right"] == "he wants you **to** come early"


def test_the_fields_the_card_already_shows_are_kept_out_of_the_prose(tmp_path: Path):
    """
    An `Occurrences:` line listing each session's count is the sparkline on the
    card, retold in words, and First seen / Last seen / Severity are three of
    its stats. Only Status carries something the CSV does not — the rule-18 `!`
    flag and what was decided about it.
    """
    note = dashboard._parse_note(_NOTE)

    assert note["status"].startswith("Active (marked `!`")
    assert set(note["duplicated"]) == {"Occurrences", "First seen", "Last seen", "Severity"}
    assert "4 sessions" not in note["notes"]
    assert note["notes"].endswith("rate of **5.10**.")


def test_the_decisions_are_newest_first_whatever_order_they_are_written_in():
    """
    The convention in memory.md is to prepend a new decision, but the one in
    force is the most recent whichever end it was written at — so they are
    sorted by the date in their own title, not by position in the file.
    """
    note = dashboard._parse_note(_NOTE)

    assert [d["title"][:38] for d in note["decisions"]] == [
        "Rule-18 changed approach, 2025-03-25 —",
        "Rule-18 changed approach, 2025-03-18 —",
    ]
    assert note["decisions"][0]["body"] == "Four sessions."


def test_nothing_in_a_note_is_ever_silently_dropped():
    """
    The parser's safety net. A section written in a shape nobody anticipated
    should lose its styling, never its content — so every line of the source
    has to be reachable somewhere in the result.
    """
    import re

    note = dashboard._parse_note(_NOTE)

    def words(text: str) -> set:
        return set(re.findall(r"[A-Za-z0-9]+", text))

    reachable = words(" ".join([
        note["status"], note["notes"], note["retained"],
        *note["rest"],
        *(f'{e["wrong"]} {e["right"]} {e["date"]} {e["source"]}' for e in note["examples"]),
        *(f'{d["title"]} {d["body"]}' for d in note["decisions"]),
        *note["duplicated"].values(),
    ]))
    # The field labels are the parser's keys, not content it has to hand back.
    labels = words("Status Occurrences First seen Last Severity Notes Typical examples")

    for line in _NOTE.splitlines():
        if not line.strip() or line.strip() == "Typical examples:":
            continue
        assert not words(line) - reachable - labels, line

    assert "A paragraph in no particular shape, which must survive anyway." in note["rest"]


def test_a_category_with_no_prose_has_no_disclosure(tmp_path: Path):
    """A mistake that has been retired lives under `# Improvements`, so there is
    no persistent section for it — and the card must not render an empty one."""
    assert dashboard._parse_note("") is None
    assert dashboard._parse_note("   \n  \n") is None


# --- do this next -------------------------------------------------------------


def test_the_first_action_is_the_one_where_drilling_is_the_wrong_answer(tmp_path: Path):
    """
    "Knows it, still says it wrong" leads because it is the only state whose
    obvious response — drill it — makes things worse by spending the one focus
    slot a speaker has. Everything else on the list is a thing to start.
    """
    from voxlib import drill

    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [
        ("2026-08-01", 1000, [("Article Errors", 2, 12)]),
        ("2026-08-02", 1000, [("Article Errors", 2, 14)]),
    ])
    _drill(directory / "drills.csv", "Article Errors", [("2026-08-02", 10, 10, drill.BLOCKED)])

    actions = dashboard.build_model(analysis_dir=directory)["actions"]

    assert actions[0]["kind"] == "automaticity-gap"
    assert actions[0]["title"] == "Stop drilling Article Errors — produce it in dialogue"
    assert "100% correct over 10 drill items" in actions[0]["detail"]
    # The ladder and the card grid are one section now, so that is where it points.
    assert actions[0]["anchor"] == "patterns"


def test_an_overdue_question_pattern_counts_even_with_no_rung_three(tmp_path: Path):
    """
    The schedule covers question patterns the recording cannot measure, and they
    are kept out of the ladder table for that reason. Being off the table must
    not mean being off the to-do list.
    """
    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [("2026-08-01", 1000, [("Article Errors", 2, 4)])])
    (directory / "conversation_focus_log.md").write_text(
        "# Conversation Focus Log\n\n"
        "| Mistake name | Last drilled | Correct streak | Next due |\n|---|---|---|---|\n"
        "| Article Errors | 2026-08-02 | 1 | 2026-08-04 |\n"
        "| Question Register And Softening Frames | 2026-08-02 | 1 | 2026-08-03 |\n",
        encoding="utf-8")

    actions = dashboard.build_model(analysis_dir=directory, today="2026-08-10")["actions"]
    overdue = next(a for a in actions if a["kind"] == "overdue")

    assert overdue["title"] == "2 practice slots are overdue"
    assert "the oldest since 2026-08-03" in overdue["detail"]
    assert "Question Register And Softening Frames" in overdue["detail"]


def test_the_action_list_stays_short_enough_to_work_through(tmp_path: Path):
    """A to-do list long enough to need prioritising is one nobody starts, and
    everything on it is also reachable in the section it points at."""
    from voxlib import drill, practice

    directory = tmp_path / "analysis"
    directory.mkdir()
    # Enough conditions to trigger seven actions: three drilled-but-still-wrong
    # patterns, one with no drill, no conversation practice, an overdue slot, a
    # promotable form and a failing scenario criterion.
    _history(directory / "mistakes.csv", [
        ("2026-08-01", 1000, [(f"Category {n}", 3, 5) for n in range(4)]),
        ("2026-08-02", 1000, [(f"Category {n}", 3, 6) for n in range(4)]),
    ])
    for n in range(3):
        _drill(directory / "drills.csv", f"Category {n}",
               [("2026-08-02", 10, 10, drill.BLOCKED)])
    _practice(directory / "practice_history.csv", [
        {"date": "2026-08-03", "words": 100, "errors": {"?a form": 1},
         "mode": practice.ASK_MODE},
        {"date": "2026-08-04", "words": 100, "errors": {"?a form": 1},
         "mode": practice.ASK_MODE},
    ])
    _scenarios(directory / "asking_scenarios.csv", [
        ("2026-08-04", "blocked-help", "work", "peer", "ask", 2, 4, ["form"])])
    (directory / "conversation_focus_log.md").write_text(
        "# Conversation Focus Log\n\n"
        "| Mistake name | Last drilled | Correct streak | Next due |\n|---|---|---|---|\n"
        "| Category 0 | 2026-08-02 | 1 | 2026-08-04 |\n", encoding="utf-8")

    actions = dashboard.build_model(analysis_dir=directory, today="2026-08-20")["actions"]

    assert len(actions) == dashboard.MAX_ACTIONS
    # The gap kind is itself capped at two, so it cannot crowd out the rest.
    assert sum(1 for a in actions if a["kind"] == "automaticity-gap") == 2
    assert len({a["kind"] for a in actions}) == 4


def test_an_empty_project_is_told_to_do_nothing(tmp_path: Path):
    """On a fresh clone there is no evidence for any advice, and inventing some
    would be the page's worst possible failure mode."""
    assert dashboard.build_model(analysis_dir=tmp_path / "nothing")["actions"] == []


# --- the headline, made to say something ---------------------------------------
#
# The hero number was honest and inert: "24.75, 14.83 worse than the 3-session
# average" with no cause attached, beside two cumulative totals that only ever
# go up. These cover what replaced them.


def test_the_headline_names_what_moved_it(tmp_path: Path):
    """
    Every category in a session divides by the same denominator, so the total
    rate is the sum of the per-category rates and the change in the total is the
    sum of the per-category changes. Naming the biggest mover is arithmetic, not
    a guess — which is the only reason the page is allowed to assert it.
    """
    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [
        ("2026-08-01", 1000, [("Article Errors", 2, 4), ("Extra to After Modal", 3, 2)]),
        ("2026-08-02", 1000, [("Article Errors", 2, 4), ("Extra to After Modal", 3, 2)]),
        ("2026-08-03", 1000, [("Article Errors", 2, 20), ("Extra to After Modal", 3, 1)]),
    ])

    headline = dashboard.build_model(analysis_dir=directory)["headline"]
    drivers = headline["drivers"]

    assert drivers[0]["category"] == "Article Errors"
    assert drivers[0]["before"] == 4.0 and drivers[0]["after"] == 20.0
    assert drivers[0]["change"] == 16.0
    # The second mover went the other way, and is reported as such.
    assert drivers[1]["category"] == "Extra to After Modal"
    assert drivers[1]["change"] == -1.0
    # And they account for the headline delta.
    assert sum(d["change"] for d in drivers) == pytest.approx(headline["delta"], abs=0.05)


def test_an_untested_category_counts_as_zero_in_that_arithmetic_only(tmp_path: Path):
    """
    A blank means the structure never came up, so it contributed no occurrences
    to the session's count — which is exactly how the total rate already treats
    it. That is the one place a blank may read as zero, and it must not leak
    into the category's own trend.
    """
    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [
        ("2026-08-01", 1000, [("Article Errors", 2, 6)]),
        ("2026-08-02", 1000, [("Article Errors", 2, None)]),
    ])

    model = dashboard.build_model(analysis_dir=directory)
    card = model["categories"][0]

    assert model["headline"]["drivers"][0]["change"] == -6.0   # 6.0 -> 0.0 in the total
    assert card["series"][1]["state"] == "untested"            # but still untested here
    assert card["latest_rate"] == 6.0                          # and its own rate is unchanged


def test_a_transcribed_but_unanalysed_recording_is_the_first_thing_to_do(tmp_path: Path):
    """
    The pipeline writes fluency_history.csv on transcription; the coach writes
    mistakes.csv during analysis. A date in the first and not the second is a
    transcript nobody has read — and until it is read, every ranking on the page
    is answering a question about an older session.
    """
    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [("2026-09-08", 1000, [("Article Errors", 2, 4)])])
    _fluency_csv(directory / "fluency_history.csv", [
        _fluency_row(date="2026-09-08", run_at="2026-09-08T10:00:00"),
        _fluency_row(date="2026-09-17", run_at="2026-09-17T10:00:00"),
    ])

    model = dashboard.build_model(analysis_dir=directory, today="2026-09-17")

    assert model["headline"]["unanalysed"] == ["2026-09-17"]
    assert model["actions"][0]["kind"] == "unanalysed"
    assert model["actions"][0]["title"] == "Analyse the 2026-09-17 recording"
    # It is in the chronology and the speech panel, and in neither grammar view.
    assert model["timeline"][0]["date"] == "2026-09-17"
    assert model["timeline"][0]["rate"] is None
    assert "2026-09-17" not in model["dates"]


def test_the_page_says_how_old_its_evidence_is(tmp_path: Path):
    """A dashboard rebuilt without a new session looks identical to a fresh one,
    and the only thing that says otherwise is the gap between the two dates."""
    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [("2026-09-08", 1000, [("Article Errors", 2, 4)])])

    same_day = dashboard.build_model(analysis_dir=directory, today="2026-09-08")
    later = dashboard.build_model(analysis_dir=directory, today="2026-09-17")

    assert same_day["headline"]["days_since_analysis"] == 0
    assert later["headline"]["days_since_analysis"] == 9


def test_the_direction_counts_cover_every_tracked_pattern(tmp_path: Path):
    """
    The tile reads "N of M improving", so the four buckets have to add up to the
    number of tracked categories or the remainder goes missing without anything
    looking wrong.

    Built from a fixture rather than from `analysis/`, which is gitignored: on a
    fresh clone that directory is empty and the assertion would hold vacuously.
    """
    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [
        # One of each: improving, worsening, steady, and one too new to say.
        ("2026-08-01", 1000, [("Improver", 2, 9), ("Worsener", 2, 1), ("Steady", 2, 3)]),
        ("2026-08-02", 1000, [("Improver", 2, 5), ("Worsener", 2, 3), ("Steady", 2, 3)]),
        ("2026-08-03", 1000, [("Improver", 2, 1), ("Worsener", 2, 9), ("Steady", 2, 3),
                              ("Newcomer", 2, 2)]),
    ])

    model = dashboard.build_model(analysis_dir=directory)
    headline = model["headline"]

    assert headline["tracked"] == 4 == len(model["categories"])
    assert sum(headline["directions"].values()) == headline["tracked"]
    # Three sessions is not enough evidence to call any of these directions, so
    # the movement is reported as unreadable rather than as improvement.
    assert headline["directions"]["not separable yet"] == 2
    assert headline["separable"] == 0


# --- the level line -----------------------------------------------------------


def test_the_page_recomputes_the_level_rather_than_reading_it_back(tmp_path: Path):
    """
    The same rule as the impact ranking: the page calls `level.gather` so it
    cannot disagree with `python -m voxlib.level`. Reading level_history.csv
    would show whatever was last written, which is stale the moment a threshold
    moves or a session is analysed without `--write`.
    """
    from voxlib import level as level_module

    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [("2026-08-01", 1000, [("Article Errors", 2, 4)])])
    # A history file that disagrees with the source data on purpose.
    (directory / "level_history.csv").write_text(
        "date,level,level_index\n2026-08-01,C1.1,7\n", encoding="utf-8")

    reported = dashboard.build_model(analysis_dir=directory)["level"]
    computed = level_module.gather(directory)

    assert reported["current"]["label"] == computed[-1].label
    assert reported["current"]["label"] != "C1.1"


def test_a_project_with_no_sessions_shows_no_level(tmp_path: Path):
    """On a fresh clone there is nothing to place on the scale, and a rung
    invented from no evidence is the worst thing this section could do."""
    empty = dashboard.build_model(analysis_dir=tmp_path / "nothing")["level"]

    assert empty["readings"] == []
    assert "current" not in empty


def test_the_rising_floor_is_reported_separately_from_the_level(tmp_path: Path):
    """
    A level held steady by hysteresis looks like nothing happening. On the real
    record the line sat at B1+ throughout while the worst single session went
    from B1 to B1+ and stayed there — which is the same evidence saying
    something did.
    """
    directory = tmp_path / "analysis"
    # Three weak sessions, then four that never drop that low again.
    _write_level_history(directory, [
        ("2026-08-01", 8, 4), ("2026-08-02", 8, 4), ("2026-08-03", 8, 4),
        ("2026-08-04", 2, 2), ("2026-08-05", 2, 2), ("2026-08-06", 2, 2),
        ("2026-08-07", 2, 2),
    ])

    floor = dashboard.build_model(analysis_dir=directory)["level"]["floor"]

    assert floor["last_at_worst"] == "2026-08-03"
    assert floor["sessions_since"] == 4
    assert floor["floor_since"] > floor["worst"]


def test_the_floor_is_not_claimed_from_too_little_history(tmp_path: Path):
    """Three sessions cannot establish that a floor has risen."""
    directory = tmp_path / "analysis"
    _write_level_history(directory, [("2026-08-01", 8, 4), ("2026-08-02", 2, 2)])

    assert dashboard.build_model(analysis_dir=directory)["level"]["floor"] is None


def _write_level_history(directory: Path, sessions: list[tuple]) -> None:
    """Sessions of (date, clarity_count, polish_count), with the fluency and
    lexical histories needed for three dimensions to be measured."""
    from voxlib import fluency as fluency_module
    from voxlib import lexis

    directory.mkdir(parents=True, exist_ok=True)
    rows = []
    for date, clarity, polish in sessions:
        mistakes.record_session(
            directory / "mistakes.csv", date=date, reliable_words=1000,
            counts=[MistakeCount("A clarity mistake", 4, clarity),
                    MistakeCount("A polish mistake", 2, polish)])
        rows.append(f"{date}T10:00:00,{date},pipeline,solo,1,100,2,0.05,0.02,1050,1000,"
                    f"10.0,95.0,segment,1,0.2,30,2.5,0.3,20")
    (directory / "fluency_history.csv").write_text(
        ",".join(fluency_module.HISTORY_COLUMNS) + "\n" + "\n".join(rows) + "\n",
        encoding="utf-8")
    lex = [",".join(lexis.HISTORY_COLUMNS)]
    for index, (date, _, _) in enumerate(sessions):
        lex.append(f"{date},500,200,0.40,50,100.0,{index},40,80.0,"
                   f"{min(index, lexis.RECENT_BASELINE_SESSIONS)}")
    (directory / "lexis_history.csv").write_text("\n".join(lex) + "\n", encoding="utf-8")


def test_a_direction_is_not_claimed_from_a_couple_of_instances(tmp_path: Path):
    """
    The correction this section needed most. Most observations in a session are
    one or two instances, and a rate built on them moves a long way on nothing:
    reported as improving or worsening, every category gets a coloured verdict
    on what is really a coin flip, and the page then carries those verdicts into
    its rankings and its encouragement.
    """
    directory = tmp_path / "analysis"
    directory.mkdir()
    # A category that drifts by one instance a session, and one that changes by
    # an order of magnitude on counts large enough to mean it.
    _history(directory / "mistakes.csv", [
        ("2026-08-01", 2000, [("Drifter", 3, 0), ("Mover", 3, 30)]),
        ("2026-08-02", 2000, [("Drifter", 3, 0), ("Mover", 3, 28)]),
        ("2026-08-03", 2000, [("Drifter", 3, 1), ("Mover", 3, 31)]),
        ("2026-08-04", 2000, [("Drifter", 3, 1), ("Mover", 3, 2)]),
        ("2026-08-05", 2000, [("Drifter", 3, 2), ("Mover", 3, 1)]),
        ("2026-08-06", 2000, [("Drifter", 3, 3), ("Mover", 3, 2)]),
    ])

    cards = {c["category"]: c for c in
             dashboard.build_model(analysis_dir=directory)["categories"]}

    assert cards["Mover"]["separable"] is True
    assert cards["Mover"]["direction"] == "improving"
    assert cards["Drifter"]["separable"] is False
    assert cards["Drifter"]["direction"] == "not separable yet"
    # The shape of the move is still recorded — it is the claim that is withheld.
    assert cards["Drifter"]["direction_shape"] == "worsening"


def test_the_count_travels_with_the_rate(tmp_path: Path):
    """A rate on its own cannot say whether it rests on one instance or twenty,
    and those are not the same evidence."""
    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [
        ("2026-08-01", 2000, [("A mistake", 3, 1)]),
        # Untested later: the count must follow the rate to the same session.
        ("2026-08-02", 2000, [("A mistake", 3, None)]),
    ])

    card = dashboard.build_model(analysis_dir=directory)["categories"][0]

    assert card["latest_rate"] == 0.5
    assert card["latest_count"] == 1


def test_the_trend_is_split_by_what_an_error_costs(tmp_path: Path):
    """
    The split the total hides. A page that plots only the total reports whichever
    category is most frequent, and that can be one a listener understands
    instantly — so the line climbs while the errors that actually cost
    comprehension are falling.
    """
    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [
        ("2026-08-01", 1000, [("Serious", 4, 6), ("Cosmetic", 2, 1)]),
        ("2026-08-02", 1000, [("Serious", 4, 2), ("Cosmetic", 2, 20)]),
    ])

    sessions = dashboard.build_model(analysis_dir=directory)["sessions"]

    assert sessions[0]["clarity_rate"] == 6.0 and sessions[0]["polish_rate"] == 1.0
    assert sessions[1]["clarity_rate"] == 2.0 and sessions[1]["polish_rate"] == 20.0
    # The total moves the opposite way from the half that matters.
    assert sessions[1]["rate"] > sessions[0]["rate"]
    assert sessions[1]["clarity_rate"] < sessions[0]["clarity_rate"]
    assert sessions[0]["clarity_count"] == 6


def test_the_drill_suggestion_skips_a_category_nobody_has_seen(tmp_path: Path):
    """
    Impact will happily nominate a serious category observed three times in one
    session. A drill written from that is a guess about a rare event, and it
    costs the one focus slot a speaker has.
    """
    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [
        ("2026-08-01", 1000, [("Rare but serious", 5, 3), ("Common enough", 3, 8)]),
        ("2026-08-02", 1000, [("Rare but serious", 5, 0), ("Common enough", 3, 7)]),
    ])

    actions = dashboard.build_model(analysis_dir=directory)["actions"]
    drill_action = next(a for a in actions if a["kind"] == "no-drill")

    assert "Common enough" in drill_action["title"]
    assert "enough instances on record" in drill_action["detail"]


def test_the_page_reports_whether_its_own_denominator_holds(tmp_path: Path):
    """
    Every figure on the page divides by reliable words. Whether that is the
    right divisor is testable, and a dashboard that never asks is asserting its
    own premise.
    """
    directory = tmp_path / "analysis"
    directory.mkdir()
    _history(directory / "mistakes.csv", [
        (f"2026-08-{d:02d}", words, [("A mistake", 3, count)])
        for d, (words, count) in enumerate(
            zip([1000, 1600, 2200, 2800, 3400, 4000], [9, 6, 10, 5, 9, 6]), start=1)
    ])

    report = dashboard.build_model(analysis_dir=directory)["exposure"]

    assert report["length_effect"] is True
    assert report["supports_per_word"] is False
    assert "not removing it" in report["verdict"]
