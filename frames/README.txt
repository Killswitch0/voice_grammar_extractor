Frames — what a chance to make each mistake looks like.

Everything else this project measures is a numerator. "Six article mistakes per
thousand words" cannot say out of how many chances, because nothing counted how
many singular countable nouns you actually said. Words spoken stood in for
chances, and `python -m voxlib.exposure` shows that on this record the
substitution does not hold: counts track how many categories were being looked
for better than they track anything you did.

A frame is the missing denominator. It is a regex that matches a line where the
structure came up at all — whether or not it went wrong.

    frames:
      - category: <the "## <Mistake Name>" heading in analysis/memory.md>
        note: <one or two sentences: which approximation this trigger makes>
        trigger: <regex matching a line that gave you a chance to get it wrong>

Read them with:

    python -m voxlib.opportunity              # chances, errors, accuracy
    python -m voxlib.opportunity --write      # also writes opportunity_history.csv
    python -m voxlib.exposure                 # which denominator each category earns

Four rules, each of which this directory got wrong at least once:

  - **Trigger the structure, never the error.** A trigger that looks for the
    mistake scores every chance as a failure. "because of" is the frame; "because
    of + clause" is the error, and `mistakes.csv` already counts those.

  - **Include the cases you get right.** The quantifier frame counts "much" and
    "a lot of" as well as "many", because the mistake is the *choice*. One
    session ran "many" sixteen times against "much" twice; a trigger on the
    wrong half alone would have found chances only in the sessions already lost.

  - **Narrow beats broad, and it is measurable.** The preposition frame lists
    exactly the verbs this category has gone wrong on. Widening it to common
    motion and speech verbs took it from +0.48 against the recorded errors to
    +0.10 — the extra chances were ones the mistake was never available in, and
    they diluted the denominator until it stopped predicting anything.

  - **Write the trigger from the grammar, then test it. Not the other way
    round.** `exposure` scores your frame against the word denominator and a
    frame is only adopted if it wins. That gate is a sanity check on a
    twelve-session history, not a search objective: trying twenty variants until
    one passes is fitting the regex to this particular record, and it will not
    survive the next ten sessions. If you cannot say in the `note` why the frame
    is the right linguistic description of the opportunity, it is not one.

Triggers compile with `re.IGNORECASE | re.VERBOSE`. VERBOSE is what lets a long
alternation be written across several lines and stay reviewable; the cost is
that unescaped whitespace is ignored, so a literal space must be written `\s`
(`a\s+lot\s+of`, not `a lot of`). A `#` would start a comment — don't use one
inside a trigger.

One chance per line, not per match. A line containing the frame twice is still
one moment of speaking, and inflating the denominator is the direction that
flatters.

Not every category can have a frame. "Redundant Subject Pronoun" and
"Noun-as-Adjective Word Form" need a parser to spot the opportunity, and nothing
here has one — they keep the per-1,000-words rate and the page says so. A
category with no frame, and a frame that fails the gate, behave identically:
this directory can only add information, never remove any.

This directory is personal data, like `drills/` and `analysis/`, and is
gitignored: the frames are built from the mistakes *you* make, so there is
nothing generic to ship. An invented, impersonal example lives in
tests/fixtures/frames/.
