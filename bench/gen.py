"""Generate synthetic songs with exact ground truth (key, tempo, chords, instruments, lyrics).

MIDI -> fluidsynth (GeneralUser GS) -> wav; optional spoken lyrics via macOS `say` mixed in at known times.
Writes data/synthetic/<id>.mp3 + <id>.json. Needs fluidsynth, ffmpeg and macOS `say` (for the lyrics).
The committed audio is what the leaderboard uses; regenerate only to change the set.
    uv run python -m bench.gen
"""
import json, os, subprocess, tempfile, urllib.request
import mido
from .common import SYNTH, CACHE

SF_URL = "https://github.com/mrbumpy409/GeneralUser-GS/raw/main/GeneralUser-GS.sf2"
SF = str(CACHE / "GeneralUser-GS.sf2")
OUT = str(SYNTH)
NOTE = {"C": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "F": 5, "F#": 6, "Gb": 6,
        "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11}
QUAL = {"maj": [0, 4, 7], "min": [0, 3, 7], "7": [0, 4, 7, 10], "maj7": [0, 4, 7, 11],
        "min7": [0, 3, 7, 10], "dim": [0, 3, 6], "sus4": [0, 5, 7]}
GM = {"piano": 0, "electric piano": 4, "organ": 16, "nylon guitar": 24, "steel guitar": 25,
      "distorted guitar": 30, "acoustic bass": 32, "electric bass": 33, "synth bass": 38,
      "strings": 48, "cello": 42, "trumpet": 56, "flute": 73, "synth pad": 89, "saxophone": 65}

# Each song: sections of (key, chords per bar, bars) ; chord = "Root:qual" lasting `beats` beats
SONGS = [
    dict(id="s1_pop_C", bpm=100, key="C major",
         prog=["C:maj", "G:maj", "A:min", "F:maj"] * 4, beats_per_chord=4,
         parts=[("piano", 0), ("electric bass", 0), ("drums", 4)],
         melody=None, lyrics=None),
    dict(id="s2_minor_Fsharp", bpm=132, key="F# minor",
         prog=["F#:min", "D:maj", "A:maj", "E:maj"] * 5, beats_per_chord=4,
         parts=[("synth pad", 0), ("synth bass", 0), ("drums", 0), ("distorted guitar", 8)],
         melody=None, lyrics=None),
    dict(id="s3_jazz_Eb", bpm=92, key="Eb major",
         prog=["F:min7", "Bb:7", "Eb:maj7", "C:min7"] * 4, beats_per_chord=4,
         parts=[("electric piano", 0), ("acoustic bass", 0), ("drums", 0), ("saxophone", 8)],
         melody="sax", lyrics=None),
    dict(id="s4_modulation_D_to_E", bpm=112, key="D major -> E major at bar 9",
         prog=["D:maj", "B:min", "G:maj", "A:maj"] * 2 + ["E:maj", "C#:min", "A:maj", "B:maj"] * 2,
         beats_per_chord=4, modulation_bar=9, keys=["D major", "E major"],
         parts=[("strings", 0), ("piano", 0), ("electric bass", 0), ("flute", 4)],
         melody="flute", lyrics=None),
    dict(id="s5_slow_Bbminor_fast_changes", bpm=76, key="Bb minor",
         prog=["Bb:min", "Gb:maj", "Db:maj", "F:7", "Bb:min", "Eb:min", "F:sus4", "F:7"] * 2,
         beats_per_chord=2, parts=[("organ", 0), ("cello", 0)],
         melody=None, lyrics=None),
    dict(id="s6_lyrics_G", bpm=96, key="G major",
         prog=["G:maj", "E:min", "C:maj", "D:maj"] * 4, beats_per_chord=4,
         parts=[("steel guitar", 0), ("electric bass", 0), ("drums", 4)],
         melody=None,
         lyrics=[(2.0, "Walking down the copper river in the rain"),
                 (12.0, "Every window holds a candle and a name"),
                 (22.0, "I will carry what you gave me through the night"),
                 (32.0, "Till the morning paints the harbor gold and white")]),
    dict(id="s7_lyrics_minor_A", bpm=120, key="A minor",
         prog=["A:min", "F:maj", "C:maj", "G:maj", "A:min", "F:maj", "D:min", "E:7"] * 2, beats_per_chord=4,
         parts=[("nylon guitar", 0), ("acoustic bass", 0), ("strings", 8), ("drums", 0)],
         melody=None,
         lyrics=[(4.0, "Seven lanterns floating on the quiet bay"),
                 (16.0, "Paper boats that never learned to find their way"),
                 (24.0, "Hold the rope and pull the anchor from the sand")]),
]


def chord_pcs(ch):
    r, q = ch.split(":")
    return NOTE[r], QUAL[q]


def build(song):
    bpm, bpc = song["bpm"], song["beats_per_chord"]
    spb = 60 / bpm
    tpb = 480
    mid = mido.MidiFile(ticks_per_beat=tpb)
    meta = mido.MidiTrack(); mid.tracks.append(meta)
    meta.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(bpm)))
    nbeats = len(song["prog"]) * bpc
    bars = nbeats // 4
    events = {}  # channel -> list of (tick, msg)

    def add(ch, tick, note, dur, vel):
        events.setdefault(ch, []).append((tick, mido.Message("note_on", channel=ch, note=note, velocity=vel)))
        events[ch].append((tick + dur, mido.Message("note_off", channel=ch, note=note, velocity=0)))

    truth_instr = []
    for idx, (name, start_bar) in enumerate(song["parts"]):
        start_beat = start_bar * 4
        truth_instr.append(dict(name=name, start=round(start_beat * spb, 2), end=round(nbeats * spb, 2)))
        if name == "drums":
            ch = 9
            for b in range(start_beat, nbeats):
                t = b * tpb
                if b % 4 in (0, 2): add(ch, t, 36, 120, 110)
                if b % 4 in (1, 3): add(ch, t, 38, 120, 100)
                add(ch, t, 42, 100, 70); add(ch, t + tpb // 2, 42, 100, 55)
            continue
        ch = idx if idx < 9 else idx + 1
        events.setdefault(ch, []).append((0, mido.Message("program_change", channel=ch, program=GM[name])))
        is_melody = song.get("melody") and name in ("saxophone", "flute")
        for ci, chord in enumerate(song["prog"]):
            b0 = ci * bpc
            if b0 < start_beat: continue
            root, ivs = chord_pcs(chord)
            t0 = b0 * tpb
            if "bass" in name or name == "cello":
                add(ch, t0, 36 + root, bpc * tpb - 20, 100)
            elif is_melody:
                # simple chord-tone melody: one note per beat
                for k in range(bpc):
                    pc = (root + ivs[k % len(ivs)]) % 12
                    add(ch, t0 + k * tpb, 72 + pc if pc < 7 else 60 + pc, tpb - 30, 90)
            else:
                notes = [60 + ((root + iv) % 12) - (12 if (root + iv) % 12 > 7 else 0) for iv in ivs]
                if name in ("steel guitar", "nylon guitar"):  # strum each beat
                    for k in range(bpc):
                        for j, n in enumerate(sorted(notes)):
                            add(ch, t0 + k * tpb + j * 15, n, tpb - 40, 80)
                else:
                    for n in notes:
                        add(ch, t0, n, bpc * tpb - 20, 75)
    for ch, evs in events.items():
        tr = mido.MidiTrack(); mid.tracks.append(tr)
        evs.sort(key=lambda e: (e[0], e[1].type == "note_on"))
        last = 0
        for t, m in evs:
            tr.append(m.copy(time=t - last)); last = t

    chords = [dict(start=round(i * bpc * spb, 3), end=round((i + 1) * bpc * spb, 3), chord=c)
              for i, c in enumerate(song["prog"])]
    keys = [dict(start=0.0, end=round(nbeats * spb, 2), key=song["key"])]
    if "keys" in song:
        mb = (song["modulation_bar"] - 1) * 4 * spb
        keys = [dict(start=0.0, end=round(mb, 2), key=song["keys"][0]),
                dict(start=round(mb, 2), end=round(nbeats * spb, 2), key=song["keys"][1])]
    truth = dict(id=song["id"], bpm=bpm, time_signature="4/4", duration=round(nbeats * spb, 2),
                 keys=keys, chords=chords, instruments=truth_instr,
                 lyrics=[dict(start=t, text=x) for t, x in (song["lyrics"] or [])])
    return mid, truth


def render(song, mid, truth):
    with tempfile.TemporaryDirectory() as td:
        mp = os.path.join(td, "x.mid"); wav = os.path.join(td, "x.wav")
        mid.save(mp)
        subprocess.run(["fluidsynth", "-ni", "-g", "0.8", "-r", "44100", "-F", wav, SF, mp], check=True,
                       capture_output=True)
        inputs = ["-i", wav]; filt = []
        for i, (t, text) in enumerate(song["lyrics"] or []):
            a = os.path.join(td, f"l{i}.aiff")
            subprocess.run(["say", "-v", "Samantha", "-r", "150", "-o", a, text], check=True)
            # measure spoken duration for truth end time
            d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a],
                                     capture_output=True, text=True).stdout)
            truth["lyrics"][i]["end"] = round(t + d, 2)
            inputs += ["-i", a]
            filt.append(f"[{i+1}:a]adelay={int(t*1000)}|{int(t*1000)},volume=2.2[v{i}]")
        out = os.path.join(OUT, song["id"] + ".mp3")
        if filt:
            n = len(filt)
            fc = ";".join(filt) + ";[0:a]" + "".join(f"[v{i}]" for i in range(n)) + \
                 f"amix=inputs={n+1}:duration=first:normalize=0[o]"
            cmd = ["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", fc, "-map", "[o]",
                   "-t", str(truth["duration"] + 1), "-b:a", "192k", out]
        else:
            cmd = ["ffmpeg", "-y", "-v", "error", "-i", wav, "-t", str(truth["duration"] + 1), "-b:a", "192k", out]
        subprocess.run(cmd, check=True)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    if not os.path.exists(SF):
        os.makedirs(CACHE, exist_ok=True)
        print("downloading soundfont"); urllib.request.urlretrieve(SF_URL, SF)
    for s in SONGS:
        mid, truth = build(s)
        render(s, mid, truth)
        json.dump(truth, open(os.path.join(OUT, s["id"] + ".json"), "w"), indent=1)
        print(s["id"], truth["duration"], "s")
