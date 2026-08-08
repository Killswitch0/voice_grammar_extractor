# Voice Grammar Extractor

Console app: extracts only **your** lines from a video/audio file (mp4, webm,
mkv, mp3, wav, etc.) — separating them from other voices — and saves them to a
text document in chronological order. The result is ready to feed to any AI
so it can analyze your grammar and find recurring mistakes.

The app **never sends anything to any AI itself** — it only prepares
`transcript_clean.txt`, which you paste into a chat with an AI yourself.

**Beyond a one-off review:** this project also ships a Claude Code workflow
(`CLAUDE.md`) that turns repeated recordings into an actual coaching loop —
tracking which mistakes keep recurring, which have improved, and which came
back, in a persistent `analysis/memory.md`. See `HOW_IT_WORKS.md` for the
full picture, or jump to ["Tracking progress over
time"](#tracking-progress-over-time-with-claude-code) below.

## Quickstart (Docker, one command)

The fastest way to get going — no Python setup, no dependency wrangling:

1. Install Docker (Docker Desktop on Mac/Windows, or Docker Engine on Linux —
   `docker compose` is included in all of these since 2021).

   **Before your first build:** this project's dependencies (torch, pyannote,
   whisper) take several GB. If you're on Docker Desktop, go to Settings →
   Resources → Advanced and make sure "Disk image size" has at least
   ~20GB of headroom *before* building — a full disk mid-build causes
   `Input/output error` failures that look like a network problem but aren't.
2. Download this project folder and put your recording(s) inside it (e.g. in
   a `recordings/` subfolder you create).
3. **Only if your recordings have other voices besides yours**, you need a
   free HuggingFace token for the diarization models:
   - Sign up at https://huggingface.co
   - Create a token: https://huggingface.co/settings/tokens ("Read" access is enough)
   - Accept the usage terms on the model pages (takes a minute, just an "Agree" button; for "Company/university" you can put "Personal" or leave it blank):
     - https://huggingface.co/pyannote/speaker-diarization-community-1
     - https://huggingface.co/pyannote/embedding
   - Run `cp .env.example .env` and paste your token into `.env`

   Skip this entirely if you only ever use `--no-diarization`.
4. Run it:

   **macOS/Linux:**
   ```bash
   ./run.sh recordings/call.webm --reference voice_reference/my_reference.wav
   ```
   **Windows (PowerShell):**
   ```powershell
   .\run.ps1 recordings\call.webm --reference voice_reference\my_reference.wav
   ```

That's it — one command. The image builds itself the first time (a few
minutes), every run after that starts instantly. Results land in `./output/`
right inside this same folder.

Solo recording, no other voices? Even simpler:
```bash
./run.sh recordings/monologue.mp4 --no-diarization
```

Don't know which voice in the recording is yours? Use the picker helper first:
```bash
./identify.sh recordings/call.webm        # macOS/Linux
.\identify.ps1 recordings\call.webm       # Windows
```

Any flag from the "Useful flags" table below works the same way, just
appended after the file: `./run.sh recordings/call.webm --reference ... --whisper-model medium --dry-run`.

## Installation

1. Python 3.10+ and ffmpeg must be installed:
   ```bash
   # Ubuntu/Debian
   sudo apt install ffmpeg
   # macOS
   brew install ffmpeg
   ```

2. Dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. **Only if your recordings contain other voices** (dialogues, calls) —
   you need a free HuggingFace token for the diarization models. See
   [Quickstart step 3](#quickstart-docker-one-command) above for how to get
   one, then set it as an environment variable (or pass it with `--hf-token`):
   ```bash
   export HF_TOKEN=hf_yourtoken
   ```

## Usage

### If the recording has other voices (call, interview, dialogue)

You'll need a reference sample of your voice — a short, clean clip (10–30
sec) where only you are talking. Two ways to get it:

**Option A — interactive helper** (no manual ffmpeg cutting needed):
```bash
python identify_speaker.py call.webm --hf-token hf_xxx -o output/
```
The script diarizes the file itself, lets you listen to a short sample of
each voice found, and asks which one is yours. Saves the chosen one as
`voice_reference/my_reference.wav`.

**Option B — manual**, if you already know the timestamp you want:
```bash
ffmpeg -i any_recording.mp4 -ss 00:00:05 -t 20 -vn my_voice.wav
```

Run on a single file:
```bash
python main.py call.webm --reference voice_reference/my_reference.wav -o output/
```

Run on a whole folder of recordings (all your lines get merged into one document):
```bash
python main.py recordings_folder/ --reference voice_reference/my_reference.wav -o output/
```

### Check the result first (without the slow transcription)

**Make this your default habit whenever a recording has other voices** —
don't only reach for it when something looks wrong. `--threshold` that
worked for one call may not work for the next one (different mic, different
background noise, different other speaker), so re-checking costs nothing
and can save a long wasted transcription run:
```bash
python main.py call.webm --reference voice_reference/my_reference.wav --dry-run
```
Shows the number of speakers found, how many segments were identified as
yours, and what share of the total speech in the file that is — without
running whisper at all. If the numbers don't match your expectations, adjust
`--threshold` and try again. Only move on to a full run once the split looks right.

**The number to check first is the one in brackets under `Speakers (you)`** —
that's how many speakers were matched as you, and it should always be exactly
`1`:

```
┃ File                   ┃ Speakers (you) ┃ Your lines ┃ Your speech ┃ Share ┃
│ part_01.webm           │          2 (1) │     78/140 │   ~18.4 min │   61% │
│ interview [draft].webm │          3 (2) │    190/210 │   ~40.0 min │   92% │
```

The second row is wrong: two of the three speakers were matched as you, so
another person's sentences would end up in your transcript. `0` is the other
failure — you'd get an empty document. Anything other than `1` is printed in
red with an explanation; raise or lower `--threshold` and re-check.

### If the recording is just you (solo, monologue, journal)

No diarization needed — the whole file is treated as your speech:
```bash
python main.py monologue.mp4 --no-diarization -o output/
```

### Useful flags

| Flag | Purpose |
|---|---|
| `--language en` | Speech language for recognition (default `en`). `--language auto` — detect it once per file (for mixed-language speech) |
| `--whisper-model medium` | Recognition quality: `tiny` < `base` < `small` < `medium` < `large-v3`. Bigger = more accurate but slower |
| `--threshold 0.8` | Voice similarity threshold. If omitted, it's auto-calibrated per recording; pass it explicitly to override — raise it if the system confuses you with others, lower it if it misses your lines |
| `--device cuda` | Use GPU, if available |
| `-v` | Verbose logging |
| `--config path.yaml` | Take settings from a YAML file instead of a long list of flags (see `config.example.yaml`) |
| `--no-cache` | Recompute everything from scratch, ignoring saved progress |
| `--split-chars 15000` | Additionally split `transcript_clean.txt` into parts of the given size in `output/parts/` |
| `--low-confidence-threshold -0.5` | Whisper confidence threshold below which a line is marked `[?]` in the annotated document |
| `--dry-run` | Only diarization + identification, no transcription — quickly check the voice separation |
| `--remove-fillers` | Remove pure filler sounds (um, uh, erm) from the transcript |
| `--batch-size 8` | Enable batched transcription — speeds up long lines, especially on GPU |
| `--log-file run.log` | Also write the run log to a file (useful for long unattended runs) |

## Output

Three files will appear in the output folder:

- **`transcript_annotated.txt`** — with timestamps and the source file name, for your review:
  ```
  === call.webm ===
  [00:00:12] So I think we should probably to consider this option.
  [00:01:03] [?] This is a mumbled sentence
  ```
  The `[?]` marker means a low-confidence line (unclear diction/noise);
  double-check it against the original before trusting its grammar.

- **`transcript_clean.txt`** — just the lines, one per line, nothing else.
  This is the file you paste into an AI with a prompt like:
  > "Here's a list of my spoken lines in English. Analyze the grammar, find
  > the most frequently repeated mistakes, and group them by type."

- **`fluency.json`** — the run's fluency measurement: hesitation fillers per
  100 words, speaking rate, and (solo recordings only) pause statistics.
  Measured by the pipeline rather than eyeballed off the transcript later, so
  the value is reproducible and therefore actually comparable between
  recordings. See "Fluency measurement" below.

When it's done, a short stats summary is also printed to the console — number
of lines, total duration of your speech, an approximate word count, and the
fluency line — so you get a sense of the material's volume without opening the
document.

If a run extracts no lines at all, it fails with an explanation instead of
writing two empty files over the previous run's output — an empty transcript is
indistinguishable from "you said nothing" once it's been archived.

## Fluency measurement

Alongside the transcripts, every run measures:

| Metric | Meaning |
|---|---|
| `low_confidence_share` | Fraction of lines whisper wasn't sure about (the `[?]` ones) |
| `fillers_per_100_words` | Hesitation sounds (`um`, `uh`, `erm`) per 100 reliable words |
| `words_per_minute` | Speaking rate across your own reliable speech |
| `median_pause_sec`, `long_pauses` | Gaps between your consecutive lines — **solo recordings only** |

Three deliberate choices worth knowing about:

- **Only lines whisper was confident about are counted.** A mis-recognized
  line says nothing about how you actually spoke, so `[?]` lines are excluded
  — the same rule the analysis workflow applies to grammar. This matters more
  than it sounds: in this project's own history, one session had 60% of its
  lines marked `[?]`, and 17 of its 20 "fillers" were inside them. Counted
  over reliable lines, its apparent 10x jump in hesitation disappears.
  `low_confidence_share` is reported alongside for exactly that reason, and
  the run prints a warning when it goes above 40% — at that point the number
  is describing your microphone, not your English.
- **`uh-huh` and `mm-hmm` are not counted as hesitation.** They're backchannel
  agreement — the spoken equivalent of a nod — so counting them would say
  something about how much you were listening, not how much you hesitated.
  (`--remove-fillers` leaves them intact for the same reason.)
- **Pause statistics are only reported for solo recordings.** In a recording
  with other voices, the gap between two of your lines is mostly the other
  person talking, so the number would mean something different from file to
  file. It comes back blank rather than misleading. (Unlike the word metrics,
  these do use every line — a timestamp is valid even when the words on it
  weren't recognized.)

The filler rate is a **lower bound**: whisper discards many real hesitations
before they reach the transcript, so treat it as "at least this much".

An empty cell always means "not measured", never zero.

If an `analysis/` folder exists next to `main.py` (it's this project's coaching
workspace — see "Tracking progress over time" below), each run also appends its
measurement to `analysis/fluency_history.csv`, append-only, so the trend
accumulates on its own without anyone maintaining it by hand.

## Tracking progress over time with Claude Code

Pasting `transcript_clean.txt` into an AI once gives you a one-off review.
`CLAUDE.md` sets up a full personal-coach workflow instead: open this
project folder in Claude Code and ask it to "analyze the new recording." It
will archive the session's transcript under `analysis/sessions/`, produce a
coaching report (CEFR estimate, ranked mistakes, natural-English rewrites,
vocabulary suggestions, targeted exercises), and update `analysis/memory.md`
— the running record of which mistakes are still recurring, which have
improved, and what to focus on next.

A `[?]` marker in `transcript_annotated.txt` (see "Output" above) means
low-confidence recognition — the coaching workflow is instructed to exclude
those lines from grammar judgment rather than guess whether a "mistake" is
real or just Whisper mishearing you. See `CLAUDE.md` for the full workflow
and the exact `memory.md` format.

`analysis/` is excluded from this project's own repo (see `.gitignore`) —
it's your personal data, not something to publish alongside the code. That
also means it isn't backed up anywhere by default; see
[`analysis/BACKUP.md`](analysis/BACKUP.md) for a 10-minute setup that gives
it its own private repo and a one-command backup.

## Installing as a console command

If you don't want to type `python main.py` every time:

```bash
pip install -e .
```

After that, these commands are available from any folder:
```bash
voice-extractor recordings_folder/ --reference voice_reference/my_reference.wav
identify-speaker call.webm --hf-token hf_xxx -o output/
```

## Filler filter and batched transcription

`--remove-fillers` removes pure filler sounds (`um`, `uh`, `erm`) from the text.
It deliberately does **not** touch meaningful filler words like "like", "you
know", "I mean" — a regex can't reliably tell those apart from a fully
meaningful use of the same word (e.g. "I **like** it" is not a filler), and
for grammar analysis, the risk of accidentally breaking a real sentence is
worse than leaving a few extra fillers in place.

It also leaves `uh-huh` and `mm-hmm` alone: those are agreement, not
hesitation, and stripping the `uh` out of `uh-huh` would leave `-huh` behind —
a broken line invented by the tool in a document meant for grammar review.

Note that using it makes the filler metric unmeasurable for that run (the
sounds are gone before they can be counted) — the filler columns come back
blank, and `words_per_minute` is unaffected.

`--batch-size 8` enables faster-whisper's `BatchedInferencePipeline` — gives a
noticeable speedup on long lines, especially on GPU. Off by default (regular
sequential mode), since some versions of faster-whisper had bugs with internal
timestamps during batching — not critical for this tool (only text and
recognition confidence are used), but enabling it remains your deliberate choice.

## Crash resilience (progress cache)

Diarization and transcription are the longest steps. Progress for each file
is saved to `output/.cache/` as soon as it's ready (after diarization, after
identification, and after each transcribed line). If the script crashes or
you interrupt it mid-way — re-running on the same files won't recompute
steps that are already done, it will pick up where it left off. If a file has
changed since then, its cache is automatically reset.

To recompute from scratch anyway, use `--no-cache`.

## Config file instead of a long command

If you use the tool regularly with the same settings, it's more convenient to
keep them in a YAML file:

```bash
cp config.example.yaml my_config.yaml
# edit my_config.yaml to your liking
python main.py recordings_folder/ --config my_config.yaml
```

Any command-line flag passed explicitly overrides the corresponding value
from the config.

## Splitting into parts for AI

If you've been accumulating recordings for a while and `transcript_clean.txt`
becomes too big for a single AI prompt, add `--split-chars 15000` — you'll get
`output/parts/part_1.txt`, `part_2.txt`, etc., each part no longer than the
given number of characters (lines are never split in the middle).

## Docker

The [Quickstart](#quickstart-docker-one-command) section above (`run.sh` /
`run.ps1`, powered by `docker-compose.yml`) is the recommended way to run
this in Docker. If you'd rather not use Compose and prefer plain `docker`
commands:

```bash
docker build -t voice-grammar-extractor .

# Solo recording (no other voices) — no HuggingFace token needed:
docker run --rm \
  -v "$(pwd):/workspace" -w /workspace \
  -v "hf_cache:/root/.cache/huggingface" \
  voice-grammar-extractor \
  recordings/monologue.mp4 --no-diarization -o output

# Recording with other voices — needs a HuggingFace token (see Quickstart step 3 above for how to get one):
docker run --rm \
  -v "$(pwd):/workspace" -w /workspace \
  -v "hf_cache:/root/.cache/huggingface" \
  -e HF_TOKEN=hf_yourtoken \
  voice-grammar-extractor \
  recordings/call.webm --reference voice_reference/my_reference.wav -o output
```

The named volume `hf_cache` caches downloaded models (whisper, and pyannote
if you use diarization) so they aren't re-downloaded every time the container
is recreated. `HF_TOKEN` itself is only required for the diarization case.

A note on `identify_speaker.py` / `./identify.sh` in Docker: diarization and
sample-cutting work fine inside the container, but actual audio *playback*
usually won't — containers don't have access to your machine's audio device
by default. If playback fails, the cut samples are still right there on your
host machine at `output/speaker_samples/SPEAKER_XX.wav` (thanks to the volume
mount) — just open them with your own media player, then answer the "which
number is you" prompt in the terminal as usual.

On native Linux (not Docker Desktop), files written by the container under
`./output/` will be owned by `root`. If that's inconvenient, fix it with
`sudo chown -R $USER:$USER output/` afterward.

## Running tests

Unit tests cover the parts of the pipeline that don't need torch/pyannote/
whisper (caching, config loading, filler removal, document formatting) —
they run in under a second, with no GPU or HuggingFace token required:

```bash
pip install -e ".[dev]"
pytest
```

## If pip complains about version conflicts

The torch/torchaudio/pyannote ecosystem changes fast, and `pip` sometimes
installs an incompatible combination of versions (e.g. torchaudio newer than
what the installed pyannote.audio supports — you'd then see an error like
`module 'torchaudio' has no attribute 'AudioMetaData'` at runtime). If that happens:

```bash
pip install --upgrade "pyannote.audio>=4.0.0" --break-system-packages
```

The code is designed for the current pyannote.audio 4.x branch.

## Known limitations

- Simultaneous speech from multiple people (interruptions) is recognized
  worse — diarization in its default configuration isn't built for full
  speech overlap.
- The accuracy of identifying "your" voice depends on the quality of the
  reference sample: use a clean clip without music or background noise.
- Nothing forces exactly one speaker to be recognized as you — each speaker is
  compared against the reference independently, so two similar voices can both
  clear the threshold. This is now reported rather than silent (a warning in
  the log, and the `Speakers (you)` column in `--dry-run`), but you still have
  to act on it by adjusting `--threshold`.
- Without an explicit `--threshold`, the value is auto-calibrated **per file**,
  so a batch of recordings can be split at different points. Pass
  `--threshold` explicitly when you want a batch to be directly comparable;
  the run warns when the auto-picked values differed.
- The filler rate is a lower bound — whisper drops many hesitations before
  they reach the transcript. Useful as a trend, not as an absolute figure.
- Models (whisper, pyannote) are downloaded on first run — you need internet
  for that; after that, they work offline.
- In `--no-diarization` mode (solo recording), the progress cache can't skip
  the actual whisper pass over the whole file when resuming after a crash —
  it's structured as one continuous pass that can't be interrupted and
  resumed mid-way. The cache there only guarantees that already-done lines
  won't be duplicated in the final document, not that time is saved on
  re-run. In diarization mode (multiple voices), the cache works truly
  per-line — each line is transcribed independently.
