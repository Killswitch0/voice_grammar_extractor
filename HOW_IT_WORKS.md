# How It Works & Why

## The problem

You want to improve your spoken English grammar over months, not just once.
To do that, an AI needs to see what you actually said — but your source
material is scattered across video/audio recordings (calls, monologues,
webm clips), mixed in with other people's voices. And a one-off "review this
transcript" chat forgets everything the moment it ends: no memory of what
you already fixed, what keeps coming back, or what to focus on next time.

## What this project does

Two stages:

1. **Extraction** — turns raw recordings into a plain list of **only your
   sentences**, in the order you said them.
2. **Coaching memory** — a Claude Code workflow (the `analyze-recording`
   skill, dispatched from `CLAUDE.md`) that reads
   that transcript, analyzes your grammar, and maintains a persistent
   `analysis/memory.md` across every recording — so mistakes get tracked as
   trends (recurring / improving / regressed), not re-discovered from
   scratch every time.

## Stage 1 — Extraction pipeline

```
 ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
 │  Video/Audio │ ──> │   Extract    │ ──> │   Diarize    │ ──> │    Merge     │
 │  (any format)│     │   Audio      │     │ "who spoke   │     │  same-speaker│
 │              │     │  (ffmpeg)    │     │  when"       │     │  fragments   │
 │              │     │              │     │ (pyannote)   │     │  back into   │
 │              │     │              │     │              │     │  phrases     │
 └──────────────┘     └──────────────┘     └──────────────┘     └──────┬───────┘
                                                                       │
        ┌──────────────────────────────────────────────────────────────┘
        v
 ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌───────────────────┐
 │  Identify    │ ──> │  Transcribe  │ ──> │   Format     │ ──> │ transcript_clean  │
 │  "which one  │     │  only YOUR   │     │  chronologi- │     │ transcript_annot- │
 │  voice is    │     │   lines      │     │  cal order + │     │ ated (with [?])   │
 │   yours"     │     │  (whisper)   │     │  [?] markers │     │ lines.json        │
 └──────────────┘     └──────────────┘     └──────────────┘     │ fluency.json      │
                                                                └───────────────────┘
```

| Step | Tool | What it answers |
|---|---|---|
| 1. Extract audio | `ffmpeg` | "Turn any video/audio container into a clean waveform" |
| 2. Diarize | `pyannote.audio` | "At each moment, who is speaking?" (only if other voices are present) |
| 3. Merge segments | this tool | "Which of those cuts were mid-sentence pauses rather than real turn boundaries?" |
| 4. Identify | cosine similarity vs. your reference voice sample | "Which speaker is *me*?" |
| 5. Transcribe | `faster-whisper` | "What did *my* segments actually say?" |
| 6. Format | this tool | "Put it in chronological order, one line per line, plus a `[?]` marker on low-confidence lines — and the same lines structured in `lines.json`" |
| 7. Measure fluency | this tool | "How fast, how hesitant, how much pausing?" — written to `fluency.json` (see `voxlib/fluency.py`) |

If it's just you talking (a journal, a monologue) — steps 2 through 4 are
skipped entirely with `--no-diarization`, and transcription runs on the whole
file, where whisper does its own splitting by pauses.

## Stage 2 — Coaching memory (Claude Code + the `analyze-recording` skill)

```
 ┌───────────────────┐     ┌───────────────────┐     ┌────────────────────┐
 │ lines.json        │ ──> │ Claude Code       │ ──> │ analysis/sessions/ │
 │ (+ fluency.json,  │     │ reads the skill,  │     │ YYYY-MM-DD.md      │
 │  from Stage 1)    │     │ skips the low-    │     │ (this session's    │
 │                   │     │ confidence lines, │     │  coaching report)  │
 │                   │     │ compares against  │     │                    │
 │                   │     │ memory.md         │     │                    │
 └───────────────────┘     └─────────┬─────────┘     └────────────────────┘
                                     │
                                     v
                         ┌───────────────────────┐
                         │ analysis/memory.md    │
                         │ updated in place:     │
                         │ - new mistakes added  │
                         │ - recurring ones      │
                         │   bumped              │
                         │ - fixed ones moved to │
                         │   "Improvements"      │
                         │ - regressions flagged │
                         └───────────────────────┘
```

Every new recording runs through this loop and folds into the same
`memory.md` — that's what turns isolated reviews into an actual trend line
of your English improving (or not) over time.

| Concept | Purpose |
|---|---|
| `analysis/sessions/YYYY-MM-DD.md` | Full report for one recording: CEFR estimate, ranked mistakes, natural-English rewrites, vocabulary, targeted exercises |
| `analysis/memory.md` | The one file that persists — current level, active mistakes with occurrence counts, vocabulary to learn, next 3-5 goals |
| `analysis/memory_archive.md` | Long-resolved mistakes get moved here so `memory.md` itself stays short and readable |
| `analysis/scores_history.csv` | Append-only numeric record (CEFR, scores, filler rate) per session — for graphing progress later, separate from the readable text in `memory.md` |
| `analysis/mistakes.csv` | Append-only record of which mistake categories occurred how often, per session, against that session's reliable-word count. The machine-readable spine under `memory.md`'s prose counters: `python -m voxlib.mistakes` renders it as a trend table ranked by impact |
| `analysis/opportunity_history.csv` | How many *chances* each tracked mistake had, per session — counted over the archived transcripts through the regexes in `frames/`. Every other number here is a numerator: `mistakes.csv` says how often a form went wrong and nothing said how often it was tried, so words spoken stood in for chances. `python -m voxlib.exposure` tests whether that substitution holds per category, and a frame is only used as a denominator where it beats the word count |
| `analysis/conversation_focus_log.md` | Written only by Conversation Practice Mode (the `practice-answer` skill, triggered by "let's practice" instead of "analyze the recording") — tracks which `memory.md` patterns were drilled in dialogue and when. Recording analysis reads it for context (to flag a mistake that was drilled in practice but is still occurring) but never writes to it — see "Same repo, second mode" below |

## Why it's built this way

**Extraction:**
- **Diarization is separate from transcription** — whisper is good at
  turning speech into text, but it has no concept of "whose voice this is."
  pyannote does one job (cluster voices), whisper does the other (recognize
  words). Chaining specialized tools beats one tool trying to do both badly.
- **Identification uses a voice embedding, not a fixed speaker label** —
  pyannote renames speakers (`SPEAKER_00`, `SPEAKER_01`, ...) independently
  in every file. Matching by *voice similarity* to a saved reference is the
  only way to reliably say "this one is you" across many different recordings.
- **Diarization's cuts are not sentence boundaries** — it splits wherever a
  voice stops, mid-sentence pauses included, and whisper is markedly worse on
  a two-second fragment than on a whole phrase: it has no surrounding words to
  condition on. Worse, a fragment carries no judgeable grammar even when it's
  recognized perfectly, and a mistake spanning the cut is invisible to both
  halves. So same-speaker turns closer than `--merge-gap` are stitched back
  together first. The raw segments stay in the cache, so the gap can be
  retuned without re-running the model.
- **Nothing is sent to any AI automatically** — extraction only *prepares*
  the text. What happens with it next is a separate, deliberate step.
- **A cut between files is not a full stop** — a long session is recorded in
  parts and the recorder cuts on a timer, so one sentence routinely ends up
  split across two files. The half that survives on its own looks like a
  mistake nobody made ("understand that I'm struggling" has no subject until
  you see the previous file's last line). Both halves get flagged rather than
  joined: whether two files really are consecutive parts of one recording is
  something only the owner knows, and stitching unrelated recordings together
  would invent a sentence that was never spoken.
- **Whisper doesn't grade grammar** — it predicts the most likely words for
  a sound. That means in ambiguous, mumbled spots it can occasionally "smooth
  over" a subtle grammar slip. The `[?]` marker flags exactly those lines.

**Coaching memory:**
- **Category names must stay consistent across sessions** — if "article
  errors" quietly became "determiner issues" next week, the occurrence count
  would look like two separate one-off mistakes instead of one recurring
  pattern. the workflow explicitly requires reusing existing category names
  from `memory.md`.
- **`[?]`-marked lines are excluded from grammar judgment** — a line whisper
  wasn't sure it heard can't tell you anything about how it was spoken, so
  scoring one risks inventing a mistake that was never made. The coaching
  workflow reads `lines.json`, where that flag sits on the line itself: the
  two text documents each carry only half of what's needed (sentences in one,
  markers in the other) and don't align one-to-one, and a rule this important
  shouldn't rest on matching them up by eye every session. The same file's
  totals also say how much of the session had to be discarded — past 40%,
  the session is a different and much smaller sample than the ones before it,
  and isn't comparable with them.
- **Regressions are tracked distinctly, not just re-added** — a mistake
  that was marked "improved" and then reappears is a different, more
  important signal than a mistake showing up for the first time. It gets
  moved back and called out explicitly, not silently re-counted.
- **Scores default to staying the same, not drifting.** Without an explicit
  anchor, an LLM re-estimating CEFR/grammar/vocabulary/naturalness/fluency
  from scratch each session tends to wobble up and down a little even with
  no real change — noise that would masquerade as progress or decline.
  the workflow requires a concrete reason from the transcript before moving
  any score from its previous value.
- **Fluency is tracked separately from grammar.** Filler-word frequency
  ("um", "uh") says something real about how fluently you speak, but it's
  not a grammar mistake — mixing it into the mistake-pattern list would
  muddy both signals. It lives in its own line in `memory.md` and its own
  column in `scores_history.csv`.
- **Phrase-fillers are tracked separately again.** "You know", "I mean" and
  their relatives do the same job as "um" for some speakers, but they're
  ordinary words, so the hesitation counter can't see them and
  `--remove-fillers` deliberately leaves them alone. Counting them in with
  hesitation sounds would blur two different habits together; counting them
  by eye each session is how the number stops being comparable. So
  `voxlib/discourse.py` counts them, on their own axis.
- **A chance is not the same as a word.** Every rate here divides by reliable
  words, which is only right if what is counted rises with words. On this
  project's own record it does not — `voxlib/exposure.py` finds session totals
  tracking *how many categories were being looked for* (+0.57) better than
  anything said (-0.26), with the rate falling as sessions get longer (-0.59).
  So `frames/` counts the opportunities directly: one regex per category,
  matching a line where the structure came up at all, whether or not it went
  wrong. It is a lexical proxy rather than a parsed one and it is stated as
  such — what it buys is a series comparable with itself, which the per-word
  rate demonstrably is not. Nothing is adopted on faith: both denominators are
  scored over the same sessions and a frame is used only where it wins, so a
  category with a bad frame and a category with no frame behave identically.
- **Mistake counts are data, not prose.** `memory.md` is rewritten from its
  own previous text every session, which makes it a retelling of a retelling
  by the fourth one — patterns have already gone missing that way. The counts
  live in `analysis/mistakes.csv` with the session's word count beside them,
  so rates can be normalized (sessions here range 1,844-2,547 reliable words),
  absences can be counted mechanically, and "no opportunity to make this
  mistake" stays distinct from "made it zero times".
- **Fluency is measured by code, not read off the transcript.** A metric only
  earns its place in a months-long trend if the same input always produces the
  same number, and a judgment call re-made each session doesn't guarantee that
  — the rule ("`uh-huh` is agreement, not hesitation, so it doesn't count")
  has to live somewhere executable, not in prose inside each report.
  `voxlib/fluency.py` owns it, `analysis/fluency_history.csv` accumulates it,
  and the coaching side only reads. Where a number genuinely can't be
  recovered — pauses in a diarized recording, where the gap between your lines
  is the other person talking — it's left blank rather than estimated.
- **`memory.md` is bounded on purpose** — entries only move into it after
  they've genuinely recurred, and long-resolved ones age out into
  `memory_archive.md` after 10+ sessions of silence. The file you actually
  read stays short; nothing is lost, just archived.
- **Progress is cached per file** (Stage 1) — diarization and transcription
  are the slow steps. A crash shouldn't mean starting over.
- **Same repo, second mode, each side writes only its own file.** This
  this project also has a second mode — Interactive Conversation Practice,
  the `practice-answer` skill, triggered by "let's practice" instead of
  "analyze the recording" — for
  typed dialogue drills targeted at your actual recurring mistakes instead
  of random topics. It reads `memory.md` to pick what to drill but never
  writes to it: mixing typed-conversation practice into the scores tracked
  here would break the session-to-session comparability rule above.
  Instead it keeps its own rotation bookkeeping in
  `analysis/conversation_focus_log.md`. Recording analysis, in turn, may
  read that log for context — e.g. to flag a mistake that was drilled in
  conversation but still showed up in a new recording — but never writes
  to it either. The two modes' rules are never followed at the same time.
