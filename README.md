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

### If the recording is just you (solo, monologue, journal)

No diarization needed — the whole file is treated as your speech:
```bash
python main.py monologue.mp4 --no-diarization -o output/
```

### Useful flags

| Flag | Purpose |
|---|---|
| `--language en` | Speech language for recognition (default `en`). `--language auto` — auto-detect (for mixed-language speech) |
| `--whisper-model medium` | Recognition quality: `tiny` < `base` < `small` < `medium` < `large-v3`. Bigger = more accurate but slower |
| `--threshold 0.8` | Voice similarity threshold. Raise it if the system confuses you with others; lower it if it misses your lines |
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

Two files will appear in the output folder:

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

When it's done, a short stats summary is also printed to the console — number
of lines, total duration of your speech, and an approximate word count — so
you get a sense of the material's volume without opening the document.

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
- Models (whisper, pyannote) are downloaded on first run — you need internet
  for that; after that, they work offline.
- In `--no-diarization` mode (solo recording), the progress cache can't skip
  the actual whisper pass over the whole file when resuming after a crash —
  it's structured as one continuous pass that can't be interrupted and
  resumed mid-way. The cache there only guarantees that already-done lines
  won't be duplicated in the final document, not that time is saved on
  re-run. In diarization mode (multiple voices), the cache works truly
  per-line — each line is transcribed independently.
