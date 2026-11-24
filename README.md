# Music Bench

**Can an audio model hear music?** Give it a song, ask for a full metadata timeline (tempo, key, every
chord change, the instruments and when they play, the lyrics with timestamps) and score the answer
against ground truth.

Results and write-up: **https://musicbench.odapt.ai** · Leaderboard: [LEADERBOARD.md](LEADERBOARD.md)

## What's in the test

| Set | Songs | Ground truth | Measures |
|---|---|---|---|
| Generated | 7 songs rendered from MIDI (committed in `data/synthetic/`) | Exact: we wrote the MIDI | chords, key and key changes, tempo, instruments and entry times, spoken lyrics |
| Beatles | 4 songs | Human chord and key labels ([Isophonics](http://isophonics.net/datasets)) | chords, key, tempo |
| Obscure | 6 songs by Zweieck, a German band few models will have read about | Isophonics | chords, key changes, tempo |
| Pitch-shifted | 2 Beatles songs moved to a new key | Isophonics, transposed | whether the model listens or recites a song it knows |
| Lyrics | 8 obscure Creative Commons songs | Human line timings ([JamendoLyrics](https://github.com/f90/jamendolyrics)) | word error, line timing |

Every song is asked twice with the same prompt (`bench/common.py`). Chords and keys are scored with
[mir_eval](https://github.com/craffel/mir_eval) (major/minor chord accuracy over time, MIREX weighted key
score); lyrics with [jiwer](https://github.com/jitsi/jiwer). An answer the model refuses or that isn't
valid JSON scores zero for that song.

## Run it on your model

Needs [uv](https://docs.astral.sh/uv/) and ffmpeg.

```bash
git clone https://github.com/luquitared/music-bench && cd music-bench
uv sync

# 1. Fetch the real set: annotations, then audio (YouTube via yt-dlp, JamendoLyrics mp3s).
uv run python -m bench.real

# 2. Ask your model. Two providers are built in:
export GEMINI_API_KEY=...
uv run python -m bench.run --provider gemini --model gemini-4-neon

export OPENAI_API_KEY=...   # any OpenAI-compatible endpoint that takes input_audio
uv run python -m bench.run --provider openai --model openai/gpt-audio --base-url https://openrouter.ai/api/v1 --key-env OPENROUTER_API_KEY

# 3. Score everything in results/ and rebuild the leaderboard.
uv run python -m bench.leaderboard
```

The model has to accept audio as input; the whole song is sent as one mp3. Another API is one function
in `bench/run.py` (`PROVIDERS`). A run is about 40 requests; answers that already exist are skipped, so
an interrupted run picks up where it stopped.

The generated songs are committed. `uv run python -m bench.gen` rebuilds them (needs fluidsynth and
macOS `say`), but the leaderboard always uses the committed audio.

## Submit to the leaderboard

Open a pull request that adds `results/<your-model>/`:

- `meta.json` (written by `bench.run`): model, provider, date, runs. Add `submitted_by` and any settings
  worth knowing in `notes` (thinking level, temperature). Use the prompt as it is, with no system prompt.
- the raw answers, `synthetic/*.json` and `real/*.json`, two runs per song, unedited.
- the regenerated `results/leaderboard.json` and `LEADERBOARD.md`.

CI rescores every model from the raw answers and fails if a submission is incomplete or the leaderboard
files don't match. Please don't hand-edit answers; if a model needed a different prompt to work at all,
say so in `notes` and in the PR.

## Caveats

- 20 real songs is small. Treat differences under about 5 points as noise.
- YouTube uploads can change or disappear; `bench.real audio` checks each file's length against its
  annotation and warns when they differ.
- One Isophonics label is corrected (Here Comes the Sun is listed as A minor; it's A major).
- Instruments are only scored on the generated set; none of the real datasets label them.

## Data and licenses

Code and the generated songs: MIT. Not included in the repo, and fetched from their sources when you
run `bench.real`: the Isophonics annotations, the JamendoLyrics annotations (MIT) and songs (Creative
Commons, per song; see their `JamendoLyrics.csv`), and the commercial recordings, which you download
yourself for research use. The generated songs were rendered with the
[GeneralUser GS](https://github.com/mrbumpy409/GeneralUser-GS) SoundFont.
