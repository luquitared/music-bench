"""The real-audio set: human annotations + audio you fetch yourself.

    uv run python -m bench.real truth   # annotations only -> data/real/<id>.json (what scoring needs; CI runs this)
    uv run python -m bench.real audio   # audio -> data/real/<id>.mp3 (what running a model needs; needs ffmpeg)

Sources:
  - Isophonics (isophonics.net): chords, keys and beats for Zweieck (an obscure German band) and four
    Beatles songs. Audio is fetched from YouTube with yt-dlp; durations are checked against the annotation.
  - Two Beatles songs pitch-shifted with ffmpeg: a memorization probe (truth transposed to match).
  - JamendoLyrics (github.com/f90/jamendolyrics, annotations MIT, songs Creative Commons): eight
    obscure English songs with human line-level lyric timings.
No audio or third-party annotation is committed to this repo.
"""
import csv, json, os, re, statistics, subprocess, sys, tarfile, urllib.request, urllib.parse
from .common import REAL, CACHE

PCS = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
PC = {"C": 0, "B#": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "Fb": 4, "F": 5, "E#": 5, "F#": 6,
      "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11, "Cb": 11}

ISO_TARS = {"Zweieck": "http://isophonics.net/files/annotations/Zweieck%20Annotations.tar.gz",
            "The Beatles": "http://isophonics.net/files/annotations/The%20Beatles%20Annotations.tar.gz"}
JAMENDO_REPO = "https://github.com/f90/jamendolyrics.git"
JAMENDO_RAW = "https://raw.githubusercontent.com/f90/jamendolyrics/master"

ISO_SONGS = [  # (id, artist, annotation path, YouTube id)
    ("zw_mr_morgan", "Zweieck", "Zwielicht/09_-_Mr_Morgan", "McB_0oKyROQ"),
    ("zw_akne", "Zweieck", "Zwielicht/07_-_Akne", "QgO2CLdYpKo"),
    ("zw_blass", "Zweieck", "Zwielicht/08_-_Blass", "WVCBQMPdinM"),
    ("zw_tigerfest", "Zweieck", "Zwielicht/06_-_Tigerfest", "2OzmFl7llFA"),
    ("zw_duell", "Zweieck", "Zwielicht/17_-_Duell", "7ZEpV5nEAyk"),
    ("zw_zuhause", "Zweieck", "Zwielicht/18_-_Zuhause", "bb5bNhND7qk"),
    ("bt_here_comes_the_sun", "The Beatles", "11_-_Abbey_Road/07_-_Here_Comes_The_Sun", "xUNqsfFUwhY"),
    ("bt_eleanor_rigby", "The Beatles", "07_-_Revolver/02_-_Eleanor_Rigby", "6gluNoLVKiQ"),
    ("bt_let_it_be", "The Beatles", "12_-_Let_It_Be/06_-_Let_It_Be", "QDYfEBY9NM4"),
    ("bt_in_my_life", "The Beatles", "06_-_Rubber_Soul/11_-_In_My_Life", "ngzQTxXEcxQ"),
]
KEY_FIX = {"bt_here_comes_the_sun": "A major"}  # Isophonics labels it A:minor; its chords are A/D/E
SHIFTS = [("bt_let_it_be", 2), ("bt_here_comes_the_sun", -3)]  # semitones
JAMENDO = ["HILA_-_Give_Me_the_Same", "Songwriterz_-_Back_In_Time", "Avercage_-_Embers", "Color_Out_-_Falling_Star",
           "The.madpix.project_-_One_Way_Street", "JASON_MILLER_-_CROWD_PLEASER", "Ridgway_-_Fire_Inside",
           "Slingshot_Miracle_-_Whistler"]


def jid(name): return "jl_" + re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def song_ids():
    return [s[0] for s in ISO_SONGS] + [f"{s}_shift{n:+d}" for s, n in SHIFTS] + [jid(n) for n in JAMENDO]


def lab(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        p = line.strip().split("\t") if "\t" in line else line.strip().split(None, 2)
        if len(p) >= 3: rows.append((float(p[0]), float(p[1]), "\t".join(x.strip() for x in p[2:])))
    return rows


def fetch_iso():
    root = CACHE / "isophonics"
    for artist, url in ISO_TARS.items():
        if (root / "chordlab" / artist).exists(): continue
        root.mkdir(parents=True, exist_ok=True)
        tgz = CACHE / (artist.replace(" ", "_") + ".tar.gz")
        print("downloading", url); urllib.request.urlretrieve(url, tgz)
        with tarfile.open(tgz) as t: t.extractall(root, filter="data")
    return root


def fetch_jamendo_lines():
    root = CACHE / "jamendolyrics_lines"; root.mkdir(parents=True, exist_ok=True)
    for n in JAMENDO:
        f = root / f"{n}.csv"
        if not f.exists():
            urllib.request.urlretrieve(f"{JAMENDO_RAW}/annotations/lines/{urllib.parse.quote(n)}.csv", f)
    return root


def iso_truth(sid, artist, path, iso):
    chords = [dict(start=s, end=e, chord=c) for s, e, c in lab(iso / "chordlab" / artist / f"{path}.lab")]
    keys = []
    for s, e, k in lab(iso / "keylab" / artist / f"{path}.lab"):
        if not k.startswith("Key"): continue
        r, _, mode = k.split("\t")[-1].partition(":")
        if r == "N": continue
        keys.append(dict(start=s, end=e, key=KEY_FIX.get(sid) or f'{r} {"minor" if mode.startswith("min") else "major"}'))
    bpm = None
    bp = iso / "beat" / artist / f"{path}.txt"
    if bp.exists():
        ts = [float(l.split()[0]) for l in open(bp) if l.strip()]
        ibi = [b - a for a, b in zip(ts, ts[1:]) if b > a]
        if ibi: bpm = round(60 / statistics.median(ibi), 1)
    return dict(id=sid, bpm=bpm, duration=round(chords[-1]["end"], 2), keys=keys, chords=chords, lyrics=[],
                has=["chords", "keys"] + (["bpm"] if bpm else []), audio=None)


def transpose_chord(c, n):
    m = re.match(r"^([A-G][#b]?)(.*)$", c)
    if not m: return c
    rest = m.group(2)
    bm = re.match(r"^(.*)/([A-G][#b]?)$", rest)
    if bm: rest = bm.group(1) + "/" + PCS[(PC[bm.group(2)] + n) % 12]
    return PCS[(PC[m.group(1)] + n) % 12] + rest


def truth():
    REAL.mkdir(parents=True, exist_ok=True)
    iso = fetch_iso()
    by = {}
    for sid, artist, path, yt in ISO_SONGS:
        t = iso_truth(sid, artist, path, iso); t["audio"] = f"https://www.youtube.com/watch?v={yt}"
        by[sid] = t
    for sid, n in SHIFTS:
        t = json.loads(json.dumps(by[sid])); t["id"] += f"_shift{n:+d}"; t["audio"] = f"{sid} pitch-shifted {n:+d} semitones"
        for c in t["chords"]: c["chord"] = transpose_chord(c["chord"], n)
        for k in t["keys"]:
            r_, m = k["key"].split(); k["key"] = f"{PCS[(PC[r_] + n) % 12]} {m}"
        by[t["id"]] = t
    lines = fetch_jamendo_lines()
    for name in JAMENDO:
        rows = list(csv.DictReader(open(lines / f"{name}.csv", encoding="utf-8")))
        lyr = [dict(start=float(l["start_time"]), end=float(l["end_time"]), text=l["lyrics_line"]) for l in rows]
        by[jid(name)] = dict(id=jid(name), bpm=None, duration=round(lyr[-1]["end"], 2), keys=[], chords=[], lyrics=lyr,
                             has=["lyrics"], audio=f"https://www.jamendo.com (JamendoLyrics: {name}.mp3)")
    for sid, t in by.items():
        json.dump(t, open(REAL / f"{sid}.json", "w"), indent=1)
    print(f"wrote {len(by)} truth files to {REAL}")


def ffprobe(f, what="format=duration"):
    return subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", what, "-of", "csv=p=0", f],
                          capture_output=True, text=True).stdout.strip()


def audio():
    REAL.mkdir(parents=True, exist_ok=True)
    for sid, artist, path, yt in ISO_SONGS:
        a = REAL / f"{sid}.mp3"
        if not a.exists():
            subprocess.run([sys.executable, "-m", "yt_dlp", "-q", "-x", "--audio-format", "mp3", "--audio-quality", "192K",
                            "-o", str(REAL / f"{sid}.%(ext)s"), f"https://www.youtube.com/watch?v={yt}"], check=True)
        t = json.load(open(REAL / f"{sid}.json"))
        d = float(ffprobe(str(a)))
        flag = "" if abs(d - t["duration"]) < 3 else "   <-- duration differs from the annotation; scores will suffer"
        print(f"{sid:28} audio {d:6.1f}s  annotation {t['duration']:6.1f}s{flag}")
    for sid, n in SHIFTS:
        src, dst = REAL / f"{sid}.mp3", REAL / f"{sid}_shift{n:+d}.mp3"
        if dst.exists(): continue
        r, sr = 2 ** (n / 12), int(ffprobe(str(src), "stream=sample_rate"))
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af",
                        f"asetrate={sr*r:.0f},aresample={sr},atempo={1/r:.6f}", "-b:a", "192k", str(dst)], check=True)
        print("pitch-shifted", dst.name)
    for name in JAMENDO:
        a = REAL / f"{jid(name)}.mp3"
        if not a.exists():
            urllib.request.urlretrieve(f"{JAMENDO_RAW}/mp3/{urllib.parse.quote(name)}.mp3", a)
            print("downloaded", a.name)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("truth", "all"): truth()
    if cmd in ("audio", "all"): audio()
