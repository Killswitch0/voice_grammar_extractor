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

from . import asking, brief, drill, fluency, focus_log, level, mistakes, practice, vocab

logger = logging.getLogger(__name__)

# How many recent sessions the headline compares the latest one against. Three
# is the same window `mistakes._stalled` uses, for the same reason: two sessions
# cannot tell a trend from a bad day.
BASELINE_WINDOW = 3

# What it takes for "the form is known" to be a claim about the owner rather
# than about a small sample. A drill is five items by design, and an accuracy of
# a perfect score over one item is not evidence of anything, and a mixed block
# can carry a single item of a given pattern — which would otherwise read as a
# perfect score on the harder condition.
MIN_DRILL_ITEMS = 5
FORM_KNOWN_ACCURACY = 0.8

# The three rungs, in the order a pattern climbs them. The names are the ones
# CLAUDE.md gives the files: drills.csv is what the owner knows, practice_
# history.csv is what they produce while attending to it, mistakes.csv is what
# they produce when they have forgotten they are being measured.
LADDER_STATES = {
    "no-drill": "No drill yet",
    "thin-evidence": "Too few drill items to tell",
    "form-unreliable": "Form not reliable yet",
    "automaticity-gap": "Knows it, still says it wrong",
    "clean": "Clean in the last measured session",
    "retiring": "Ready to retire",
}


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
            # Transcript quality, not speech quality. Kept beside the rates
            # because a session where much of the transcript was unreliable is a
            # weaker measurement of everything above, and never mixed into them.
            "low_confidence_share": recording.low_confidence_share if recording else None,
            "mode": (recording.mode or recording.origin) if recording else "",
            "speech_minutes": recording.speech_minutes if recording else None,
        })
    return sessions


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
# discourse-marker rate is "for this speaker the larger problem by two orders of
# magnitude" — which is the only reason a falling marker rate is worth a chart of
# its own rather than a column in a table.
SPEECH_METRICS = [
    {
        "key": "filler_rate", "label": "Filler sounds", "unit": "per 100 words",
        "decimals": 2,
        "note": "um / uh / erm over reliable words. A lower bound on real "
                "disfluency \u2014 whisper drops many hesitations before this can count them.",
    },
    {
        "key": "marker_rate", "label": "Discourse markers", "unit": "per 100 words",
        "decimals": 2,
        "note": "\u201cyou know\u201d, \u201cI mean\u201d, \u201ckind of\u201d and "
                "friends. Counted, never stripped \u2014 and for this speaker the larger "
                "of the two by two orders of magnitude.",
    },
    {
        "key": "median_pause", "label": "Median pause", "unit": "seconds",
        "decimals": 2,
        "note": "The gap between consecutive lines, over all of them \u2014 a timestamp is "
                "valid whether or not the words on it were recognised.",
    },
    {
        "key": "long_pause_rate", "label": "Pauses over 2s", "unit": "per minute of speech",
        "decimals": 2,
        "note": "The recorded count divided by the recorded speech minutes, because a count "
                "on its own rises with the length of the session. Both numbers are in the "
                "table.",
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
        fluency.VAD_BASIS: "VAD-tight turns (diarization)",
        fluency.SEGMENT_BASIS: "whisper segments (solo)",
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


def _level(analysis_dir: Path) -> dict:
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
        return {"readings": [], "scale": level.SCALE}

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
    }


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


def _ladder_state(card: dict, drill_stat: Optional[dict]) -> str:
    """Which rung a pattern is stuck on.

    The order matters. A pattern clean for three sessions is resolved whether or
    not it was ever drilled, so that is checked first; and "knows it, still says
    it wrong" is only claimed once there is enough drill evidence to support the
    first half of the sentence.
    """
    if card["ready_for_improvements"]:
        return "retiring"
    if not drill_stat or not drill_stat["attempted"]:
        return "no-drill"
    if drill_stat["attempted"] < MIN_DRILL_ITEMS:
        return "thin-evidence"
    if (drill_stat["accuracy"] or 0) < FORM_KNOWN_ACCURACY:
        return "form-unreliable"
    if card["latest_rate"]:
        return "automaticity-gap"
    return "clean"


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
            "state": _ladder_state(card, stat),
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
        "state_labels": LADDER_STATES,
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
            "title": f"{len(retiring)} pattern{'' if len(retiring) == 1 else 's'} "
                     "ready to retire",
            "detail": ", ".join(f"{r['category']} (clean {r['absence_streak']} sessions "
                                "running)" for r in retiring[:2]),
            "anchor": "patterns",
        })

    # Only the ones whose improvement is bigger than counting noise. Before this
    # test the line read "8 of 19 improving" on differences of a single instance,
    # which is encouragement rather than a measurement.
    improving = [c for c in categories if c["direction"] == "improving"]
    if improving:
        wins.append({
            "kind": "improving",
            "title": f"{len(improving)} of {len(categories)} patterns are measurably "
                     "improving",
            "detail": "the biggest by impact: "
                      + ", ".join(c["category"] for c in improving[:3]),
            "anchor": "patterns",
        })
    leaning = [c for c in categories
               if c["direction_shape"] == "improving" and not c["separable"]]
    if leaning and not improving:
        wins.append({
            "kind": "leaning",
            "title": f"{len(leaning)} more are pointing the right way",
            "detail": "not yet far enough from chance to call it, on counts this small: "
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
            "title": f"{len(known)} form{'' if len(known) == 1 else 's'} reliable under test",
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
                "title": "Question scenarios are going better",
                "detail": f"{first['met']}/{first['total']} on {first['date']} to "
                          f"{last['met']}/{last['total']} on {last['date']}",
                "anchor": "asking",
            })

    for metric in speech.get("metrics", []):
        measured = [p for p in metric["points"] if p["value"] is not None]
        if len(measured) < 3 or metric["key"] in SOLO_ONLY_METRICS:
            continue
        first, last = measured[0], measured[-1]
        if last["value"] < first["value"]:
            wins.append({
                "kind": "speech",
                "title": f"{metric['label']} are down",
                "detail": f"{first['value']} to {last['value']} {metric['unit']}, "
                          f"{first['date']} to {last['date']}",
                "anchor": "speech",
            })

    for pattern in asking_model.get("patterns", []):
        if pattern["status"].lower().startswith("improving"):
            wins.append({
                "kind": "asking-pattern",
                "title": f"{pattern['name']} is improving",
                "detail": f"{pattern['sessions_with_error']} sessions with an error"
                          + (f", last on {pattern['last_error']}"
                             if pattern["last_error"] and pattern["last_error"] != "\u2014"
                             else " on record"),
                "anchor": "askpatterns",
            })

    return wins[:MAX_ACTIONS]


def _next_actions(ladder: dict, asking_model: dict, speech: dict,
                  headline: dict) -> list[dict]:
    """
    The one thing this page could not answer: what to do about any of it.

    Every number on it was reachable and none of it was actionable without
    reading three sections against each other — the ladder for the diagnosis,
    the cards for the impact ranking, the schedule for what is overdue. This
    assembles the crossing that a reader was doing by hand, in priority order,
    and nothing here is new data: every line points at the section it came from.
    """
    actions: list[dict] = []
    rows = ladder.get("rows", [])

    # 0. A recording that has been transcribed but not analysed. It outranks
    #    everything else because every number on the page is answering a
    #    question about an older session until it is done.
    for pending in headline.get("unanalysed", [])[:1]:
        actions.append({
            "kind": "unanalysed",
            "title": f"Analyse the {pending} recording",
            "detail": ("the pipeline has transcribed it, but no session has read it \u2014 "
                       "so it is in the timeline and the speech panel and in none of the "
                       "grammar sections, and every ranking here predates it"),
            "anchor": "timeline",
        })

    # 1. Knows the form and still says it wrong. The only state where the
    #    obvious response — drill it — is the wrong one, so it leads.
    for row in [r for r in rows if r["state"] == "automaticity-gap"][:2]:
        drilled = row["drill"]
        actions.append({
            "kind": "automaticity-gap",
            "title": f"Stop drilling {row['category']} \u2014 produce it in dialogue",
            "detail": (f"{round((drilled['accuracy'] or 0) * 100)}% correct over "
                       f"{drilled['attempted']} drill items, and still "
                       f"{row['speech_rate']} per 1,000 words in the recording"
                       + (" \u2014 and not moving" if row["stalled"] else "")),
            "anchor": "patterns",
        })

    # 2. The middle rung has no measurements at all.
    if not ladder.get("attended_sessions") and ladder.get("asking_sessions"):
        actions.append({
            "kind": "no-attended-practice",
            "title": "Run a conversation-practice session",
            "detail": (f"All {ladder['asking_sessions']} recorded practice sessions were "
                       "question practice, so nothing bridges the drills and the recordings "
                       "for any of these patterns"),
            "anchor": "patterns",
        })

    # 3. The spaced-repetition schedule, which is the one thing here with a date
    #    attached and therefore the one thing that can be late.
    overdue = [r for r in rows if r["overdue"]]
    overdue += [d for d in ladder.get("dialogue_only", []) if d["overdue"]]
    if overdue:
        oldest = min(o["next_due"] for o in overdue)
        names = ", ".join(o["category"] for o in sorted(overdue,
                                                        key=lambda o: o["next_due"])[:3])
        actions.append({
            "kind": "overdue",
            "title": f"{len(overdue)} practice slots are overdue",
            "detail": f"the oldest since {oldest} \u2014 {names}"
                      + (", \u2026" if len(overdue) > 3 else ""),
            "anchor": "patterns",
        })

    # 4. A pattern with no drill cannot be diagnosed above rung 3 at all, so the
    #    highest-impact one is the cheapest thing to learn something about.
    no_drill = [r for r in rows if r["state"] == "no-drill"]
    if no_drill:
        first = no_drill[0]
        actions.append({
            "kind": "no-drill",
            "title": f"Write a drill for {first['category']}",
            "detail": (f"{len(no_drill)} of {len(rows)} tracked mistakes have none, and this "
                       f"is the highest-impact one \u2014 impact {first['impact']}, "
                       f"{first['speech_rate']} per 1,000 words"),
            "anchor": "patterns",
        })

    # 5. A form seen in two separate sessions has earned a name.
    for form in [f for f in asking_model.get("provisional", []) if f["ready"]][:1]:
        actions.append({
            "kind": "promote",
            "title": f"Give \u201c{form['name']}\u201d a category and a drill",
            "detail": (f"corrected in {form['sessions']} separate sessions "
                       f"({form['total']} times), which makes it a pattern rather than "
                       "a slip"),
            "anchor": "askpatterns",
        })

    # 6. The question side, where the criteria are the only thing that repeats.
    criteria = asking_model.get("criteria", [])
    totals = asking_model.get("totals", {})
    if criteria and totals.get("runs"):
        worst = criteria[0]
        actions.append({
            "kind": "asking",
            "title": f"Question practice: \u201c{worst['criterion']}\u201d keeps failing",
            "detail": (f"missed in {worst['count']} of {totals['runs']} scenario runs "
                       f"\u2014 more often than any other criterion"),
            "anchor": "asking",
        })

    # 7. Only if it is real: a session the pipeline says is not comparable.
    if speech.get("any_unreliable"):
        actions.append({
            "kind": "recording",
            "title": "Check the recording setup",
            "detail": ("at least one session lost enough words to low-confidence "
                       "recognition that the pipeline stopped treating it as comparable"),
            "anchor": "quality",
        })

    return actions[:MAX_ACTIONS]


def build_model(*, analysis_dir: Path, today: Optional[str] = None,
                out_dir: Optional[Path] = None) -> dict:
    """Everything the page draws, already derived. Missing files are empty
    sections, never an error: a fresh clone has none of them."""
    mistake_rows = mistakes.load(analysis_dir / "mistakes.csv")
    fluency_rows = fluency.latest_per_date(
        fluency.load_history(analysis_dir / "fluency_history.csv"))
    drill_stats = _drill_stats(drill.load_history(analysis_dir / "drills.csv"))
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

    return {
        "generated_at": generated,
        "generated_full": datetime.now().isoformat(timespec="minutes").replace("T", " "),
        "headline": headline,
        "dates": dates,
        "sessions": sessions,
        "cohort": sorted(cohort),
        "categories": categories,
        "scores": scores,
        "ladder": ladder,
        "speech": speech,
        "asking": asking_model,
        "actions": _next_actions(ladder, asking_model, speech, headline),
        "working": _whats_working(ladder, categories, speech, asking_model),
        "level": _level(analysis_dir),
        "vocabulary": _vocabulary(analysis_dir),
        "timeline": _timeline(sessions, speech["sessions"], practice_sessions,
                              scenario_runs, _reports(analysis_dir, out_dir)),
    }


# --- rendering ----------------------------------------------------------------

# The palette is the data-viz reference instance, validated for both modes with
# `scripts/validate_palette.js` (2 categorical slots, all six checks PASS light
# and dark). The heat ramp is one hue stepped by distance from the surface — so
# it inverts in dark mode rather than being flipped automatically, because blue
# 700 on a near-black surface is invisible exactly where the value is highest.
_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Spoken English Progress</title>
<style>
  :root {
    color-scheme: light;
    --page: #f9f9f7;
    --surface: #fcfcfb;
    --ink: #0b0b0b;
    --ink-2: #52514e;
    --muted: #898781;
    --grid: #e1e0d9;
    --axis: #c3c2b7;
    --border: rgba(11,11,11,0.10);
    --series-1: #2a78d6;
    --series-2: #eb6834;
    --good: #0ca30c;
    --warning: #fab219;
    --critical: #d03b3b;
    --heat-0: rgba(42,120,214,0.07);
    --heat-1: #9ec5f4;
    --heat-2: #6da7ec;
    --heat-3: #2a78d6;
    --heat-4: #1c5cab;
    --heat-5: #0d366b;
    --quality: #c3c2b7;
    --hollow: #c3c2b7;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) {
      color-scheme: dark;
      --page: #0d0d0d;
      --surface: #1a1a19;
      --ink: #ffffff;
      --ink-2: #c3c2b7;
      --muted: #898781;
      --grid: #2c2c2a;
      --axis: #383835;
      --border: rgba(255,255,255,0.10);
      --series-1: #3987e5;
      --series-2: #d95926;
      --heat-0: rgba(57,135,229,0.10);
      --heat-1: #184f95;
      --heat-2: #256abf;
      --heat-3: #3987e5;
      --heat-4: #86b6ef;
      --heat-5: #cde2fb;
      --quality: #383835;
      --hollow: #4a4a47;
    }
  }
  :root[data-theme="dark"] {
    color-scheme: dark;
    --page: #0d0d0d;
    --surface: #1a1a19;
    --ink: #ffffff;
    --ink-2: #c3c2b7;
    --muted: #898781;
    --grid: #2c2c2a;
    --axis: #383835;
    --border: rgba(255,255,255,0.10);
    --series-1: #3987e5;
    --series-2: #d95926;
    --heat-0: rgba(57,135,229,0.10);
    --heat-1: #184f95;
    --heat-2: #256abf;
    --heat-3: #3987e5;
    --heat-4: #86b6ef;
    --heat-5: #cde2fb;
    --quality: #383835;
    --hollow: #4a4a47;
  }

  * { box-sizing: border-box; }
  body {
    margin: 0;
    padding: 0 16px 64px;
    background: var(--page);
    color: var(--ink);
    font: 15px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 1100px; margin: 0 auto; }

  header { display: flex; flex-wrap: wrap; gap: 12px; align-items: baseline;
           justify-content: space-between; padding: 32px 0 8px; }
  h1 { font-size: 20px; font-weight: 600; margin: 0; letter-spacing: -0.01em; }
  .sub { color: var(--muted); font-size: 13px; }
  button.ghost { background: none; border: 1px solid var(--border); color: var(--ink-2);
                 border-radius: 8px; padding: 5px 10px; font: inherit; font-size: 13px;
                 cursor: pointer; }
  button.ghost:hover { border-color: var(--axis); color: var(--ink); }

  /* Section nav — ten sections and ten thousand pixels, with nothing to click */
  nav.sections { position: sticky; top: 0; z-index: 6; display: flex; gap: 2px;
                 overflow-x: auto; padding: 8px 0; margin: 0 -4px 4px;
                 background: var(--page); border-bottom: 1px solid var(--border);
                 scrollbar-width: none; }
  nav.sections::-webkit-scrollbar { display: none; }
  nav.sections a { flex: none; font-size: 12px; color: var(--ink-2); text-decoration: none;
                   padding: 5px 10px; border-radius: 8px; white-space: nowrap;
                   display: flex; gap: 6px; align-items: center; }
  nav.sections a:hover { background: var(--heat-0); color: var(--ink); }
  nav.sections a[aria-current="true"] { color: var(--ink); background: var(--heat-0);
                                        font-weight: 500; }
  nav.sections .badge { font-size: 10px; font-variant-numeric: tabular-nums;
                        color: var(--muted); }
  section { scroll-margin-top: 56px; }

  /* Do this next */
  .actions { display: grid; gap: 2px; }
  .action-row { display: grid; grid-template-columns: 22px 1fr; gap: 12px;
                padding: 12px 0; border-top: 1px solid var(--border); }
  .action-row:first-child { border-top: none; }
  .action-n { font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums;
              padding-top: 1px; }
  .action-title { font-size: 13.5px; font-weight: 600; line-height: 1.4; }
  .action-detail { font-size: 12px; color: var(--ink-2); margin-top: 3px; line-height: 1.5; }
  .action-link { font-size: 11px; color: var(--series-1); text-decoration: none;
                 margin-top: 5px; display: inline-block; }
  .action-link:hover { text-decoration: underline; }

  .card { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
          padding: 20px; margin-top: 16px; }
  .card > h2 { font-size: 15px; font-weight: 600; margin: 0 0 2px; }
  .card > .sub { margin-bottom: 18px; max-width: 72ch; }
  .card-head { display: flex; flex-wrap: wrap; gap: 8px; align-items: flex-start;
               justify-content: space-between; margin-bottom: 14px; }

  /* Hero + tiles */
  .hero-row { display: flex; flex-wrap: wrap; gap: 32px; align-items: flex-end; }
  .hero-val { font-size: 52px; font-weight: 600; line-height: 1; letter-spacing: -0.02em; }
  .hero-label { color: var(--ink-2); font-size: 13px; margin-top: 8px; max-width: 34ch; }
  .delta { font-size: 13px; font-weight: 500; margin-top: 8px; display: flex;
           gap: 6px; align-items: center; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(118px, 1fr));
           gap: 20px 24px; flex: 1 1 320px; }
  .tile-label { color: var(--muted); font-size: 12px; }
  .tile-val { font-size: 21px; font-weight: 600; margin-top: 2px; }
  .tile-note { color: var(--muted); font-size: 11px; margin-top: 2px; }
  .driver { font-size: 12px; color: var(--ink-2); margin-top: 8px; max-width: 46ch;
            line-height: 1.5; }
  .driver b { color: var(--ink); font-weight: 600; }

  /* Charts */
  .plot { width: 100%; position: relative; }
  .plot svg { display: block; width: 100%; height: auto; overflow: visible; }
  .legend { display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 10px; }
  .legend-item { display: flex; gap: 7px; align-items: center; font-size: 12px;
                 color: var(--ink-2); }
  .key-line { width: 14px; height: 2px; border-radius: 1px; flex: none; }
  .key-box { width: 11px; height: 11px; border-radius: 2px; flex: none; }
  .note { color: var(--muted); font-size: 12px; margin-top: 14px; max-width: 78ch; }

  /* Quality strip */
  .strip-wrap { padding: 0 58px 0 40px; }    /* the line chart's own left/right margins */
  .strip { display: flex; gap: 2px; margin-top: 4px; align-items: flex-end; height: 17px; }
  @media (max-width: 560px) { .strip-wrap { padding: 0; } }
  .strip-cell { flex: 1; height: 6px; border-radius: 2px; background: var(--quality); }

  /* Heatmap */
  .heat-scroll { overflow-x: auto; margin: 0 -4px; padding: 0 4px 4px; }
  .heat { display: grid; gap: 2px; min-width: max-content; }
  .heat-label { font-size: 12px; color: var(--ink-2); padding-right: 12px;
                white-space: nowrap; display: flex; align-items: center; gap: 6px;
                position: sticky; left: 0; z-index: 1; background: var(--surface); }
  .heat-label .nm { overflow: hidden; text-overflow: ellipsis; min-width: 0; }
  @media (max-width: 780px) { .heat-label { max-width: 146px; } }
  .heat-date { font-size: 10px; color: var(--muted); text-align: center;
               font-variant-numeric: tabular-nums; }
  .cell { min-width: 24px; height: 22px; border-radius: 3px; background: var(--heat-0);
          cursor: default; }
  .cell[data-state="untested"] { background: none; box-shadow: inset 0 0 0 1px var(--hollow); }
  .cell[data-state="before"] { background: none; }
  .cell:hover, .cell:focus-visible { outline: 2px solid var(--ink); outline-offset: 1px; }
  .sev { font-size: 10px; color: var(--muted); font-variant-numeric: tabular-nums; flex: none; }

  /* Cards grid */
  .controls { display: flex; flex-wrap: wrap; gap: 14px; align-items: center;
              margin: 20px 0 4px; font-size: 13px; color: var(--ink-2); }
  .controls select, .controls label { font: inherit; color: inherit; }
  .controls select { background: var(--surface); color: var(--ink);
                     border: 1px solid var(--border); border-radius: 8px; padding: 4px 8px; }
  /* One expandable row per pattern. The collapsed row is the diagnosis, the
     detail is the evidence — previously two sections that listed the same
     the same names in the same order. */
  .row-toggle { background: none; border: 0; padding: 0; font: inherit; color: inherit;
                cursor: pointer; display: flex; gap: 6px; align-items: baseline;
                text-align: left; width: 100%; }
  .row-toggle:hover .pname { color: var(--series-1); }
  .caret { color: var(--muted); font-size: 9px; flex: none; }
  .row-toggle[aria-expanded="true"] .pname { font-weight: 600; }
  .pname { line-height: 1.4; }
  .row-ex { font-size: 11.5px; line-height: 1.4; margin-top: 4px; color: var(--muted);
            display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
            overflow: hidden; }
  .row-ex .right { color: var(--ink-2); font-weight: 500; }
  .row-ex .wrong { text-decoration: line-through; text-decoration-color: var(--hollow); }
  /* The table sets `white-space: nowrap` on every cell so the diagnosis columns
     stay on one line. The detail cell holds prose, and inheriting that made it
     one very long line, clipped at the card edge. */
  tr.detail-row > td { padding: 0 8px 26px 26px; border-bottom: 1px solid var(--grid);
                       white-space: normal; text-align: left; }
  .pdetail { max-width: 78ch; }
  .permalink { font-size: 11px; color: var(--muted); text-decoration: none;
               margin-top: 16px; display: inline-block; }
  .permalink:hover { color: var(--series-1); }
  #patterns tbody tr { scroll-margin-top: 64px; }
  #patterns tbody th[scope="row"] { min-width: 250px; }
  #patterns tbody tr:target > th, #patterns tbody tr:target > td { background: var(--heat-0); }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
  .chip { font-size: 11px; padding: 2px 7px; border-radius: 999px;
          border: 1px solid var(--border); color: var(--ink-2); display: flex;
          gap: 5px; align-items: center; }
  /* inline-block, not inline: outside a flex row a bare span ignores width */
  .dot { width: 7px; height: 7px; border-radius: 50%; flex: none; display: inline-block; }
  .mstats { display: grid; grid-template-columns: 1fr 1fr; gap: 10px 12px; margin-top: 14px;
            font-size: 12px; }
  .mstats .k { color: var(--muted); }
  .mstats .v { font-weight: 500; font-variant-numeric: tabular-nums; margin-top: 1px; }
  details { margin-top: 12px; border-top: 1px solid var(--border); padding-top: 10px; }
  summary { font-size: 12px; color: var(--ink-2); cursor: pointer; }
  summary:hover { color: var(--ink); }

  /* An open card takes the whole grid row: at a third of the width its notes
     wrap to a very short measure, and its two neighbours stretch to match a
     tall row of mostly blank space. */
  .pdetail .prose, .pdetail .ex-list { max-width: 74ch; }

  /* Worked examples — the only part of a note you can practise from */
  .ex-list { display: grid; gap: 8px; margin: 2px 0 0; }
  .ex { font-size: 12.5px; line-height: 1.45; }
  .ex .wrong { color: var(--ink-2); text-decoration: line-through;
               text-decoration-color: var(--hollow); }
  .ex .arrow { color: var(--muted); margin: 0 6px; }
  .ex .right { color: var(--ink); font-weight: 500; }
  .ex .when { color: var(--muted); font-size: 11px; margin-left: 6px;
              font-variant-numeric: tabular-nums; }
  .note-head { font-size: 11px; color: var(--muted); margin: 16px 0 6px;
               text-transform: uppercase; letter-spacing: 0.04em; }
  .prose { font-size: 12.5px; line-height: 1.55; color: var(--ink-2); margin: 0 0 10px; }
  .prose code, .ex code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                          font-size: 0.92em; background: var(--heat-0);
                          padding: 0 4px; border-radius: 4px; }
  .prose strong { color: var(--ink); font-weight: 600; }
  .status { font-size: 12px; color: var(--ink-2); line-height: 1.5; }
  .decision { border-left: 2px solid var(--grid); padding-left: 10px; margin-top: 12px; }
  .decision .dt { font-size: 12px; font-weight: 600; color: var(--ink); line-height: 1.45; }

  /* Vocabulary */
  .vrow { display: grid; grid-template-columns: minmax(130px, 200px) 1fr auto;
          gap: 14px; align-items: center; padding: 11px 0;
          border-top: 1px solid var(--border); }
  .vrow:first-of-type { border-top: none; }
  .vphrase { font-size: 13px; font-weight: 600; }
  .vsub { font-size: 11px; color: var(--muted); margin-top: 3px; line-height: 1.4; }
  .vmove { font-size: 11px; display: flex; gap: 6px; align-items: center;
           justify-content: flex-end; white-space: nowrap; }
  .spark-cells { display: flex; gap: 2px; align-items: flex-end; height: 26px; }
  .spark-cells i { flex: 1; min-width: 4px; background: var(--series-1);
                   border-radius: 1px 1px 0 0; }
  .spark-cells i[data-zero="1"] { background: var(--grid); }

  /* Level */
  .lvl-head { display: flex; flex-wrap: wrap; gap: 32px; align-items: flex-end; }
  .lvl-val { font-size: 44px; font-weight: 600; line-height: 1; letter-spacing: -0.02em; }
  .lvl-note { color: var(--ink-2); font-size: 12px; margin-top: 8px; max-width: 48ch;
              line-height: 1.5; }
  .dims { display: grid; grid-template-columns: repeat(auto-fit, minmax(218px, 1fr));
          gap: 22px 26px; margin-top: 24px; }
  .dim-name { display: flex; gap: 10px; align-items: baseline;
              justify-content: space-between; font-size: 13px; font-weight: 600;
              border-bottom: 1px solid var(--border); padding-bottom: 6px;
              margin-bottom: 12px; }
  .dim-rung { font-size: 11px; font-weight: 500; color: var(--ink-2); display: flex;
              gap: 6px; align-items: center; white-space: nowrap; }
  .mrow { margin-bottom: 14px; }
  .mlab { font-size: 12px; color: var(--ink-2); display: flex; gap: 10px;
          justify-content: space-between; align-items: baseline; }
  .mval { font-variant-numeric: tabular-nums; color: var(--ink); font-weight: 600;
          flex: none; }
  .mneed { font-size: 11px; color: var(--muted); margin-top: 3px; }
  .mnote-s { font-size: 11px; color: var(--muted); line-height: 1.45; margin-top: 4px; }

  /* Timeline */
  a.report { color: var(--series-1); text-decoration: none; }
  a.report:hover { text-decoration: underline; }
  .tags { display: flex; flex-wrap: wrap; gap: 5px; }

  /* Horizontal bars */
  .bars { display: grid; gap: 6px; margin: 2px 0 4px; max-width: 520px; }
  .bar-row { display: grid; grid-template-columns: 96px 1fr 34px; gap: 10px;
             align-items: center; font-size: 12px; }
  .bar-label { color: var(--ink-2); text-align: right; }
  .bar-track { height: 14px; }
  .bar-track i { display: block; height: 100%; background: var(--series-1);
                 border-radius: 0 4px 4px 0; }
  .bar-val { font-variant-numeric: tabular-nums; font-weight: 600; }
  .bar-row:hover .bar-track i, .bar-row:focus-visible .bar-track i { filter: brightness(1.08); }

  /* Speech metrics */
  .metrics { display: grid; grid-template-columns: repeat(auto-fit, minmax(215px, 1fr));
             gap: 22px 24px; margin-top: 2px; }
  .metric .mlabel { font-size: 12px; color: var(--muted); }
  .metric .val { font-size: 21px; font-weight: 600; margin-top: 1px; }
  .metric .unit { font-size: 12px; font-weight: 400; color: var(--ink-2); }
  .metric .mnote { font-size: 11px; color: var(--muted); margin-top: 8px; }
  .metric .delta-s { font-size: 11px; margin-top: 2px; display: flex; gap: 5px; }
  .meter { position: relative; height: 6px; border-radius: 3px; background: var(--heat-0);
           min-width: 84px; }
  .meter i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 3px;
             background: var(--series-1); }
  .meter u { position: absolute; top: -3px; bottom: -3px; width: 1px;
             background: var(--axis); }

  /* Ladder */
  .rungs { display: flex; flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
  .rung-def { font-size: 12px; color: var(--ink-2); flex: 1 1 200px; min-width: 180px;
              border-left: 2px solid var(--grid); padding-left: 10px; }
  .rung-def b { display: block; color: var(--ink); font-weight: 600; }
  .notice { border-left: 2px solid var(--warning); padding: 3px 0 3px 12px;
            margin: 0 0 18px; font-size: 12.5px; color: var(--ink-2); max-width: 82ch; }
  .chipbar { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 14px; }
  button.state { font: inherit; font-size: 12px; padding: 4px 10px; border-radius: 999px;
                 border: 1px solid var(--border); background: none; color: var(--ink-2);
                 cursor: pointer; display: flex; gap: 7px; align-items: center; }
  button.state:hover { border-color: var(--axis); color: var(--ink); }
  button.state[aria-pressed="true"] { border-color: var(--ink); color: var(--ink); }
  .count { font-variant-numeric: tabular-nums; font-weight: 600; }
  td.rung, th.rung, td.where, th.where { text-align: left; }
  td.where, th.where { white-space: normal; min-width: 200px; }
  tbody th[scope="row"] { white-space: normal; min-width: 190px; }
  #ladder td, #ladder th { padding: 7px 8px; vertical-align: top; }
  .cellrow { display: flex; gap: 7px; align-items: baseline; }
  .detail { color: var(--muted); font-size: 11px; }
  .overdue { color: var(--critical); }
  .action { color: var(--ink-2); }

  /* Tables */
  table { border-collapse: collapse; width: 100%; font-size: 12px;
          font-variant-numeric: tabular-nums; }
  caption { text-align: left; color: var(--muted); font-size: 12px; padding-bottom: 8px; }
  th, td { text-align: right; padding: 5px 8px; border-bottom: 1px solid var(--grid);
           white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; }
  thead th { color: var(--muted); font-weight: 500; }
  .table-wrap { overflow-x: auto; }
  [hidden] { display: none !important; }

  /* Tooltip */
  .tip { position: fixed; z-index: 10; pointer-events: none; opacity: 0;
         transition: opacity .1s; background: var(--surface); color: var(--ink);
         border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px;
         font-size: 12px; box-shadow: 0 6px 24px rgba(0,0,0,.14); max-width: 260px; }
  .tip-head { color: var(--muted); font-size: 11px; margin-bottom: 4px; }
  .tip-row { display: flex; gap: 8px; align-items: baseline; }
  .tip-val { font-weight: 600; font-variant-numeric: tabular-nums; }
  .tip-name { color: var(--ink-2); }
  @media (prefers-reduced-motion: reduce) { .tip { transition: none; } }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <div>
      <h1>Spoken English progress</h1>
      <div class="sub" id="meta"></div>
    </div>
    <button class="ghost" id="theme" type="button">Theme</button>
  </header>
  <nav class="sections" id="nav" aria-label="Sections"></nav>
  <section class="card" id="headline"></section>
  <section class="card" id="actions"></section>
  <section class="card" id="working"></section>
  <section class="card" id="level"></section>
  <section class="card" id="trend"></section>
  <section class="card" id="heatmap"></section>
  <section class="card" id="patterns"></section>
  <section class="card" id="asking"></section>
  <section class="card" id="askpatterns"></section>
  <section class="card" id="vocabulary"></section>
  <section class="card" id="speech"></section>
  <section class="card" id="quality"></section>
  <section class="card" id="timeline"></section>
</div>
<script id="model" type="application/json">__MODEL_JSON__</script>
<script>
"use strict";
const MODEL = JSON.parse(document.getElementById("model").textContent);

const SECTION_LABELS = {
  headline: "Overview",
  actions: "Do this next",
  working: "What's working",
  level: "Level",
  trend: "Rate over time",
  heatmap: "Every mistake",
  patterns: "What to work on",
  asking: "Asking questions",
  askpatterns: "Question patterns",
  vocabulary: "Words to retire",
  speech: "How it was spoken",
  quality: "Reliability",
  timeline: "Timeline",
};

/* ---------- helpers ---------- */
const NS = "http://www.w3.org/2000/svg";
const num = (v, d = 2) => v === null || v === undefined ? "\\u2014" : v.toFixed(d);
// Same number without the trailing zeros a fixed precision adds.
const trim = (v) => v === null || v === undefined ? "\\u2014"
  : String(parseFloat(v.toFixed(3)));
const int = (v) => v === null || v === undefined ? "\\u2014" : v.toLocaleString("en-US");
const shortDate = (d) => d.slice(5).replace("-", "/");
// Narrow enough for a season of column headers side by side: "8/3", not "08/03".
const tinyDate = (d) => `${+d.slice(5, 7)}/${+d.slice(8, 10)}`;

function el(tag, props = {}, kids = []) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined) continue;
    if (k === "text") node.textContent = v;            // labels are untrusted data
    else if (k === "class") node.className = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("data") || k === "tabindex" || k === "hidden")
      node.setAttribute(k === "tabindex" ? "tabindex" : k, v);
    else node[k] = v;
  }
  for (const kid of [].concat(kids)) if (kid) node.append(kid);
  return node;
}
function svg(tag, attrs = {}) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs))
    if (v !== null && v !== undefined) node.setAttribute(k, v);
  return node;
}
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

/* ---------- tooltip (one instance, shared) ---------- */
const tip = el("div", { class: "tip" });
document.body.append(tip);
function showTip(x, y, head, rows) {
  tip.textContent = "";
  tip.append(el("div", { class: "tip-head", text: head }));
  for (const row of rows) {
    const line = el("div", { class: "tip-row" });
    if (row.color) line.append(el("span", { class: "key-line", style: `background:${row.color}` }));
    line.append(el("span", { class: "tip-val", text: row.value }));
    if (row.name) line.append(el("span", { class: "tip-name", text: row.name }));
    tip.append(line);
  }
  tip.style.opacity = "1";
  const box = tip.getBoundingClientRect();
  const left = Math.min(Math.max(8, x + 14), window.innerWidth - box.width - 8);
  const top = Math.min(Math.max(8, y - box.height - 12), window.innerHeight - box.height - 8);
  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
}
const hideTip = () => { tip.style.opacity = "0"; };

/* ---------- axis ticks ---------- */
function ticks(max, count = 5) {
  if (!(max > 0)) return [0];
  const raw = max / count;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) || 10 * mag;
  const out = [];
  const last = Math.ceil(max / step) * step;          // the top tick is >= the data, always
  for (let v = 0; v <= last + step * 0.001; v += step) out.push(Math.round(v * 100) / 100);
  return out;
}

/* ---------- responsive render ---------- */
function responsive(host, draw) {
  let width = 0;
  const run = () => {
    const w = Math.max(240, Math.floor(host.clientWidth));
    if (w === width) return;
    width = w;
    host.textContent = "";
    host.append(draw(w));
  };
  run();
  new ResizeObserver(run).observe(host);
}
</script>
<script>
/* ---------- the trend chart ---------- */
function lineChart(width, sessions, series, opts = {}) {
  const H = Math.max(210, Math.min(300, Math.round(width * 0.42)));
  const M = { top: 14, right: 58, bottom: 30, left: 40 };
  const iw = width - M.left - M.right;
  const ih = H - M.top - M.bottom;
  const values = series.flatMap((s) => sessions.map((d) => d[s.key])).filter((v) => v !== null);
  const scale = ticks(Math.max(...values, 1) * 1.08);
  const top = scale[scale.length - 1];
  const x = (i) => M.left + (sessions.length < 2 ? iw / 2 : (i / (sessions.length - 1)) * iw);
  const y = (v) => M.top + ih - (v / top) * ih;

  const root = svg("svg", { viewBox: `0 0 ${width} ${H}`, width, height: H,
                            role: "img" });

  for (const t of scale) {                                      // hairline, solid, recessive
    root.append(svg("line", { x1: M.left, x2: M.left + iw, y1: y(t), y2: y(t),
                              stroke: t === 0 ? css("--axis") : css("--grid"), "stroke-width": 1 }));
    root.append(Object.assign(svg("text", { x: M.left - 8, y: y(t) + 4, fill: css("--muted"),
                                            "font-size": 11, "text-anchor": "end",
                                            "font-variant-numeric": "tabular-nums" }),
                              { textContent: t }));
  }
  const every = sessions.length > 8 ? 2 : 1;                    // thin the x labels, never overlap
  sessions.forEach((s, i) => {
    if (i % every && i !== sessions.length - 1) return;
    root.append(Object.assign(svg("text", { x: x(i), y: H - 10, fill: css("--muted"),
                                            "font-size": 11, "text-anchor": "middle" }),
                              { textContent: shortDate(s.date) }));
  });

  for (const s of series) {
    const color = css(s.token);
    let run = [];
    const flush = () => {
      if (run.length > 1)
        root.append(svg("path", { d: "M" + run.map((p) => `${p[0]},${p[1]}`).join("L"),
                                  fill: "none", stroke: color, "stroke-width": 2,
                                  "stroke-linejoin": "round", "stroke-linecap": "round" }));
      else if (run.length === 1)
        root.append(svg("circle", { cx: run[0][0], cy: run[0][1], r: 2.5, fill: color }));
      run = [];
    };
    sessions.forEach((d, i) => {
      const v = d[s.key];
      if (v === null || v === undefined) flush(); else run.push([x(i), y(v)]);
    });
    flush();
    const last = sessions.reduce((best, d, i) =>
      (d[s.key] === null || d[s.key] === undefined ? best : i), -1);
    if (last >= 0) {
      const lastValue = sessions[last][s.key];
      root.append(svg("circle", { cx: x(last), cy: y(lastValue), r: 4.5, fill: color,
                                  stroke: css("--surface"), "stroke-width": 2 }));
      // Direct end label, selective — and anchored at the end so a series that
      // stops in the middle of the chart does not write over the line after it.
      const atEdge = last === sessions.length - 1;
      root.append(Object.assign(
        svg("text", { x: x(last) + (atEdge ? 10 : 0), y: y(lastValue) - (atEdge ? -4 : 10),
                      fill: css("--ink"), "font-size": 12, "font-weight": 600,
                      "text-anchor": atEdge ? "start" : "middle" }),
        { textContent: lastValue.toFixed(opts.decimals ?? 1) }));
    }
  }

  const hair = svg("line", { y1: M.top, y2: M.top + ih, stroke: css("--axis"),
                             "stroke-width": 1, opacity: 0 });
  root.append(hair);
  sessions.forEach((d, i) => {                                   // the crosshair finds the X
    const half = sessions.length < 2 ? iw : iw / (sessions.length - 1) / 2;
    const band = svg("rect", { x: Math.max(M.left, x(i) - half), y: M.top,
                               width: Math.max(1, half * 2), height: ih,
                               fill: "transparent", tabindex: 0 });
    const show = (ev) => {
      hair.setAttribute("x1", x(i)); hair.setAttribute("x2", x(i));
      hair.setAttribute("opacity", 1);
      const box = root.getBoundingClientRect();
      const rows = series
        .filter((s) => d[s.key] !== null && d[s.key] !== undefined)
        .map((s) => ({
          color: css(s.token), value: num(d[s.key], opts.decimals ?? 2), name: s.label,
        }));
      for (const extra of (opts.extraRows ? opts.extraRows(d) : [])) rows.push(extra);
      showTip(ev.clientX ?? box.left + x(i), ev.clientY ?? box.top + M.top, d.date, rows);
    };
    band.addEventListener("pointermove", show);
    band.addEventListener("focus", show);
    band.addEventListener("pointerleave", () => { hair.setAttribute("opacity", 0); hideTip(); });
    band.addEventListener("blur", () => { hair.setAttribute("opacity", 0); hideTip(); });
    root.append(band);
  });
  return root;
}
</script>
<script>
/* ---------- heat scale ---------- */
// At or below this many instances, a session's rate is mostly noise.
const THIN_EVIDENCE = 2;

const BINS = [
  { max: 0.75, token: "--heat-1", label: "\\u2264 0.75" },
  { max: 1.5, token: "--heat-2", label: "0.75\\u20131.5" },
  { max: 3, token: "--heat-3", label: "1.5\\u20133" },
  { max: 6, token: "--heat-4", label: "3\\u20136" },
  { max: Infinity, token: "--heat-5", label: "> 6" },
];
const binOf = (rate) => BINS.find((b) => rate <= b.max) || BINS[BINS.length - 1];

function heatGrid(model) {
  const dates = model.dates;
  const grid = el("div", { class: "heat",
    style: `grid-template-columns: max-content repeat(${dates.length}, minmax(24px, 1fr))` });
  grid.append(el("div", { class: "heat-label" }));
  for (const d of dates) grid.append(el("div", { class: "heat-date", text: tinyDate(d) }));

  // One tab stop for the whole grid, arrow keys within it. Giving every cell
  // tabindex=0 puts the great majority of the page's focus stops inside this one
  // table — reaching the section below it then takes a press of Tab per cell.
  const cells = [];
  for (const cat of model.categories) {
    const label = el("div", { class: "heat-label", title: cat.category }, [
      el("span", { class: "sev", text: `s${cat.severity}` }),
      el("span", { class: "nm", text: cat.category }),
    ]);
    grid.append(label);
    const row = [];
    for (const point of cat.series) {
      // The first cell of the first row is the grid's single tab stop; `cells`
      // alone is still empty for every cell of that first row.
      const cell = el("div", { class: "cell",
                               tabindex: cells.length || row.length ? -1 : 0 });
      cell.setAttribute("role", "gridcell");
      cell.setAttribute("aria-label", `${cat.category}, ${point.date}, `
        + (point.state === "seen" ? `${point.rate} per 1,000 words`
          : point.state === "clean" ? "clean"
          : point.state === "untested" ? "never came up" : "not tracked yet"));
      row.push(cell);
      cell.dataset.state = point.state;
      if (point.state === "seen") {
        cell.style.background = `var(${binOf(point.rate).token})`;
        // Thin evidence, less ink. A cell built on one or two instances is a
        // different kind of number from one built on twenty, and colouring
        // them alike invites reading a gradient that is mostly chance.
        if (point.occurrences <= THIN_EVIDENCE) cell.style.opacity = "0.45";
      }
      else if (point.state === "clean") cell.style.background = "var(--heat-0)";
      const rows = point.state === "seen"
        ? [{ value: num(point.rate), name: "per 1,000 words" },
           { value: `${point.occurrences}\\u00d7`, name: `in ${int(point.reliable_words)} words` }]
        : [{ value: point.state === "clean" ? "0" : "\\u2014",
             name: point.state === "clean" ? "clean \\u2014 the structure came up and was right"
               : point.state === "untested" ? "never came up this session \\u2014 not measured"
               : "not tracked yet" }];
      const show = (ev) => showTip(ev.clientX ?? 0, ev.clientY ?? 0,
                                   `${cat.category} \\u00b7 ${point.date}`, rows);
      cell.addEventListener("pointermove", show);
      cell.addEventListener("focus", (ev) => {
        const b = cell.getBoundingClientRect();
        showTip(b.right, b.top, `${cat.category} \\u00b7 ${point.date}`, rows);
      });
      cell.addEventListener("pointerleave", hideTip);
      cell.addEventListener("blur", hideTip);
      grid.append(cell);
    }
    cells.push(row);
  }

  const MOVES = {
    ArrowRight: [0, 1], ArrowLeft: [0, -1], ArrowDown: [1, 0], ArrowUp: [-1, 0],
  };
  grid.setAttribute("role", "grid");
  grid.setAttribute("aria-label", "Mistake rate by category and session");
  grid.addEventListener("keydown", (event) => {
    const move = MOVES[event.key];
    const home = event.key === "Home", end = event.key === "End";
    if (!move && !home && !end) return;
    let position = null;
    cells.forEach((row, y) => {
      const x = row.indexOf(document.activeElement);
      if (x >= 0) position = [y, x];
    });
    if (!position) return;
    const [y, x] = position;
    const target = home ? [y, 0] : end ? [y, cells[y].length - 1] : [y + move[0], x + move[1]];
    const next = (cells[target[0]] || [])[target[1]];
    if (!next) return;
    event.preventDefault();
    document.activeElement.setAttribute("tabindex", "-1");
    next.setAttribute("tabindex", "0");
    next.focus();
  });
  return grid;
}

function heatTable(model) {
  const table = el("table");
  table.append(el("caption", { text:
    "Rate per 1,000 reliable words. \\u201c0\\u201d = the structure came up and was right; "
    + "\\u201c\\u2014\\u201d = it never came up, so nothing was measured." }));
  const head = el("tr", {}, [el("th", { text: "Mistake" })]);
  for (const d of model.dates) head.append(el("th", { text: tinyDate(d) }));
  table.append(el("thead", {}, [head]));
  const body = el("tbody");
  for (const cat of model.categories) {
    const tr = el("tr", {}, [el("th", { scope: "row", text: cat.category })]);
    for (const p of cat.series)
      tr.append(el("td", { text: p.state === "seen" ? num(p.rate)
                                 : p.state === "clean" ? "0" : "\\u2014" }));
    body.append(tr);
  }
  table.append(body);
  return el("div", { class: "table-wrap" }, [table]);
}
</script>
<script>
/* ---------- sparkline for one category ---------- */
function sparkline(width, cat, top, height = 36) {
  const H = height, pad = 3;
  const points = cat.series;
  const x = (i) => pad + (points.length < 2 ? 0 : (i / (points.length - 1)) * (width - pad * 2));
  const y = (v) => H - pad - (top > 0 ? (v / top) * (H - pad * 2) : 0);
  const root = svg("svg", { viewBox: `0 0 ${width} ${H}`, width, height: H,
                            "aria-hidden": "true" });
  root.append(svg("line", { x1: 0, x2: width, y1: H - pad, y2: H - pad,
                            stroke: css("--grid"), "stroke-width": 1 }));
  const color = css("--series-1");
  let run = [];
  const flush = () => {
    if (run.length > 1)
      root.append(svg("path", { d: "M" + run.map((p) => `${p[0]},${p[1]}`).join("L"),
                                fill: "none", stroke: color, "stroke-width": 2,
                                "stroke-linejoin": "round", "stroke-linecap": "round" }));
    else if (run.length === 1)
      root.append(svg("circle", { cx: run[0][0], cy: run[0][1], r: 2, fill: color }));
    run = [];
  };
  points.forEach((p, i) => {
    if (p.state === "seen") run.push([x(i), y(p.rate)]);
    else if (p.state === "clean") { run.push([x(i), y(0)]); }
    else flush();                                   // untested breaks the line, never a zero
  });
  flush();
  const lastSeen = [...points].reverse().find((p) => p.state === "seen" || p.state === "clean");
  if (lastSeen) {
    const i = points.lastIndexOf(lastSeen);
    root.append(svg("circle", { cx: x(i), cy: y(lastSeen.state === "seen" ? lastSeen.rate : 0),
                                r: 4, fill: color, stroke: css("--surface"),
                                "stroke-width": 2 }));
  }
  return root;
}

/* memory.md is written for a person, so it carries inline markdown. Rendered as
   preformatted text it showed the syntax instead, asterisks and backticks and
   all.
   Tokenised into real elements — and every piece of content set with
   textContent, never innerHTML, because this is the owner's own prose and the
   page's rule is that text is data. */
function inlineMarkdown(text) {
  const frag = document.createDocumentFragment();
  const pattern = /\\*\\*([^*]+)\\*\\*|`([^`]+)`|(?<![\\w*])\\*([^*\\n]+)\\*(?![\\w*])/g;
  let last = 0, match;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) frag.append(document.createTextNode(text.slice(last, match.index)));
    const [tag, body] = match[1] !== undefined ? ["strong", match[1]]
      : match[2] !== undefined ? ["code", match[2]]
      : ["em", match[3]];
    const node = document.createElement(tag);
    node.textContent = body;
    frag.append(node);
    last = pattern.lastIndex;
  }
  if (last < text.length) frag.append(document.createTextNode(text.slice(last)));
  return frag;
}

function prose(text, cls = "prose") {
  const node = el("div", { class: cls });
  node.append(inlineMarkdown(text));
  return node;
}

function example(ex) {
  const row = el("div", { class: "ex" });
  row.append(el("span", { class: "wrong", text: ex.wrong }));
  row.append(el("span", { class: "arrow", text: "\\u2192" }));
  const right = el("span", { class: "right" });
  right.append(inlineMarkdown(ex.right));       // corrections carry **emphasis**
  row.append(right);
  if (ex.date) row.append(el("span", { class: "when",
    text: ex.source ? `${ex.date} \\u00b7 ${ex.source}` : ex.date }));
  return row;
}

function noteBlock(note) {
  const body = el("div");
  if (note.examples.length) {
    body.append(el("div", { class: "note-head", text: "Examples" }));
    body.append(el("div", { class: "ex-list" }, note.examples.map(example)));
  }
  // Status carries the one thing the CSV does not: the rule-18 `!` flag and
  // what was decided about it. The other four header fields are the card's own
  // numbers retold in prose, and are left out — see `_parse_note`.
  if (note.status) {
    body.append(el("div", { class: "note-head", text: "Status" }));
    body.append(prose(note.status, "status"));
  }
  if (note.notes || note.rest.length) {
    body.append(el("div", { class: "note-head", text: "Notes" }));
    if (note.notes) body.append(prose(note.notes));
    for (const paragraph of note.rest) body.append(prose(paragraph));
  }
  if (note.decisions.length) {
    const history = el("details", { style: "border-top:none;margin-top:6px" }, [
      el("summary", { text: `Changes of approach (${note.decisions.length})` }),
    ]);
    for (const decision of note.decisions) {
      const block = el("div", { class: "decision" });
      const title = el("div", { class: "dt" });
      title.append(inlineMarkdown(decision.title));
      block.append(title);
      if (decision.body) block.append(prose(decision.body));
      history.append(block);
    }
    body.append(history);
  }
  return body;
}

const DIRECTION = {
  improving: { token: "--good", text: "improving" },
  worsening: { token: "--critical", text: "worsening" },
  steady: { token: "--muted", text: "steady" },
  "n/a": { token: "--muted", text: "too few sessions" },
  // The rate moved, but on these counts the move cannot be told from chance.
  // Colouring it green or red would be picking a side of a coin flip.
  "not separable yet": { token: "--muted", text: "too few instances to tell" },
};

function patternDetail(cat) {
  const body = el("div", { class: "pdetail" });

  // The chart is scaled to this pattern alone. Shared across every pattern it
  // takes its scale from the worst of them, which draws all the rest as
  // near-straight lines along the baseline.
  const own = Math.max(...cat.series.filter((p) => p.state === "seen")
    .map((p) => p.rate), 0) || 1;
  const plot = el("div", { class: "plot", style: "max-width:560px" });
  body.append(plot);
  responsive(plot, (w) => sparkline(w, cat, own, 96));
  body.append(el("div", { class: "detail", style: "margin-top:2px",
    text: `scaled to this pattern's own range, 0 to ${num(own)} per 1,000 words` }));

  const stat = (label, value) => el("div", {}, [
    el("div", { class: "k", text: label }), el("div", { class: "v", text: value }),
  ]);
  const stats = el("div", { class: "mstats" }, [
    stat("Latest rate", cat.latest_rate === null ? "not measured"
      : num(cat.latest_rate) + (cat.latest_count ? ` (${cat.latest_count} instances)` : "")),
    stat("Impact", num(cat.impact)),
    stat("Tier", `severity ${cat.severity} \u00b7 ${cat.tier}`),
    stat("Recency-weighted rate", num(cat.weighted_rate)),
    stat("Measured in", `${cat.sessions_measured} of `
      + `${cat.series.filter((p) => p.state !== "before").length} sessions`),
    stat("First seen", cat.first_seen),
    stat("Last seen", cat.last_seen || "never"),
  ]);
  if (cat.drill) {
    stats.append(stat("Drill blocks", `${cat.drill.attempts}, last ${cat.drill.last_date}`));
    stats.append(stat("Drill accuracy", cat.drill.accuracy === null ? "\u2014"
      : `${Math.round(cat.drill.accuracy * 100)}% `
        + `(${cat.drill.correct}/${cat.drill.attempted})`));
  }
  body.append(stats);

  if (cat.note) body.append(noteBlock(cat.note));
  body.append(el("a", { class: "permalink", href: `#${cat.slug}`,
                        text: "\u00b6 link to this pattern" }));
  return body;
}
</script>
<script>
/* ---------- page ---------- */
const H = MODEL.headline;
document.getElementById("meta").textContent =
  `${H.sessions} sessions \\u00b7 ${H.first_date} \\u2192 ${H.last_date} `
  + `\\u00b7 built ${MODEL.generated_full}`;

/* headline */
(() => {
  const host = document.getElementById("headline");
  const worse = H.delta !== null && H.delta > 0;
  const deltaNode = H.delta === null ? null : el("div", { class: "delta",
      style: `color: var(${worse ? "--critical" : "--good"})` }, [
    el("span", { text: worse ? "\\u25b2" : "\\u25bc" }),
    el("span", { text: `${Math.abs(H.delta).toFixed(2)} ${worse ? "worse" : "better"} than the `
      + `${H.baseline_window}-session average before it (${num(H.baseline_mean)})` }),
  ]);
  const scoreNotes = H.score_movement.filter((s) => s.distinct === 1).map((s) => s.label);

  // What actually moved it. The total rate is the sum of the per-category
  // rates, so naming the biggest mover is arithmetic — and without it the
  // delta above is an alarm with no cause attached.
  const top = H.drivers[0];
  const driverNode = top && H.delta !== null
      && Math.abs(top.change) >= Math.abs(H.delta) * 0.25
    ? el("div", { class: "driver" }, [
        el("span", { text: "Mostly " }),
        el("b", { text: top.category }),
        el("span", { text: `: ${num(top.before)} \\u2192 ${num(top.after)}, `
          + `${top.change > 0 ? "+" : "\\u2212"}${num(Math.abs(top.change))} of the `
          + `${H.delta > 0 ? "rise" : "fall"}` }),
        H.drivers[1] ? el("span", { text: `. Then ${H.drivers[1].category} `
          + `(${H.drivers[1].change > 0 ? "+" : "\\u2212"}`
          + `${num(Math.abs(H.drivers[1].change))}).` }) : el("span", { text: "." }),
      ])
    : null;

  // How many trends can be told from counting noise at all. Reporting the raw
  // improving/worsening split here meant reporting coin flips.
  const unsure = H.directions["not separable yet"] || 0;
  const tail = [
    `${unsure} moved but not beyond chance`,
    `${H.directions.steady || 0} steady`,
    `${H.directions["n/a"] || 0} too new to say`,
  ].join(", ");

  host.append(el("div", { class: "hero-row" }, [
    el("div", {}, [
      el("div", { class: "hero-val", text: num(H.rate) }),
      el("div", { class: "hero-label",
        text: `tracked mistakes per 1,000 reliable words \\u00b7 ${H.rate_date}` }),
      deltaNode,
      driverNode,
    ]),
    el("div", { class: "tiles" }, [
      el("div", {}, [
        el("div", { class: "tile-label", text: "Level" }),
        el("div", { class: "tile-val",
          text: (MODEL.level.current || {}).label || H.cefr || "\\u2014" }),
        el("div", { class: "tile-note", text: MODEL.level.target
          ? `next is ${MODEL.level.target.label}`
          : `${H.cefr} in scores_history.csv` }),
      ]),
      el("div", {}, [
        el("div", { class: "tile-label", text: "Recordings analysed" }),
        el("div", { class: "tile-val", text: String(H.sessions) }),
        el("div", { class: "tile-note", text: `${MODEL.categories.length} mistakes tracked` }),
      ]),
      // Cumulative totals of minutes and words used to sit here. They only
      // ever go up and they prompt nothing; the denominator they described is
      // in the reliability table, next to the share of it that survived.
      el("div", {}, [
        el("div", { class: "tile-label", text: "Measurable trends" }),
        el("div", { class: "tile-val", text: `${H.separable} of ${H.tracked}` }),
        el("div", { class: "tile-note", text: tail }),
      ]),
      el("div", {}, [
        el("div", { class: "tile-label", text: "Last analysed" }),
        el("div", { class: "tile-val", text: H.days_since_analysis === null ? "\\u2014"
          : H.days_since_analysis === 0 ? "today"
          : `${H.days_since_analysis} day${H.days_since_analysis === 1 ? "" : "s"} ago` }),
        el("div", { class: "tile-note", text: H.unanalysed.length
          ? `${H.unanalysed[H.unanalysed.length - 1]} recorded, not analysed yet`
          : H.last_date }),
      ]),
    ]),
  ]));
  if (scoreNotes.length) host.append(el("div", { class: "note", text:
    `Self-assessed scores have not moved: ${scoreNotes.join(", ")} `
    + `${scoreNotes.length === 1 ? "has" : "have"} taken one value across all `
    + `${H.sessions} sessions. They are a coarse 0\\u201310 judgment and change on a scale of `
    + `months \\u2014 the mistake rate above is the number that actually moves, so it leads here.` }));
})();

/* do this next */
(() => {
  const host = document.getElementById("actions");
  if (!MODEL.actions.length) { host.hidden = true; return; }
  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Do this next" }),
      el("div", { class: "sub", text:
        "Nothing new here \\u2014 this is the crossing of the rung a pattern fails on, its "
        + "impact ranking and what the schedule says is late, which otherwise means reading "
        + "three sections against each other. Every line says where it came from." }),
    ]),
  ]));

  const list = el("div", { class: "actions" });
  MODEL.actions.forEach((action, index) => {
    list.append(el("div", { class: "action-row" }, [
      el("div", { class: "action-n", text: String(index + 1) }),
      el("div", {}, [
        el("div", { class: "action-title", text: action.title }),
        el("div", { class: "action-detail", text: action.detail }),
        el("a", { class: "action-link", href: `#${action.anchor}`,
                  text: `\\u2193 ${SECTION_LABELS[action.anchor] || action.anchor}` }),
      ]),
    ]));
  });
  host.append(list);
})();

/* trend */
(() => {
  const host = document.getElementById("trend");
  const series = [
    { key: "rate", token: "--series-1", label: "all tracked categories" },
    { key: "cohort_rate", token: "--series-2",
      label: `the ${H.cohort_size} tracked since day one` },
  ];
  const words = MODEL.sessions.map((s) => s.reliable_words).filter(Boolean);
  const plot = el("div", { class: "plot" });
  const table = el("div", { hidden: "" });
  const toggle = el("button", { class: "ghost", type: "button", text: "Table view" });

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Mistake rate over time" }),
      el("div", { class: "sub", text:
        "Occurrences per 1,000 reliable words. The two lines differ because the number of "
        + "tracked categories grows as coaching finds new patterns \\u2014 the orange line counts "
        + "the same categories at both ends, so it is the one comparable across the whole "
        + "history." }),
    ]),
    toggle,
  ]));
  const chartSide = el("div", {});
  host.append(chartSide);
  chartSide.append(el("div", { class: "legend" }, series.map((s) =>
    el("div", { class: "legend-item" }, [
      el("span", { class: "key-line", style: `background: var(${s.token})` }),
      el("span", { text: s.label }),
    ]))));
  chartSide.append(plot);
  chartSide.append(el("div", {}, [
    el("div", { class: "legend", style: "margin:12px 0 2px" }, [
      el("div", { class: "legend-item" }, [
        el("span", { class: "key-box", style: "background: var(--quality)" }),
        el("span", { text: "share of words whisper was unsure of \\u2014 taller is worse" }),
      ]),
    ]),
    (() => {
      const strip = el("div", { class: "strip" });
      const quality = new Map(MODEL.speech.sessions.map((q) => [q.date, q]));
      for (const s of MODEL.sessions) {
        // The WORD share, not the line share: a two-word "Yeah." weighs as much
        // as a full sentence by line, and that is where whisper is least sure.
        // fluency.warn_if_unreliable fires on this one for the same reason.
        const q = quality.get(s.date);
        const share = q ? q.word_share : null;
        const cell = el("div", { class: "strip-cell", tabindex: 0,
          style: `height:${share === null ? 2 : 3 + Math.round(share * 34)}px` });
        const rows = [
          { value: share === null ? "\\u2014" : `${Math.round(share * 100)}%`,
            name: "of words were low-confidence" },
          { value: q && q.line_share !== null ? `${Math.round(q.line_share * 100)}%` : "\\u2014",
            name: "of lines \\u2014 the weaker reading" },
          { value: int(s.reliable_words), name: "reliable words" },
          { value: s.mode || "\\u2014", name: "run mode" },
        ];
        const show = (ev) => showTip(ev.clientX ?? 0, ev.clientY ?? 0, s.date, rows);
        cell.addEventListener("pointermove", show);
        cell.addEventListener("focus", () => {
          const b = cell.getBoundingClientRect(); showTip(b.right, b.top, s.date, rows);
        });
        cell.addEventListener("pointerleave", hideTip);
        cell.addEventListener("blur", hideTip);
        strip.append(cell);
      }
      return el("div", { class: "strip-wrap" }, [strip]);
    })(),
  ]));
  host.append(el("div", { class: "note", text:
    `Sessions range from ${int(Math.min(...words))} to ${int(Math.max(...words))} reliable words. `
    + "The rate already divides by that, but a short session measures it less precisely, and a "
    + "session with many low-confidence lines is a weaker measurement of everything above." }));
  host.append(table);

  responsive(plot, (w) => lineChart(w, MODEL.sessions, series, {
    extraRows: (d) => [
      { value: int(d.reliable_words), name: "reliable words" },
      { value: String(d.categories_tracked), name: "categories tracked" },
    ],
  }));

  toggle.addEventListener("click", () => {
    const showTable = chartSide.hidden;
    chartSide.hidden = !showTable;
    table.hidden = showTable;
    toggle.textContent = showTable ? "Table view" : "Chart view";
    if (!table.hidden && !table.dataset.built) {
      table.dataset.built = "1";
      const t = el("table");
      t.append(el("thead", {}, [el("tr", {}, [
        el("th", { text: "Session" }), el("th", { text: "All tracked" }),
        el("th", { text: "Day-one categories" }), el("th", { text: "Occurrences" }),
        el("th", { text: "Reliable words" }), el("th", { text: "Categories" }),
        el("th", { text: "Low-confidence lines" }),
      ])]));
      const body = el("tbody");
      for (const s of MODEL.sessions) body.append(el("tr", {}, [
        el("th", { scope: "row", text: s.date }),
        el("td", { text: num(s.rate) }), el("td", { text: num(s.cohort_rate) }),
        el("td", { text: String(s.occurrences) }), el("td", { text: int(s.reliable_words) }),
        el("td", { text: `${s.categories_measured}/${s.categories_tracked} measured` }),
        el("td", { text: s.low_confidence_share === null ? "\\u2014"
          : `${Math.round(s.low_confidence_share * 100)}%` }),
      ]));
      t.append(body);
      table.append(el("div", { class: "table-wrap" }, [t]));
    }
  });
})();

/* heatmap */
(() => {
  const host = document.getElementById("heatmap");
  const chart = el("div", {}, [el("div", { class: "heat-scroll" }, [heatGrid(MODEL)])]);
  const table = el("div", { hidden: "" }, [heatTable(MODEL)]);
  const toggle = el("button", { class: "ghost", type: "button", text: "Table view" });
  toggle.addEventListener("click", () => {
    const showTable = chart.hidden;
    chart.hidden = !showTable;
    table.hidden = showTable;
    toggle.textContent = showTable ? "Table view" : "Chart view";
  });
  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Every tracked mistake, session by session" }),
      el("div", { class: "sub", text:
        "Ranked by impact. A hollow cell means the structure never came up that session, so "
        + "nothing was measured \\u2014 it is not a clean session." }),
    ]),
    toggle,
  ]));
  const legend = el("div", { class: "legend" });
  legend.append(el("div", { class: "legend-item" }, [
    el("span", { class: "key-box", style: "background: var(--heat-0)" }),
    el("span", { text: "clean (0)" }),
  ]));
  for (const bin of BINS) legend.append(el("div", { class: "legend-item" }, [
    el("span", { class: "key-box", style: `background: var(${bin.token})` }),
    el("span", { text: bin.label }),
  ]));
  legend.append(el("div", { class: "legend-item" }, [
    el("span", { class: "key-box",
                 style: "background: var(--heat-3); opacity: 0.45" }),
    el("span", { text: `≤ ${THIN_EVIDENCE} instances — too few to read` }),
  ]));
  legend.append(el("div", { class: "legend-item" }, [
    el("span", { class: "key-box", style: "box-shadow: inset 0 0 0 1px var(--hollow)" }),
    el("span", { text: "never came up" }),
  ]));
  chart.prepend(legend);          // the colour scale belongs to the grid, not the card
  host.append(chart);
  host.append(table);
})();



/* ---------- asking questions ---------- */
function barList(items, { max, label, value, tip }) {
  const top = max || Math.max(...items.map(value), 1);
  const wrap = el("div", { class: "bars" });
  for (const item of items) {
    const row = el("div", { class: "bar-row", tabindex: 0 }, [
      el("span", { class: "bar-label", text: label(item) }),
      el("div", { class: "bar-track" }, [
        el("i", { style: `width:${Math.max(2, (value(item) / top) * 100)}%` }),
      ]),
      el("span", { class: "bar-val", text: String(value(item)) }),
    ]);
    if (tip) {
      const rows = tip(item);
      const show = (ev) => showTip(ev.clientX ?? 0, ev.clientY ?? 0, label(item), rows);
      row.addEventListener("pointermove", show);
      row.addEventListener("focus", () => {
        const b = row.getBoundingClientRect(); showTip(b.right, b.top, label(item), rows);
      });
      row.addEventListener("pointerleave", hideTip);
      row.addEventListener("blur", hideTip);
    }
    wrap.append(row);
  }
  return wrap;
}

(() => {
  const host = document.getElementById("asking");
  const A = MODEL.asking;
  if (!A.totals.runs && !A.drill_totals.items && !A.practice.length) {
    host.hidden = true; return;
  }
  const share = (met, total) => total ? `${Math.round((met / total) * 100)}%` : "\\u2014";

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Asking questions" }),
      el("div", { class: "sub", text:
        "The half of this project a recording cannot measure. Whether a question was well "
        + "asked is not in a transcript \\u2014 it needs a situation, a reply that withholds "
        + "something, and criteria written in advance \\u2014 so nothing here has an "
        + "unmonitored-speech rung, and every score is small enough that it is shown next to "
        + "the number it divides." }),
    ]),
  ]));

  /* the headline numbers */
  const tiles = el("div", { class: "tiles", style: "margin-bottom:22px" }, [
    el("div", {}, [
      el("div", { class: "tile-label", text: "Scenario criteria met" }),
      el("div", { class: "tile-val", text: share(A.totals.met, A.totals.total) }),
      el("div", { class: "tile-note",
        text: `${A.totals.met} of ${A.totals.total} across ${A.totals.runs} runs` }),
    ]),
    el("div", {}, [
      el("div", { class: "tile-label", text: "By session" }),
      el("div", { class: "tile-val",
        text: A.by_date.map((d) => `${d.met}/${d.total}`).join(" \\u2192 ") || "\\u2014" }),
      el("div", { class: "tile-note",
        text: A.by_date.map((d) => d.date.slice(5)).join(" \\u2192 ") }),
    ]),
    el("div", {}, [
      el("div", { class: "tile-label", text: "Warm-up drill items tried" }),
      el("div", { class: "tile-val",
        text: `${A.drill_totals.attempted} of ${A.drill_totals.items}` }),
      el("div", { class: "tile-note", text: "too few to score" }),
    ]),
    el("div", {}, [
      el("div", { class: "tile-label", text: "Typed words in this mode" }),
      el("div", { class: "tile-val", text: int(A.practice_totals.words) }),
      el("div", { class: "tile-note",
        text: `${A.practice_totals.sessions} sessions, `
          + `${A.practice_totals.errors} tracked errors` }),
    ]),
  ]);
  host.append(tiles);

  /* which criteria fail, across scenarios */
  if (A.criteria.length) {
    host.append(el("h3", { text: "Which criteria fail",
      style: "font-size:13px;font-weight:600;margin:4px 0 4px" }));
    host.append(el("div", { class: "sub", style: "margin-bottom:10px", text:
      "The one dimension with repeats \\u2014 the same criterion failing across different "
      + "situations is a pattern rather than a property of one of them." }));
    host.append(barList(A.criteria, {
      label: (c) => c.criterion,
      value: (c) => c.count,
      tip: (c) => c.scenarios.map((name) => ({ value: "", name })),
    }));
  }

  /* every run */
  host.append(el("h3", { text: "Every scenario run",
    style: "font-size:13px;font-weight:600;margin:26px 0 10px" }));
  const runs = el("table");
  runs.append(el("thead", {}, [el("tr", {}, [
    el("th", { text: "Date" }), el("th", { class: "rung", text: "Scenario" }),
    el("th", { class: "rung", text: "Register" }), el("th", { class: "rung", text: "Function" }),
    el("th", { text: "Score" }), el("th", { class: "where", text: "Failed" }),
  ])]));
  const runBody = el("tbody");
  for (const r of A.runs) {
    runBody.append(el("tr", {}, [
      el("th", { scope: "row", text: r.date }),
      el("td", { class: "rung" }, [
        el("div", { text: r.scenario }),
        el("div", { class: "detail", text: r.pack }),
      ]),
      el("td", { class: "rung", text: r.register || "\\u2014" }),
      el("td", { class: "rung", text: r.function || "\\u2014" }),
      el("td" , {}, [el("div", { class: "cellrow" }, [
        el("span", { class: "dot",
          style: `background: var(${r.clean ? "--good" : r.met ? "--warning" : "--critical"})` }),
        el("span", { text: `${r.met}/${r.total}` }),
      ])]),
      el("td", { class: "where", text: r.failed.join(", ") || "nothing" }),
    ]));
  }
  runs.append(runBody);
  host.append(el("div", { class: "table-wrap" }, [runs]));

  const groupable = [...A.registers, ...A.functions].filter((g) => g.enough);
  if (!groupable.length) host.append(el("div", { class: "note", text:
    `${A.totals.runs} runs across ${A.registers.length} registers and ${A.functions.length} `
    + "functions \\u2014 close to one run each, so neither is aggregated into a score here. "
    + `${A.min_runs_to_group} runs in a group is the minimum for the number to mean anything; `
    + "until then the per-run table above is the whole of the evidence." }));

  /* the warm-up drills */
  if (A.drills.length) {
    host.append(el("h3", { text: "Warm-up drill blocks",
      style: "font-size:13px;font-weight:600;margin:26px 0 10px" }));
    const t = el("table");
    t.append(el("thead", {}, [el("tr", {}, [
      el("th", { text: "Drill" }), el("th", { class: "rung", text: "Pattern" }),
      el("th", { text: "Offered" }), el("th", { text: "Attempted" }),
      el("th", { text: "Correct" }), el("th", { text: "Last run" }),
    ])]));
    const body = el("tbody");
    for (const d of A.drills) {
      body.append(el("tr", {}, [
        el("th", { scope: "row", text: d.category }),
        el("td", { class: "rung", text: `${d.attempts} block(s)` }),
        el("td", { text: String(d.items) }),
        el("td" , {}, [el("div", { class: "cellrow", style: "justify-content:flex-end" }, [
          d.attempted ? null : el("span", { class: "dot",
            style: "box-shadow: inset 0 0 0 1px var(--hollow)" }),
          el("span", { text: String(d.attempted) }),
        ])]),
        el("td", { text: String(d.correct) }),
        el("td", { text: d.last_date }),
      ]));
    }
    t.append(body);
    host.append(el("div", { class: "table-wrap" }, [t]));
    host.append(el("div", { class: "note", text:
      `${A.drill_totals.attempted} of ${A.drill_totals.items} items offered have ever been `
      + "answered: one block ended early and the next was skipped by request. There is no "
      + "accuracy to report here \\u2014 the number in the Correct column is out of Attempted, "
      + "not out of Offered." }));
  }

  /* typed dialogue in this mode */
  if (A.practice.length) {
    host.append(el("h3", { text: "Typed dialogue",
      style: "font-size:13px;font-weight:600;margin:26px 0 10px" }));
    const t = el("table");
    t.append(el("thead", {}, [el("tr", {}, [
      el("th", { text: "Date" }), el("th", { class: "rung", text: "Focus" }),
      el("th", { text: "Words" }), el("th", { text: "Errors" }),
      el("th", { text: "Per 1,000" }), el("th", { text: "Re-productions" }),
    ])]));
    const body = el("tbody");
    for (const s of A.practice) {
      body.append(el("tr", {}, [
        el("th", { scope: "row", text: s.date }),
        el("td", { class: "rung" }, [
          el("div", { text: s.focus || "\\u2014" }),
          el("div", { class: "detail",
            text: s.breakdown.map((b) => `${b.category} \\u00d7${b.count}`).join(", ") }),
        ]),
        el("td", { text: int(s.words) }),
        el("td", { text: String(s.errors) }),
        el("td", { text: num(s.rate) }),
        el("td", { text: String(s.reproductions) }),
      ]));
    }
    t.append(body);
    host.append(el("div", { class: "table-wrap" }, [t]));
    host.append(el("div", { class: "note", text:
      "Words and errors are this mode's only, never pooled with conversation practice: an "
      + "asking session contributes words to the denominator while giving most grammar "
      + "categories no chance to appear. \\u201cRe-productions\\u201d counts the corrections "
      + "that landed; the column recording the ones asked for and missed was added after the "
      + "earliest sessions here, so those read as none rather than as unmeasured." }));
  }
})();

/* ---------- question patterns and untracked forms ---------- */
(() => {
  const host = document.getElementById("askpatterns");
  const A = MODEL.asking;
  if (!A.patterns.length && !A.provisional.length && !A.register_notes.length) {
    host.hidden = true; return;
  }

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Question patterns being tracked" }),
      el("div", { class: "sub", text:
        "asking_memory.md, by hand \\u2014 the counterpart of memory.md for a skill the "
        + "recording cannot see." }),
    ]),
  ]));

  if (A.patterns.length) {
    const t = el("table");
    t.append(el("thead", {}, [el("tr", {}, [
      el("th", { text: "Pattern" }), el("th", { class: "rung", text: "Status" }),
      el("th", { text: "Sessions with an error" }), el("th", { text: "Last error" }),
    ])]));
    const body = el("tbody");
    for (const p of A.patterns) {
      const active = p.status.toLowerCase().startsWith("active");
      body.append(el("tr", {}, [
        el("th", { scope: "row" }, [
          el("div", { class: "cellrow" }, [
            el("span", { text: p.name }),
            p.name === A.worst
              ? el("span", { class: "chip", text: "watch this one" }) : null,
          ]),
        ]),
        el("td", { class: "rung" }, [el("div", { class: "cellrow" }, [
          el("span", { class: "dot",
            style: `background: var(${active ? "--critical" : "--good"})` }),
          el("span", { text: p.status || "\\u2014" }),
        ])]),
        el("td", { text: p.sessions_with_error || "\\u2014" }),
        el("td", { text: p.last_error || "\\u2014" }),
      ]));
    }
    t.append(body);
    host.append(el("div", { class: "table-wrap" }, [t]));
  }

  if (A.provisional.length) {
    host.append(el("h3", { text: "Untracked forms",
      style: "font-size:13px;font-weight:600;margin:26px 0 8px" }));
    host.append(el("div", { class: "sub", style: "margin-bottom:10px", text:
      `Corrected in a session but covered by no category yet. Seen in `
      + `${A.promote_after} separate sessions it stops being a slip and earns a category `
      + "name and a drill of its own." }));
    const t = el("table");
    t.append(el("thead", {}, [el("tr", {}, [
      el("th", { text: "Form" }), el("th", { text: "Sessions" }), el("th", { text: "Times" }),
      el("th", { text: "Last seen" }), el("th", { class: "where", text: "" }),
    ])]));
    const body = el("tbody");
    for (const f of A.provisional) {
      body.append(el("tr", {}, [
        el("th", { scope: "row", text: f.name }),
        el("td", { text: String(f.sessions) }),
        el("td", { text: String(f.total) }),
        el("td", { text: f.last_seen }),
        el("td", { class: "where", text: f.ready ? "give it a category and a drill" : "" }),
      ]));
    }
    t.append(body);
    host.append(el("div", { class: "table-wrap" }, [t]));
  }

  if (A.register_notes.length) {
    const notes = el("details", {}, [
      el("summary", { text: `Register notes (${A.register_notes.length})` }),
    ]);
    for (const note of A.register_notes)
      notes.append(el("div", { class: "note", style: "margin-top:8px", text: note }));
    host.append(notes);
  }
})();

/* ---------- one small chart, own scale, gaps for what wasn't measured ---------- */
function smallLine(width, points, decimals) {
  const H = 58, pad = 4, left = 0;
  const values = points.map((p) => p.value).filter((v) => v !== null && v !== undefined);
  const top = Math.max(...values, 0) * 1.15 || 1;
  const x = (i) => left + pad + (points.length < 2 ? 0
    : (i / (points.length - 1)) * (width - left - pad * 2));
  const y = (v) => H - pad - (v / top) * (H - pad * 2);
  const root = svg("svg", { viewBox: `0 0 ${width} ${H}`, width, height: H });
  root.append(svg("line", { x1: left, x2: width, y1: H - pad, y2: H - pad,
                            stroke: css("--grid"), "stroke-width": 1 }));
  const color = css("--series-1");
  let run = [];
  const flush = () => {
    if (run.length > 1)
      root.append(svg("path", { d: "M" + run.map((p) => `${p[0]},${p[1]}`).join("L"),
                                fill: "none", stroke: color, "stroke-width": 2,
                                "stroke-linejoin": "round", "stroke-linecap": "round" }));
    else if (run.length === 1)
      root.append(svg("circle", { cx: run[0][0], cy: run[0][1], r: 2.5, fill: color }));
    run = [];
  };
  points.forEach((p, i) => {
    if (p.value === null || p.value === undefined) flush(); else run.push([x(i), y(p.value)]);
  });
  flush();
  const lastIndex = points.reduce(
    (best, p, i) => (p.value === null || p.value === undefined ? best : i), -1);
  if (lastIndex >= 0)
    root.append(svg("circle", { cx: x(lastIndex), cy: y(points[lastIndex].value), r: 4,
                                fill: color, stroke: css("--surface"), "stroke-width": 2 }));

  points.forEach((p, i) => {                       // a hit band per session, focusable
    const half = points.length < 2 ? width : (width - left - pad * 2) / (points.length - 1) / 2;
    const band = svg("rect", { x: Math.max(0, x(i) - half), y: 0,
                               width: Math.max(1, half * 2), height: H,
                               fill: "transparent", tabindex: 0 });
    const rows = [{
      value: p.value === null || p.value === undefined ? "not measured" : num(p.value, decimals),
      name: "",
    }];
    const show = (ev) => showTip(ev.clientX ?? 0, ev.clientY ?? 0, p.date, rows);
    band.addEventListener("pointermove", show);
    band.addEventListener("focus", () => {
      const b = band.getBoundingClientRect(); showTip(b.right, b.top, p.date, rows);
    });
    band.addEventListener("pointerleave", hideTip);
    band.addEventListener("blur", hideTip);
    root.append(band);
  });
  return root;
}

/* ---------- words to retire ---------- */
(() => {
  const host = document.getElementById("vocabulary");
  const V = MODEL.vocabulary;
  if (!V.rows || !V.rows.length) { host.hidden = true; return; }

  const MOVE = {
    rising: { token: "--critical", text: "still rising" },
    level: { token: "--warning", text: "not budging" },
    falling: { token: "--good", text: "falling" },
    // Said too rarely to have a direction — the same restraint the mistake
    // trends apply, for the same reason.
    "too few to tell": { token: "--muted", text: "too few to tell" },
    "never said": { token: "--muted", text: "never said" },
  };

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Words to retire" }),
      el("div", { class: "sub", text:
        "memory.md carries a table of phrases to stop using and what to say instead. It is "
        + "written every session and read every session, and nothing ever checked it \\u2014 "
        + "a standing instruction with no feedback loop, which is the kind of advice that "
        + "can be wrong for months without anyone noticing. Counted here over the reliable "
        + "lines of every archived session, worst first." }),
    ]),
  ]));

  const bars = (counts) => {
    const top = Math.max(...counts, 1);
    const wrap = el("div", { class: "spark-cells" });
    counts.forEach((n) => {
      const bar = el("i", { style: `height:${n ? Math.max(12, (n / top) * 100) : 6}%` });
      if (!n) bar.dataset.zero = "1";
      wrap.append(bar);
    });
    return wrap;
  };

  for (const row of V.rows) {
    const move = MOVE[row.movement] || MOVE.level;
    const detail = row.replacements.length
      ? "instead: " + row.replacements
          .map((r) => `${r.phrase} (${r.total}×, ${r.movement})`).join(", ")
      : "no replacement from the table has been said yet";
    const block = el("div", { class: "vrow" }, [
      el("div", {}, [
        el("div", { class: "vphrase", text: row.phrase }),
        el("div", { class: "vsub", text: detail }),
      ]),
      bars(row.counts),
      el("div", {}, [
        el("div", { class: "vmove", style: `color: var(${move.token})` }, [
          el("span", { class: "dot", style: `background: var(${move.token})` }),
          el("span", { text: move.text }),
        ]),
        el("div", { class: "vsub", style: "text-align:right",
                    text: `${row.total}× in all` }),
      ]),
    ]);
    const rows = [
      { value: String(row.total), name: "times in all" },
      { value: `${num(row.early, 2)} → ${num(row.late, 2)}`,
        name: "per 1,000 words, first half to second" },
    ];
    const show = (ev) => showTip(ev.clientX ?? 0, ev.clientY ?? 0, row.phrase, rows);
    block.addEventListener("pointermove", show);
    block.addEventListener("pointerleave", hideTip);
    host.append(block);
  }

  const notes = [];
  if (V.never_said.length) notes.push(
    `${V.never_said.length} entries in the table have never appeared in an archived `
    + `session: ${V.never_said.slice(0, 4).join(", ")}`
    + (V.never_said.length > 4 ? ", …" : "") + ".");
  notes.push("A count cannot tell a word used well from one leaned on \\u2014 a phrase can "
    + "be on the list for being vague rather than forbidden. Read it as a prompt to look. "
    + "Counts are on word boundaries over reliable lines only, so “cool” does not "
    + "collect “cooling”.");
  host.append(el("div", { class: "note", text: notes.join(" ") }));
})();

/* ---------- how it was spoken ---------- */
(() => {
  const host = document.getElementById("speech");
  const S = MODEL.speech;
  if (!S.sessions.length) { host.hidden = true; return; }

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "How it was spoken" }),
      el("div", { class: "sub", text:
        "Pace, hesitation and pauses \\u2014 measured over the reliable lines only, the same "
        + "population the grammar analysis uses." }),
    ]),
  ]));

  /* pace: one series per measurement basis, never joined across them */
  const paceSeries = S.pace.series.map((s, i) => ({
    key: s.key, label: `${s.label} \\u00b7 ${s.measured} session${s.measured === 1 ? "" : "s"}`,
    token: i === 0 ? "--series-1" : "--series-2",
  }));
  host.append(el("h3", { text: "Speaking pace",
    style: "font-size:13px;font-weight:600;margin:6px 0 8px" }));
  host.append(el("div", { class: "legend" }, paceSeries.map((s) =>
    el("div", { class: "legend-item" }, [
      el("span", { class: "key-line", style: `background: var(${s.token})` }),
      el("span", { text: s.label }),
    ]))));
  const pacePlot = el("div", { class: "plot" });
  host.append(pacePlot);
  responsive(pacePlot, (w) => lineChart(w, S.pace.rows, paceSeries, {
    decimals: 1,
    extraRows: (d) => [
      { value: num(d.speech_minutes, 1), name: "minutes of speech" },
      { value: int(d.reliable_words), name: "reliable words" },
    ],
  }));
  host.append(el("div", { class: "note", text:
    "Two lines because words per minute is measured against two different denominators, and "
    + "they are not comparable. Diarization hands over VAD-tight turns; without it whisper's "
    + "own segments swallow the pauses inside them \\u2014 the same speaker at the same speed "
    + "reads far faster one way than the other. The two recording modes alternate through "
    + "this history, so the honest chart is two series with gaps rather than one line with a "
    + `step in it. ${S.pace.unmeasured} backfilled session(s) are absent: they were counted `
    + "from an archived transcript, with no clock to measure time against." }));

  /* the small multiples */
  host.append(el("h3", { text: "Hesitation and pauses",
    style: "font-size:13px;font-weight:600;margin:26px 0 10px" }));
  const grid = el("div", { class: "metrics" });
  for (const metric of S.metrics) {
    const measured = metric.points.filter((p) => p.value !== null && p.value !== undefined);
    const latest = measured.length ? measured[measured.length - 1] : null;
    const first = measured.length ? measured[0] : null;
    const panel = el("div", { class: "metric" });
    panel.append(el("div", { class: "mlabel", text: metric.label }));
    panel.append(el("div", { class: "val" }, [
      el("span", { text: latest ? num(latest.value, metric.decimals) : "\\u2014" }),
      el("span", { class: "unit", text: ` ${metric.unit}` }),
    ]));
    if (latest && first && measured.length > 1 && first.value !== latest.value) {
      const down = latest.value < first.value;
      // Down is better for all four: fewer fillers, fewer crutch markers,
      // shorter and fewer pauses. Stated rather than assumed from the arrow.
      panel.append(el("div", { class: "delta-s",
        style: `color: var(${down ? "--good" : "--critical"})` }, [
        el("span", { text: down ? "\\u25bc" : "\\u25b2" }),
        el("span", { text: `${num(Math.abs(latest.value - first.value), metric.decimals)} `
          + `since ${first.date}` }),
      ]));
    }
    const plot = el("div", { class: "plot", style: "margin-top:8px" });
    panel.append(plot);
    responsive(plot, (w) => smallLine(w, metric.points, metric.decimals));
    panel.append(el("div", { class: "mnote", text: metric.solo_only
      ? `${metric.note} Solo recordings only.` : metric.note }));
    grid.append(panel);
  }
  host.append(grid);
  if (S.metrics.some((m) => m.solo_only)) host.append(el("div", { class: "note", text:
    "The two pause measures are blank for the diarized sessions by design, not by accident: "
    + "in a recording with another voice in it the gap between two of your lines is mostly "
    + "the other person talking, so the same number would mean two different things." }));
})();

/* ---------- how reliable each session was ---------- */
(() => {
  const host = document.getElementById("quality");
  const S = MODEL.speech;
  if (!S.sessions.length) { host.hidden = true; return; }
  const pct = (v) => v === null || v === undefined ? "\\u2014" : `${Math.round(v * 100)}%`;

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "How reliable each session was" }),
      el("div", { class: "sub", text:
        "Input quality, not speaking quality: high values mean the microphone, not the "
        + "speaker. It belongs here rather than in the charts above because when it moves, "
        + "every number on this page changes meaning \\u2014 a session that lost a quarter of "
        + "its words is a weaker measurement of all of them." }),
    ]),
  ]));

  host.append(el("div", { class: "notice", text: S.any_unreliable
    ? `At least one session is at or above the ${pct(S.warn_share)} word-share mark where `
      + "the pipeline stops treating it as comparable. Check the mic before reading anything "
      + "into that session's fluency."
    : `No session on record reaches the ${pct(S.warn_share)} word-share mark where the `
      + "pipeline warns that a session is not comparable. Read by line the numbers look far "
      + "far worse, but that mostly counts two-word replies, which is why "
      + "the word share is the one to act on." }));

  const table = el("table");
  table.append(el("thead", {}, [el("tr", {}, [
    el("th", { text: "Session" }), el("th", { class: "rung", text: "Mode" }),
    el("th", { text: "Files" }), el("th", { text: "Lines" }),
    el("th", { text: "Low-conf. lines" }), el("th", { class: "rung", text: "Words lost" }),
    el("th", { text: "Reliable words" }), el("th", { text: "Speech" }),
  ])]));
  const body = el("tbody");
  for (const q of S.sessions) {
    const share = q.word_share;
    const meter = el("div", { class: "meter" }, [
      el("i", { style: `width:${Math.min(100, (share || 0) * 100)}%;`
        + `background: var(${q.unreliable ? "--critical" : "--series-1"})` }),
      el("u", { style: `left:${S.warn_share * 100}%`, title: "the warning threshold" }),
    ]);
    body.append(el("tr", {}, [
      el("th", { scope: "row", text: q.date }),
      el("td", { class: "rung", text: q.mode || "\\u2014" }),
      el("td", { text: q.files === null ? "\\u2014" : String(q.files) }),
      el("td", { text: int(q.total_lines) }),
      el("td", { text: `${int(q.low_confidence_lines)} \\u00b7 ${pct(q.line_share)}` }),
      el("td", { class: "rung" }, [
        el("div", { class: "cellrow" }, [
          el("span", { text: pct(share) }), meter,
        ]),
      ]),
      el("td", { text: int(q.reliable_words) }),
      el("td", { text: q.speech_minutes ? `${num(q.speech_minutes, 1)} min` : "\\u2014" }),
    ]));
  }
  table.append(body);
  table.append(el("caption", { text:
    "\\u201cWords lost\\u201d is the share of words whisper was unsure of \\u2014 the reading "
    + "the pipeline acts on. The tick marks the threshold at which it warns." }));
  host.append(el("div", { class: "table-wrap" }, [table]));
})();

/* ---------- what to work on: one expandable row per pattern ---------- */
(() => {
  const host = document.getElementById("patterns");
  const L = MODEL.ladder;
  if (!L.rows.length) { host.hidden = true; return; }
  const byCategory = new Map(MODEL.categories.map((c) => [c.category, c]));

  const ACTIONS = {
    "retiring": "Move it to Improvements in memory.md",
    "no-drill": "Write a drill",
    "thin-evidence": "Drill it again — one item is not a score",
    "form-unreliable": "Keep drilling until the form is reliable",
    "automaticity-gap": "More drilling will not fix this — produce it in dialogue",
    "clean": "Watch it — one clean session is not a streak",
  };

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "What to work on" }),
      el("div", { class: "sub", text:
        "Ranked by impact — severity × √(recency-weighted rate), the ranking "
        + "python -m voxlib.mistakes prints, so the page and the CLI always agree. Three "
        + "files measure three different things about the same mistake, and the rung a row "
        + "fails on says what to do about it: a form drilled to 100% that still appears in "
        + "every recording is not a knowledge problem. Open a row for its trend, its worked "
        + "examples and its notes." }),
    ]),
  ]));

  host.append(el("div", { class: "rungs" }, [
    el("div", { class: "rung-def" }, [
      el("b", { text: "1 · Knows the form" }),
      el("span", { text: "drills.csv — the only score here with a real denominator. "
        + "Blocked means the pattern was named; mixed means it had to be noticed." }),
    ]),
    el("div", { class: "rung-def" }, [
      el("b", { text: "2 · Produces it when attending" }),
      el("span", { text: "practice_history.csv — typed dialogue, errors per 1,000 words "
        + "the owner produced." }),
    ]),
    el("div", { class: "rung-def" }, [
      el("b", { text: "3 · Produces it unmonitored" }),
      el("span", { text: "mistakes.csv — the recording, per 1,000 reliable words. The "
        + "only rung that measures speech." }),
    ]),
  ]));

  if (!L.attended_sessions) host.append(el("div", { class: "notice", text:
    `Rung 2 has no measurements. All ${L.asking_sessions} recorded practice sessions were `
    + "question practice (mode “ask”); conversation practice — the mode that "
    + "drills these grammar categories in dialogue — has never been recorded, so nothing "
    + "bridges the drill and the recording. Grammar errors logged during question practice "
    + "are shown as a count, not a rate: those sessions add words to the denominator without "
    + "giving most of these categories a chance to appear." }));

  if (L.states["no-drill"]) host.append(el("div", { class: "notice", text:
    `${L.states["no-drill"]} of the ${L.rows.length} tracked mistakes have no drill, so `
    + "rungs 1 and 2 cannot be measured for them at all — the only evidence on record "
    + "is what the recording caught. A drill is the cheapest way to find out whether one of "
    + "them is a knowledge gap or an automaticity gap; drills/README.txt has the format." }));

  /* ---- controls: the state filter and the sort, in one row ---- */
  const order = Object.keys(L.state_labels).filter((k) => L.states[k]);
  let active = null;
  const bar = el("div", { class: "chipbar" });
  const sort = el("select", { id: "sort-by" }, [
    el("option", { value: "impact", text: "impact" }),
    el("option", { value: "latest", text: "latest rate" }),
    el("option", { value: "severity", text: "severity" }),
    el("option", { value: "recent", text: "most recently seen" }),
    el("option", { value: "due", text: "next due" }),
    el("option", { value: "name", text: "name" }),
  ]);
  const hide = el("input", { type: "checkbox", id: "hide-clean" });
  const table = el("div");

  const dot = (token) => el("span", { class: "dot", style: `background: var(${token})` });
  const hollow = () => el("span", { class: "dot",
    style: "box-shadow: inset 0 0 0 1px var(--hollow)" });

  const cell = (status, main, detail) => {
    const td = el("td", { class: "rung" });
    td.append(el("div", { class: "cellrow" }, [
      status === null ? hollow() : dot(status), el("span", { text: main }),
    ]));
    if (detail) td.append(el("div", { class: "detail", text: detail }));
    return td;
  };

  const rungOne = (r) => {
    const d = r.drill;
    if (!d || !d.attempted) return cell(null, "never drilled");
    const pct = `${Math.round(d.accuracy * 100)}% (${d.correct}/${d.attempted})`;
    const detail = `blocked ${d.blocked.correct}/${d.blocked.attempted}`
      + ` · mixed ${d.mixed.correct}/${d.mixed.attempted}`;
    if (d.attempted < 5) return cell("--warning", pct, `${detail} — too few to tell`);
    return cell(d.accuracy >= 0.8 ? "--good" : "--critical", pct, detail);
  };

  const rungTwo = (r) => {
    if (r.attended_rate !== null && r.attended_rate !== undefined)
      return cell(r.attended_rate > 0 ? "--critical" : "--good", num(r.attended_rate),
                  "per 1,000 typed words");
    if (r.attended_in_asking)
      return cell("--warning", `${r.attended_in_asking}×`, "question practice only");
    return cell(null, "not measured");
  };

  const rungThree = (r) => {
    if (r.speech_rate === null || r.speech_rate === undefined)
      return cell(null, "not measured", `untested ×${r.untested_since}`);
    const detail = r.absence_streak
      ? `clean ×${r.absence_streak} running`
      : `${DIRECTION[r.direction] ? DIRECTION[r.direction].text : r.direction}`
        + `${r.stalled ? " · stalled" : ""}`;
    // The count beside the rate: a rate on its own hides whether it rests on
    // one instance or twenty.
    const shown = num(r.speech_rate)
      + (r.speech_count ? ` (${r.speech_count})` : "");
    return cell(r.speech_rate > 0 ? "--critical" : "--good", shown, detail);
  };

  /* ---- the rows ---- */
  // Which patterns are open. Survives a re-render on purpose — unlike anything
  // about the DOM, which `build` recreates from scratch every time.
  const expanded = new Set();

  const row = (r) => {
    const cat = byCategory.get(r.category);
    const detailId = `${r.slug}-detail`;
    const open = expanded.has(r.slug);

    const toggle = el("button", { class: "row-toggle", type: "button" });
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-controls", detailId);
    toggle.append(el("span", { class: "caret", text: open ? "▼" : "▶" }));
    const name = el("div", {}, [
      el("div", { class: "pname" }, [
        el("span", { class: "sev", text: `s${r.severity} ` }),
        el("span", { text: r.category }),
      ]),
    ]);
    // The most recent worked example stays visible without opening anything —
    // it is the one line on this page you can practise from.
    const latest = cat && cat.note && cat.note.examples.length
      ? cat.note.examples[cat.note.examples.length - 1] : null;
    if (latest) {
      const line = el("div", { class: "row-ex",
        title: `${latest.wrong} → ${latest.right}` });
      line.append(el("span", { class: "wrong", text: latest.wrong }));
      line.append(el("span", { text: " → " }));
      const right = el("span", { class: "right" });
      right.append(inlineMarkdown(latest.right));
      line.append(right);
      name.append(line);
    }
    toggle.append(name);

    const due = r.next_due
      ? el("span", { class: r.overdue ? "overdue" : null,
                     text: r.overdue ? `${r.next_due} · overdue` : r.next_due })
      : el("span", { class: "detail", text: "not scheduled" });

    const tr = el("tr", { id: r.slug }, [
      el("th", { scope: "row" }, [toggle]),
      rungOne(r), rungTwo(r), rungThree(r),
      el("td", {}, [due]),
      el("td", { class: "where" }, [
        el("div", { text: L.state_labels[r.state] }),
        el("div", { class: "detail action", text: ACTIONS[r.state] || "" }),
      ]),
    ]);

    const detailTr = el("tr", { class: "detail-row" });
    if (!open) detailTr.hidden = true;
    const holder = el("td", { id: detailId, colSpan: 6 });
    detailTr.append(holder);
    // Built on first open: a detail per pattern, notes and charts included, is a
    // lot of DOM to create for rows nobody looks at.
    //
    // The guard asks this cell whether it is already filled, rather than
    // remembering which patterns have been built. A set of slugs outlives the
    // nodes it was describing: `build` replaces every row, so after a re-render
    // — a sort, a filter chip, or following another pattern's link — the slug
    // was still marked built while the new cell was empty, and the row opened
    // to nothing.
    const fill = () => {
      if (holder.firstChild || !cat) return;
      holder.append(patternDetail(cat));
    };
    if (open) fill();

    toggle.addEventListener("click", () => {
      const nowOpen = !expanded.has(r.slug);
      if (nowOpen) { expanded.add(r.slug); fill(); } else { expanded.delete(r.slug); }
      detailTr.hidden = !nowOpen;
      toggle.setAttribute("aria-expanded", String(nowOpen));
      toggle.firstChild.textContent = nowOpen ? "▼" : "▶";
      if (nowOpen) window.dispatchEvent(new Event("resize"));
    });

    return [tr, detailTr];
  };

  const build = () => {
    let rows = active ? L.rows.filter((r) => r.state === active) : L.rows;
    if (hide.checked) rows = rows.filter((r) => r.state !== "retiring");
    const rank = {
      impact: (a, b) => b.impact - a.impact,
      latest: (a, b) => (b.speech_rate ?? -1) - (a.speech_rate ?? -1),
      severity: (a, b) => b.severity - a.severity || b.impact - a.impact,
      recent: (a, b) => (b.last_seen || "").localeCompare(a.last_seen || ""),
      due: (a, b) => (a.next_due || "9999").localeCompare(b.next_due || "9999"),
      name: (a, b) => a.category.localeCompare(b.category),
    };
    rows = [...rows].sort(rank[sort.value]);

    table.textContent = "";
    const t = el("table");
    t.append(el("thead", {}, [el("tr", {}, [
      el("th", { text: `Mistake (${rows.length})` }),
      el("th", { class: "rung", text: "1 · Knows the form" }),
      el("th", { class: "rung", text: "2 · Attending" }),
      el("th", { class: "rung", text: "3 · Unmonitored" }),
      el("th", { text: "Next due" }),
      el("th", { class: "where", text: "Where it breaks" }),
    ])]));
    const body = el("tbody");
    for (const r of rows) for (const node of row(r)) body.append(node);
    t.append(body);
    table.append(el("div", { class: "table-wrap" }, [t]));
  };

  const chips = [];
  const paint = () => chips.forEach(([b, k]) =>
    b.setAttribute("aria-pressed", String(active === k)));
  for (const key of [null, ...order]) {
    const b = el("button", { class: "state", type: "button" }, [
      el("span", { class: "count", text: String(key ? L.states[key] : L.rows.length) }),
      el("span", { text: key ? L.state_labels[key] : "all patterns" }),
    ]);
    b.addEventListener("click", () => {
      active = active === key ? null : key;
      paint(); build();
    });
    chips.push([b, key]);
    bar.append(b);
  }
  paint();
  host.append(bar);
  host.append(el("div", { class: "controls" }, [
    el("label", { htmlFor: "sort-by", text: "Sort by" }), sort,
    el("label", { htmlFor: "hide-clean" },
       [hide, el("span", { text: " Hide the ones ready to retire" })]),
  ]));
  host.append(table);

  sort.addEventListener("change", build);
  hide.addEventListener("change", build);

  // A pattern can be linked to: #pattern-<name> opens that row. The page had
  // one of these per tracked pattern and no way to point at any of them.
  const openFromHash = () => {
    const slug = location.hash.slice(1);
    if (!slug || !L.rows.some((r) => r.slug === slug)) return false;
    if (!expanded.has(slug) || !document.getElementById(slug)) {
      expanded.add(slug);
      active = null;                 // a filter may be hiding the row
      paint();
      build();
    }
    const target = document.getElementById(slug);
    if (target) target.scrollIntoView({ block: "center" });
    return true;
  };

  build();
  if (!openFromHash()) {
    // Otherwise open the top-ranked row, so the page always shows one pattern's
    // examples and notes without a click.
    expanded.add(L.rows[0].slug);
    build();
  }
  window.addEventListener("hashchange", openFromHash);

  if (L.dialogue_only.length) {
    const list = el("div", { class: "note" });
    list.append(el("div", { text:
      "On the practice schedule but absent from the table above, because the recording "
      + "cannot measure them — question-asking is not a grammar category, so these have "
      + "no rung 3:" }));
    for (const d of L.dialogue_only) {
      list.append(el("div", { style: "margin-top:6px" }, [
        el("span", { text: `${d.category} — last drilled ${d.last_drilled}, streak `
          + `${d.streak}, due ` }),
        el("span", { class: d.overdue ? "overdue" : null,
                     text: d.overdue ? `${d.next_due} (overdue)` : d.next_due }),
      ]));
    }
    host.append(list);
  }
})();

/* ---------- what is working ---------- */
(() => {
  const host = document.getElementById("working");
  if (!MODEL.working.length) { host.hidden = true; return; }

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "What's working" }),
      el("div", { class: "sub", text:
        "The counterpart of the list above, and nothing on it is rounded in a flattering "
        + "direction: every line is a measurement that moved the right way, and the block "
        + "does not appear at all when none did." }),
    ]),
  ]));

  const list = el("div", { class: "actions" });
  for (const win of MODEL.working) {
    list.append(el("div", { class: "action-row" }, [
      el("div", { class: "action-n" }, [
        el("span", { class: "dot", style: "background: var(--good)" }),
      ]),
      el("div", {}, [
        el("div", { class: "action-title", text: win.title }),
        el("div", { class: "action-detail", text: win.detail }),
        el("a", { class: "action-link", href: `#${win.anchor}`,
                  text: `↓ ${SECTION_LABELS[win.anchor] || win.anchor}` }),
      ]),
    ]));
  }
  host.append(list);
})();

/* ---------- the level line ---------- */
function levelChart(width, L) {
  const top = L.scale.length - 1;
  const bottom = L.below_scale;                 // one row for "below B1"
  const rows = top - bottom + 1;
  const rowH = 26;
  const M = { top: 10, right: 46, bottom: 30, left: 116 };
  const H = M.top + rows * rowH + M.bottom;
  const iw = width - M.left - M.right;
  const readings = L.readings;
  const x = (i) => M.left + (readings.length < 2 ? iw / 2
    : (i / (readings.length - 1)) * iw);
  const y = (rung) => M.top + (top - rung) * rowH + rowH / 2;

  const root = svg("svg", { viewBox: `0 0 ${width} ${H}`, width, height: H, role: "img" });

  for (let rung = bottom; rung <= top; rung += 1) {
    root.append(svg("line", { x1: M.left, x2: M.left + iw, y1: y(rung), y2: y(rung),
                              stroke: css("--grid"), "stroke-width": 1 }));
    root.append(Object.assign(
      svg("text", { x: M.left - 10, y: y(rung) + 4, fill: css("--muted"), "font-size": 11,
                    "text-anchor": "end" }),
      { textContent: rung < 0 ? "below B1" : L.scale[rung] }));
  }
  const every = readings.length > 8 ? 2 : 1;
  readings.forEach((r, i) => {
    if (i % every && i !== readings.length - 1) return;
    root.append(Object.assign(
      svg("text", { x: x(i), y: H - 10, fill: css("--muted"), "font-size": 11,
                    "text-anchor": "middle" }),
      { textContent: shortDate(r.date) }));
  });

  // The level itself: a step, because it only changes on the session that
  // completes a qualifying run — between those it is flat by definition.
  const levelled = readings.map((r, i) => [i, r.level]).filter(([, v]) => v !== null);
  if (levelled.length) {
    let d = "";
    levelled.forEach(([i, value], n) => {
      if (!n) { d += `M${x(i)},${y(value)}`; return; }
      d += `L${x(i)},${y(levelled[n - 1][1])}L${x(i)},${y(value)}`;
    });
    root.append(svg("path", { d, fill: "none", stroke: css("--series-1"),
                              "stroke-width": 2, "stroke-linejoin": "round",
                              "stroke-linecap": "round" }));
    const [lastIndex, lastValue] = levelled[levelled.length - 1];
    root.append(svg("circle", { cx: x(lastIndex), cy: y(lastValue), r: 4.5,
                                fill: css("--series-1"), stroke: css("--surface"),
                                "stroke-width": 2 }));
  }

  // Every session's own reading, which is what the level is smoothed out of.
  readings.forEach((r, i) => {
    if (r.rung === null) return;
    root.append(svg("circle", { cx: x(i), cy: y(r.rung), r: r.reliable ? 3.5 : 2.5,
                                fill: r.reliable ? css("--series-2") : "none",
                                stroke: r.reliable ? css("--surface") : css("--series-2"),
                                "stroke-width": r.reliable ? 1.5 : 1 }));
  });

  const hair = svg("line", { y1: M.top, y2: M.top + rows * rowH, stroke: css("--axis"),
                             "stroke-width": 1, opacity: 0 });
  root.append(hair);
  readings.forEach((r, i) => {
    const half = readings.length < 2 ? iw : iw / (readings.length - 1) / 2;
    const band = svg("rect", { x: Math.max(M.left, x(i) - half), y: M.top,
                               width: Math.max(1, half * 2), height: rows * rowH,
                               fill: "transparent", tabindex: 0 });
    const rows_ = [
      { color: css("--series-1"), value: r.level_label, name: "level" },
      { color: css("--series-2"), value: r.rung_label, name: "this session alone" },
    ];
    if (r.blockers.length) rows_.push({ value: r.blockers.join(", "), name: "held back by" });
    if (!r.reliable) rows_.push({ value: "not comparable", name: "too many words lost" });
    const show = (ev) => {
      hair.setAttribute("x1", x(i)); hair.setAttribute("x2", x(i));
      hair.setAttribute("opacity", 1);
      showTip(ev.clientX ?? 0, ev.clientY ?? 0, r.date, rows_);
    };
    band.addEventListener("pointermove", show);
    band.addEventListener("focus", () => {
      const b = band.getBoundingClientRect();
      hair.setAttribute("x1", x(i)); hair.setAttribute("x2", x(i));
      hair.setAttribute("opacity", 1);
      showTip(b.right, b.top, r.date, rows_);
    });
    band.addEventListener("pointerleave", () => { hair.setAttribute("opacity", 0); hideTip(); });
    band.addEventListener("blur", () => { hair.setAttribute("opacity", 0); hideTip(); });
    root.append(band);
  });
  return root;
}

(() => {
  const host = document.getElementById("level");
  const L = MODEL.level;
  if (!L.readings || !L.readings.length) { host.hidden = true; return; }
  const cur = L.current;

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Level" }),
      el("div", { class: "sub", text:
        "A CEFR band is about a year wide, which makes it useless as weekly feedback \\u2014 "
        + "scores_history.csv has recorded the same letter for every session so far. This "
        + "cuts the band into rungs and earns each one against explicit thresholds, so the "
        + "same history always gives the same answer. It is calibrated against your own "
        + "record: a rung on your line, not an exam result." }),
    ]),
  ]));

  host.append(el("div", { class: "lvl-head" }, [
    el("div", {}, [
      el("div", { class: "lvl-val", text: cur.label }),
      el("div", { class: "lvl-note", text: cur.index === null ? "not yet established"
        : `rung ${cur.index + 1} of ${L.scale.length}`
          + (L.target ? ` \\u00b7 next is ${L.target.label}` : "")
          + (cur.session_label !== cur.label
             ? ` \\u00b7 this session alone reads ${cur.session_label}` : "") }),
    ]),
    el("div", { style: "flex:1 1 300px" }, [
      el("div", { class: "lvl-note", style: "margin-top:0", text: cur.blockers.length
        ? "Held here by " + L.dimensions.filter((d) => d.blocking)
            .map((d) => d.label.toLowerCase()).join(" and ")
          + `. The rung moves when all but one dimension reach it, none is more than one `
          + `rung below, and that holds for ${L.promotion_sessions} sessions running.`
        : `The rung moves when all but one dimension reach it and that holds for `
          + `${L.promotion_sessions} sessions running.` }),
      L.floor ? el("div", { class: "lvl-note", text:
        `The line has not moved, but the floor under it has: the worst single session was `
        + `${L.floor.worst_label}, last seen on ${L.floor.last_at_worst}, and none of the `
        + `${L.floor.sessions_since} sessions since has read below `
        + `${L.floor.floor_since_label}.` }) : null,
    ]),
  ]));

  const plot = el("div", { class: "plot", style: "margin-top:18px" });
  host.append(el("div", { class: "legend", style: "margin-top:20px" }, [
    el("div", { class: "legend-item" }, [
      el("span", { class: "key-line", style: "background: var(--series-1)" }),
      el("span", { text: "level \\u2014 what the evidence sustains" }),
    ]),
    el("div", { class: "legend-item" }, [
      el("span", { class: "key-box",
                   style: "background: var(--series-2); border-radius: 50%" }),
      el("span", { text: "one session on its own" }),
    ]),
  ]));
  host.append(plot);
  responsive(plot, (w) => levelChart(w, L));

  /* the four dimensions, and what the next rung asks of each */
  const grid = el("div", { class: "dims" });
  for (const dim of L.dimensions) {
    const block = el("div", {});
    block.append(el("div", { class: "dim-name" }, [
      el("span", { text: dim.label }),
      el("span", { class: "dim-rung" }, [
        dim.rung === null
          ? el("span", { class: "dot", style: "box-shadow: inset 0 0 0 1px var(--hollow)" })
          : el("span", { class: "dot",
              style: `background: var(${dim.blocking ? "--warning" : "--good"})` }),
        el("span", { text: dim.rung_label }),
      ]),
    ]));
    for (const m of dim.measures) {
      const row = el("div", { class: "mrow" });
      row.append(el("div", { class: "mlab" }, [
        el("span", { text: m.label }),
        el("span", { class: "mval",
                     text: m.value === null ? "not measured" : trim(m.value) }),
      ]));
      if (m.threshold !== null && m.threshold !== undefined) {
        row.append(el("div", { class: "meter", style: "margin-top:5px" }, [
          el("i", { style: `width:${Math.round((m.progress || 0) * 100)}%;`
            + `background: var(${m.met ? "--good" : "--series-1"})` }),
        ]));
        row.append(el("div", { class: "mneed", text: m.met
          ? `clears ${L.target.label} (${m.lower_is_better ? "\\u2264" : "\\u2265"} `
            + `${trim(m.threshold)} ${m.unit})`
          : `${L.target.label} needs ${m.lower_is_better ? "\\u2264" : "\\u2265"} `
            + `${trim(m.threshold)} ${m.unit}` }));
      } else {
        row.append(el("div", { class: "mneed", text: L.target
          ? `ungated at ${L.target.label}` : "no next rung" }));
      }
      row.append(el("div", { class: "mnote-s", text: m.note }));
      block.append(row);
    }
    grid.append(block);
  }
  host.append(grid);

  host.append(el("div", { class: "note", text:
    `${cur.measured} of ${cur.dimensions_total} dimensions were measured this session `
    + `(${L.min_dimensions} needed, or the reading is marked provisional). Coherence is `
    + "absent on purpose \\u2014 nothing here measures it, and a dimension scored on "
    + "impression would put back the drift this scale exists to remove. Interaction comes "
    + `from question practice and only counts while under ${L.interaction_max_age_days} days `
    + `old. Calibration ${L.calibration}: move a threshold and this whole line moves with `
    + "it, which is why the rows in level_history.csv carry the calibration that made them." }));
})();

/* ---------- session timeline ---------- */
(() => {
  const host = document.getElementById("timeline");
  const T = MODEL.timeline;
  if (!T.length) { host.hidden = true; return; }
  const linked = T.filter((e) => e.report).length;

  host.append(el("div", { class: "card-head" }, [
    el("div", {}, [
      el("h2", { text: "Session timeline" }),
      el("div", { class: "sub", text:
        "Everything dated, newest first \\u2014 the union of recordings and practice, because "
        + "practice happens on days with no recording and a chronology that dropped those "
        + "would suggest nothing was done on them." }),
    ]),
  ]));

  const t = el("table");
  t.append(el("thead", {}, [el("tr", {}, [
    el("th", { text: "Date" }), el("th", { class: "rung", text: "What happened" }),
    el("th", { class: "rung", text: "Mode" }), el("th", { text: "Reliable words" }),
    el("th", { text: "Mistakes / 1,000" }), el("th", { text: "Words lost" }),
    el("th", { text: "Practice" }), el("th", { text: "Scenarios" }),
  ])]));
  const body = el("tbody");
  for (const e of T) {
    const tags = el("div", { class: "tags" });
    if (e.recording) tags.append(el("span", { class: "chip", text: "recording" }));
    for (const mode of e.practice_modes)
      tags.append(el("span", { class: "chip",
        text: mode === "ask" ? "question practice" : "conversation practice" }));
    if (e.scenarios) tags.append(el("span", { class: "chip",
      text: `${e.scenarios} scenario${e.scenarios === 1 ? "" : "s"}` }));

    // A relative link to the archived report. It opens from the page's own
    // folder, so it keeps working as long as output/ sits beside analysis/.
    const date = e.report
      ? el("a", { class: "report", href: e.report, text: e.date })
      : el("span", { text: e.date });

    body.append(el("tr", {}, [
      el("th", { scope: "row" }, [date]),
      el("td", { class: "rung" }, [tags]),
      el("td", { class: "rung", text: e.mode || "\\u2014" }),
      el("td", { text: e.reliable_words === null ? "\\u2014" : int(e.reliable_words) }),
      el("td", { text: e.rate === null ? "\\u2014" : num(e.rate) }),
      el("td", { text: e.word_share === null || e.word_share === undefined
        ? "\\u2014" : `${Math.round(e.word_share * 100)}%` }),
      el("td", { text: e.practice_words ? `${int(e.practice_words)} words` : "\\u2014" }),
      el("td", { text: e.scenario_total ? `${e.scenario_met}/${e.scenario_total}` : "\\u2014" }),
    ]));
  }
  t.append(body);
  host.append(el("div", { class: "table-wrap" }, [t]));
  host.append(el("div", { class: "note", text: linked
    ? `${linked} of ${T.length} dates link to their archived session report under `
      + "analysis/sessions/. The rest are practice-only days, which write no report."
    : "No archived reports were found to link to \\u2014 the page was built without knowing "
      + "where it would be written, so the dates here are plain text." }));
})();

/* ---------- section nav ---------- */
(() => {
  const host = document.getElementById("nav");
  const gaps = (MODEL.ladder.states || {})["automaticity-gap"] || 0;
  const criteria = MODEL.asking.totals;
  // A badge only where one number genuinely summarises the section. Every
  // section carrying a count would just be more digits to read past.
  const badges = {
    actions: String(MODEL.actions.length),
    working: String(MODEL.working.length),
    level: (MODEL.level.current || {}).label || "",
    heatmap: `${MODEL.categories.length}`,
    patterns: gaps ? `${gaps} gaps` : `${MODEL.categories.length}`,
    asking: criteria.total ? `${Math.round((criteria.met / criteria.total) * 100)}%` : "",
    quality: MODEL.speech.any_unreliable ? "check" : "",
    timeline: `${MODEL.timeline.length}`,
  };
  const links = [];
  for (const section of document.querySelectorAll("section[id]")) {
    if (section.hidden) continue;
    const heading = section.querySelector("h2");
    const label = SECTION_LABELS[section.id]
      || (heading ? heading.textContent : section.id);
    const link = el("a", { href: `#${section.id}` }, [
      el("span", { text: label }),
      badges[section.id] ? el("span", { class: "badge", text: badges[section.id] }) : null,
    ]);
    host.append(link);
    links.push([link, section]);
  }

  // Which section you are actually in, so a 10,000px page says where you are.
  const seen = new Map();
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) seen.set(entry.target, entry.intersectionRatio);
    let best = null, bestRatio = 0;
    for (const [link, section] of links) {
      const ratio = seen.get(section) || 0;
      if (ratio > bestRatio) { bestRatio = ratio; best = link; }
    }
    for (const [link] of links)
      link.setAttribute("aria-current", String(link === best && bestRatio > 0));
  }, { threshold: [0, 0.1, 0.25, 0.5, 0.75, 1] });
  for (const [, section] of links) observer.observe(section);
})();

/* theme */
document.getElementById("theme").addEventListener("click", () => {
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const current = document.documentElement.dataset.theme || (dark ? "dark" : "light");
  document.documentElement.dataset.theme = current === "dark" ? "light" : "dark";
  window.dispatchEvent(new Event("resize"));
});
</script>
</body>
</html>
"""


def render(model: dict) -> str:
    """The page, with the model inlined. `<` is escaped so no string in the data
    can close the script tag it is sitting in."""
    payload = json.dumps(model, ensure_ascii=False).replace("<", "\\u003c")
    return _TEMPLATE.replace("__MODEL_JSON__", payload)


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
    parser.add_argument("--open", action="store_true", help="Open it in the browser when built")
    args = parser.parse_args(argv)

    model = build_model(analysis_dir=args.analysis, out_dir=args.out.parent)
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
