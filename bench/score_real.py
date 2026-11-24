"""Scoring for the real set (mir_eval chords and keys, jiwer lyrics). Used by bench.leaderboard."""
import json, glob, os, re, sys, statistics
import numpy as np
import mir_eval, jiwer

QMAP = {"": "maj", "m": "min", "major": "maj", "minor": "min", "dom7": "7", "m7": "min7", "min7b5": "hdim7",
        "m7b5": "hdim7", "sus": "sus4", "7sus4": "sus4(b7)", "add9": "maj(9)", "madd9": "min(9)", "m6": "min6",
        "dim7": "dim7", "+": "aug", "maj9": "maj9", "m9": "min9", "min9": "min9", "11": "11", "13": "13"}


def fix_chord(c):
    c = (c or "N").strip()
    if c in ("N", "X", "", "N.C.", "NC"): return "N"
    c = c.replace("♯", "#").replace("♭", "b")
    m = re.match(r"^([A-G][#b]?)(?::)?([^/]*)(/.*)?$", c)
    if not m: return "X"
    q = QMAP.get(m.group(2).strip(), m.group(2).strip())
    lab = f"{m.group(1)}:{q}"
    try:
        mir_eval.chord.validate(lab); return lab
    except Exception:
        return f"{m.group(1)}:maj" if not q.startswith("min") else f"{m.group(1)}:min"


def strip_bass(c): return c.split("/")[0]


def segs(lst, field, fix=lambda x: x, dur=None):
    iv, lb = [], []
    for s in lst:
        st, en = float(s.get("start") or 0), float(s.get("end") or 0)
        if en <= st: continue
        iv.append([st, en]); lb.append(fix(s.get(field)))
    return np.array(iv) if iv else np.zeros((0, 2)), lb


def chord_scores(truth, pred, offset=0.0):
    ri, rl = segs(truth["chords"], "chord", strip_bass)
    pi, pl = segs(pred.get("chords") or [], "chord", fix_chord)
    if not len(pi): return dict(root=0, majmin=0, sevenths=0)
    pi = pi + offset
    pi = np.clip(pi, 0, None)
    pi, pl = pi[pi[:, 1] > pi[:, 0]], [l for l, v in zip(pl, pi[:, 1] > pi[:, 0]) if v]
    pi, pl = mir_eval.util.adjust_intervals(pi, pl, ri.min(), ri.max(), "N", "N")
    mi, rl2, pl2 = mir_eval.util.merge_labeled_intervals(ri, rl, pi, pl)
    d = mir_eval.util.intervals_to_durations(mi)
    out = {}
    for name, fn in [("root", mir_eval.chord.root), ("majmin", mir_eval.chord.majmin), ("sevenths", mir_eval.chord.sevenths)]:
        comp = fn(rl2, pl2)
        out[name] = mir_eval.chord.weighted_accuracy(comp, d)
    return out


def norm_key(k):
    k = re.sub(r"[- ]?flat", "b", re.sub(r"[- ]?sharp", "#", k or "", flags=re.I), flags=re.I)
    m = re.match(r"^\s*([A-G][#b]?)\s*(major|minor|maj|min|m)?", k, re.I)
    if not m: return None
    mode = "minor" if (m.group(2) or "").lower().startswith("m") and (m.group(2) or "").lower() not in ("maj", "major") else "major"
    return f"{m.group(1)} {mode}"


def at(lst, t):
    for s in lst:
        if (s.get("start") or 0) <= t < (s.get("end") or 0): return s.get("key")
    return None


def key_score(truth, pred):
    tk, pk = truth["keys"], pred.get("keys") or []
    if pk and pk[-1].get("end"): pk[-1] = dict(pk[-1], end=max(pk[-1]["end"], truth["duration"] + 5))
    tot = w = 0
    for t in np.arange(0, truth["duration"], 0.25):
        a = at(tk, t)
        if not a: continue
        b = norm_key(at(pk, t) or "")
        w += 1
        if b:
            try: tot += mir_eval.key.weighted_score(a, b)
            except Exception: pass
    return tot / w if w else None


def norm(s): return " ".join(re.sub(r"[^\w' ]", " ", s.lower()).split())


def lyrics_scores(truth, pred):
    ref = norm(" ".join(l["text"] for l in truth["lyrics"]))
    pl = pred.get("lyrics") or []
    hyp = norm(" ".join(l.get("text", "") for l in pl)) or "x"
    wer = jiwer.wer(ref, hyp)
    errs = []
    for l in truth["lyrics"]:
        lt = norm(l["text"])
        if not lt or not pl: continue
        best = min(pl, key=lambda p: jiwer.wer(lt, norm(p.get("text", "")) or "x"))
        if jiwer.wer(lt, norm(best.get("text", "")) or "x") <= 0.5:
            errs.append(abs(float(best.get("start") or 0) - l["start"]))
    return dict(wer=wer, n_lines_true=len(truth["lyrics"]), n_lines_pred=len(pl),
                lines_matched=len(errs) / len(truth["lyrics"]),
                line_start_med_err=statistics.median(errs) if errs else None,
                lines_within_1s=sum(e <= 1 for e in errs) / len(truth["lyrics"]))
