"""
The dashboard — every history in `analysis/` as one page you can look at.

The data this project produces is correct and almost unreadable. A season of
`mistakes.csv` is hundreds of rows; the question it answers ("is this pattern
fading or not?") needs those rows pivoted, normalized by a denominator that
changes every session, and read against a severity judgment stored in a third
place. Done by eye, once a month, that is not a thing anyone keeps doing.

**This module computes nothing.** Every number on the page is produced by the
module that owns the file it came from — `mistakes.summarize` for impact,
direction and absence streaks, `fluency.load_history` for how the recording came
out, `drill.load_history` for the scores that have a denominator. `build_model`
pivots and labels; `render` draws. The rule is deliberate and worth keeping: the
definitions here are subtle (per-1,000 normalization, severity x sqrt(rate) with
recency weights (3,2,1), an absence streak that only explicit zeros extend), they
are already specified and tested in Python, and a second copy of any of them in
JavaScript would drift silently until the page and `python -m voxlib.mistakes`
disagreed about the same question.

Three things the page refuses to draw, each because the honest version is
different from the obvious one:

**An untested cell is a hole, not a zero.** `mistakes.csv` distinguishes "the
structure never came up" (blank) from "it came up and was clean" (0), and a
good share of any history is blank. A heatmap that fills those with the clean
colour reports months of imaginary progress.

**Pace is not one series.** `fluency_history.csv` measures words per minute
against two different denominators — VAD-tight turns under diarization, whisper's
own pause-inclusive segments without it — and the recorded history crosses that
line partway through. One line through both shows a collapse in pace that is
purely a change of instrument, which is why `fluency.HistoryRow.comparable_pace`
exists and why the pace panel is grouped by basis.

**The total mistake rate is partly an artefact of tracking more mistakes.** The
category count grows as coaching finds new patterns — a handful at the start,
several times that later — so the all-categories rate rises even if nothing
about the speaker changes. The page plots it, because it is the real number, and
plots beside it the rate over only the categories tracked since the first
session, which is the one comparable across the whole history.

Output is a single self-contained file under `output/` (already gitignored): data
inlined, charts drawn by hand in SVG, no network at load. Nothing personal
reaches the repo, and the page works offline from `file://` forever.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
from datetime import date as date_type
from datetime import datetime
from pathlib import Path
from typing import Optional

from . import (asking, brief, drill, exposure, fluency, focus_log, level, mistakes,
               opportunity, practice, priority, vocab)
from .dashboard_page import TEMPLATE

logger = logging.getLogger(__name__)

# How many recent sessions the headline compares the latest one against. Three
# is the same window `mistakes._stalled` uses, for the same reason: two sessions
# cannot tell a trend from a bad day.
BASELINE_WINDOW = 3

# The rung definitions and the thresholds behind them moved to `priority.py`
# when the ranking did. This module draws them and no longer decides them, which
# is the rule stated at the top of this file and the one place it was quietly
# broken: `_ladder_state` was a real metric living in the renderer.
MIN_DRILL_ITEMS = priority.MIN_DRILL_ITEMS
FORM_KNOWN_ACCURACY = priority.FORM_KNOWN_ACCURACY
LADDER_STATES = priority.LADDER_STATES

# The page's own words for the rungs and what to do about each. `priority.py`
# keeps the project's terms because the coach reads them with the rules at hand;
# the page is read by a person who has not, and "automaticity gap" or "rung 2"
# tells them nothing.
PLAIN_STATES = {
    "no-drill": "No drill for it yet",
    "thin-evidence": "Too few drill answers yet",
    "form-unreliable": "The rule isn't solid yet",
    "automaticity-gap": "Know the rule, still slip when speaking",
    "clean": "Not heard in your last recording",
    "retiring": "Fixed",
}
PLAIN_ACTIONS = {
    "automaticity-gap": "Practise it in conversation",
    "form-unreliable": "Keep drilling it",
    "no-drill": "Write a drill for it",
    "thin-evidence": "Drill it again",
    "clean": "Keep an eye on it",
    "retiring": "Take it off the list",
}
PLAIN_TIERS = {"clarity": "serious", "polish": "minor"}


def _load_scores(path: Path) -> list[dict]:
    """`scores_history.csv` — the only history no module owns.

    It is written by hand (by the coach, per CLAUDE.md) and read by nothing else,
    so there is no loader to reuse and no shared definition to drift from.
    """
    if not path.exists():
        return []

    def number(raw: str) -> Optional[float]:
        raw = (raw or "").strip()
        try:
            return float(raw) if raw else None
        except ValueError:
            return None

    rows = []
    with path.open("r", encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            rows.append({
                "date": (raw.get("date") or "").strip(),
                "cefr": (raw.get("cefr") or "").strip(),
                "grammar": number(raw.get("grammar_score")),
                "vocabulary": number(raw.get("vocabulary_score")),
                "naturalness": number(raw.get("naturalness_score")),
                "fluency": number(raw.get("fluency_score")),
                "filler_rate": number(raw.get("filler_rate_per_100_words")),
            })
    rows.sort(key=lambda r: r["date"])
    return rows


# The five fields every `## <Mistake>` section in memory.md opens with. Four of
# them are already on the card, computed from the CSV that the prose is a
# retelling of — an `Occurrences:` line listing every session's count is the
# sparkline above it, in words. Only Status carries something the data does not:
# the rule-18 flag and what was decided about it.
_NOTE_FIELD = re.compile(r"^(Status|Occurrences|First seen|Last seen|Severity|Notes"
                         r"|Earlier note retained):\s*(.*)$")
_EXAMPLES_MARKER = re.compile(r"^Typical examples:\s*$")
# `- "wrong" -> "right" (a date)`, optionally with where it came from:
# `(a date, question practice)`. Every bullet on record fits this shape.
_EXAMPLE = re.compile(r'^-\s*"(?P<wrong>.+?)"\s*->\s*"(?P<right>.+?)"'
                      r'\s*(?:\((?P<date>\d{4}-\d\d-\d\d)(?:,\s*(?P<source>[^)]+))?\))?\s*$')
# A paragraph opening in bold is a dated decision — "Rule-18 changed approach,
# <date> — ..." — rather than a description of the mistake.
_DECISION = re.compile(r"^\*\*(?P<title>.+?)\*\*(?P<body>.*)$", re.S)


def _slug(name: str, taken: set[str]) -> str:
    """A stable element id for one pattern, so it can be linked to.

    The page lists every tracked pattern and had no way to point at one of them:
    no anchor, nothing to paste into a note to yourself. Derived from the name
    rather than the position so the link survives a re-ranking, and
    de-duplicated in case two names ever reduce to the same thing.
    """
    base = "pattern-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    slug, suffix = base, 2
    while slug in taken:
        slug, suffix = f"{base}-{suffix}", suffix + 1
    taken.add(slug)
    return slug


def _decision_date(decision: dict) -> str:
    found = re.search(r"\d{4}-\d\d-\d\d", decision["title"])
    return found.group(0) if found else ""


def _parse_note(body: str) -> Optional[dict]:
    """One `## <Mistake>` section of memory.md, taken apart.

    The page used to print this whole block as preformatted text, which was
    wrong in three ways at once: the inline markdown showed as literal asterisks
    and backticks, the worked examples — the only part you could practise from —
    sat in the middle of a long paragraph, and four of the header fields
    repeated numbers already on the card in better form.

    `rest` is the safety net. Anything this does not recognise is kept and
    rendered as prose, so a section written in a shape nobody anticipated loses
    its styling rather than its content.
    """
    if not body or not body.strip():
        return None

    fields: dict[str, str] = {}
    examples: list[dict] = []
    rest: list[str] = []
    decisions: list[dict] = []

    # The header block and the examples list are line-oriented; everything after
    # them is paragraphs. Split at the first blank line that follows a field.
    lines = body.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        field = _NOTE_FIELD.match(stripped)
        if field:
            fields[field.group(1)] = field.group(2).strip()
        elif _EXAMPLES_MARKER.match(stripped):
            pass                       # the bullets below it carry the content
        elif stripped.startswith("- "):
            example = _EXAMPLE.match(stripped)
            if example:
                examples.append({
                    "wrong": example.group("wrong"),
                    "right": example.group("right"),
                    "date": example.group("date") or "",
                    "source": (example.group("source") or "").strip(),
                })
            else:
                # A bullet in some other shape: keep the text, lose the styling.
                rest.append(stripped[2:])
        elif not stripped:
            pass
        else:
            break                      # into the free paragraphs
        index += 1

    remainder = "\n".join(lines[index:]).strip()
    if remainder:
        for paragraph in re.split(r"\n\s*\n", remainder):
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            decision = _DECISION.match(paragraph)
            if decision:
                decisions.append({"title": decision.group("title").strip(),
                                  "body": decision.group("body").strip()})
            else:
                rest.append(paragraph)

    return {
        "status": fields.get("Status", ""),
        "notes": fields.get("Notes", ""),
        "retained": fields.get("Earlier note retained", ""),
        "examples": examples,
        # Newest first: the most recent decision is the one in force. Sorted by
        # the date in the title rather than by position, because the convention
        # in memory.md is to prepend, and a file that ever appends instead would
        # silently show a superseded decision at the top.
        "decisions": sorted(decisions, key=_decision_date, reverse=True),
        "rest": rest,
        # What the card already shows from the CSV, kept out of the rendering but
        # not thrown away, so a future reader can see what was skipped and why.
        "duplicated": {k: v for k, v in fields.items()
                       if k in {"Occurrences", "First seen", "Last seen", "Severity"}},
    }


def _stable_cohort(rows: list[mistakes.SessionRow], dates: list[str]) -> set[str]:
    """Categories tracked in every session on record.

    The only set whose summed rate is comparable across the whole history: it is
    counting the same things at both ends. Everything else mixes a change in the
    speaker with a change in what was being looked for.
    """
    if not dates:
        return set()
    per_date = [{r.category for r in rows if r.date == date} for date in dates]
    return set.intersection(*per_date) if per_date else set()


def _sessions(rows: list[mistakes.SessionRow],
              fluency_rows: list[fluency.HistoryRow]) -> list[dict]:
    """One entry per session date: the rates, the denominator, and how the
    recording that produced them came out."""
    dates = mistakes.session_dates(rows)
    cohort = _stable_cohort(rows, dates)
    recordings = {row.date: row for row in fluency_rows}

    sessions = []
    for date in dates:
        day = [r for r in rows if r.date == date]
        # Constant across a session by construction — `mistakes.record_session`
        # writes the same denominator onto every row it appends.
        reliable = day[0].reliable_words if day else 0
        measured = [r for r in day if r.occurrences is not None]
        occurrences = sum(r.occurrences or 0 for r in day)
        cohort_occurrences = sum(r.occurrences or 0 for r in day if r.category in cohort)
        # The split that decides what to work on, and the one the total hides: a
        # clarity-tier error costs the listener the meaning, a polish-tier one
        # only sounds foreign. A total dominated by a low-severity category can
        # climb steeply while the part that impedes comprehension falls.
        clarity = sum(r.occurrences or 0 for r in day
                      if r.severity >= mistakes.CLARITY_SEVERITY)
        polish = sum(r.occurrences or 0 for r in day
                     if r.severity < mistakes.CLARITY_SEVERITY)
        recording = recordings.get(date)

        def rate(count: int) -> Optional[float]:
            return round(count / reliable * 1000, 2) if reliable > 0 else None

        sessions.append({
            "date": date,
            "reliable_words": reliable,
            "categories_tracked": len(day),
            "categories_measured": len(measured),
            "categories_untested": len(day) - len(measured),
            "occurrences": occurrences,
            "rate": rate(occurrences),
            "cohort_rate": rate(cohort_occurrences),
            "clarity_rate": rate(clarity),
            "polish_rate": rate(polish),
            "clarity_count": clarity,
            "polish_count": polish,
            # Transcript quality, not speech quality. Kept beside the rates
            # because a session where much of the transcript was unreliable is a
            # weaker measurement of everything above, and never mixed into them.
            "low_confidence_share": recording.low_confidence_share if recording else None,
            "mode": (recording.mode or recording.origin) if recording else "",
            "speech_minutes": recording.speech_minutes if recording else None,
        })
    return sessions


def _exposure(mistake_rows: list[mistakes.SessionRow]) -> dict:
    """Whether dividing by words is comparing like with like — see exposure.py."""
    report = exposure.analyse(mistake_rows)
    if report is None:
        return {}
    return {
        "verdict": report.verdict,
        "supports_per_word": report.supports_per_word,
        "length_effect": report.length_effect,
        "within_category": report.mean_within_category,
        "rate_vs_words": report.rate_vs_words,
        "total_vs_categories": report.total_vs_categories,
        "spread": report.spread,
        "narrow": report.spread < 2,
    }


def _delta_drivers(sessions: list[dict], categories: list[dict]) -> list[dict]:
    """Which categories moved the headline rate, and by how much.

    The total rate is the sum of the per-category rates — every category in a
    session divides by the same denominator — so the change in the total really
    is the sum of the per-category changes, and naming the biggest one is
    arithmetic rather than a guess. A blank counts as zero here because that is
    how it counts in the total: an untested category contributed no occurrences
    to the session's count.

    Without this the headline says only that it got worse, and leaves the reader
    to find the cause by hovering every point on a chart.
    """
    if len(sessions) < 2:
        return []
    latest = sessions[-1]["date"]
    baseline = [s["date"] for s in sessions[:-1][-BASELINE_WINDOW:]]
    if not baseline:
        return []

    drivers = []
    for card in categories:
        rates = {point["date"]: point["rate"] or 0.0 for point in card["series"]}
        after = rates.get(latest, 0.0)
        before = sum(rates.get(d, 0.0) for d in baseline) / len(baseline)
        if after != before:
            drivers.append({
                "category": card["category"],
                "before": round(before, 2),
                "after": round(after, 2),
                "change": round(after - before, 2),
            })
    drivers.sort(key=lambda d: -abs(d["change"]))
    return drivers


def _days_between(earlier: str, later: str) -> Optional[int]:
    try:
        return (date_type.fromisoformat(later) - date_type.fromisoformat(earlier)).days
    except ValueError:
        return None


def _headline(sessions: list[dict], scores: list[dict],
              fluency_rows: list[fluency.HistoryRow], cohort_size: int,
              categories: list[dict], unanalysed: list[str], today: str) -> dict:
    """The hero figure and the tiles around it.

    The hero is the latest all-categories rate, compared against the mean of the
    previous `BASELINE_WINDOW` sessions rather than against the single session
    before it — consecutive sessions here differ by a factor of three on nothing
    more than how long the owner happened to talk.
    """
    latest = sessions[-1] if sessions else None
    baseline = [s["rate"] for s in sessions[:-1][-BASELINE_WINDOW:] if s["rate"] is not None]
    baseline_mean = round(sum(baseline) / len(baseline), 2) if baseline else None

    delta = None
    if latest and latest["rate"] is not None and baseline_mean:
        delta = round(latest["rate"] - baseline_mean, 2)

    minutes = sum(r.speech_minutes or 0 for r in fluency_rows)
    directions: dict[str, int] = {}
    for card in categories:
        directions[card["direction"]] = directions.get(card["direction"], 0) + 1
    separable = sum(1 for card in categories if card["separable"])
    return {
        "rate": latest["rate"] if latest else None,
        "rate_date": latest["date"] if latest else None,
        "baseline_mean": baseline_mean,
        "baseline_window": len(baseline),
        "delta": delta,
        "cefr": scores[-1]["cefr"] if scores else "",
        "cefr_since": scores[0]["date"] if scores else "",
        # How much the self-assessed scores have actually moved. Typically very
        # little — and a page that quietly omitted them for being flat would look
        # like it had lost them, so the flatness is stated instead.
        "score_movement": _score_movement(scores),
        "scores": scores[-1] if scores else None,
        "sessions": len(sessions),
        "first_date": sessions[0]["date"] if sessions else "",
        "last_date": sessions[-1]["date"] if sessions else "",
        "speech_minutes": round(minutes, 1) if minutes else None,
        "reliable_words": sum(s["reliable_words"] for s in sessions),
        "cohort_size": cohort_size,
        # What moved the hero number, largest first.
        "drivers": _delta_drivers(sessions, categories),
        "directions": directions,
        "separable": separable,
        # Named, because "1 of 19" under a neutral label reads like a score when
        # the one may be a category getting worse.
        "separable_names": ", ".join(
            f"{c['category']} {c['direction']}" for c in categories if c["separable"]),
        "clarity_rate": sessions[-1]["clarity_rate"] if sessions else None,
        "tracked": len(categories),
        # How long the page has been describing the same evidence, and whether
        # there is a recording sitting in fluency_history.csv that no analysis
        # session has caught up with yet — the pipeline writes that file, the
        # coach writes mistakes.csv, so a date in one and not the other is a
        # transcript nobody has read.
        "days_since_analysis": (_days_between(sessions[-1]["date"], today)
                                if sessions else None),
        "unanalysed": unanalysed,
    }


def _score_movement(scores: list[dict]) -> list[dict]:
    """First value, latest value, and how many distinct values each score has
    taken.

    The coach's own 0-10 judgments are the metric a reader instinctively looks
    for first, and on the history so far they are nearly constant — grammar,
    vocabulary and naturalness have taken exactly one value each across every
    session on record. That is a fact about the granularity of the scale, not
    about the speaker, so it is reported as a count rather than drawn as a line
    chart of a horizontal line.
    """
    if not scores:
        return []
    movement = []
    for key, label in (("cefr", "CEFR"), ("grammar", "Grammar"),
                       ("vocabulary", "Vocabulary"), ("naturalness", "Naturalness"),
                       ("fluency", "Fluency")):
        values = [s[key] for s in scores if s[key] not in (None, "")]
        movement.append({
            "key": key,
            "label": label,
            "first": values[0] if values else None,
            "latest": values[-1] if values else None,
            "distinct": len(set(values)),
        })
    return movement


def _drill_stats(drill_rows: list[drill.HistoryRow]) -> dict[str, dict]:
    """Per-category drill results, split by condition.

    Blocked and mixed are not the same test. In a blocked drill the owner knows
    which pattern is being asked; in a mixed block the drills are interleaved and
    they have to notice which rule applies, which is the condition that predicts
    unprompted speech. Summed together, a strong blocked score hides how little
    mixed evidence there is — on the history so far, two of the three drills have
    exactly one mixed item.
    """
    by_category: dict[str, list[drill.HistoryRow]] = {}
    for row in drill_rows:
        by_category.setdefault(row.category, []).append(row)

    stats = {}
    for category, attempts in by_category.items():
        def totals(rows: list[drill.HistoryRow]) -> dict:
            attempted = sum(r.attempted for r in rows)
            correct = sum(r.correct for r in rows)
            return {
                "attempted": attempted,
                "correct": correct,
                "accuracy": round(correct / attempted, 3) if attempted else None,
            }
        stats[category] = {
            "attempts": len(attempts),
            "items": sum(a.items for a in attempts),
            "last_date": attempts[-1].date,
            "conditions": sorted({a.condition for a in attempts}),
            **totals(attempts),
            "blocked": totals([a for a in attempts if a.condition == drill.BLOCKED]),
            "mixed": totals([a for a in attempts if a.condition == drill.MIXED]),
        }
    return stats


def _categories(rows: list[mistakes.SessionRow], dates: list[str],
                drill_stats: dict[str, dict], notes: dict[str, str]) -> list[dict]:
    """Every tracked category, ranked by impact, with its per-session series.

    `mistakes.summarize` supplies the judgment — impact, direction, streaks —
    and this attaches the three things it does not know about: the session-by-
    session shape of the rate, whatever the drill history says about the same
    category, and the prose from `memory.md` that says what the mistake actually
    looks like.
    """
    trends = mistakes.summarize(rows)
    by_category: dict[str, dict[str, mistakes.SessionRow]] = {}
    for row in rows:
        by_category.setdefault(row.category, {})[row.date] = row

    cards = []
    taken: set[str] = set()
    for trend in trends:
        recorded = by_category.get(trend.category, {})
        first = trend.first_seen
        series = []
        for date in dates:
            if date < first:
                # Before the category was ever tracked. Not an absence: nobody
                # was looking for it, so the series starts here rather than
                # drawing a run of zeros nobody measured.
                series.append({"date": date, "state": "before", "rate": None})
            elif date not in recorded:
                series.append({"date": date, "state": "untested", "rate": None})
            else:
                row = recorded[date]
                if row.occurrences is None:
                    series.append({"date": date, "state": "untested", "rate": None})
                else:
                    series.append({
                        "date": date,
                        "state": "clean" if row.occurrences == 0 else "seen",
                        "rate": row.rate_per_1000,
                        "occurrences": row.occurrences,
                        "reliable_words": row.reliable_words,
                    })

        cards.append({
            "category": trend.category,
            "slug": _slug(trend.category, taken),
            "severity": trend.severity,
            "tier": trend.tier,
            "impact": round(trend.impact, 2),
            "direction": trend.reported_direction,
            "direction_shape": trend.direction,
            "separable": trend.separable,
            "latest_count": trend.latest_count,
            "evidence": trend.evidence,
            "thin": trend.thin,
            "stalled": trend.stalled,
            "absence_streak": trend.absence_streak,
            "untested_since": trend.untested_since,
            "ready_for_improvements": trend.ready_for_improvements,
            "latest_rate": trend.latest_rate,
            "weighted_rate": round(trend.weighted_rate, 2),
            "first_seen": trend.first_seen,
            "last_seen": trend.last_seen,
            "sessions_measured": trend.sessions_measured,
            "total_occurrences": trend.total_occurrences,
            "series": series,
            # The only accuracy on the page with a known denominator — the
            # recording can say how often a form went wrong, never how often it
            # was tried.
            "drill": drill_stats.get(trend.category),
            "note": _parse_note(notes.get(trend.category, "")),
        })
    return cards


# What each speech metric means and which way is better. Taken from
# `fluency.py`'s module docstring rather than guessed: the filler rate is a lower
# bound because whisper drops hesitations before we see the text, and the
# discourse-marker rate can be a far larger habit than the fillers — which is the
# only reason a falling marker rate is worth a chart of its own rather than a
# column in a table.
SPEECH_METRICS = [
    {
        "key": "filler_rate", "label": "Um / uh sounds", "unit": "per 100 words",
        "decimals": 2,
        "note": "um / uh / erm. The transcriber drops some of them, so the real number is "
                "a bit higher. Lower is better.",
    },
    {
        "key": "marker_rate", "label": "\u201cYou know\u201d / \u201cI mean\u201d",
        "unit": "per 100 words", "decimals": 2,
        "note": "\u201cyou know\u201d, \u201cI mean\u201d, \u201ckind of\u201d and "
                "similar filler phrases \u2014 often a far larger habit than the filler "
                "sounds. Lower is better.",
    },
    {
        "key": "median_pause", "label": "Median pause", "unit": "seconds",
        "decimals": 2,
        "note": "The typical gap between your sentences.",
    },
    {
        "key": "long_pause_rate", "label": "Pauses over 2s", "unit": "per minute of speech",
        "decimals": 2,
        "note": "Long pauses per minute of speaking. Lower is better.",
    },
]

# Metrics computed from line timings, which mean something different when
# another voice is present: the gap between two of the owner's lines in a
# diarized recording is mostly the other person talking. `fluency._pause_stats`
# therefore records them for solo recordings only, and a blank here is that
# decision rather than a measurement that went missing.
SOLO_ONLY_METRICS = {"median_pause", "long_pause_rate"}


def _speech(rows: list[fluency.HistoryRow]) -> dict:
    """
    How the speech itself came out, per session, and how much of it was
    measurable.

    Pace is grouped by `speech_time_basis` and never joined across it. The two
    bases put the same speaker at very different figures — diarization hands over
    VAD-tight turns while whisper's own segments swallow the pauses inside them —
    and a history can cross that line partway through. A single line drawn
    through both shows a collapse in pace that never happened.

    The backfilled sessions are the other trap: they wrote `0.0` for speech
    minutes and words per minute because there was no clock to measure them
    with, so a chart that trusts the column plots three sessions of total
    silence. They are excluded by having no basis at all.
    """
    sessions = []
    for row in rows:
        pauses_measured = row.long_pauses is not None and bool(row.speech_minutes)
        sessions.append({
            "date": row.date,
            "mode": row.mode or row.origin,
            "origin": row.origin,
            "files": row.files,
            "total_lines": row.total_lines,
            "low_confidence_lines": row.low_confidence_lines,
            "line_share": row.low_confidence_share,
            # The share to act on. `warn_if_unreliable` fires on this one and not
            # on the line share, because a two-word "Yeah." weighs as much as a
            # full sentence by line, and short backchannels are exactly where
            # whisper is least confident.
            "word_share": row.low_confidence_word_share,
            "total_words": row.total_words,
            "reliable_words": row.reliable_words,
            "speech_minutes": row.speech_minutes,
            "wpm": row.words_per_minute if row.comparable_pace else None,
            "basis": row.speech_time_basis,
            "filler_count": row.filler_count,
            "filler_rate": row.fillers_per_100_words,
            "marker_count": row.discourse_marker_count,
            "marker_rate": row.discourse_markers_per_100_words,
            "median_pause": row.median_pause_sec,
            "long_pauses": row.long_pauses,
            "long_pause_rate": (round(row.long_pauses / row.speech_minutes, 2)
                                if pauses_measured else None),
            "unreliable": (row.low_confidence_word_share is not None
                           and row.low_confidence_word_share >= fluency.LOW_CONFIDENCE_WARN_SHARE),
        })

    bases = [b for b in (fluency.VAD_BASIS, fluency.SEGMENT_BASIS)
             if any(s["basis"] == b for s in sessions)]
    labels = {
        fluency.VAD_BASIS: "Recordings with other people",
        fluency.SEGMENT_BASIS: "Solo recordings",
    }
    # One key per basis, blank everywhere else, so the line simply stops at the
    # change of instrument instead of stepping across it.
    pace_rows = [{
        "date": s["date"],
        **{f"wpm_{b}": (s["wpm"] if s["basis"] == b else None) for b in bases},
        "speech_minutes": s["speech_minutes"],
        "reliable_words": s["reliable_words"],
        "basis": s["basis"],
    } for s in sessions]

    return {
        "sessions": sessions,
        "pace": {
            "rows": pace_rows,
            "series": [{"key": f"wpm_{b}", "basis": b, "label": labels[b],
                        "measured": sum(1 for s in sessions if s["basis"] == b)}
                       for b in bases],
            "unmeasured": sum(1 for s in sessions if not s["basis"]),
        },
        "metrics": [{
            **metric,
            "solo_only": metric["key"] in SOLO_ONLY_METRICS,
            "points": [{"date": s["date"], "value": s[metric["key"]]} for s in sessions],
        } for metric in SPEECH_METRICS],
        "warn_share": fluency.LOW_CONFIDENCE_WARN_SHARE,
        "long_pause_sec": fluency.LONG_PAUSE_SEC,
        "any_unreliable": any(s["unreliable"] for s in sessions),
    }


# How few runs a dimension needs before a per-group score is noise. The
# scenario history has seven runs across seven distinct registers and seven
# distinct functions — one run each — so a chart grouped by either would be a
# row of bars with a denominator of one apiece.
MIN_RUNS_TO_GROUP = 3


def _grouped_scenarios(runs: list[asking.ScenarioRun], field: str) -> list[dict]:
    """Scenario results grouped by one of their dimensions, with the count kept.

    The count is the point. Whether "manager register" is a weak spot is not
    answerable from one run in it, and the page says so rather than drawing the
    bar anyway.
    """
    groups: dict[str, list[asking.ScenarioRun]] = {}
    for run in runs:
        groups.setdefault(getattr(run, field) or "\u2014", []).append(run)
    out = [{
        "name": name,
        "runs": len(group),
        "met": sum(r.criteria_met for r in group),
        "total": sum(r.criteria_total for r in group),
        "enough": len(group) >= MIN_RUNS_TO_GROUP,
    } for name, group in groups.items()]
    out.sort(key=lambda g: (g["met"] / g["total"] if g["total"] else 1, -g["runs"]))
    return out


def _asking_mode(scenario_runs: list[asking.ScenarioRun], drill_stats: dict[str, dict],
                 sessions: list[practice.PracticeSession], memory: asking.AskingMemory) -> dict:
    """
    Question practice — the half of this project the recording cannot measure.

    A recording can be scored for grammar because the sentences are there to
    read. Whether the owner asked a good question is not in the transcript at
    all: it needs a situation, a reply that withholds something, and criteria
    written in advance. So this panel has no rung 3 and never will, and the
    thing to be careful about instead is the denominator — every score here is
    small enough that it has to be shown next to the number it divides.
    """
    by_date: dict[str, list[asking.ScenarioRun]] = {}
    for run in scenario_runs:
        by_date.setdefault(run.date, []).append(run)

    failures: dict[str, list[str]] = {}
    for run in scenario_runs:
        for criterion in run.failed:
            failures.setdefault(criterion, []).append(run.scenario)

    drills = sorted(
        ({"category": category, **stat} for category, stat in drill_stats.items()),
        key=lambda d: (-(d["items"] - d["attempted"]), d["category"]),
    )
    ask_sessions = [s for s in sessions if s.mode == practice.ASK_MODE]

    return {
        "runs": [{
            "date": run.date, "scenario": run.scenario, "pack": run.pack,
            "register": run.register, "function": run.function,
            "met": run.criteria_met, "total": run.criteria_total,
            "failed": run.failed, "clean": run.clean,
        } for run in scenario_runs],
        "totals": {
            "runs": len(scenario_runs),
            "met": sum(r.criteria_met for r in scenario_runs),
            "total": sum(r.criteria_total for r in scenario_runs),
        },
        "by_date": [{
            "date": date,
            "runs": len(group),
            "met": sum(r.criteria_met for r in group),
            "total": sum(r.criteria_total for r in group),
        } for date, group in sorted(by_date.items())],
        # The one dimension with repeats: the same criterion fails across
        # different scenarios, which is what makes it a pattern rather than a
        # property of one situation.
        "criteria": sorted(({"criterion": name, "count": len(scenarios),
                             "scenarios": scenarios} for name, scenarios in failures.items()),
                           key=lambda c: (-c["count"], c["criterion"])),
        "registers": _grouped_scenarios(scenario_runs, "register"),
        "functions": _grouped_scenarios(scenario_runs, "function"),
        "min_runs_to_group": MIN_RUNS_TO_GROUP,
        "drills": drills,
        "drill_totals": {
            "items": sum(d["items"] for d in drills),
            "attempted": sum(d["attempted"] for d in drills),
            "correct": sum(d["correct"] for d in drills),
        },
        "practice": [{
            "date": s.date, "focus": s.focus, "words": s.learner_words,
            "errors": s.errors, "rate": s.rate_per_1000,
            "reproductions": s.reproductions, "long_turns": s.long_turns,
            "breakdown": sorted(({"category": c, "count": n}
                                 for c, n in s.errors_by_category.items()
                                 if not practice.is_provisional(c)),
                                key=lambda e: -e["count"]),
            "notes": s.notes,
        } for s in ask_sessions],
        "practice_totals": {
            "sessions": len(ask_sessions),
            "words": sum(s.learner_words for s in ask_sessions),
            "errors": sum(s.errors for s in ask_sessions),
            "reproductions": sum(s.reproductions for s in ask_sessions),
        },
        # Forms corrected in a session that no tracked category covers. Two
        # sessions with the same one earns it a category and a drill.
        "provisional": [{
            "name": form.name, "sessions": form.sessions, "total": form.total,
            "first_seen": form.first_seen, "last_seen": form.last_seen,
            "ready": form.ready_to_promote,
        } for form in practice.provisional_trends(sessions)],
        "promote_after": practice.SESSIONS_TO_PROMOTE,
        "patterns": [{
            "name": pattern.name, "status": pattern.status,
            "sessions_with_error": pattern.sessions_with_error,
            "last_error": pattern.last_error, "note": pattern.note,
        } for pattern in memory.patterns],
        "register_notes": memory.register_notes,
        "worst": memory.worst.name if memory.worst else "",
    }


def _timeline(sessions: list[dict], speech: list[dict],
              practice_sessions: list[practice.PracticeSession],
              scenario_runs: list[asking.ScenarioRun],
              reports: dict[str, str]) -> list[dict]:
    """
    Every dated thing in the project, newest first.

    The union of recording dates and practice dates rather than just the
    recordings: practice happens on days with no recording, and a chronology
    that dropped those would suggest nothing was done on them.
    """
    speech_by_date = {row["date"]: row for row in speech}
    mistakes_by_date = {row["date"]: row for row in sessions}
    practice_by_date: dict[str, list[practice.PracticeSession]] = {}
    for session in practice_sessions:
        practice_by_date.setdefault(session.date, []).append(session)
    scenarios_by_date: dict[str, list[asking.ScenarioRun]] = {}
    for run in scenario_runs:
        scenarios_by_date.setdefault(run.date, []).append(run)

    dates = set(mistakes_by_date) | set(speech_by_date) | set(practice_by_date)
    dates |= set(scenarios_by_date)

    entries = []
    for date in sorted(dates, reverse=True):
        recording = mistakes_by_date.get(date)
        quality = speech_by_date.get(date)
        drilled = practice_by_date.get(date, [])
        runs = scenarios_by_date.get(date, [])
        entries.append({
            "date": date,
            "report": reports.get(date, ""),
            "recording": bool(recording or quality),
            "mode": quality["mode"] if quality else "",
            "reliable_words": recording["reliable_words"] if recording else (
                quality["reliable_words"] if quality else None),
            "rate": recording["rate"] if recording else None,
            "word_share": quality["word_share"] if quality else None,
            "practice_sessions": len(drilled),
            "practice_modes": sorted({s.mode for s in drilled}),
            "practice_words": sum(s.learner_words for s in drilled),
            "scenarios": len(runs),
            "scenario_met": sum(r.criteria_met for r in runs),
            "scenario_total": sum(r.criteria_total for r in runs),
        })
    return entries


def _vocabulary(analysis_dir: Path) -> dict:
    """Whether the phrases the coach retired are actually going away.

    Computed from the archive rather than read back from `vocab_history.csv`,
    for the same reason the level line is: the table in memory.md changes
    between sessions, and a file written before the last edit describes a
    different table.
    """
    substitutions = vocab.parse_substitutions(analysis_dir / "memory.md")
    counts = vocab.measure_history(analysis_dir / "sessions", substitutions)
    if not counts:
        return {"rows": []}

    trends = {(t.phrase, t.kind): t for t in vocab.summarize(counts)}
    dates = sorted({c.date for c in counts})

    rows = []
    for substitution in substitutions:
        retired = trends.get((substitution.phrase, "retired"))
        if not retired or not retired.total:
            continue
        rows.append({
            "phrase": substitution.phrase,
            "movement": retired.movement,
            "counts": retired.counts,
            "total": retired.total,
            "early": retired.early,
            "late": retired.late,
            "replacements": [{
                "phrase": r,
                "counts": trends[(r, "replacement")].counts,
                "total": trends[(r, "replacement")].total,
                "movement": trends[(r, "replacement")].movement,
            } for r in substitution.replacements
                if (r, "replacement") in trends and trends[(r, "replacement")].total],
        })
    # Worst first: a retired phrase still rising is the one to look at.
    order = {"rising": 0, "level": 1, "falling": 2, "too few to tell": 3, "never said": 4}
    rows.sort(key=lambda r: (order.get(r["movement"], 9), -r["total"]))

    return {
        "rows": rows,
        "dates": dates,
        "never_said": [s.phrase for s in substitutions
                       if not (trends.get((s.phrase, "retired"))
                               and trends[(s.phrase, "retired")].total)],
        "tracked": len(substitutions),
    }


def _level(analysis_dir: Path) -> tuple[dict, list]:
    """The sub-band level line, recomputed rather than read back.

    `level.gather` is called here for the same reason `mistakes.summarize` is:
    the page must never be able to disagree with the CLI. Reading
    `level_history.csv` instead would show whatever was last written, which is
    stale the moment a threshold moves or a session is analysed without
    `--write` being run.

    It needs `lexis_history.csv` for the range dimension, and that file is
    written by `python -m voxlib.lexis --write`. Without it, range reads as
    unmeasured and the page says so rather than quietly scoring three
    dimensions as four.
    """
    readings = level.gather(analysis_dir)
    if not readings:
        return {"readings": [], "scale": level.SCALE}, []

    latest = readings[-1]
    target = (None if latest.level is None
              else min(max(latest.level, 0) + 1, len(level.SCALE) - 1))

    dimensions = []
    for dimension in level.DIMENSIONS:
        rung = latest.dimension_rungs[dimension.key]
        measures = []
        for measure in dimension.measures:
            value = latest.values.get(measure.key)
            threshold = None if target is None else measure.thresholds[target]
            measures.append({
                "key": measure.key,
                "label": measure.label,
                "unit": measure.unit,
                "note": measure.note,
                "value": value,
                "rung": latest.measure_rungs[measure.key],
                "rung_label": level.label(latest.measure_rungs[measure.key]),
                "threshold": threshold,
                "lower_is_better": measure.lower_is_better,
                "met": None if value is None or threshold is None else (
                    value <= threshold if measure.lower_is_better else value >= threshold),
                # How far along the way to the next rung, as a share. Monotonic
                # in the right direction for both polarities, and exactly 1 when
                # the threshold is cleared.
                "progress": None if value is None or threshold is None or not value else (
                    min(1.0, round(threshold / value, 3)) if measure.lower_is_better
                    else min(1.0, round(value / threshold, 3))),
            })
        dimensions.append({
            "key": dimension.key,
            "label": dimension.label,
            "note": dimension.note,
            "rung": rung,
            "rung_label": level.label(rung),
            "blocking": dimension.key in latest.blockers,
            "measures": measures,
        })

    return {
        "scale": level.SCALE,
        "below_scale": level.BELOW_SCALE,
        "calibration": level.CALIBRATION,
        "promotion_sessions": level.PROMOTION_SESSIONS,
        "min_dimensions": level.MIN_MEASURED_DIMENSIONS,
        "interaction_max_age_days": level.INTERACTION_MAX_AGE_DAYS,
        "readings": [{
            "date": r.date,
            "rung": r.rung,
            "rung_label": r.session_label,
            "level": r.level,
            "level_label": r.label,
            "reliable": r.reliable,
            "provisional": r.provisional,
            "blockers": r.blockers,
        } for r in readings],
        "current": {
            "label": latest.label,
            "index": latest.level,
            "session_label": latest.session_label,
            "session_index": latest.rung,
            "provisional": latest.provisional,
            "blockers": latest.blockers,
            "measured": sum(1 for v in latest.dimension_rungs.values() if v is not None),
            "dimensions_total": len(level.DIMENSIONS),
        },
        "target": None if target is None else {"index": target, "label": level.SCALE[target]},
        "dimensions": dimensions,
        # The floor rising is a real finding that the level line alone hides: it
        # sat at B1+ throughout while the worst single session went from B1 to
        # B1+ and stayed there.
        "floor": _level_floor(readings),
    }, readings


def _level_floor(readings: list) -> Optional[dict]:
    """The worst session reading, and how long since anything was that low.

    A level held steady by hysteresis looks like nothing happening. The lowest
    single-session reading moving up is the same evidence saying otherwise.
    """
    scored = [r for r in readings if r.rung is not None and r.reliable]
    if len(scored) < 4:
        return None
    worst = min(r.rung for r in scored)
    last_at_worst = max(r.date for r in scored if r.rung == worst)
    since = [r for r in scored if r.date > last_at_worst]
    if not since:
        return None
    return {
        "worst": worst,
        "worst_label": level.label(worst),
        "last_at_worst": last_at_worst,
        "sessions_since": len(since),
        "floor_since": min(r.rung for r in since),
        "floor_since_label": level.label(min(r.rung for r in since)),
    }


def _ladder(cards: list[dict], drill_stats: dict[str, dict],
            sessions: list[practice.PracticeSession], focus: dict[str, focus_log.FocusRow],
            today: str) -> dict:
    """
    The three rungs side by side, per pattern.

    CLAUDE.md already names them — `drills.csv` is the only score with a real
    denominator, `practice_history.csv` is "the rung between knows the form and
    produces it unmonitored", `mistakes.csv` is the unmonitored one — but nothing
    in the project has ever shown them together, so the question they answer
    between them could not be asked: *where* does a pattern break down? A form
    drilled to 100% that still appears in every recording is not a knowledge
    problem and more drilling will not fix it. A form never drilled at all
    cannot be diagnosed at any rung above it.

    Rung 2 is read per mode and never pooled. `practice_rates` explains why: an
    asking session contributes words to the denominator while contributing
    nothing most grammar categories could appear in, so one rate over both modes
    understates every one of them.
    """
    answer_rates = practice.practice_rates(sessions, mode=practice.ANSWER_MODE)
    ask_rates = practice.practice_rates(sessions, mode=practice.ASK_MODE)
    ask_counts: dict[str, int] = {}
    for session in sessions:
        if session.mode != practice.ASK_MODE:
            continue
        for category, count in session.errors_by_category.items():
            if not practice.is_provisional(category):
                ask_counts[category] = ask_counts.get(category, 0) + count

    answer_words = sum(s.learner_words for s in sessions
                       if s.mode == practice.ANSWER_MODE)

    rows = []
    for card in cards:
        category = card["category"]
        stat = drill_stats.get(category)
        schedule = focus.get(category)
        rows.append({
            "category": category,
            "slug": card["slug"],
            "severity": card["severity"],
            "tier": card["tier"],
            "impact": card["impact"],
            "state": priority.ladder_state(
                ready_for_improvements=card["ready_for_improvements"],
                latest_rate=card["latest_rate"], drill=stat),
            # Rung 1 — knows the form. Mixed is reported separately because it is
            # the harder condition and the one with almost no data.
            "drill": stat,
            # Rung 2 — produces it while attending to it.
            "attended_rate": answer_rates.get(category),
            "attended_in_asking": ask_counts.get(category),
            "asking_rate": ask_rates.get(category),
            # Rung 3 — produces it unmonitored.
            "speech_rate": card["latest_rate"],
            "speech_count": card["latest_count"],
            "evidence": card["evidence"],
            "thin": card["thin"],
            "speech_weighted": card["weighted_rate"],
            "direction": card["direction"],
            "separable": card["separable"],
            "stalled": card["stalled"],
            "absence_streak": card["absence_streak"],
            "untested_since": card["untested_since"],
            "last_seen": card["last_seen"],
            "last_drilled": schedule.last_drilled if schedule else "",
            "streak": schedule.streak if schedule else None,
            "next_due": schedule.next_due if schedule else "",
            "overdue": bool(schedule and schedule.next_due and schedule.next_due < today),
        })

    counts: dict[str, int] = {}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1

    # Patterns on the spaced-repetition schedule that the recording cannot
    # measure at all: question-asking is not a grammar category, so these have a
    # rung 1 and a rung 2 and no rung 3, and putting them in the table above
    # would give them a column of permanent blanks.
    tracked = {card["category"] for card in cards}
    dialogue_only = [{
        "category": row.category,
        "last_drilled": row.last_drilled,
        "streak": row.streak,
        "next_due": row.next_due,
        "overdue": bool(row.next_due and row.next_due < today),
    } for row in focus.values() if row.category not in tracked]

    return {
        "rows": rows,
        "states": counts,
        "state_labels": PLAIN_STATES,
        "dialogue_only": dialogue_only,
        "today": today,
        # Whether rung 2 has any measurement at all. Every practice session on
        # record is a question-practice one, so for grammar categories the middle
        # rung is empty — which is itself the finding, and a blank column that
        # said nothing about why would read as a bug.
        "attended_sessions": sum(1 for s in sessions if s.mode == practice.ANSWER_MODE),
        "attended_words": answer_words,
        "asking_sessions": sum(1 for s in sessions if s.mode == practice.ASK_MODE),
    }


def _loop(state: practice.LoopState, dates: list[str]) -> dict:
    """
    Whether the loop is turning — the question this page could not ask.

    Every other panel measures the English. This one measures the *process*, and
    on the history that prompted it the two say opposite things: recordings have
    continued every seven to nine days while the last corrected repetition was a
    month earlier and every row of the schedule is past its date. The page's
    freshness indicator read "last analysed 1 day ago", which is true and reads
    as health.

    Rule 19 is the whole reason this belongs at the top rather than in a corner:
    the recording is the instrument and only the corrected repetitions train, so
    a page that leads with the measurement while the treatment has stopped is
    reporting on the half that cannot improve anything.

    Takes the state rather than building one. `priority.blockers` needs the same
    reading to decide whether the treatment side has stopped, and two
    constructions from the same inputs are two things that can drift apart —
    the strip could say the loop was running while the action list said it was
    not, and nothing would have been wrong with either.
    """
    rhythm = mistakes.cadence(dates)
    return {
        "today": state.today,
        "sides": [{
            "key": side.key, "label": side.label, "last": side.last,
            "days": side.days, "state": side.state, "detail": side.detail,
        } for side in state.sides],
        "worst": state.worst.key,
        "running": all(side.running for side in state.sides),
        "instrument_ahead": state.instrument_ahead,
        "window_days": state.window_days,
        "recordings_in_window": state.recordings_in_window,
        "sessions_in_window": state.sessions_in_window,
        "repetitions_in_window": state.repetitions_in_window,
        "missed_in_window": state.missed_in_window,
        "warn_days": practice.LOOP_WARN_DAYS,
        "stale_days": practice.LOOP_STALE_DAYS,
        "cadence": {
            "gaps": rhythm.gaps,
            "median": rhythm.median_gap,
            "recent": rhythm.recent_median,
            "direction": rhythm.direction,
        },
    }


def _opportunity(analysis_dir: Path, frames_dir: Path,
                 mistake_rows: list[mistakes.SessionRow]) -> dict:
    """How many chances each mistake had, and whether that denominator earned
    its place — see `opportunity.py` and `exposure.compare_denominators`.

    Recomputed from the archive rather than read back from
    `opportunity_history.csv`, for the same reason the level line and the
    vocabulary counts are: a file written before the last frame edit describes
    different frames, and the page must never be able to disagree with the CLI.
    """
    frames = opportunity.load_frames(frames_dir)
    if not frames:
        return {"frames": 0, "rows": [], "adopted": []}

    counts = opportunity.count(analysis_dir / "sessions", frames)
    scores = opportunity.accuracy(counts, mistake_rows, frames)
    verdicts = {v.category: v for v in exposure.compare_denominators(mistake_rows, counts)}

    rows = []
    for score in scores:
        verdict = verdicts.get(score.category)
        rows.append({
            "category": score.category,
            "note": score.note,
            "opportunities": score.opportunities,
            "errors": score.errors,
            "accuracy": score.accuracy,
            "sessions": score.sessions,
            "enough": score.enough,
            "frozen": score.frozen,
            "series": score.series,
            "adopted": bool(verdict and verdict.prefer_opportunities),
            "verdict": verdict.verdict if verdict else "",
            "r_words": verdict.r_words if verdict else None,
            "r_opportunities": verdict.r_opportunities if verdict else None,
        })
    rows.sort(key=lambda r: (not r["adopted"], -(r["opportunities"] or 0)))
    return {
        "frames": len(frames),
        "rows": rows,
        "adopted": [r["category"] for r in rows if r["adopted"]],
        "frozen": [r["category"] for r in rows if r["frozen"]],
        "min_opportunities": opportunity.MIN_OPPORTUNITIES,
        "min_sessions": opportunity.MIN_SESSIONS,
    }


def _progress(sessions: list[dict], level_model: dict) -> dict:
    """"Am I better than when I started?" — the comparison the page never made.

    The all-categories rate cannot answer it. It is the sum of the per-category
    rates and the number of categories grows as coaching finds them: on the
    history that prompted this, the polish-tier rate went 0.00 to 11.59 without
    the speaker changing at all, because no polish category existed on day one.

    The day-one cohort can answer it, counts the same things at both ends, and
    was already computed — it appeared only as a column inside a table view
    nobody opens. So all three series are compared over the same windows and the
    cohort one is the one labelled as the answer.
    """
    if len(sessions) < BASELINE_WINDOW * 2:
        return {"comparable": False, "window": BASELINE_WINDOW, "sessions": len(sessions)}

    early, late = sessions[:BASELINE_WINDOW], sessions[-BASELINE_WINDOW:]

    def mean(rows: list[dict], key: str) -> Optional[float]:
        values = [r[key] for r in rows if r[key] is not None]
        return round(sum(values) / len(values), 2) if values else None

    series = []
    for key, label, note in (
        ("clarity_rate", "Serious mistakes",
         "the ones where a listener can lose your meaning"),
        ("cohort_rate", "Same checklist as day one",
         "only the mistakes tracked since your first recording, counted the same way at "
         "both ends, so it's the fair before-and-after comparison"),
        ("rate", "Everything tracked",
         "not a fair comparison: it goes up whenever a new mistake type is added to the list"),
    ):
        before, after = mean(early, key), mean(late, key)
        series.append({
            "key": key, "label": label, "note": note,
            "before": before, "after": after,
            "change": (None if before is None or after is None
                       else round(after - before, 2)),
            # Better means lower for every one of these.
            "better": (None if before is None or after is None else after < before),
        })

    readings = level_model.get("readings", [])
    return {
        "comparable": True,
        "window": BASELINE_WINDOW,
        "sessions": len(sessions),
        "from_date": early[0]["date"],
        "to_date": late[-1]["date"],
        "days": _days_between(early[0]["date"], late[-1]["date"]),
        "series": series,
        "level_from": readings[0]["level_label"] if readings else "",
        "level_to": readings[-1]["level_label"] if readings else "",
        "level_moved": bool(readings and readings[0]["level_label"] != readings[-1]["level_label"]),
    }


def _treatment(drill_rows: list[drill.HistoryRow],
               practice_sessions: list[practice.PracticeSession]) -> list[dict]:
    """Every date on which something was actually trained, for the trend chart.

    The page had a chart of what happened and no record of what was done, on any
    shared axis, so the one question the whole project exists to answer — is the
    practice changing the speech? — could not even be looked at. These are the
    marks that put the two together.

    Association, never proof. Twelve sessions, a recording mode that changed
    partway, and no controlled anything: the chart's job is to let a pattern be
    noticed, and the caption's job is to say that noticing is all it is.
    """
    events: dict[str, dict] = {}
    for row in drill_rows:
        event = events.setdefault(row.date, {"date": row.date, "drills": 0, "items": 0,
                                             "sessions": 0, "repetitions": 0, "missed": 0})
        event["drills"] += 1
        event["items"] += row.attempted
    for session in practice_sessions:
        event = events.setdefault(session.date, {"date": session.date, "drills": 0, "items": 0,
                                                 "sessions": 0, "repetitions": 0, "missed": 0})
        event["sessions"] += 1
        event["repetitions"] += session.reproductions
        event["missed"] += session.reproductions_missed
    # Only the repetitions are treatment (rule 19); a drill is a measurement of
    # the form. Both are drawn, weighted differently, and the distinction is
    # what stops a run of drills reading as a month of training.
    for event in events.values():
        event["treatment"] = event["repetitions"] > 0
    return sorted(events.values(), key=lambda e: e["date"])


def _reports(analysis_dir: Path, out_dir: Optional[Path]) -> dict[str, str]:
    """Date -> a link to that session's archived report, where one exists.

    Relative to wherever the page is being written, because both that and the
    analysis directory are command-line arguments. Without an output directory
    there is nothing to be relative to, so the timeline simply carries no links
    rather than guessing at a path that would 404.
    """
    directory = analysis_dir / "sessions"
    if out_dir is None or not directory.is_dir():
        return {}
    links = {}
    for report in sorted(directory.glob("*.md")):
        date = report.stem
        if len(date) == 10 and date.count("-") == 2:
            try:
                links[date] = os.path.relpath(report, out_dir)
            except ValueError:
                return {}          # different drives on Windows: no relative path exists
    return links


# How many actions the page leads with. A to-do list long enough to need
# prioritising is one nobody works through, and everything on it is also
# reachable in the section it points at.
MAX_ACTIONS = 5


def _whats_working(ladder: dict, categories: list[dict], speech: dict,
                   asking_model: dict) -> list[dict]:
    """
    The counterpart of the action list, and the harder half to get right.

    Everything else on this page is problem-facing — a hero number that has
    risen five sessions running, five things to fix, a grid of errors — and it
    is meant to be opened every week for months. A page that only ever reports
    failure is one you stop opening, while some of the tracked patterns are in
    fact improving.

    So: nothing invented, nothing rounded in a flattering direction, and no
    entry at all when the data does not support one. An empty list renders as no
    block rather than as encouragement.
    """
    wins: list[dict] = []
    rows = ladder.get("rows", [])

    retiring = [r for r in rows if r["state"] == "retiring"]
    if retiring:
        wins.append({
            "kind": "retiring",
            "title": f"{len(retiring)} mistake{'' if len(retiring) == 1 else 's'} fixed",
            "detail": ", ".join(f"{r['category']} (none in your last {r['absence_streak']} "
                                "recordings)" for r in retiring[:2]),
            "anchor": "patterns",
        })

    # Only the ones whose improvement is bigger than counting noise. Before this
    # test the line read "8 of 19 improving" on differences of a single instance,
    # which is encouragement rather than a measurement.
    improving = [c for c in categories if c["direction"] == "improving"]
    if improving:
        wins.append({
            "kind": "improving",
            "title": f"{len(improving)} of {len(categories)} mistakes are clearly "
                     "improving",
            "detail": "The biggest: "
                      + ", ".join(c["category"] for c in improving[:3]),
            "anchor": "patterns",
        })
    leaning = [c for c in categories
               if c["direction_shape"] == "improving" and not c["separable"]]
    if leaning and not improving:
        wins.append({
            "kind": "leaning",
            "title": f"{len(leaning)} more are heading the right way",
            "detail": "Too early to be sure, but going down: "
                      + ", ".join(c["category"] for c in leaning[:3]),
            "anchor": "patterns",
        })

    # A form that holds up under test, on enough items to mean it. Not the same
    # claim as producing it unmonitored — that is what the third rung is for.
    known = [r for r in rows if r["drill"]
             and r["drill"]["attempted"] >= MIN_DRILL_ITEMS
             and (r["drill"]["accuracy"] or 0) >= FORM_KNOWN_ACCURACY]
    if known:
        wins.append({
            "kind": "form-known",
            "title": f"{len(known)} rule{'' if len(known) == 1 else 's'} you get right in "
                     "drills",
            "detail": ", ".join(f"{r['category']} "
                                f"({r['drill']['correct']}/{r['drill']['attempted']})"
                                for r in known[:3]),
            "anchor": "patterns",
        })

    by_date = asking_model.get("by_date", [])
    if len(by_date) >= 2:
        first, last = by_date[0], by_date[-1]
        before = first["met"] / first["total"] if first["total"] else 0
        after = last["met"] / last["total"] if last["total"] else 0
        if after > before:
            wins.append({
                "kind": "asking",
                "title": "Question practice is going better",
                "detail": f"{last['met']} of {last['total']} goals met on {last['date']}, "
                          f"up from {first['met']} of {first['total']} on {first['date']}",
                "anchor": "asking",
            })

    for metric in speech.get("metrics", []):
        measured = [p for p in metric["points"] if p["value"] is not None]
        if len(measured) < 3 or metric["key"] in SOLO_ONLY_METRICS:
            continue
        # First against last, with nothing in between and no noise test, called
        # 2.10 -> 2.09 a win — the flattering-direction claim this function's
        # docstring forbids, while the entry above it is separability-gated for
        # exactly that reason. Compared as windows, and only past a margin: the
        # same 25% the rate directions use in `mistakes._direction`.
        window = min(BASELINE_WINDOW, len(measured) // 2)
        before = sum(p["value"] for p in measured[:window]) / window
        after = sum(p["value"] for p in measured[-window:]) / window
        if before and after < before * (1 - mistakes.STALL_IMPROVEMENT):
            wins.append({
                "kind": "speech",
                "title": f"{metric['label']} are down",
                "detail": f"{round(before, 2)} \u2192 {round(after, 2)} {metric['unit']}, "
                          f"your first {window} recording{'' if window == 1 else 's'} "
                          f"against your last {window}",
                "anchor": "speech",
            })

    for pattern in asking_model.get("patterns", []):
        if pattern["status"].lower().startswith("improving"):
            wins.append({
                "kind": "asking-pattern",
                "title": f"{pattern['name']} is improving",
                "detail": f"{pattern['sessions_with_error']} practice sessions with a mistake"
                          + (f", last on {pattern['last_error']}"
                             if pattern["last_error"] and pattern["last_error"] != "\u2014"
                             else " on record"),
                "anchor": "askpatterns",
            })

    return wins[:MAX_ACTIONS]


def _fluency_slot(speech: dict, vocabulary: dict) -> Optional[dict]:
    """Rule 17's reserved slot, which nothing on this page could ever fill.

    Impact is computed from `mistakes.csv`, and the discourse-marker rate, the
    filler rate and the vocabulary table are not in it — so they have no impact
    score, lose every ranked comparison against grammar by default, and then
    never get worked on. The rule reserves a slot precisely because at this
    level they are frequently the larger obstacle: "you know" ran 105 times in
    2,364 words while the article rate was a seventh of that.

    Worst first, and only where the evidence carries it: a rising retired phrase
    outranks a marker rate that merely failed to fall.
    """
    rising = [row for row in vocabulary.get("rows", []) if row["movement"] == "rising"]
    markers = next((m for m in speech.get("metrics", []) if m["key"] == "marker_rate"), None)
    points = [pt for pt in (markers or {}).get("points", []) if pt["value"] is not None]

    if rising:
        worst = max(rising, key=lambda r: r["total"])
        return {
            "kind": "vocabulary",
            "category": f"\u201c{worst['phrase']}\u201d",
            "detail": f"You've said it {worst['total']} times across your recordings and it's "
                      "still going up. Words to retire has replacements to try.",
            "anchor": "vocabulary",
        }
    if len(points) >= 2 and points[-1]["value"] >= points[-2]["value"]:
        return {
            "kind": "markers",
            "category": markers["label"],
            "detail": f"{points[-1]['value']} per 100 words on {points[-1]['date']}, "
                      f"up from {points[-2]['value']} the time before.",
            "anchor": "speech",
        }
    return None


def _times(count: Optional[int]) -> str:
    return f"{count or 0} time{'' if count == 1 else 's'}"


def _plain_why(target: priority.Target, *, overdue_days: Optional[int],
               evidence: Optional[int], drillable_first: bool) -> str:
    """Why a pattern is on the list, from the same facts `priority._reasons`
    reads, in words for the person rather than for the coach."""
    parts = []
    stat = target.drill
    if target.state == "automaticity-gap" and stat:
        parts.append(f"{round((stat['accuracy'] or 0) * 100)}% right in drills "
                     f"({stat['correct']}/{stat['attempted']}), but still "
                     f"{_times(target.latest_count)} in your last recording")
    if drillable_first:
        parts.append("the most important mistake without a drill, with enough examples "
                     "on record to write one" + (f" ({evidence} so far)" if evidence else ""))
    if "stalled" in target.flags:
        parts.append(f"no better than {mistakes.STALL_WINDOW} recordings ago, so try a "
                     "different approach")
    if "thin" in target.flags:
        parts.append(f"heard only {_times(evidence)} so far, so it could be a fluke")
    if overdue_days is not None:
        parts.append(f"review is {overdue_days} days overdue")
    if "frozen" in target.flags:
        parts.append(f"hasn't come up in your last {mistakes.STALL_WINDOW} recordings, so it's "
                     "too early to call it fixed")
    text = "; ".join(parts)
    return text[:1].upper() + text[1:] + "." if text else ""


def _plain_blocker(block: priority.Blocker, loop: practice.LoopState,
                   ladder: dict) -> tuple[str, str]:
    """A blocker's title and detail in plain words, rebuilt from the same
    readings `priority.blockers` decided on — its own wording cites rules and
    rungs, which is right for the coach and opaque on the page."""
    if block.kind == "unanalysed":
        return block.title, ("It has been transcribed but not analysed yet, so nothing on "
                             "this page includes it.")
    if block.kind == "treatment-stopped":
        unbridged = not ladder["attended_sessions"] and ladder["asking_sessions"]
        if loop.train.state == "never":
            since = "You haven't done a practice session with corrections yet"
        else:
            since = f"Your last practice with corrections was {loop.train.days} days ago"
        detail = (f"{since}, and you've recorded {loop.recordings_in_window} time"
                  f"{'' if loop.recordings_in_window == 1 else 's'} in the last "
                  f"{loop.window_days} days. Recordings only measure your English; "
                  "practice is what improves it.")
        if unbridged:
            detail += (" Choose conversation practice (\u201clet's practice\u201d): every "
                       "session so far was question practice, which doesn't work on the "
                       "grammar mistakes below.")
        return ("Do a conversation practice session" if unbridged
                else "Do a practice session"), detail
    if block.kind == "overdue-dialogue":
        late = sorted((row for row in ladder["dialogue_only"] if row["overdue"]),
                      key=lambda row: row["next_due"])
        names = ", ".join(row["category"] for row in late[:3]) + (", \u2026" if len(late) > 3 else "")
        return (f"{len(late)} question skill{'' if len(late) == 1 else 's'} due for review",
                f"Overdue since {late[0]['next_due']}: {names}. Say \u201clet's practice "
                "asking\u201d to review them. Recordings can't measure these, so this "
                "reminder is the only thing that keeps track of them.")
    return block.title, block.detail


def _actions(targets: list, blocking: list[tuple[priority.Blocker, str, str]],
             fluency_slot: Optional[dict], plain: dict[str, dict]) -> list[dict]:
    """
    The one thing to do next, and the four behind it.

    Rule 20 is the reason the first one is drawn differently from the rest: five
    things to carry into a session is a list of zero, and the page used to print
    five of equal weight. The ranking is `priority.py`'s and nothing is decided
    here — this only turns it into rows, in the page's words (`plain`, per
    category, and each blocker's rewording alongside it).
    """
    actions = [{
        "kind": block.kind,
        "title": title,
        "detail": detail,
        "anchor": block.anchor,
        "blocking": True,
    } for block, title, detail in blocking]

    # Rule 17 reserves a slot for fluency or vocabulary, and a reserved slot that
    # gets truncated away is not reserved. So the grammar targets are cut to fit
    # around it rather than the other way round — without this the slot existed
    # in the code and never once appeared on the page.
    room = MAX_ACTIONS - len(actions) - (1 if fluency_slot else 0)
    for target in targets[:max(room, 0)]:
        words = plain[target.category]
        actions.append({
            "kind": target.state,
            "title": f"{words['action']}: {target.category}",
            "detail": words["why"] or words["state"] + ".",
            "anchor": "patterns",
            "slug": target.slug,
            "blocking": False,
        })

    if fluency_slot:
        actions.append({
            "kind": "fluency-slot",
            "title": f"Say {fluency_slot['category']} less",
            "detail": fluency_slot["detail"],
            "anchor": fluency_slot["anchor"],
            "blocking": False,
        })

    return actions[:MAX_ACTIONS]


def build_model(*, analysis_dir: Path, today: Optional[str] = None,
                out_dir: Optional[Path] = None,
                frames_dir: Optional[Path] = None) -> dict:
    """Everything the page draws, already derived. Missing files are empty
    sections, never an error: a fresh clone has none of them."""
    mistake_rows = mistakes.load(analysis_dir / "mistakes.csv")
    fluency_rows = fluency.latest_per_date(
        fluency.load_history(analysis_dir / "fluency_history.csv"))
    drill_rows = drill.load_history(analysis_dir / "drills.csv")
    drill_stats = _drill_stats(drill_rows)
    scores = _load_scores(analysis_dir / "scores_history.csv")
    notes = brief.persistent_notes(analysis_dir / "memory.md")
    practice_sessions = practice.load(analysis_dir / "practice_history.csv")
    focus = focus_log.load(analysis_dir / "conversation_focus_log.md")
    scenario_runs = asking.load_history(analysis_dir / "asking_scenarios.csv")
    asking_drills = _drill_stats(drill.load_history(analysis_dir / "asking_drills.csv"))
    asking_memory = asking.parse_memory(analysis_dir / "asking_memory.md")

    dates = mistakes.session_dates(mistake_rows)
    sessions = _sessions(mistake_rows, fluency_rows)
    cohort = _stable_cohort(mistake_rows, dates)
    categories = _categories(mistake_rows, dates, drill_stats, notes)
    generated = today or datetime.now().strftime("%Y-%m-%d")
    speech = _speech(fluency_rows)
    # Transcribed by the pipeline, never picked up by an analysis session.
    unanalysed = [row["date"] for row in speech["sessions"] if row["date"] not in set(dates)]
    ladder = _ladder(categories, drill_stats, practice_sessions, focus, generated)
    asking_model = _asking_mode(scenario_runs, asking_drills, practice_sessions, asking_memory)
    headline = _headline(sessions, scores, fluency_rows, len(cohort), categories,
                         unanalysed, generated)
    level_model, level_readings = _level(analysis_dir)
    vocabulary = _vocabulary(analysis_dir)
    chances = _opportunity(analysis_dir,
                           frames_dir or (analysis_dir.parent / "frames"),
                           mistake_rows)
    # One reading, used by the strip that draws it and by the ranking that acts
    # on it. `overdue_rows` is `(category, next_due)` for everything past its
    # date, built here because `focus_log` owns that file and `practice` has
    # never imported it.
    overdue_rows = [(row.category, row.next_due) for row in focus.values()
                    if row.next_due and row.next_due < generated]
    loop_state = practice.loop_state(practice_sessions, dates, overdue_rows,
                                     today=generated)
    loop = _loop(loop_state, dates)

    # The ranking, once, in the order `priority.py` defines — then narrowed to
    # rule 17's portfolio. Both the action list and the focus table read this,
    # so the two cannot fall out of step with each other or with the CLI.
    overdue = {row.category: _days_between(row.next_due, generated)
               for row in focus.values()
               if row.next_due and row.next_due < generated}
    targets = priority.rank(
        mistakes.summarize(mistake_rows),
        drills=drill_stats,
        slugs={card["category"]: card["slug"] for card in categories},
        overdue={k: v for k, v in overdue.items() if v is not None},
        frozen=set(chances.get("frozen", [])),
    )
    slate = priority.slate(targets)
    blocking = priority.blockers(
        unanalysed=unanalysed,
        loop=loop_state,
        attended_sessions=ladder["attended_sessions"],
        asking_sessions=ladder["asking_sessions"],
        # Only the ones no tracked category covers: a grammar pattern that is
        # late already carries that as a flag on its own row.
        dialogue_overdue=[(row["category"], row["next_due"])
                          for row in ladder["dialogue_only"] if row["overdue"]],
    )
    fluency_slot = _fluency_slot(speech, vocabulary)

    cards_by_name = {card["category"]: card for card in categories}
    drillable_first = next((t.category for t in targets
                            if t.state == "no-drill" and "thin" not in t.flags), None)
    plain = {t.category: {
        "state": PLAIN_STATES[t.state],
        "action": PLAIN_ACTIONS[t.state],
        "why": _plain_why(t, overdue_days=overdue.get(t.category),
                          evidence=cards_by_name.get(t.category, {}).get("evidence"),
                          drillable_first=t.category == drillable_first),
    } for t in targets}
    actions = _actions(slate, [(b, *_plain_blocker(b, loop_state, ladder)) for b in blocking],
                       fluency_slot, plain)
    progress = _progress(sessions, level_model)

    return {
        "generated_at": generated,
        "generated_full": datetime.now().isoformat(timespec="minutes").replace("T", " "),
        "headline": headline,
        "loop": loop,
        "dates": dates,
        "sessions": sessions,
        "cohort": sorted(cohort),
        "exposure": _exposure(mistake_rows),
        "opportunity": chances,
        "categories": categories,
        "scores": scores,
        "ladder": ladder,
        "speech": speech,
        "asking": asking_model,
        "actions": actions,
        "verdict": _verdict(progress, categories, actions),
        "slate": [{
            "category": target.category, "slug": target.slug, "state": target.state,
            "state_label": LADDER_STATES[target.state], "action": target.action,
            "tier": target.tier, "severity": target.severity, "impact": target.impact,
            "latest_rate": target.latest_rate, "latest_count": target.latest_count,
            "flags": target.flags, "why": target.why, "slot": target.slot,
            "drill": target.drill,
            "plain_state": plain[target.category]["state"],
            "plain_action": plain[target.category]["action"],
            "plain_why": plain[target.category]["why"],
            "plain_tier": PLAIN_TIERS.get(target.tier, target.tier),
        } for target in slate],
        "blocking": [{"kind": b.kind, "title": b.title, "detail": b.detail,
                      "anchor": b.anchor} for b in blocking],
        "progress": progress,
        "treatment": _treatment(drill_rows, practice_sessions),
        "working": _whats_working(ladder, categories, speech, asking_model),
        "level": level_model,
        "vocabulary": vocabulary,
        "timeline": _timeline(sessions, speech["sessions"], practice_sessions,
                              scenario_runs, _reports(analysis_dir, out_dir)),
    }


def _verdict(progress: dict, categories: list[dict], actions: list[dict]) -> list[dict]:
    """The page in three or four sentences: what got better, what got worse, what
    to do. Nothing here is new — each line restates a reading from Start to now,
    the pattern directions or the action list — but those are three places to
    read against each other, and the first question on opening the page is the
    answer they give together."""
    lines = []
    series = {s["key"]: s for s in progress.get("series", [])}
    for key, what in (("clarity_rate", "Serious mistakes"),
                      ("cohort_rate", "Mistakes on your day-one checklist")):
        row = series.get(key)
        if not row or row["change"] is None or not row["before"]:
            continue
        percent = round(abs(row["change"]) / row["before"] * 100)
        if percent < 5:
            lines.append({"tone": "neutral", "text": f"{what} are about the same as when you "
                                                     "started."})
            continue
        lines.append({
            "tone": "good" if row["better"] else "bad",
            "text": f"{what} are {'down' if row['better'] else 'up'} {percent}% since you "
                    f"started ({num_text(row['before'])} \u2192 {num_text(row['after'])} per "
                    "1,000 words).",
        })

    worse = sorted((c for c in categories if c["direction"] == "worsening"),
                   key=lambda c: -c["impact"])
    if worse:
        worst = worse[0]
        lines.append({"tone": "bad", "text":
                      f"{worst['category']} {'is' if len(worse) == 1 else 'are the biggest'} "
                      "getting worse"
                      + (f": {_times(worst['latest_count'])} in your last recording."
                         if worst["latest_count"] else ".")})
    if actions:
        lines.append({"tone": "next", "text": f"Next: {actions[0]['title']}."})
    return lines


def num_text(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


# --- rendering ----------------------------------------------------------------


def render(model: dict) -> str:
    """The page, with the model inlined. `<` is escaped so no string in the data
    can close the script tag it is sitting in."""
    payload = json.dumps(model, ensure_ascii=False).replace("<", "\\u003c")
    return TEMPLATE.replace("__MODEL_JSON__", payload)


def _repo_root() -> Path:
    return Path(__file__).parent.parent


def main(argv: list[str] | None = None) -> int:
    """`python -m voxlib.dashboard` — build the page and optionally open it."""
    import argparse
    import webbrowser

    parser = argparse.ArgumentParser(
        prog="python -m voxlib.dashboard",
        description="Build the progress dashboard from the histories in analysis/.",
    )
    parser.add_argument("--analysis", type=Path, default=_repo_root() / "analysis",
                        help="Directory holding the history files (default: analysis/)")
    parser.add_argument("--out", type=Path, default=_repo_root() / "output" / "dashboard.html",
                        help="Where to write the page (default: output/dashboard.html)")
    parser.add_argument("--frames", type=Path, default=_repo_root() / "frames",
                        help="Trigger definitions for the chances panel (default: frames/). "
                             "Without any, every category keeps the per-1,000-words rate.")
    parser.add_argument("--open", action="store_true", help="Open it in the browser when built")
    args = parser.parse_args(argv)

    model = build_model(analysis_dir=args.analysis, out_dir=args.out.parent,
                        frames_dir=args.frames)
    if not model["sessions"]:
        print(f"No sessions recorded in {args.analysis} — nothing to draw yet.")
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(model), encoding="utf-8")

    headline = model["headline"]
    print(f"{args.out} — {headline['sessions']} sessions, "
          f"{len(model['categories'])} tracked mistakes, "
          f"{headline['first_date']} → {headline['last_date']}")
    if args.open:
        webbrowser.open(args.out.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
