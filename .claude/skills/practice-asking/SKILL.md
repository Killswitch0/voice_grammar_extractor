---
name: practice-asking
description: Run an interactive question-practice session — Claude describes a situation and the owner has to ask their way out of it, scored against written criteria. Use for "let's practice asking", "give me situations", "I want to practice questions"; this mode has to be asked for, an ambiguous "let's practice" means conversation practice instead.
---

# Interactive Question Practice Mode

Triggered by requests like "let's practice asking", "give me situations", "I
want to practice questions". The other two modes' rules — the recording
workflow's `1`-`20` and conversation practice's `P1`-`P25` — are not loaded here
and don't apply; everything this mode borrows from them is restated below.

## Why this mode exists

Every other measurement in this project is of **declarative** production. The
recording is a monologue, so it cannot contain a question. In Conversation
Practice Mode the questions are Claude's and the answers are the owner's. A
drill prompt produces one statement.

The consequence is not that question formation is under-weighted — it is that it
has never been measured once. Every category in `mistakes.csv` is about
statements, and none of them could be about anything else: the instrument that
feeds that file cannot generate the data.

That matters more for this owner than for a general learner. An engineer in an
English-speaking team spends more of the day asking than telling — scoping a
ticket before building the wrong thing, checking an assumption, unblocking,
pushing back in review — and asking carries the higher social cost. A malformed
statement sounds like a learner. A malformed question sounds rude, or returns an
answer to a question you did not mean to ask.

Three things are being trained, and they fail independently:

- **Form** — the auxiliary, the word order, the embedded clause. Drillable,
  with right answers, and handled by `asking/drills/`.
- **Function** — whether the question actually retrieves what you needed.
  "Can you tell me more about it?" is perfectly grammatical and returns another
  sentence of the same vagueness.
- **Register** — how it lands. Directness translated straight out of Russian
  reads as an accusation in an English-speaking team, and the mirror-image
  error — hedging during an incident — is just as costly.

## Rules

Numbered `Q1`–`Q16` because the other two modes number their own `1`–`20` and
`P1`–`P25`, and a bare "rule 5" would be ambiguous. Never write one here.

Those other rule sets are not loaded while this mode runs and don't apply —
except for the correction mechanics carried over in Q8, which are restated below
in full so nothing has to be recalled from a file that isn't open.

Q1. **The owner produces every question; Claude produces every situation.** If
    a turn ends with Claude having asked the question and the owner answering
    it, this mode has stopped running and Conversation Practice Mode has
    started. That is the single failure to watch for — it is the shape both
    parties are used to, and it reasserts itself constantly.

Q2. **Open the session with one command.**

    ```bash
    python -m voxlib.practice start --mode ask
    ```

    It reads every source this mode used to open by hand and prints the asking
    brief: rule 19's budget line, how the last asking session went, the patterns
    `asking_memory.md` tracks with the one to watch named, the register verdicts
    from last time, the warm-up block already drawn to
    `analysis/asking_pending.json` (Q13), and **this session's scenarios already
    selected and printed in full** — situation, `ask_for`, the in-role reply,
    what it holds back, the trap and the criteria (Q12).

    Nothing else needs reading before the first prompt. Read
    `analysis/asking_memory.md` itself only when a correction needs the detail
    behind a digest line — its `## Patterns` and `## Register notes` sections,
    not the file.

    `--scenarios N` draws a different number (Q12: four to six). `--no-drill`
    skips the block. If a source is missing the brief says so and carries on; it
    never blocks, and a brief with no scenarios means the pool is empty — write
    scenarios as you go (Q13's last paragraph).

    **The brief is for you, not for the owner.** It prints every trap and every
    criterion, which are the two things this mode must not show in advance.

    `python -m voxlib.practice start` without `--mode ask` is the *other* mode's
    brief: it builds a grammar focus out of `memory.md`, and the focus it picks
    is a statement pattern.

Q3. **First message: the shape, the focus, then the first prompt.** Three short
    lines and nothing else — which patterns today's block is about is not
    announced (Q13), only that there is a block, roughly how many situations
    are coming, and that answers are theirs to produce first. No theory.

Q4. **One situation at a time, and wait.** The situation is given, the owner
    asks, and nothing else happens until they have. Same discipline as P1–P2 and
    for the same reason: a message containing a situation and a hint and a model
    question is a message the owner reads instead of answering.

Q5. **The turn cycle is four steps, and the fourth is the point.**

    1. Claude gives the situation and what to ask for (`situation`, `ask_for`).
    2. The owner produces the question — in writing, in their own words.
    3. Claude answers **in role** as the person in the situation (`reply`).
    4. The owner asks a follow-up.

    Correction comes after step 4, not between the steps. Interrupting at step 2
    turns the scenario back into a drill item.

Q6. **Answer in role, and hold something back.** The `reply` in each scenario is
    deliberately incomplete, and `holds_back` says what it withholds. Deliver it
    flatly, the way a busy colleague would — do not helpfully volunteer the
    missing half.

    This is not a flourish. On a real team the first answer almost never settles
    it, and asking again is the skill that separates someone who gets unblocked
    from someone who waits. It is also what gives the follow-up something to be
    a follow-up to.

Q7. **Never produce the model question before they have produced theirs.** Not
    as an example, not as "something like…", not embedded in the situation. The
    scenario files carry no model question at all, precisely so that there is
    nothing to leak. If they are stuck, name what the question needs to
    establish — never how to phrase it.

Q8. **Corrections run in two stages: they repair it, then they produce it
    again.** These are the answering mode's P21 and P22, and they are the whole
    treatment — a correction they only read is recognition, and recognition is
    the half that already works.

    **Stage one — flag it, don't fix it.** Quote the fragment as they wrote it,
    name at most what *kind* of thing is wrong ("something about the recipient",
    "the ending on that verb"), and let them repair it:

    ```
    🔎 Something's off here:
    "<their fragment, quoted exactly>"
    (at most one hint at what kind of thing is wrong — never the corrected form)
    ```

    If the repair lands: `✅ That's it.` + `📌 Why:` (one short explanation).
    If it misses, don't hint twice — give the form:

    ```
    ❌ Original: ...
    ✅ Correct: ...
    📌 Why: (one short explanation)
    ```

    Correct directly, with no flag stage, when the error is a word or
    collocation they don't have, when it's a one-off outside every tracked
    pattern, or when they already missed a flag on that pattern this session.

    **Stage two — they build a new one.** Every correction ends with `🔁 Your
    turn:` and one instruction to produce the same frame with *different content
    words*. Never "repeat the correct version".

    **Three outcomes each, not two.** A repair that avoids the structure
    ("Do I have time to test it?" for a flagged `mind`-frame) is a **dodge**, not
    a success — name the avoidance and give the form. A re-production that comes
    back as *your* sentence is a **copy-back**: say so, then ask once more with
    the content pinned — a topic and two or three words your model answer doesn't
    contain. Both dodges look correct from the sentence alone and both mean the
    form isn't available for production yet. A copy-back never counts towards
    `--reproductions`.

    Two adjustments this mode needs:

    - **Correct after the follow-up, not after each question**, so one exchange
      produces one correction pass. Take the two costliest errors across both
      questions and let the rest go.
    - **The re-production is another question, in another situation.** "Now say
      it correctly" is recognition. Give a one-line variant of the same
      situation with different content and have them ask again.

Q9. **Register is a correction category here, not a nicety.** A question that is
    grammatically perfect and lands as an accusation has failed at exactly the
    thing this mode exists to train, and it gets flagged like any other error —
    quote it, name what it does to the listener, let them repair it.

    Judge it on what it costs the listener — the same scale the rest of the
    project rates severity on: 5, they take a different meaning or have to ask
    again; 4, they recover it with a visible beat of effort; 3, instant but the
    sentence's skeleton is wrong; 2, instant, only the trim is off; 1, nobody
    notices. An unhedged "Why did you do it like that?" to a senior colleague in
    a public review costs more than a missing article ever has.

    **Register is intent and directness only — never phrasing.** If a question
    lands badly because the grammar came out wrong, that is a `form` error and it
    is scored there; charging it to `register` as well counts one mistake twice
    and hides which half actually failed. "Don't you mind if I…" reads as a
    complaint, but what went wrong is the negative, not the stance.

    And judge it against the scenario's `register`, not against a general
    preference for politeness. The urgent scenarios are there because
    over-hedging during an incident is the mirror-image error, and softening
    frames are wrong in them.

Q10. **Score each scenario against its `criteria`, out loud, at the end of the
     exchange.** One line, each criterion met or not — `form ✅ function ✅
     register ❌ followup ✅`.

     They are scored rather than judged freely because a scenario's answer space
     is open: "Does that affect us?" and "Is our service affected?" are both
     right and no pattern covers both. A yes/no call against a written line is
     the closest this can get to a denominator, and the count of criteria
     offered is what makes 11 of 16 mean the same thing next month. A free
     impression does not survive a week.

     Don't rewrite a criterion mid-session to fit what they said. If one is
     genuinely wrong, note it and fix the YAML afterwards.

Q11. **The follow-up is scored, not a bonus round.** Every scenario has a
     `followup` criterion, and it is the one most likely to fail: accepting the
     first answer is the default behaviour, in English and in Russian both. If
     they take the incomplete reply and move on, that criterion is missed and
     says so.

Q12. **Four to six scenarios a session, mixed by register.** **The brief has
     already chosen them** — the rules below are what it applies, kept here
     because they are what the choice means:

     - Scenarios never run before come first, then the ones whose criteria failed
       last time. Both facts come from `analysis/asking_scenarios.csv`, which
       `practice end` writes; the markdown log in `asking_memory.md` is a
       rendering of it, not the record.
     - A scenario that ran clean in the previous session is ranked last rather
       than excluded, so a small pool still fills a session.
     - **Register is varied, not setting.** The selection takes one scenario per
       register before it takes a second from any of them: five peer-level work
       scenarios train less than one peer, one manager and one stranger — the
       grammar is the same in all five and the social calibration is what
       differs.

     Don't re-derive the selection by hand. If it looks wrong, that is a bug in
     `voxlib/asking.py`, not a step to redo.

     **The brief draws four; `--scenarios 6` is for a session with time in it.**
     Four to six is the range, and every session on record has run two — so the
     number to watch is the floor, not the ceiling. Three is the real minimum: it
     is the fewest that puts three registers in front of them, and a session of
     two is eight criteria, which is too thin to read anything out of.

     **Ending early is allowed and costs nothing.** A scenario that wasn't
     reached is simply never recorded, so it still counts as never run and comes
     first next session. Stop after a completed exchange — a scenario abandoned
     between the question and the follow-up scores nothing and teaches nothing.

     The `trap` line is for you, not to be read out. It says what to watch for;
     announcing it removes the error before it can be made. Same for `holds_back`
     and the criteria.

Q13. **Open with the warm-up block from Q2** — six interleaved prompts from
     `asking/drills`, before the first scenario. It is a warm-up that puts the
     question frames in front of them, not the session.

     **Hand all six over in one message and take the six answers back in one.**
     The block is written, with time to think, and scored against a key at the
     end either way — so asking it prompt by prompt measures exactly the same
     thing at six times the cost, in the part of the session with the least
     learning in it. Then correct the misses together: one Q8 flag on the
     costliest, a one-line correction on each of the rest, and one
     re-production. The scenarios are where this mode's discipline actually
     matters (Q4), and they keep it.

     Record the answers verbatim and first-attempt, in prompt order, before
     correcting anything:

     ```bash
     python -m voxlib.drill --drills-dir asking/drills \
       --pending analysis/asking_pending.json answer "a1" "a2" "a3" "a4" "a5" "a6"
     ```

     Verbatim and first-attempt — not the version produced after a correction.
     An empty string `""` is how a prompt they skipped is recorded, because the
     answers are paired with the prompts by position.

     Which pattern a prompt belongs to is withheld on purpose, and don't announce
     it either — naming it restores the priming the interleaving exists to
     remove. Correct from your own knowledge of English; the answer key is not
     printed.

     Expect scores below the 100% that blocked grammar drills produced. That
     ceiling is what mixed blocks exist to get past.

     **`asking/` is gitignored and starts empty**, so on a new machine there may
     be no drill and no scenario pack at all. Say so, run the session from
     scenarios you write into `asking/scenarios/` as you go — the format is in
     `asking/README.txt`, with a complete invented example in
     `tests/fixtures/asking/` — and skip the block rather than improvising prompts
     and scoring them by hand. An unscored improvised block is the written
     exercise this mode exists to replace.

Q14. **Close the session with one command, before finishing it.**

     ```bash
     python -m voxlib.practice end --date YYYY-MM-DD --mode ask \
       --focus "<the question pattern that failed most>" \
       --words <words they produced> --reproductions <Q8 count> --long-turns 0 \
       --scenario "standup-migration:4/4" \
       --scenario "estimate-pressure:2/4:form,followup" \
       --notes "5 scenarios, 17/20 criteria" \
       "Embedded Question Word Order:2" "Question Register And Softening Frames:1"
     ```

     It scores the block from the recorded answers, appends the practice row,
     moves the schedule on in `conversation_focus_log.md`, writes each scenario
     to `analysis/asking_scenarios.csv`, and adds this session's rows to both
     log tables in `asking_memory.md`. Its output is what Q10 and the end-of-
     session report are read from.

     - **`--mode ask` is not optional**, and it does two things. It keeps this
       session out of the answering-mode denominator — a dozen short questions
       and three long turns are not comparable word counts, and pooling them
       understates every typed rate. And it points every drill file at this
       mode's own: `asking/drills`, `asking_drills.csv`,
       `asking_drill_items.csv`, `asking_pending.json`. Without it a question
       block lands in the grammar drill trend the recording workflow reads.
     - **`--scenario "<name>:<met>/<total>:<failed,ids>"`**, one per scenario,
       using the criterion ids from Q10's score line. `/<total>` may be left off
       for a scenario in the pool — the YAML knows how many criteria it has, and
       a hand-typed denominator that disagrees with it is a number nobody can
       interpret later. A scenario with nothing failed takes no third field.
     - **`--long-turns 0`**, unless a scenario genuinely produced a long turn.
       Six-plus sentences of connected speech is a long turn; four questions is
       not.
     - `--dry-run` prints what it would write without writing it.

     Then update the prose in `asking_memory.md` by hand (Q16) — the two tables
     are already written.

Q15. **What this mode owns, and what it must never touch.** It owns
     `analysis/asking_memory.md`, `analysis/asking_archive.md`,
     `analysis/asking_scenarios.csv`, `analysis/asking_drills.csv`,
     `analysis/asking_drill_items.csv` and `analysis/asking_pending.json`, and
     it appends to `analysis/practice_history.csv` and
     `analysis/conversation_focus_log.md` through `practice end`.

     It never writes to `analysis/memory.md`, `analysis/mistakes.csv`,
     `analysis/scores_history.csv`, `analysis/drills.csv` or
     `analysis/drill_items.csv`. `memory.md`'s scores have to stay comparable
     across recordings, and a question pattern has no place in a file whose rows
     are supposed to be produced by the recording — a category there that the
     recording can never test would sit at "no opportunity" forever and quietly
     break the promotion logic in the analysis workflow.

Q16. **`analysis/asking_memory.md` is this mode's tracker**, the counterpart of
     `memory.md`. Its prose is written by hand at the end of each session; its
     two log tables are written by `practice end` (Q14). Create it from this
     structure if it doesn't exist:

     ```markdown
     # Question Practice Memory

     Last updated:
     Sessions:

     ## Patterns

     ### <Pattern Name — the same string used as a drill `category`>
     Status: Active / Improving
     Sessions with an error:
     Last error:
     Typical examples:
     - "<exact quote>" -> "<corrected version>" (<date>)
     Notes:

     ## Register notes

     What lands badly, and in which register. Prose, not a table.

     ## Scenario log

     | Date | Scenario | Criteria met | Failed |
     |---|---|---|---|

     ## Session history

     | Date | Scenarios | Criteria met | Drill score | Biggest problem |
     |---|---|---|---|---|
     ```

     Those headings are load-bearing: the brief parses `## Patterns` (`Status:`,
     `Sessions with an error:`, `Last error:` and the first of `Notes:`) and the
     bolded lead of each `## Register notes` paragraph, and `practice end`
     appends to the two tables by name. Keep the shape; the words inside it are
     yours.

     **Keep the file bounded — this one is read at the start of every session.**

     - Cap `Typical examples` at 3 per pattern, replacing the oldest.
     - Cap `## Register notes` at roughly one paragraph per register, each led by
       a bolded verdict (`**Stranger, in writing — the worst result so far.**`).
       That lead is what the brief digests; a paragraph without one is prose
       nobody reads at speed. Rewrite a register's paragraph rather than adding
       a second one for it.
     - **A section about the instrument rather than about the English goes to
       `analysis/asking_archive.md`** as soon as the decision it records has been
       carried out — in the rules, in the scenario YAML, or in the code. Those
       sections are how the rubric and the drills got fixed and they are worth
       keeping; they are not worth re-reading before every session, and they were
       over half the file by the third one.
     - The scenario log keeps every row: it is short, and it is what the
       selection reads back through `asking_scenarios.csv`.

## Goal

The owner leaves able to ask for what they need at work in English without
rehearsing it first — the right question, formed correctly, aimed at the person
who can answer it, and asked again when the first answer doesn't settle it.
