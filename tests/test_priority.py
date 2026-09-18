"""
The ranking: what to work on, and why that and not the thing above it.

These are mostly claims about *order*, because the order is the design. The
thing being guarded against throughout is a ranking that quietly becomes a
function of something other than the English — how long since you last
practised, how serious one rare category is, how many polish errors happen to be
frequent.
"""

from datetime import date, timedelta

from voxlib import mistakes, practice, priority


def _trend(category: str, *, severity: int = 3, impact: float = 1.0,
           latest_rate: float = 1.0, evidence: int = 20, thin: bool = False,
           ready: bool = False, stalled: bool = False) -> mistakes.CategoryTrend:
    return mistakes.CategoryTrend(
        category=category, severity=severity, first_seen="2026-08-01",
        last_seen="2026-08-09", sessions_measured=5, total_occurrences=evidence,
        latest_rate=latest_rate, weighted_rate=1.0, impact=impact,
        absence_streak=3 if ready else 0, untested_since=0, direction="steady",
        stalled=stalled, separable=True, latest_count=1,
        evidence=1 if thin else evidence)


def _drill(attempted: int, correct: int) -> dict:
    return {"attempted": attempted, "correct": correct,
            "accuracy": round(correct / attempted, 3) if attempted else None,
            "items": attempted}


def _rank(trends, drills=None, **kw):
    return priority.rank(trends, drills=drills or {}, slugs={}, **kw)


# --- the ladder state ----------------------------------------------------------

def test_a_resolved_pattern_is_retiring_whether_or_not_it_was_drilled():
    """Clean for three measured sessions is resolved on its own evidence. A
    pattern nobody ever drilled is not thereby unresolved."""
    assert priority.ladder_state(ready_for_improvements=True, latest_rate=0.0,
                                 drill=None) == "retiring"


def test_one_perfect_item_is_not_evidence_that_the_form_is_known():
    """A mixed block can carry a single item of a pattern, which would otherwise
    read as a perfect score on the harder condition."""
    assert priority.ladder_state(ready_for_improvements=False, latest_rate=2.0,
                                 drill=_drill(1, 1)) == "thin-evidence"


def test_knowing_the_form_and_still_saying_it_wrong_is_its_own_state():
    assert priority.ladder_state(ready_for_improvements=False, latest_rate=2.0,
                                 drill=_drill(10, 10)) == "automaticity-gap"


def test_a_drill_that_was_never_written_is_not_a_failed_drill():
    assert priority.ladder_state(ready_for_improvements=False, latest_rate=2.0,
                                 drill=None) == "no-drill"


# --- the order -----------------------------------------------------------------

def test_what_to_do_about_it_outranks_how_much_it_costs():
    """The rung a pattern fails on decides whether any action exists and which
    one, so it sorts before impact. "Knows it, still says it wrong" and "never
    drilled" are not two values of one quantity — the response to the first is
    the opposite of the response to the second."""
    ranked = _rank(
        [_trend("Undrilled", impact=9.0), _trend("Knows it", impact=1.0)],
        {"Knows it": _drill(10, 10)})

    assert [t.category for t in ranked] == ["Knows it", "Undrilled"]
    assert ranked[0].action == "Produce it in dialogue"


def test_a_ranking_resting_on_a_handful_of_instances_does_not_lead():
    """Impact will happily nominate a severity-5 category seen three times in one
    session, and the action on a no-drill row is "build something" — an
    investment, spent on a guess about a rare event."""
    ranked = _rank([_trend("Rare but serious", severity=5, impact=9.0, thin=True),
                    _trend("Common enough", severity=3, impact=4.0)])

    assert [t.category for t in ranked] == ["Common enough", "Rare but serious"]
    assert "enough instances on record" in ranked[0].why


def test_only_one_row_claims_to_be_the_highest_impact_one():
    """It is a superlative. Written onto every no-drill row it said the same
    thing five times, which is how a reason becomes wallpaper."""
    ranked = _rank([_trend("A", impact=5.0), _trend("B", impact=4.0), _trend("C", impact=3.0)])

    claims = [t for t in ranked if "highest-impact" in t.why]
    assert len(claims) == 1
    assert claims[0].category == "A"


def test_being_late_explains_a_row_and_never_moves_one():
    """If lateness reordered the table, the ranking would become a function of
    how long since you last practised rather than of what is wrong with your
    English — and a fortnight off would silently rewrite it."""
    trends = [_trend("Important", impact=9.0), _trend("Late", impact=1.0)]

    before = [t.category for t in _rank(trends)]
    after = _rank(trends, overdue={"Late": 40})

    assert [t.category for t in after] == before
    assert "overdue" in next(t for t in after if t.category == "Late").flags
    assert "40 days late" in next(t for t in after if t.category == "Late").why


def test_a_frozen_streak_is_carried_as_a_flag():
    ranked = _rank([_trend("Comparatives")], frozen={"Comparatives"})

    assert "frozen" in ranked[0].flags
    assert "absence streak is frozen" in ranked[0].why


# --- the portfolio -------------------------------------------------------------

def test_a_frequent_survivable_error_cannot_own_every_slot():
    """Rule 17. Impact is a good ranking and a bad slate: one very frequent
    polish-tier error legitimately holds several top slots and crowds out
    everything the listener actually loses."""
    trends = [_trend(f"Polish {n}", severity=2, impact=9.0 - n) for n in range(5)]
    trends += [_trend(f"Clarity {n}", severity=4, impact=1.0 - n / 10) for n in range(3)]

    slate = priority.slate(_rank(trends))

    assert sum(1 for t in slate if t.tier == "polish") <= priority.MAX_POLISH
    assert sum(1 for t in slate if t.tier == "clarity") >= priority.MIN_CLARITY


def test_an_empty_tier_leaves_its_slot_empty_rather_than_padding_it():
    """Rule 17 says so, and a padded slate is how a category with nothing behind
    it comes to look like a priority."""
    slate = priority.slate(_rank([_trend("Only one", severity=4, impact=3.0)]))

    assert [t.category for t in slate] == ["Only one"]


def test_a_resolved_pattern_never_takes_a_focus_slot():
    """It belongs in what's working. There is nothing to do about it, and a slot
    is a thing to do."""
    slate = priority.slate(_rank([_trend("Done", ready=True), _trend("Live", impact=0.1)]))

    assert [t.category for t in slate] == ["Live"]


# --- the blockers --------------------------------------------------------------

TODAY = "2026-09-18"


def _ago(days: int, today: str = TODAY) -> str:
    return (date.fromisoformat(today) - timedelta(days=days)).isoformat()


def _loop(measure_days, train_days, today=TODAY):
    """A loop state with each side last touched `n` days ago, or never (None)."""
    sessions = ([practice.PracticeSession(date=_ago(train_days, today), focus="x",
                                          learner_words=200, reproductions=2)]
                if train_days is not None else [])
    dates = [_ago(measure_days, today)] if measure_days is not None else []
    return practice.loop_state(sessions, dates, [], today=today)


def test_a_stopped_treatment_outranks_every_pattern():
    """A perfect ranking acted on by nobody is not a plan, and rule 19's whole
    point is that only the corrected repetitions train."""
    blocking = priority.blockers(unanalysed=[], loop=_loop(1, 30),
                                 attended_sessions=1, asking_sessions=0)

    assert [b.kind for b in blocking] == ["treatment-stopped"]
    assert "30 days since the last corrected repetition" in blocking[0].detail


def test_a_dormant_project_is_not_told_its_loop_is_broken():
    """"The instrument is ahead of the treatment" needs the instrument to be
    running. Telling a fresh clone it is failing is the page's worst available
    failure mode."""
    assert priority.blockers(unanalysed=[], loop=_loop(90, None),
                             attended_sessions=0, asking_sessions=0) == []


def test_the_two_halves_of_one_instruction_are_one_line():
    """"Nothing is being treated" and "no conversation practice has ever been
    recorded" are the same instruction from two directions. Printed as separate
    to-dos, a list of five becomes a list of two facts."""
    blocking = priority.blockers(unanalysed=[], loop=_loop(1, 30),
                                 attended_sessions=0, asking_sessions=4)

    assert len(blocking) == 1
    assert "conversation practice specifically" in blocking[0].detail


def test_an_unread_recording_comes_before_anything_it_would_have_changed():
    blocking = priority.blockers(unanalysed=["2026-09-20"], loop=_loop(1, 1),
                                 attended_sessions=1, asking_sessions=0)

    assert blocking[0].kind == "unanalysed"
    assert "every ranking here predates it" in blocking[0].detail


def test_a_pattern_with_no_rung_three_still_reaches_the_list():
    """Question patterns are kept out of the ranked table because the recording
    cannot measure them. Nothing else on the page would mention them again."""
    blocking = priority.blockers(unanalysed=[], loop=_loop(1, 1),
                                 attended_sessions=1, asking_sessions=0,
                                 dialogue_overdue=[("Softening frames", "2026-08-21")])

    overdue = next(b for b in blocking if b.kind == "overdue-dialogue")
    assert "Softening frames" in overdue.detail
    assert overdue.anchor == "askpatterns"


# --- the loop itself -----------------------------------------------------------

def test_a_practice_session_with_no_repetitions_in_it_is_not_treatment():
    """Rule 19's own failure case. Counting the session would report the loop
    turning on exactly the evidence that it is not."""
    sessions = [practice.PracticeSession(date="2026-09-17", focus="x", learner_words=200,
                                         reproductions=0)]
    state = practice.loop_state(sessions, ["2026-09-17"], [], today="2026-09-18")

    assert state.train.state == "never"
    assert state.measure.state == "ok"


def test_a_date_in_the_future_is_not_evidence_of_recent_work():
    """A clock that was wrong, or a typo. Counted, it reports a loop running
    hard while nothing has been done."""
    state = practice.loop_state([], ["2027-05-01", "2026-09-17"], [], today="2026-09-18")

    assert state.measure.days == 1
    assert state.recordings_in_window == 1


def test_an_empty_schedule_is_nothing_to_be_late_for():
    state = practice.loop_state([], ["2026-09-17"], [], today="2026-09-18")

    assert state.review.state == "ok"
    assert state.review.detail == "nothing overdue"


def test_the_cadence_notices_the_gap_opening():
    """Every history here is per session, which assumes sessions arrive at a
    steady rate. Nothing was measuring whether they do."""
    rhythm = mistakes.cadence(["2026-08-01", "2026-08-02", "2026-08-04", "2026-08-05",
                               "2026-08-12", "2026-08-19", "2026-08-28"])

    assert rhythm.direction == "lengthening"
    assert rhythm.gaps == [1, 2, 1, 7, 7, 9]


def test_a_steady_cadence_is_not_reported_as_a_change():
    rhythm = mistakes.cadence(["2026-08-01", "2026-08-04", "2026-08-07", "2026-08-10",
                               "2026-08-13", "2026-08-16"])

    assert rhythm.direction == "steady"


def test_too_few_gaps_to_have_a_direction():
    assert mistakes.cadence(["2026-08-01", "2026-08-03"]).direction == "n/a"
    assert mistakes.cadence([]).median_gap is None


def test_the_slate_keeps_the_demotion_the_ranking_applied():
    """`slate` re-sorted what `rank` had already ordered, and dropped the thin
    key doing it — so the category demoted for resting on three instances came
    back to the top of the list, where `_actions` makes it the single bolded
    thing to do. The demotion has to survive every step between the ranking and
    the page, not just the first one.
    """
    ranked = _rank([_trend("Rare but serious", severity=5, impact=9.0, thin=True),
                    _trend("Common and solid", severity=4, impact=6.0),
                    _trend("Third", severity=4, impact=5.0)])
    chosen = priority.slate(ranked)

    assert [t.category for t in ranked][0] == "Common and solid"
    assert [t.category for t in chosen][0] == "Common and solid"
    # And the superlative stays on the row it is true of, above the thin one.
    assert "highest-impact" in chosen[0].why


def test_the_slate_never_returns_more_rows_than_it_was_asked_for():
    """The two reserved clarity slots were filled before `size` was consulted,
    so a slate of one came back with two."""
    ranked = _rank([_trend(f"Clarity {n}", severity=4, impact=9.0 - n) for n in range(4)])

    assert len(priority.slate(ranked, size=1)) == 1
