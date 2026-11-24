"""Scoring for the synthetic set (exact truth from bench.gen). Used by bench.leaderboard."""
import json, glob, os, re, sys
import jiwer

PC = {"C": 0, "B#": 0, "C#": 1, "Db": 1, "D": 2, "D#": 3, "Eb": 3, "E": 4, "Fb": 4, "F": 5, "E#": 5, "F#": 6,
      "Gb": 6, "G": 7, "G#": 8, "Ab": 8, "A": 9, "A#": 10, "Bb": 10, "B": 11, "Cb": 11}
MAJLIKE = {"maj", "7", "maj7", "", "major", "dom7", "9", "6", "add9"}
MINLIKE = {"min", "min7", "m", "m7", "minor", "dim", "dim7", "hdim7", "min9"}
FAM = [("drums", r"drum|kit|percussion|snare|hi-?hat|cymbal|kick"),
       ("bass", r"bass(?!oon)"),
       ("electric piano", r"electric piano|rhodes|wurl|e\.? ?piano|ep\b"),
       ("piano", r"piano|keys"),
       ("organ", r"organ"),
       ("guitar", r"guitar"),
       ("cello", r"cello"),
       ("strings", r"string|violin|viola|orchestra"),
       ("synth pad", r"pad|synth(?!.*bass)"),
       ("saxophone", r"sax"),
       ("flute", r"flute"),
       ("trumpet", r"trumpet|brass")]


def fam(name):
    n = name.lower()
    for f, rx in FAM:
        if re.search(rx, n): return f
    return n


def parse_chord(c):
    c = (c or "").strip()
    m = re.match(r"^([A-G][#b]?)[:]?(.*)$", c)
    if not m or m.group(1) not in PC: return None, None
    q = m.group(2).split("/")[0].strip()
    q = {"": "maj", "m": "min", "m7": "min7", "major": "maj", "minor": "min", "dom7": "7"}.get(q, q)
    return PC[m.group(1)], q


def majmin(q):
    if q in MAJLIKE: return "maj"
    if q in MINLIKE: return "min"
    return q  # sus4 etc. stay distinct


def at(segs, t, field):
    for s in segs:
        if s["start"] <= t < s["end"]: return s.get(field)
    return None


def parse_key(k):
    k = re.sub(r"[- ]?flat", "b", re.sub(r"[- ]?sharp", "#", k or "", flags=re.I), flags=re.I)
    m = re.match(r"^\s*([A-G][#b]?)\s*(major|minor|maj|min)?", k or "", re.I)
    if not m or m.group(1) not in PC: return None
    return PC[m.group(1)], "min" if (m.group(2) or "").lower().startswith("min") else "maj"


def key_score(t, p):
    """MIREX weighting: exact 1, fifth .5, relative .3, parallel .2"""
    if not t or not p: return 0
    (tr, tm), (pr, pm) = t, p
    if t == p: return 1
    if tm == pm and (pr - tr) % 12 in (5, 7): return .5
    if tm != pm and ((tm == "maj" and pr == (tr + 9) % 12) or (tm == "min" and pr == (tr + 3) % 12)): return .3
    if tr == pr: return .2
    return 0


def norm(s): return re.sub(r"[^a-z' ]", " ", s.lower()).split()


def score(truth, pred):
    dur = truth["duration"]
    ts = [i * 0.05 for i in range(int(dur / 0.05))]
    r = {}
    # tempo
    bpm = pred.get("bpm") or 0
    r["bpm_pred"] = bpm
    r["bpm_ok"] = abs(bpm - truth["bpm"]) / truth["bpm"] <= 0.04
    # key (time-weighted)
    pk = pred.get("keys") or []
    r["key"] = sum(key_score(parse_key(at(truth["keys"], t, "key")), parse_key(at(pk, t, "key"))) for t in ts) / len(ts)
    r["key_pred"] = " | ".join(f'{k.get("key")}@{k.get("start")}' for k in pk)
    # chords: frame-level
    pc = pred.get("chords") or []
    root = mm = exact = 0
    for t in ts:
        tr, tq = parse_chord(at(truth["chords"], t, "chord"))
        pr, pq = parse_chord(at(pc, t, "chord"))
        if pr is None: continue
        if pr == tr:
            root += 1
            if majmin(pq) == majmin(tq): mm += 1
            if pq == tq: exact += 1
    r["chord_root"], r["chord_majmin"], r["chord_exact"] = root / len(ts), mm / len(ts), exact / len(ts)
    # chord sequence ignoring timing (did it hear the right progression?)
    seq_t = [c["chord"] for c in truth["chords"]]
    seq_p = [c.get("chord") for c in pc]
    r["n_chords_true"], r["n_chords_pred"] = len(seq_t), len(seq_p)
    r["seq_exact"] = sum(parse_chord(a) == parse_chord(b) for a, b in zip(seq_t, seq_p)) / len(seq_t)
    # instruments: family presence + start time error
    tf = {fam(i["name"]): i for i in truth["instruments"]}
    pf = {}
    for i in pred.get("instruments") or []:
        f = fam(i.get("name", ""))
        if f not in pf or (i.get("start") or 0) < (pf[f].get("start") or 0): pf[f] = i
    # cello/strings and piano/electric piano count as near-hits
    def match(f):
        if f in pf: return f
        alt = {"cello": "strings", "electric piano": "piano", "synth pad": "strings"}.get(f)
        return alt if alt in pf else None
    hits = {f: match(f) for f in tf}
    tp = sum(1 for v in hits.values() if v)
    used = set(v for v in hits.values() if v)
    r["instr_recall"] = tp / len(tf)
    r["instr_precision"] = len(used) / len(pf) if pf else 0
    r["instr_missed"] = [f for f, v in hits.items() if not v]
    r["instr_extra"] = [f for f in pf if f not in used]
    errs = [abs((pf[v].get("start") or 0) - tf[f]["start"]) for f, v in hits.items() if v]
    r["instr_entry_err_s"] = max(errs) if errs else None
    r["instr_late_entry"] = {f: (tf[f]["start"], pf[v].get("start")) for f, v in hits.items() if v and tf[f]["start"] > 0}
    # lyrics
    if truth["lyrics"]:
        ref = " ".join(l["text"] for l in truth["lyrics"])
        hyp = " ".join(l.get("text", "") for l in pred.get("lyrics") or [])
        r["lyrics_wer"] = jiwer.wer(" ".join(norm(ref)), " ".join(norm(hyp)) or "x")
        starts = []
        for l in truth["lyrics"]:
            best = min(pred.get("lyrics") or [{}], key=lambda p: jiwer.wer(" ".join(norm(l["text"])), " ".join(norm(p.get("text", "x"))) or "x"))
            if best: starts.append(abs((best.get("start") or 0) - l["start"]))
        r["lyrics_start_err_s"] = sum(starts) / len(starts) if starts else None
    return r
