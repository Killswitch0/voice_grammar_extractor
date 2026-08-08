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
 │   yours"     │     │  (whisper)   │     │  [?] markers │     │ fluency.json      │
 └──────────────┘     └──────────────┘     └──────────────┘     └───────────────────┘
```

| Step | Tool | What it answers |
|---|---|---|
| 1. Extract audio | `ffmpeg` | "Turn any video/audio container into a clean waveform" |
| 2. Diarize | `pyannote.audio` | "At each moment, who is speaking?" (only if other voices are present) |
| 3. Merge segments | this tool | "Which of those cuts were mid-sentence pauses rather than real turn boundaries?" |
| 4. Identify | cosine similarity vs. your reference voice sample | "Which speaker is *me*?" |
| 5. Transcribe | `faster-whisper` | "What did *my* segments actually say?" |
| 6. Format | this tool | "Put it in chronological order, one line per line, plus a `[?]` marker on low-confidence lines" |
| 7. Measure fluency | this tool | "How fast, how hesitant, how much pausing?" — written to `fluency.json` (see `voxlib/fluency.py`) |

If it's just you talking (a journal, a monologue) — steps 2 through 4 are
skipped entirely with `--no-diarization`, and transcription runs on the whole
file, where whisper does its own splitting by pauses.

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
| `analysis/conversation_focus_log.md` | Written only by Conversation Practice Mode (the other mode in this same `CLAUDE.md`, triggered by "let's practice" instead of "analyze the recording") — tracks which `memory.md` patterns were drilled in dialogue and when. Recording analysis reads it for context (to flag a mistake that was drilled in practice but is still occurring) but never writes to it — see "Same repo, second mode" below |

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
  `CLAUDE.md` also has a second mode — Interactive Conversation Practice,
  triggered by "let's practice" instead of "analyze the recording" — for
  typed dialogue drills targeted at your actual recurring mistakes instead
  of random topics. It reads `memory.md` to pick what to drill but never
  writes to it: mixing typed-conversation practice into the scores tracked
  here would break the session-to-session comparability rule above.
  Instead it keeps its own rotation bookkeeping in
  `analysis/conversation_focus_log.md`. Recording analysis, in turn, may
  read that log for context — e.g. to flag a mistake that was drilled in
  conversation but still showed up in a new recording — but never writes
  to it either. The two modes' rules are never followed at the same time.
