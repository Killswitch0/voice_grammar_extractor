Question Practice Mode — the content it runs on.

Everything else in this project measures statements. The recording is a
monologue, so it produces none; in Conversation Practice Mode the questions are
Claude's and the answers are yours. Not one question you produced had ever been
measured — not because it didn't matter, but because none of the instruments
could generate the data.

This directory is the other half. Say "let's practice asking" and it runs.

Yours, not the repository's — gitignored the same way drills/ and analysis/ are.
The `trap` lines are reconstructions of the errors *you* make, and the scenarios
worth adding are the situations that actually happened to *you*, so this fills up
with your own material even where it starts out generic. This README is the only
committed file here; an invented example of both formats lives in
tests/fixtures/asking/ if you want to see complete ones.

  drills/      three drills in the ordinary drills/ format, run by
               `python -m voxlib.drill --drills-dir asking/drills`. They live
               here rather than in drills/ so that a grammar practice session
               never draws a question prompt into its mixed block by accident —
               `load_all` does not recurse, which is what keeps the two pools
               apart.

                 do-support-wh           the auxiliary, and the questions that
                                         take none (subject questions, "be",
                                         modals)
                 embedded-questions      statement order inside "do you know
                                         where..." — and the contrast, that a
                                         direct question still inverts
                 polite-question-forms   softening frames and the grammar each
                                         one governs — plus urgent items where
                                         hedging is the error

  scenarios/   the half a drill cannot do. One file per pack; each scenario is
               a situation you have to ask your way out of.

A scenario:

    - name: standup-migration
      function: verify-assumption      # the speech act being trained
      register: peer                   # peer | manager | skip-level | customer
                                       #  | stranger | service-desk | social
      situation: |
        <the setup — enough that the question has to be specific>
      ask_for: one question to Ravi    # or: two questions, three short ones
      reply: |
        <what the other person says back, in role>
      holds_back: |
        <what the reply deliberately leaves out, so a follow-up is necessary>
      criteria:
        - id: form
          check: <one thing, answerable yes or no>
        - id: function
          check: ...
        - id: register
          check: ...
        - id: followup
          check: ...
      trap: |
        <the mistake this scenario exists to catch>

Two things in there carry most of the weight.

`reply` and `holds_back`: a scenario that ends after one question is a
fill-in-the-blank exercise with a story attached. The reply is answered in role
and is deliberately incomplete, because on a real team the first answer almost
never is, and asking again is the actual skill.

`criteria`: a scenario's answer space is open — "Does that affect us?" and "Is
our service affected?" are both right and no regex covers both — so scenarios
are scored against these instead. Each is a yes/no judgement against a written
line rather than a general impression, and the count of them is the
denominator: 11 of 16 criteria met is a number that means the same thing next
month.

Keep each pack's criteria to three or four. A rubric long enough to be thorough
is one nobody applies the same way twice.

Two of the four ids are fixed and should not be reworded per scenario:

  form      one string, identical everywhere. Written per scenario it becomes a
            prediction of the error you expect, and then it scores nothing when
            a different one arrives — which is exactly what happened the first
            time a scenario failed. Specific patterns belong in the drills,
            which test one thing against an answer key.
  register  intent and directness only, never phrasing. A question that lands
            badly because the grammar came out wrong is a `form` error; charging
            it to `register` too counts one mistake twice and hides which half
            failed.

`function` and `followup` are where the per-scenario judgement lives, and they
are the two worth spending thought on.

Writing more: add scenarios from situations that actually happened to you and
went badly, which is the same principle drills/ is built on. The register
matters more than the setting — five peer-level work scenarios train less than
one peer, one manager and one stranger.
