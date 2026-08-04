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
2. **Coaching memory** — a Claude Code workflow (`CLAUDE.md`) that reads
   that transcript, analyzes your grammar, and maintains a persistent
   `analysis/memory.md` across every recording — so mistakes get tracked as
   trends (recurring / improving / regressed), not re-discovered from
   scratch every time.

## Stage 1 — Extraction pipeline

```
 ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
 │  Video/Audio │ ──> │   Extract    │ ──> │   Diarize    │ ──> │  Identify    │ ──> │  Transcribe  │ ──> │   Format     │
 │  (any format)│     │   Audio      │     │ "who spoke   │     │  "which one  │     │  only YOUR   │     │  chronologi- │
 │              │     │  (ffmpeg)    │     │  when"       │     │  voice is    │     │   lines      │     │  cal order + │
 │              │     │              │     │ (pyannote)   │     │   yours"     │     │  (whisper)   │     │  [?] markers │
 └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘     └──────────────┘     └──────┬───────┘
                                                                                                                 │
                                                                                                                 v
                                                                                                       ┌───────────────────┐
                                                                                                       │ transcript_clean  │
                                                                                                       │ transcript_annot- │
                                                                                                       │ ated (with [?])   │
                                                                                                       └───────────────────┘
```

| Step | Tool | What it answers |
|---|---|---|
| 1. Extract audio | `ffmpeg` | "Turn any video/audio container into a clean waveform" |
| 2. Diarize | `pyannote.audio` | "At each moment, who is speaking?" (only if other voices are present) |
| 3. Identify | cosine similarity vs. your reference voice sample | "Which speaker is *me*?" |
| 4. Transcribe | `faster-whisper` | "What did *my* segments actually say?" |
| 5. Format | this tool | "Put it in chronological order, one line per line, plus a `[?]` marker on low-confidence lines" |

If it's just you talking (a journal, a monologue) — steps 2 and 3 are skipped
entirely with `--no-diarization`, and step 4 runs on the whole file.

## Stage 2 — Coaching memory (Claude Code + `CLAUDE.md`)

```
 ┌───────────────────┐     ┌───────────────────┐     ┌────────────────────┐
 │ transcript_clean  │ ──> │ Claude Code       │ ──> │ analysis/sessions/ │
 │ + annotated (from │     │ reads CLAUDE.md,  │     │ YYYY-MM-DD.md      │
 │  Stage 1)         │     │ analyzes grammar, │     │ (this session's    │
 │                   │     │ compares against  │     │  coaching report)  │
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
- **Nothing is sent to any AI automatically** — extraction only *prepares*
  the text. What happens with it next is a separate, deliberate step.
- **Whisper doesn't grade grammar** — it predicts the most likely words for
  a sound. That means in ambiguous, mumbled spots it can occasionally "smooth
  over" a subtle grammar slip. The `[?]` marker flags exactly those lines.

**Coaching memory:**
- **Category names must stay consistent across sessions** — if "article
  errors" quietly became "determiner issues" next week, the occurrence count
  would look like two separate one-off mistakes instead of one recurring
  pattern. `CLAUDE.md` explicitly requires reusing existing category names
  from `memory.md`.
- **`[?]`-marked lines are excluded from grammar judgment** — the coaching
  workflow reads `transcript_annotated.txt` specifically to know which lines
  are low-confidence transcription, not genuine mistakes, before scoring anything.
- **Regressions are tracked distinctly, not just re-added** — a mistake
  that was marked "improved" and then reappears is a different, more
  important signal than a mistake showing up for the first time. It gets
  moved back and called out explicitly, not silently re-counted.
- **Scores default to staying the same, not drifting.** Without an explicit
  anchor, an LLM re-estimating CEFR/grammar/vocabulary/naturalness/fluency
  from scratch each session tends to wobble up and down a little even with
  no real change — noise that would masquerade as progress or decline.
  `CLAUDE.md` requires a concrete reason from the transcript before moving
  any score from its previous value.
- **Fluency is tracked separately from grammar.** Filler-word frequency
  ("um", "uh") says something real about how fluently you speak, but it's
  not a grammar mistake — mixing it into the mistake-pattern list would
  muddy both signals. It lives in its own line in `memory.md` and its own
  column in `scores_history.csv`.
- **`memory.md` is bounded on purpose** — entries only move into it after
  they've genuinely recurred, and long-resolved ones age out into
  `memory_archive.md` after 10+ sessions of silence. The file you actually
  read stays short; nothing is lost, just archived.
- **Progress is cached per file** (Stage 1) — diarization and transcription
  are the slow steps. A crash shouldn't mean starting over.
