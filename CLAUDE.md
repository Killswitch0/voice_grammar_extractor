# Project context

This project extracts spoken English lines from personal recordings (see
`HOW_IT_WORKS.md`) into `output/transcript_clean.txt`. The owner's goal is
long-term spoken English improvement, not a one-off report: track which
mistakes keep recurring across many recordings over months, catch what's
actually improving, and know exactly what to practice next.

**Recordings are sometimes solo and sometimes have other speakers** — don't
assume either. If it's just the owner talking, `--no-diarization` is used
(no HuggingFace token or reference voice sample needed). If other voices are
present, diarization is used with `--reference` pointing at a saved voice
sample (see `voice_reference/my_reference.wav` or wherever the owner has one) and
`--hf-token` / `HF_TOKEN`. When in doubt, ask which case this recording is.

**This distinction only matters for step 1 of the analysis workflow** (which
command to run). Either way, the output is always
`output/transcript_clean.txt` containing only the owner's lines — everything
from archiving onward treats the result identically regardless of which mode
produced it. Don't re-litigate solo-vs-diarization anywhere past that step.

# Role

When analyzing a transcript, you are the owner's personal English coach.
Your only goal is to improve their spoken English as efficiently as possible
— not to produce a beautiful report.

# Modes in this repo

This repo runs three independent modes. **Each one's rules live in its own
skill, and the skill is loaded with the `Skill` tool before anything else
happens.** Only the rules of the mode actually running are in context, which is
the point: the three rule sets are never mixed (they carry different numbering —
`1`-`20`, `P1`-`P25`, `Q1`-`Q16` — precisely so a bare rule number can't be
ambiguous), and a practice session doesn't pay to load the recording workflow it
will never run.

| Say | Skill to invoke | What it does |
|---|---|---|
| "analyze the recording", "analyze new recording", or a file under `recordings/` | `analyze-recording` | Transcribe if needed, archive, compare against memory, write the session report, update every tracker |
| "let's practice", "quiz me", "let's talk" | `practice-answer` | Conversation practice: Claude asks, the owner answers |
| "let's practice asking", "give me situations", "I want to practice questions" | `practice-asking` | Question practice: Claude describes a situation, the owner has to ask |

The distinction between the two practice modes is **who produces the question**.
An ambiguous "let's practice" means conversation practice; question practice has
to be asked for.

Don't answer a mode request from memory of how it used to work — invoke the
skill and follow what it says. Between them the three carry rules that were each
written after a specific failure, and the summary you remember is not them.

# Folder layout

```
recordings/            raw audio/video files (owner drops files here)
voice_reference/       my_reference.wav — PERMANENT, not overwritten by runs
asking/                Question Practice Mode's content. PERSONAL DATA and gitignored,
                         for the same reason `drills/` is: each scenario's `trap` is a
                         reconstruction of the owner's own error, and the situations
                         worth adding are the ones that actually happened to them.
                         Empty on a fresh clone — write content into it, don't assume
                         it's there. See asking/README.txt for both formats, and
                         tests/fixtures/asking/ for an invented complete example:
  drills/                  question-formation drills in the ordinary drill format,
                             kept out of `drills/` so a grammar session's mixed
                             block never draws one (`load_all` doesn't recurse)
  scenarios/               situation packs — one YAML per pack, each scenario a
                             situation the owner has to ask their way out of, with
                             an in-role reply, what it withholds, and the criteria
                             it is scored against
frames/                one YAML per group of categories: a regex per tracked mistake
                         matching a line where the structure came up at all. The
                         denominator everything else here lacks — `mistakes.csv` counts
                         errors and nothing counted chances, so words spoken stood in for
                         them. PERSONAL DATA and gitignored, for the same reason `drills/`
                         is: a trigger is the list of words this particular speaker gets
                         wrong. Read with `python -m voxlib.opportunity`; a frame is only
                         used as a denominator where `python -m voxlib.exposure` says it
                         predicts that category's errors better than the word count does.
                         See frames/README.txt, and tests/fixtures/frames/ for an invented
                         example. Empty on a fresh clone, and every figure downstream
                         falls back to the per-1,000-words rate while it stays that way
drills/                one YAML per spoken drill: the prompts, a model answer and a
                         counter-example per item, and the patterns that score them.
                         PERSONAL DATA and gitignored — the prompts are reconstructions
                         of the owner's own sentences, and every user's drills are
                         built from their own mistakes. See drills/README.txt for the
                         format; write a new one whenever a primary target has no
                         drill. An invented example lives in tests/fixtures/drills/.
output/                 all overwritten on every run:
  transcript_clean.txt      just the lines, one per line
  transcript_annotated.txt  timestamps, source file, [?] markers — for reading by eye
  lines.json                the same lines with per-line confidence/timing — analyze from this
  fluency.json              this run's fluency measurement
  dashboard.html            every history in analysis/ as one page, in two views.
                              **Now** answers the questions asked on every open and is
                              bounded — the same three or four screens at session 12 and at
                              session 300: a summary of three or four sentences (what got
                              better, what got worse, what to do next), the level with
                              every measure still short of the next rung as a progress bar,
                              the serious-mistake (clarity-tier) rate, ONE thing to do next
                              with the rest behind a disclosure (rule 20), "Your routine" —
                              recording, practice and reviews as elapsed time (rule 19),
                              the rate over time with drills and practice sessions marked
                              on the same axis, a then-vs-now comparison, and the mistakes
                              to work on as a rule-17 portfolio.
                              **The page is written for the owner, not for the coach.**
                              It says "serious / minor mistakes", "same checklist as day
                              one", "in drills / in practice chat / in real speech" —
                              never tiers, rungs, cohorts, rule numbers, file names or CLI
                              commands in the main text, and it says which direction is
                              good beside every number. The project's own terms stay in the
                              code (priority.py keeps them because the coach reads them),
                              and a section's reasoning goes in its folded "How is this
                              measured?" block. dashboard.py holds the plain wording
                              (PLAIN_STATES, PLAIN_ACTIONS, _plain_why, _plain_blocker,
                              _verdict); keep new text to that standard. A mistake's title
                              on the page is its `Plain name:` line in memory.md (the
                              `##` heading stays the join key and shows small beneath it),
                              and every action says what to type to start it.
                              **Evidence** holds everything that grows one row or one column
                              per session and is navigated rather than scrolled past: the
                              level detail, every tracked pattern, the chances table, the
                              heatmap, the speech panel (pace grouped by speech_time_basis
                              and never joined across it), Question Practice Mode's scores,
                              the words to retire, the reliability table, the timeline, and
                              an "About this page" block saying how much the page as a whole
                              actually knows.
                              Three things it will not draw: an untested cell as a zero, a
                              category before it was tracked, and — as the headline — a
                              total that rises as coaching finds new categories. The
                              day-one cohort is drawn instead, because it counts the same
                              things at both ends. It draws the level by calling
                              voxlib.level directly, never by reading level_history.csv, so
                              the page and `python -m voxlib.level` cannot disagree — which
                              also means the range dimension is blank until
                              `python -m voxlib.lexis --write` has been run. Built on demand
                              with `python -m voxlib.dashboard --open`, NOT by a pipeline
                              run, so rebuild it after a session to see that session in it.
                              It only ever reads analysis/ and frames/; it computes no
                              metric of its own, every number on it comes from the module
                              that owns the file it came from — the ranking from
                              voxlib/priority.py, the chances from voxlib/opportunity.py
                              (voxlib/dashboard.py says why that rule matters, and
                              voxlib/dashboard_page.py holds the page itself)
analysis/
  memory.md              the persistent, cross-session tracker — read/update every session
  memory_archive.md      long-resolved mistakes, moved out of memory.md to keep it short
  scores_history.csv     append-only numeric history (CEFR, 4 scores, filler rate) per session —
                           your assessments, written by you
  mistakes.csv           append-only, written by YOU via `python -m voxlib.mistakes add`:
                           one row per tracked mistake category per session, with the
                           session's reliable-word count as the denominator. The machine-
                           readable spine of memory.md's "Persistent Grammar Mistakes" —
                           read the trend with `python -m voxlib.mistakes`
  vocab_history.csv      REWRITTEN, not appended, by `python -m voxlib.vocab --write`: how
                           often each phrase in memory.md's "Vocabulary To Replace" table —
                           and each of its suggested replacements — was actually said, per
                           session, counted on word boundaries over the reliable lines of
                           the archived transcripts. The table was a standing instruction
                           with no feedback loop until this existed. Read it with
                           `python -m voxlib.vocab`; a phrase said fewer than
                           `vocab.MIN_FOR_MOVEMENT` times in the whole archive is reported
                           as having no direction rather than as rising
  lexis_history.csv      REWRITTEN, not appended, by `python -m voxlib.lexis --write`:
                           lexical variety (MATTR) and words new against a rolling
                           three-session baseline, per session. Derived wholly from the
                           archived annotated transcripts, so it can always be recomputed
                           and there is no judgment in it to preserve. The CEFR "range"
                           dimension, which nothing else here measures
  opportunity_history.csv  REWRITTEN, not appended, by `python -m voxlib.opportunity
                           --write`: how many chances each tracked mistake had, per
                           session, counted over the reliable lines of the archived
                           transcripts through the triggers in `frames/`. A lexical proxy
                           for a grammatical opportunity, and the same proxy every session
                           — it buys a series comparable with itself, not an exam grade.
                           Every row carries the trigger's fingerprint, so a frame edited
                           later cannot draw one trend through two different measurements
  level_history.csv      REWRITTEN, not appended, by `python -m voxlib.level --write`: the
                           sub-band level per session (B1 / B1+ / B2.1 ... ), each rung
                           earned against explicit thresholds on four dimensions —
                           accuracy (clarity tier, gated above B2.1 by the polish tier),
                           fluency (fillers, discourse markers), range (lexis_history) and
                           interaction (asking_scenarios, while under 30 days old).
                           Coherence is deliberately absent: nothing measures it. Read it
                           with `python -m voxlib.level`, which also prints what the next
                           rung needs. Every row carries the calibration that produced it;
                           moving a threshold means bumping `level.CALIBRATION` and
                           rewriting the file, because the rows are derived, not observed
  fluency_history.csv    append-only, written by the PIPELINE, never by hand: filler rate,
                           words per minute, pause stats per run (see voxlib/fluency.py).
                           Don't edit it.
  drills.csv             append-only, written by `python -m voxlib.practice end` (or
                           `drill score`): one row per drill attempt — items, attempted,
                           correct, the pool's fingerprint, and whether it was asked
                           blocked or mixed. The only score here with a denominator.
  drill_items.csv        append-only, same writer: one row per item per attempt, so
                           "which prompt keeps failing" is answerable and the next sample
                           can lead with it. Read via `python -m voxlib.drill items`.
  drill_pending.json     the sample the session opened with, plus the answers recorded
                           against it so far (`drill answer`), waiting to be scored.
                           Machine state, cleared automatically; don't edit it.
  processed.json         written by the PIPELINE: which recordings have already been
                           transcribed (matched by content, not filename). Guards against
                           merging the same audio into two sessions. Don't edit it.
  asking_memory.md       written ONLY by Question Practice Mode (Q16), by hand: the
                           question patterns tracked there and the register notes. The
                           counterpart of memory.md for a skill the recording cannot
                           measure. Its two log tables are generated by
                           `python -m voxlib.practice end`
  asking_archive.md      that mode's settled design history — decisions already carried
                           out in the rules, the YAML or the code, kept out of the file
                           read at the start of every session
  asking_scenarios.csv   append-only, written by `python -m voxlib.practice end --scenario`:
                           one row per scenario run, with the criteria met and the ones
                           that failed. What scenario selection reads
  asking_drills.csv      append-only: drill attempts from Question Practice Mode.
  asking_drill_items.csv   Same format and same writer as drills.csv / drill_items.csv —
                           separate files so a question score never lands in the
                           grammar drill trend
  asking_pending.json    that mode's pending block, the counterpart of drill_pending.json
  practice_history.csv   append-only, written by both practice modes via
                           `python -m voxlib.practice end`: one row per practice
                           session — words produced, errors by category, corrected
                           repetitions (landed and asked-for-but-not-produced,
                           counted apart), long turns. An error no tracked category
                           covers is recorded under a `?`-prefixed name quoting the
                           form itself; two sessions with the same one earns it a
                           real category and a drill. Attended production: the rung between
                           "knows the form" (drills.csv) and "produces it unmonitored"
                           (mistakes.csv). The `mode` column says which practice mode
                           produced the row — `answer` or `ask` — because the two have very
                           different word counts and are never pooled into one rate.
                           Read via `python -m voxlib.practice`.
  conversation_focus_log.md   written only by the practice modes, via
                               `python -m voxlib.practice end` — never by hand:
                               which patterns have been drilled in dialogue, when, and on
                               a spaced-repetition schedule (Last drilled / Correct streak
                               / Next due). Recording analysis mode reads it for context
                               but never writes to it.
  sessions/
    YYYY-MM-DD.txt              archived raw clean transcript for that day
    YYYY-MM-DD.annotated.txt    archived annotated transcript (has the [?] markers)
    YYYY-MM-DD.lines.json       archived machine-readable lines — what general rule 1 reads
    YYYY-MM-DD.md               that day's full session report
```

# Who writes what

Every history here is **append-only**: never rewrite a past row, even if a later
session reassesses something differently.

| File | Written by | Holds |
|---|---|---|
| `scores_history.csv` | you, by hand | your judgment calls — CEFR and the four 0-10 scores |
| `mistakes.csv` | you, via `python -m voxlib.mistakes add` | which mistakes occurred how often, per session |
| `fluency_history.csv` | the pipeline | how the recording came out and how it was spoken |
| `drills.csv` / `drill_items.csv` | `python -m voxlib.practice end` | drill attempts and per-item results — the only scores with a known denominator |
| `practice_history.csv` | `python -m voxlib.practice end` | typed practice: words produced, errors, corrected repetitions |
| `asking_scenarios.csv` | `python -m voxlib.practice end --scenario` | question-practice scenarios and the criteria they met |
| `lexis_history.csv` | `python -m voxlib.lexis --write` | lexical variety and novelty, recomputed from the archive |
| `vocab_history.csv` | `python -m voxlib.vocab --write` | whether the retired phrases are actually going away — recomputed from the archive |
| `level_history.csv` | `python -m voxlib.level --write` | the sub-band level, earned against thresholds — recomputed, never hand-edited |
| `opportunity_history.csv` | `python -m voxlib.opportunity --write` | how many chances each mistake had — recomputed from the archive and the frames |
