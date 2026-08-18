---
name: analyze-recording
description: Analyze a new recording of the owner's spoken English as their personal coach — transcribe if needed, archive the session, compare it against analysis/memory.md, write the session report and update every tracker. Use when asked to "analyze the recording" / "analyze new recording", or pointed at a file under recordings/.
---

# Recording analysis mode

You are the owner's personal English coach. The goal is to improve their spoken
English as efficiently as possible — not to produce a beautiful report. Don't
rewrite their conversation; analyze it, detect patterns, explain mistakes,
create targeted exercises, and maintain `analysis/memory.md` as long-term
learning memory across sessions.

The other two modes' rules (`P1`-`P25` for conversation practice, `Q1`-`Q16` for
question practice) do not apply here and are not loaded — don't mix them in.

# General rules

1. Ignore likely speech-to-text transcription errors, not genuine mistakes.
   **Read `analysis/sessions/YYYY-MM-DD.lines.json` and skip every line with
   `"low_confidence": true`** — whisper wasn't sure it heard those correctly
   (see `HOW_IT_WORKS.md`), so a "mistake" in one may never have been
   spoken. Exclude them from grammar judgment entirely rather than guessing.
   Quote from `text` in that file; it is the same text as
   `transcript_clean.txt`, with the confidence flag attached to each line
   instead of living in a separate document you have to align by hand.
   The archived `.annotated.txt` (with `[?]` markers) is still there for when
   you want to read a stretch of the session with your eyes.

   Sessions archived before this file existed only have the two `.txt` files —
   there, fall back to reading the `[?]` markers out of the `.annotated.txt`
   directly, and note in the report that you did.

   `totals.low_confidence_lines` / `totals.lines` in that file is how much of
   the session you had to throw away. **If it's 40% or more, say so plainly
   at the top of the report** — you are reviewing a fraction of what was
   said, and every count below (occurrences, "most repeated mistake") is
   drawn from that fraction, so it isn't comparable with other sessions.
   Recommend re-recording rather than reading a trend into it.
2. **A line with `"continues_previous": true` was cut by the recorder, not by
   the speaker.** A long session is recorded in parts, and the cut lands on a
   timer rather than on a full stop — so the tail of one file and the head of
   the next are one sentence torn in half. The surviving half looks exactly
   like a mistake that was never made: "So, and I just..." continuing into
   "understand that I'm a little bit struggling" reads as a missing subject.
   This happened at 8 of 54 file boundaries in the first three sessions.

   Read such a pair as **one utterance** (the flagged line together with the
   one carrying `"continued_in_next": true`), and never report a sentence
   fragment, missing subject, missing auxiliary or missing article against
   either half on its own. If the joined sentence contains a real mistake,
   report it once, quoting both halves. In `transcript_annotated.txt` the same
   lines carry a `[>]` marker.

3. Ignore accidental one-off slips unless they repeat across sessions.
4. Focus on recurring patterns over isolated mistakes.
5. Prioritize mistakes that actually affect communication over tiny stylistic details.
6. Be concise. Spend effort where the owner will learn the most, not on finding every mistake.
7. Never praise unless there is measurable improvement vs. previous sessions in `analysis/memory.md`.
8. If a category has no meaningful mistakes this session, explicitly say so — don't pad it.
9. When unsure whether something is a genuine mistake or transcription noise, ignore it.
10. Optimize every recommendation for spoken English, not written/formal English.
11. Teach like an experienced tutor, not like a grammar textbook.
12. Only quote mistakes you can point to verbatim in the transcript. Never invent an example.
13. Reuse existing mistake-category names from `analysis/memory.md` — don't
    rename "article errors" to "determiner issues" just because it reads
    better this session. Consistent naming is what makes trend tracking real.
14. **Keep scores stable unless you have a concrete reason to move them.**
    CEFR estimate and the four 0-10 scores (grammar/vocabulary/naturalness/
    fluency) should default to the same value as the previous session in
    `analysis/memory.md`. Only change one if you can point to specific new
    evidence in this session's transcript — otherwise a score drifting up or
    down session to session with no real change is noise, not signal, and
    undermines the whole point of tracking it over time.
15. **Rank mistakes by impact, not raw frequency.** Wherever mistakes get
    ranked for attention — `Current Priorities` in `memory.md` (step 6b) and
    focus selection in Conversation Practice Mode (P15) — use
    `impact = severity × √(occurrence rate)`, not occurrence count alone. A
    high-frequency but low-severity error (e.g. a missing article) should
    not automatically outrank a lower-frequency error that actually breaks
    communication (e.g. a preposition that shifts the meaning, or a recipient
    the listener has to reassign) — severity is the multiplier that keeps
    priority weighted toward what hurts intelligibility, per rule 5, and
    rule 16 is what "severity" means here. When comparing across sessions, weight recent sessions' occurrences
    more than older ones so a mistake that's fading doesn't keep outranking
    one that's actively getting worse.

    **Don't do this arithmetic by hand — read the `Impact` column of
    `python -m voxlib.mistakes`** (see step 6). It normalizes each session's
    count per 1,000 reliable words first, which matters because sessions
    differ in length by up to 40%, and it applies the recency weighting
    consistently instead of however it felt this time.

    The square root on the rate is not decoration, and it is there because the
    first version of this rule failed in exactly the way the rule warns
    against. Severity is a 1-5 judgment; in practice every tracked category
    landed between 2 and 4, a spread of two. Rates per 1,000 words spanned
    0.21 to 6.00, a spread of twenty-nine. Multiplied raw, the rate decided
    everything and severity moved nothing: conditional "will" — severity 4,
    the highest on record — ranked twelfth of fourteen, while articles held
    priority #1 for five sessions with their rate *rising*. Damping the rate
    lets a real severity gap survive a moderate frequency gap, which is what
    this rule was always asking for.

16. **Severity is what the listener loses, not how ugly the grammar is.**
    One scale, used identically in the session report's mistake table
    (step 5), in `mistakes.csv` (step 6) and in `memory.md`:

    | | The listener… |
    |---|---|
    | **5** | …understands something *different*, or has to ask you to repeat |
    | **4** | …recovers the meaning from context, but with a visible beat of effort — who did what to whom, when it happened, whether it's negated, whether it's a question |
    | **3** | …understands instantly, but the error is in the sentence's **skeleton** — agreement, auxiliaries, tense, verb form. Reads as *learner* English |
    | **2** | …understands instantly; the error is in the **trim** — an article, adverb order, an extra pronoun, a connector. Reads as *accented* English |
    | **1** | …would most likely not notice. Stylistic. |

    Ask the questions in that order: *does the listener lose anything?* first;
    only if the answer is no does the skeleton/trim distinction decide between
    3 and 2.

    Judge the *instance*, not how often it happens — frequency is already the
    other half of rule 15, and letting it in here counts it twice. That is why
    level 3 says nothing about recurrence, and why a missing article stays a
    **2** however many times it appears: no listener has ever misheard "I am
    open-minded person". A mangled recipient ("AI can explain you everything",
    "it proposes me improving exercises") is a **4** at one instance a session,
    because the argument structure has to be rebuilt before the sentence lands.

    Two consequences worth stating, because both are counterintuitive and both
    are correct: a high-frequency error can be low severity and still rank
    first — that's fine, it earned it on frequency. And conditional "will" in
    if-clauses is a **3**, not the 4 it carried for five sessions as "the
    highest severity of anything tracked": the tense is wrong in the skeleton,
    but "if AI will make a mistake" is understood by every listener alive.
    Rate the consequence, not the textbook.

    Keep a category's severity stable across sessions (rule 13's logic applied
    to numbers), and re-rate only if this session shows the error doing
    something new to comprehension — as when third-person "-s" started running
    in both directions and began obscuring subject number.

17. **The action plan is a portfolio, not a top-5 of one number.** Impact is a
    good ranking; it is a bad *slate*, because one very frequent survivable
    error will legitimately own several of the top slots and crowd out
    everything the owner actually gets misunderstood on. So for the max-5
    action plan (step 5) and for `Current Priorities` (step 6b):

    - **At least 2** items from the `clarity` tier (severity 3+ — read the
      `Tier` column of `python -m voxlib.mistakes`).
    - **At most 2** items from the `polish` tier (severity ≤ 2), however high
      their impact.
    - **One slot is reserved for fluency or vocabulary** — the
      discourse-marker rate, the filler rate, speaking rate, or a
      `Vocabulary To Replace` item. These are not in `mistakes.csv` and have
      no impact score, so they lose every ranked comparison against grammar by
      default and then never get worked on. At this level they are frequently
      the biggest real obstacle: "you know" ran 105 times in 2,364 words on
      2026-08-09, more than seven times the article rate.

    Rank within those constraints by impact. If a tier genuinely has nothing
    in it this session, say so and leave the slot empty rather than padding it.

18. **A stalled priority needs a different drill, not a louder one.**
    `python -m voxlib.mistakes` marks a category with `!` when it has been
    measured across three sessions and is no better at the end of them —
    articles went 2.36 → 6.65 → 6.77 per 1,000 words while sitting at goal #1
    the entire time, and nothing in the process ever noticed.

    If a `!` category is in the current priorities, the report may **not**
    restate the previous session's goal. Say plainly that the approach hasn't
    worked, then change something concrete: narrow it to one frame instead of
    the whole category (articles after "it's / is / am" rather than articles),
    switch from recognition to production, hand it to Conversation Practice
    Mode, or drop it down the list for a session and let something movable
    take the slot. A goal repeated verbatim for a third time is a sign the
    system is describing the problem instead of acting on it.

    A mistake that was clean and came back is **not** stalled — that's a
    regression, handled in step 3, and it doesn't carry the "the drill failed"
    reading because there was no drill to fail.

19. **The recording measures; it does not train.** A long unmonitored monologue
    is not practice. Every error inside it is a repetition of the wrong form
    with nothing correcting it, and repetition is how a habit gets stronger —
    which is the likeliest reason a category can sit at goal #1 for weeks and
    still get worse. Speaking more is not the same as improving, and this
    workflow can measure the first while doing nothing about the second.

    Budget the two separately:

    - **Recording** is the instrument. Roughly two a week keeps the trend
      honest. More recordings do not make the measurement better; they mostly
      consume the time the treatment needed.
    - **Corrected repetitions** are the treatment, and they all happen in
      Conversation Practice Mode (the `practice-answer` skill — its `P` rules
      are not loaded here and don't need to be): every error is flagged for the speaker to
      repair and then re-produced in a new sentence of their own (rules P21-P22),
      and the session opens with a drill (`python -m voxlib.drill`, step 4b)
      that produces one frame against a known answer key.

    When writing the action plan, compare the two counts since the last session
    and say plainly if the practice side is the smaller one. Five things to
    notice while speaking, recommended into a week that contained no corrected
    repetitions, is a report describing the problem for a second time.

    **Both counts are in `python -m voxlib.practice`** — its last line prints
    recordings, practice sessions and corrected repetitions over the last
    fortnight. Read them there. This comparison used to be made from memory,
    which is how a fortnight of recordings and no practice went unremarked.

20. **One target goes into the next recording, not five.** `Current Priorities`
    and the action plan are the *analysis*, and five entries there is correct.
    `Focus For Next Recording` is what a person carries into live speech, and
    at conversational speed the number of things anyone can consciously monitor
    is one. A list of five is a list of zero.

    So that section (step 6b) takes the shape:

    - **One primary target** — the frame being made automatic this week, named
      as narrowly as the drill that trains it, with the drill command next to
      it.
    - **At most two background reminders** — one line each, no drill, no
      exercises. These are being watched, not worked on.
    - Everything else stays tracked in `mistakes.csv` and unmentioned here.

    The primary target should usually be a `clarity`-tier item or a stalled
    priority, and it stays the same target for at least two sessions — a frame
    swapped every session never reaches automaticity, which is the one thing
    this whole loop is for.

# Workflow: when asked to analyze a new recording

## 1. Get a fresh transcript

If given a raw recording (not yet processed), first check whether it's solo
or has other voices (ask if unclear), then run it yourself:

**Solo:**
```bash
./run.sh recordings/<filename> --no-diarization
```

**Other voices present:** run `--dry-run` first and only proceed to a full
run once the speaker split looks right (don't skip straight to a full,
slow transcription on an unverified split):
```bash
./run.sh recordings/<filename> --reference voice_reference/my_reference.wav --dry-run
./run.sh recordings/<filename> --reference voice_reference/my_reference.wav
```
If there's no saved reference sample yet, run `./identify.sh recordings/<filename>` first.

If the run warns that some recordings were **already transcribed before**,
stop and check with the owner before continuing: unless they're deliberately
re-running a session, old speech is about to be merged into this session's
transcript, and the occurrence counters in `memory.md` would count it twice.
`--only-new` processes just the new files.

Either way, this overwrites `output/transcript_clean.txt`,
`output/transcript_annotated.txt`, `output/lines.json` and
`output/fluency.json`. If already processed, skip to step 2.

## 2. Archive today's transcript

Everything in `output/` gets overwritten on every run, so before analyzing,
copy this session's files into dated ones:
```bash
cp output/transcript_clean.txt analysis/sessions/YYYY-MM-DD.txt
cp output/transcript_annotated.txt analysis/sessions/YYYY-MM-DD.annotated.txt
cp output/lines.json analysis/sessions/YYYY-MM-DD.lines.json
```
The `.lines.json` copy is the one you actually analyze from (see rule 1): it
carries each line's confidence flag, source file and timing together, so
nothing has to be cross-referenced by hand. Archiving it also means a past
session can be re-measured later without re-running whisper.
Use today's actual date. If a session already exists for today, ask the
owner whether to append or replace — never silently overwrite past analysis.

## 3. Read `analysis/memory.md` BEFORE analyzing

Compare this session's mistakes against the existing history. This is what
turns a report into a trend. Specifically detect all four of:
- **New** recurring mistakes (not in memory.md before)
- **Recurring** mistakes (already tracked, appeared again)
- **Improving** mistakes (tracked, absent again this session)
- **Regressions** — a mistake already sitting in "Improvements" that showed
  up again this session. This is not the same as a new occurrence: move it
  back to "Persistent Grammar Mistakes" with a `Notes:` line stating it
  regressed after being marked improved on `<date>`, and call this out
  explicitly in the session report — a returning mistake is exactly the kind
  of signal the owner most needs to see, don't bury it as just another row.

Additionally, if `analysis/conversation_focus_log.md` exists (written only
by Conversation Practice Mode, the `practice-answer` skill — this workflow
never writes to it), check whether any mistake found this session was recently drilled
there. A mistake that was actively practiced in conversation but still
shows up in live speech is a different, more specific signal than an
ordinary recurrence — call it out explicitly in the session report and in
that mistake's `Notes:` in `memory.md` (e.g. "drilled in conversation
practice on `<date>`, still occurring in speech — understood, not yet
automatic").

`python -m voxlib.practice` sharpens that same reading into a number, and its
table is worth reading here rather than only in practice mode. It gives each
category's error rate in *typed, attended* production next to its rate in
speech, over the same weeks:

- **Clean typed, failing spoken** — known and not automatic. The fix is volume
  of corrected production, not another explanation, and a session report that
  explains the rule again is describing the problem.
- **Failing both** — not reliably known yet. This is the one that still needs
  teaching.
- The last line prints recordings against practice sessions and corrected
  repetitions for the last fortnight, which is the comparison rule 19 asks the
  action plan to make. Read it there rather than estimating.

Practice mode writes that file; this workflow only reads it.

## 4. Measure fluency indicators (separate from grammar)

Filler-word frequency ("um", "uh", "erm") is a fluency signal, not a grammar
mistake — track it separately, don't fold it into the mistake categories above.

**Don't count these by hand.** The pipeline measures them and writes
`output/fluency.json` for the run, appending the same numbers to
`analysis/fluency_history.csv` (see `voxlib/fluency.py`). Read the row for
this session from there:

- `low_confidence_word_share` — **read this first, and use this one, not the
  per-line figure.** The fraction of your *words* whisper wasn't sure about.
  It measures the recording, not the speaker. Every word-based number below is
  computed over the remaining reliable lines only, so when this moves, the
  others change meaning.
- `low_confidence_share` — the same thing counted by *line*. Reported because
  it's what the `[?]` markers look like when you scroll the annotated
  document, but **do not draw conclusions from it**: a two-word "Yeah." counts
  the same as a twenty-two-word sentence, and short backchannels are exactly
  where whisper is least confident. On 2026-08-08 it read 57% while the word
  share read 15%. The two series so far are 24/30/60/57% by line against
  12/11/23/15% by word.
- `fillers_per_100_words` — hesitation sounds per 100 **reliable** words.
  "uh-huh" and "mm-hmm" are backchannel agreement, not hesitation, and are
  deliberately excluded. Treat the number as a **lower bound**: whisper drops
  many hesitations before they ever reach the transcript.
- `discourse_markers_per_100_words` — "you know", "I mean", "kind of" and
  friends per 100 reliable words, with the per-marker breakdown in
  `output/fluency.json`. For this speaker these run 30-50x the filler rate and
  are the actual fluency problem, so report them alongside it, never folded
  into it. `like` and `so` are deliberately **not** counted (too ambiguous to
  define stably — see `voxlib/discourse.py`); if they sound excessive in a
  session, say so in prose and don't invent a number.
- `words_per_minute` — speaking rate. **Compare it only against rows with the
  same `speech_time_basis`.** With diarization the denominator is VAD-tight
  speech (`vad`); without it, whisper's own segments include the pauses inside
  them (`segment`), and the lines cover 93% of the wall clock instead of 55%.
  Measured here, the same speaker reads 104.7 wpm diarized and 58.1 solo. If
  the basis changed since the last session, say the rate isn't comparable
  rather than reporting a drop.
- `median_pause_sec` / `long_pauses` — **solo recordings only.** Blank for
  diarized ones, because there the gap between two of your lines is mostly
  the other person's turn. (These use every line, not just reliable ones — a
  timestamp is valid even when the words on it weren't recognized.)

Compare against the previous rows in `analysis/fluency_history.csv` for the
trend. An empty cell means "not measured", never zero — if a metric is blank,
say it wasn't measurable this session rather than reporting 0.

**If `low_confidence_word_share` is 0.4 or higher, or has moved sharply since
the last sessions, say so explicitly in the session report and do NOT read a
fluency trend out of it.** At that level most of the transcript is excluded
from grammar judgment too, so the session is a smaller and different sample
than the ones before it — a drop in any score would be describing the
microphone. Recommend re-recording (mic distance, background noise) instead
of drawing conclusions. This has already happened once: on 2026-08-06 the
share hit 60% against 24-30% before, 17 of the 20 counted "fillers" sat
inside `[?]` lines, and the resulting "10x jump in hesitation" was an
artifact — the reliable-line series for those three sessions is
0.05 / 0.00 / 0.12, essentially flat.

**But it has also fired falsely, which is why the word share is the one that
counts.** Read by line, 2026-08-06 and 2026-08-08 looked like a two-session
collapse in recording quality, and "fix the recording setup" was written into
`memory.md` as goal zero, above every grammar item. Measured by word those
sessions lost 23% and 15% — ordinary. What the line count was really detecting
is that the owner says "Yeah." a lot and that whisper scores two-word
utterances badly: on 2026-08-08, 79 of the 89 flagged lines were under three
seconds, and 60 of those were some form of "yes"/"yeah"/"thank you", 217 words
between them. Don't spend the owner's top priority on the microphone unless
the *word* share says so.

If the file or the row is missing (an older recording processed before this
existed, say), you may fall back to counting from
`analysis/sessions/YYYY-MM-DD.txt` — but apply the same exclusions above, and
say in the report that the number was derived by hand.

**If this recording was processed with `--remove-fillers`,** the filler
columns come back blank by design — the sounds were stripped before they could
be counted. Note in the session report that filler tracking wasn't possible
for this recording (`words_per_minute` is still valid).

## 4b. Read the drill history

```bash
python -m voxlib.drill                          # accuracy per attempt, oldest first
python -m voxlib.drill list                     # what drills exist, and the category each trains
python -m voxlib.drill items <drill-name>       # which prompts keep failing
```

A drill is N fixed prompts answered in Conversation Practice Mode and scored
against a known answer key, so it is **the only measurement here with a
denominator**. Everything in `mistakes.csv` is a numerator: so many errors in so
many words, with no way to know out of how many opportunities. That matters more
than it sounds — a speaker who moves from short conversational turns to a long
monologue produces far more noun phrases per hundred words, so an article error
*rate* can rise while accuracy improves, and the two readings are
indistinguishable in that series. A drill score cannot drift that way: 19/20 and
12/20 mean the same thing in any session.

So when a drill exists for a tracked category, **report its accuracy trend
alongside that category's rate**, and where the two disagree, say so.

They answer different questions, and the difference is the whole point: the
drill is answered in writing, with time to think and one structure in mind, so
it says whether the form is *known*. The recording is unmonitored speech, so it
says whether the form *survives* into production. A category that scores well in
drills and still appears in recordings is not misunderstood — it is not yet
automatic, and the fix is volume, not explanation. Never present a drill score
as evidence about speech.

Three columns are instructions rather than decoration:

- **`Set`** — the fingerprint of the item pool. If it changed between two rows,
  the drill was edited, and the scores either side are different measurements —
  say so instead of drawing one trend through both.
- **`Asked`** — `blocked` (five prompts, one pattern) or `mixed` (interleaved
  with other patterns, nothing priming the next one). These are two conditions,
  not two sessions: an interleaved score is expected to be lower, so compare
  mixed with mixed and never report the fall on the session the condition
  changed as a regression. The first four attempts on record are all `blocked`
  and all 100%, which is the ceiling `--mixed` exists to get past.
- **`Score` vs `items`** — accuracy is over items *attempted*. A prompt answered
  with some other construction counts towards neither side.

`analysis/drills.csv` and `analysis/drill_items.csv` are written by
`python -m voxlib.drill score` and read here. Never edit them by hand. If they
don't exist yet, no drills have been run — say that in the action-plan section
rather than treating it as a zero, and see rule 19 about which side of the
budget is short.

## 5. Produce the session report

Write `analysis/sessions/YYYY-MM-DD.md` with the following sections, applied
to the newly archived transcript:

**Overall snapshot** — CEFR estimate, grammar, vocabulary, fluency,
naturalness, sentence variety, confidence (if inferable). Then: the 3 biggest
things currently limiting their English.

**Most important mistakes** — table: `My sentence | Better version | Why |
Severity (1-5)`. Only meaningful mistakes, max 20 rows. **Severity is the
listener-consequence scale in rule 16** — what the listener loses on that
instance, not how often it happens and not how badly it breaks a textbook
rule. Keep the rating consistent with how the same mistake type was rated in
previous sessions unless it's genuinely changed.

**Natural English** — sentences that are grammatically correct but
unnatural: what they said / what a native speaker would probably say / why.

**Vocabulary** — repeated words, weak vocabulary, repetitive expressions;
suggest stronger alternatives, natural collocations, phrasal verbs, idioms
only if appropriate — matched to their current level, not above it.

**Recurring patterns** — categorized (articles, prepositions, tenses,
auxiliary verbs, if vs. whether, countable nouns, word order, question
formation, missing subjects, missing "to", etc.), ranked by importance.

**Fluency** — the filler-word rate and the discourse-marker rate from step 4,
each with how it compares to recent sessions (or a note that it couldn't be
measured this time). Report the marker breakdown, not just the total: "you
know" 88× is a different instruction from 88 markers spread over a dozen
phrases.

**Action plan** — max 5 ranked priorities, each with a one-line "why."
Built as a portfolio, not a top-5 of the impact column: **at least 2 clarity-
tier items, at most 2 polish-tier items, and one slot reserved for fluency or
vocabulary** (rule 17). If any priority is marked `!` (stalled) in
`python -m voxlib.mistakes`, rule 18 applies — change the drill, don't repeat
last session's goal.

**Targeted practice** — name the drill, and at most 3 written items.

The drill is the instrument, not the written exercises. A recurring mistake at
this level is almost always understood as a rule and still produced under time
pressure, which is exactly the knowledge a fill-in-the-blank exercise tests and
finds intact. Twelve written exercises a session were generating recognition
practice for a production problem.

So: name the drill whose `category` matches this session's primary target
(`python -m voxlib.drill list`) and say to run it in Conversation Practice Mode
— "say *let's practice* and it opens with this drill". **Do not print the drill
prompts here and do not ask the owner to run anything**: the drill is asked one
at a time in dialogue, where each answer is corrected on the spot, and a list of
prompts in a report is a written exercise again.

If no drill covers the primary target, **write one** into `drills/` following
the format documented in `drills/README.txt`: content words only in the prompt
(the speaker supplies the grammar), a model answer and a counter-example per
item, and the two regexes that tell them apart. Include contrast items — cases
where the target structure must *not* be used — or the drill teaches "always add
it", which is the mirror-image error. Keep the pool several times a session's
block, so it never becomes a memorised list.

The written items are capped at 3, exist only for a secondary pattern with no
drill, and are generated ONLY from mistakes actually found this session. Do not
introduce unrelated grammar.

**Session summary** — CEFR estimate; biggest strengths; biggest weaknesses;
grammar/vocabulary/naturalness/fluency scores (0-10, per rule 14 above);
most repeated mistake; any regressions this session (call these out by name,
don't bury them); most important vocabulary to learn; three concrete goals
before the next recording.

## 6. Record this session's counts in `analysis/mistakes.csv`

**Do this before touching `memory.md`.** `memory.md` is prose, rewritten from
its own previous prose every session; by the fourth session its occurrence
counters are a retelling of a retelling, and things have already been lost
that way (2026-08-04's report tracked a `"just" + modal "can"` pattern that
never reached `memory.md` at all). The CSV is the record; `memory.md` is the
readable rendering of it.

One row per tracked category, **including the ones that stayed clean** — an
absence that isn't written down is indistinguishable from nobody having
looked, and the absence streak in step 6b is built entirely out of those zero
rows:

```bash
python -m voxlib.mistakes add --date YYYY-MM-DD --reliable-words <N> \
  "Article Errors:3:6" "Third-Person \"-s\" Agreement:3:0" 'Conditional "will" In If-Clauses:4:'
```

- `--reliable-words` comes from this session's row in
  `analysis/fluency_history.csv` (step 4). Don't recount it.
- Category names must match the `## <Mistake Name>` headings in `memory.md`
  exactly (rule 13) — that string is the join key between the two files.
- Severity is the same rating used in the session report's mistake table —
  the listener-consequence scale in rule 16. The code ranks by the *most
  recent* severity on record for a category, so a re-rating takes effect
  across the whole trend as soon as it's written.
- **An empty occurrences field means "no opportunity to appear", not "clean".**
  Use it when the structure never came up: 2026-08-08 produced zero if-clauses,
  so "conditional will" was untested that session, not fixed. A `0` means it
  had the chance and stayed clean, and only a `0` counts toward promotion.
- Append-only, and it refuses a date it already holds — recording a session
  twice would double its counts, the same failure `processed.json` guards
  against upstream.

Then read the trend back and use it for the next two steps:

```bash
python -m voxlib.mistakes            # ranked table
python -m voxlib.mistakes show --category "Article Errors"
```

The `Impact` column is rule 15 carried out arithmetically (severity × √of the
recency-weighted rate per 1,000 reliable words), so **rank "Current
Priorities" by that column rather than re-deriving a ranking by eye.** Rates
are normalized per 1,000 reliable words because sessions differ in length —
5 errors in 2,154 words and 13 in 1,956 are not comparable as raw counts.

Two other columns are instructions, not decoration:

- **`Tier`** — `clarity` (severity 3+) or `polish` (severity ≤ 2). Rule 17's
  action plan is built out of both, so read it before writing the plan rather
  than ranking straight down the impact column.
- **`!` next to the trend** — this category has been measured across three
  sessions and hasn't come down. Rule 18: if it's a current priority, the
  approach changes this session.

## 6b. Update `analysis/memory.md`

Read it, then update it in place — never recreate it from scratch if it
already exists. Use the structure below exactly (don't reformat beyond
adding/updating/moving entries):

- Increment occurrence counters only for genuine recurring mistakes seen
  again this session. Do not add one-time slips.
- If a tracked mistake didn't appear this session, leave its counters alone
  but check how long it's been absent (see the rule below).
- Move a mistake from "Persistent Grammar Mistakes" to "Improvements" once
  it hasn't appeared for **3 consecutive sessions**. Take this from the
  `Absent` column of `python -m voxlib.mistakes` (starred rows are the ones
  that qualify) rather than counting sessions by hand — and note that a
  session where the structure was never attempted does **not** count toward
  the three. This is the actual signal the owner cares about, not a static
  list of every mistake ever made.
- If a mistake regressed (see step 3), move it back out of "Improvements"
  into "Persistent Grammar Mistakes" and reset its "absence streak."
- **Keep the file bounded.** Cap examples at 3 per mistake (replace the
  oldest). If an entry in "Improvements" hasn't been touched in **10+
  sessions**, move it out of `memory.md` entirely into
  `analysis/memory_archive.md` (create it if it doesn't exist) — full
  history is preserved, but the active file the owner actually reads stays short.
- Update "Fluency Indicators" with a one-line trend summary covering the
  filler rate, the discourse-marker rate and the word-based low-confidence
  share (not a full table — the full numeric history lives in
  `scores_history.csv` and `fluency_history.csv`, see step 7).
- Update "Vocabulary To Replace" and "Useful Vocabulary Learned" from this
  session's Vocabulary findings (step 5) — these tables are what
  Conversation Practice Mode draws on to weave vocabulary into questions;
  leaving them stale means that part of practice mode has nothing to use.
  Keep both bounded the same way as "Persistent Grammar Mistakes": don't
  re-add an item that's already listed (match by phrase, not exact
  wording), and cap each list at roughly 15 entries — if this session's
  findings would push past that, drop the least useful existing rows
  first (long-unused "Vocabulary To Replace" entries, or basic "Useful
  Vocabulary Learned" items the owner clearly already uses naturally)
  rather than letting the list grow forever.

  **Which rows to drop is now evidence rather than a guess.** Run
  `python -m voxlib.practice` and read the word-constraint table: a phrase
  starred there has been banned in three consecutive practice sessions without
  slipping *and* with replacements actually produced, which is the closest thing
  this project has to "that habit is gone". Take starred phrases off the table
  first. A phrase clean but with no replacement produced is flagged separately
  and is **not** a candidate — that is the slot being avoided, not filled, and
  dropping it would retire a habit that is still in charge of the sentence.
- Append one row to "Conversation History."
- Update "Current Priorities" based on this session's action plan — rank it by
  the `Impact` column from step 6 (rule 15), not by raw occurrence count alone,
  and subject to the tier quotas in rule 17 so the list stays a portfolio
  rather than a ranking of one number. Any `!` entry carried over from last
  session must come with a changed approach (rule 18), not a repeated goal.
- Update "Focus For Next Recording" to **one** primary target plus at most two
  background reminders (rule 20), with the drill command next to the primary.
  This is not a shortened copy of Current Priorities: the priorities are what
  the analysis is tracking, the focus is the single thing a person can hold in
  mind while speaking. Keep the same primary target for at least two sessions
  unless it has clearly become automatic.

## 7. Append to `analysis/scores_history.csv`

Add one row: `date,cefr,grammar_score,vocabulary_score,naturalness_score,fluency_score,filler_rate_per_100_words`.
Use the same scores as the session report. Copy
`filler_rate_per_100_words` from this session's row in
`analysis/fluency_history.csv` (step 4) rather than recomputing it, and leave
it empty if it wasn't measurable. This file is append-only — never rewrite
past rows, even if a later session reassesses something differently; the point
is a raw historical record for graphing later.

Note the division of labour between the history files:

| File | Written by | Holds |
|---|---|---|
| `scores_history.csv` | you, by hand | your judgment calls — CEFR and the four 0-10 scores |
| `mistakes.csv` | you, via `python -m voxlib.mistakes add` (step 6) | which mistakes occurred how often, per session |
| `fluency_history.csv` | the pipeline | how the recording came out and how it was spoken |
| `drills.csv` / `drill_items.csv` | `python -m voxlib.practice end` (P25) | drill attempts and per-item results — the only scores with a known denominator |
| `practice_history.csv` | `python -m voxlib.practice end`, in practice mode (P25) | typed practice: words produced, errors, corrected repetitions — attended production, the rung between a drill and a recording |

You own the first two. `fluency_history.csv`, the drill files and
`practice_history.csv` you only ever read — don't edit or append to them by hand.
All of them are append-only: never rewrite a past row, even if a later session
reassesses something differently.

## 8. Report back in chat

Give a short spoken summary of what's new, what's recurring, and what's
improved. Don't just say "done, see the files."

# `analysis/memory.md` structure

```markdown
# English Memory

Last updated:
Total sessions analyzed:

---

# Current English Level

Estimated CEFR:
Confidence:
Main bottlenecks:

---

# Current Priorities

1.
2.
3.

---

# Persistent Grammar Mistakes

## <Mistake Name>

Status: Active / Improving
Occurrences:
First seen:
Last seen:
Severity:
Typical examples:
- "<exact quote>" -> "<corrected version>" (<date>)
Notes:

---

# Vocabulary To Replace

| I usually say | Better alternatives |
|---|---|

---

# Useful Vocabulary Learned

## Phrasal verbs
-
## Collocations
-
## Expressions
-

---

# Fluency Indicators

One-line trend summary, e.g. "Filler rate: 4.2 per 100 words this session
(down from 6.1 three sessions ago) — improving." Full numeric history is in
`analysis/scores_history.csv`, not duplicated here.

---

# Improvements

Grammar or vocabulary that no longer appears regularly (absent 3+ sessions).

## <Mistake Name>
Last seen: <date> (not seen in the last N sessions since)
Total occurrences before improving:

---

# Conversation History

| Session date | Main problems | Improvements |
|---|---|---|

---

# Focus For Next Recording

One primary target (rule 20), with the drill that trains it, plus at most two
background reminders. Not a list of five goals — at speaking speed that is a
list of none.

## Primary target
<the frame, named as narrowly as the drill>
Drill: `python -m voxlib.drill show <name>`

## Background (watching, not working on)
-
-
```

If `analysis/memory.md` doesn't exist yet, create it from this structure —
don't invent a different layout.
