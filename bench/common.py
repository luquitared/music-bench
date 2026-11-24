"""Shared paths and the prompt every model gets."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYNTH = ROOT / "data" / "synthetic"      # committed: <id>.mp3 + <id>.json (exact truth)
REAL = ROOT / "data" / "real"            # built locally: truth by bench.truth, audio by bench.audio
CACHE = ROOT / ".cache"                  # downloaded annotations, soundfont
RESULTS = ROOT / "results"               # results/<model-slug>/{synthetic,real}/<song>.r<k>.json + meta.json
RUNS_PER_SONG = 2

PROMPT = """You are an expert music transcriptionist. Listen to this audio carefully and produce a precise
metadata timeline. Return ONLY JSON with this shape:
{
 "bpm": number,
 "time_signature": "4/4",
 "keys": [{"start": sec, "end": sec, "key": "<Tonic> major|minor"}],   // list multiple if the key changes
 "chords": [{"start": sec, "end": sec, "chord": "<Root>:<qual>"}],      // qual e.g. maj,min,7,maj7,min7,dim,aug,sus2,sus4,6,min6,9 (optionally /bass); "N" for no chord; every chord change, full song
 "instruments": [{"name": str, "start": sec, "end": sec}],              // each distinct instrument and when it plays
 "lyrics": [{"start": sec, "end": sec, "text": str}]                    // every sung/spoken line verbatim, [] if instrumental
}
Use sharps or flats as you hear them. Timestamps in seconds from the start of the file."""
