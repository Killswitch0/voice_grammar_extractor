Spoken drills — yours, not the repository's.

A drill is built from the mistakes you actually make, so the prompts in here are
reconstructions of your own sentences. That makes this directory personal data,
the same as recordings/ and analysis/: it is gitignored, and a *.yaml you add
stays on your machine.

Each file is one drill:

    name: <matches the filename, without .yaml — this is how it's invoked>
    category: <the "## <Mistake Name>" heading in analysis/memory.md it trains>
    target: <one line: which structure this makes automatic>
    instructions: |
      <context for whoever asks the prompts; keep it short>
    items:
      - prompt: he / fanatic          # content words only — you supply the grammar
        example: He's a fanatic.      # the model answer
        wrong: He's fanatic.          # the mistake this item exists to catch
        attempted: <regex matching the structure however it came out>
        correct: <regex matching only the right form>

Drills are asked inside Conversation Practice Mode — say "let's practice" — one
prompt at a time, and scored at the end. Nothing is recorded or transcribed.

The two regexes are matched against lowercased, punctuation-free text, so write
them in lower case. `attempted` must match BOTH the example and the
counter-example — it answers "was this structure tried at all", and an item it
misses is reported as "not heard" rather than as a mistake. `correct` must match
the example and reject the counter-example.

Two rules worth following, both learned the hard way:

  - Include contrast items, where the target structure must NOT be used. A drill
    that only ever adds an article, a preposition or an "-s" teaches "always add
    it", which is the mirror-image error.
  - Keep the pool several times the size of one session's block (about five
    items). A pool barely larger than a session stops testing the pattern and
    starts testing the list.

Ask Claude to write one: the session-report workflow (CLAUDE.md step 5) creates
a drill whenever the current primary target has none.

An invented, impersonal example lives in tests/fixtures/drills/ if you want to
see a complete file.
