"""Score every model in results/ and write the leaderboard.

    uv run python -m bench.leaderboard          # writes results/leaderboard.json and LEADERBOARD.md
    uv run python -m bench.leaderboard --check  # CI: fails if a submission is incomplete or the files are stale

Scores are always recomputed from the raw answers, never taken from a submission. An answer the model
refused or that isn't JSON scores zero on that song (a timeline you didn't get is a timeline you can't use).
"""
import argparse, json, statistics, sys
import numpy as np
from .common import RESULTS, SYNTH, REAL, ROOT
from . import score as S, score_real as SR
from .real import song_ids, SHIFTS

R4 = lambda v: None if v is None else round(float(v), 4)
METRICS = [  # key, label, higher is better, in overall score
    ("synthetic_chords", "Chords · generated", True, True),
    ("famous_chords", "Chords · Beatles", True, True),
    ("obscure_chords", "Chords · obscure", True, True),
    ("obscure_key", "Key · obscure", True, True),
    ("probe_key", "Key · pitch-shifted", True, False),
    ("lyrics_wer", "Lyrics word error", False, False),
    ("lyrics_within_1s", "Lyric lines ≤1s", True, True),
    ("synthetic_instruments", "Instruments · generated", True, False),
]


def failed(p): return p is None or "_raw" in p or not isinstance(p.get("chords", []), list)


def out_tokens(u):
    if not u: return None
    if u.get("output_tokens") is not None: return u["output_tokens"]
    if "candidates_token_count" in u: return (u.get("candidates_token_count") or 0) + (u.get("thoughts_token_count") or 0)
    return None


def load_runs(d, ids, runs):
    out, missing = {}, []
    for sid in ids:
        for k in range(runs):
            f = d / f"{sid}.r{k}.json"
            if not f.exists(): missing.append(f"{d.name}/{f.name}"); continue
            out.setdefault(sid, []).append(json.loads(f.read_text()))
    return out, missing


def score_model(md):
    meta = json.loads((md / "meta.json").read_text())
    runs = int(meta.get("runs", 2))
    synth_ids = sorted(p.stem for p in SYNTH.glob("*.json"))
    syn, m1 = load_runs(md / "synthetic", synth_ids, runs)
    real, m2 = load_runs(md / "real", song_ids(), runs)
    problems = m1 + m2
    toks, refusals, unparsed = [], 0, 0
    detail = {"songs": {}, "lyrics": {}, "probe": []}

    sc, sk, si = [], [], []
    for sid, preds in syn.items():
        t = json.loads((SYNTH / f"{sid}.json").read_text())
        for p in preds:
            toks.append(out_tokens(p.get("_usage")))
            if failed(p):
                sc.append(0); sk.append(0); si.append(0)
                if p.get("_raw") is None: refusals += 1
                else: unparsed += 1
                continue
            r = S.score(t, p)
            sc.append(r["chord_majmin"]); sk.append(r["key"]); si.append((r["instr_recall"] + r["instr_precision"]) / 2)

    groups = {"famous_chords": [], "obscure_chords": [], "famous_key": [], "obscure_key": [], "probe_key": []}
    wers, within = [], []
    for sid, preds in real.items():
        t = json.loads((REAL / f"{sid}.json").read_text())
        for i, p in enumerate(preds):
            toks.append(out_tokens(p.get("_usage")))
            bad = failed(p)
            if bad:
                if p.get("_raw") is None: refusals += 1   # refused, rejected by the API, or empty
                else: unparsed += 1
            if "chords" in t["has"]:
                c = 0 if bad else SR.chord_scores(t, p)["majmin"]
                k = 0 if bad else (SR.key_score(t, p) or 0)
                detail["songs"].setdefault(sid, []).append(R4(c))
                if "shift" in sid:
                    groups["probe_key"].append(k)
                    detail["probe"].append(dict(song=sid, run=i, true=t["keys"][0]["key"],
                                                pred=None if bad else [x.get("key") for x in p.get("keys") or []][:3]))
                elif sid.startswith("zw_"):
                    groups["obscure_chords"].append(c); groups["obscure_key"].append(k)
                else:
                    groups["famous_chords"].append(c); groups["famous_key"].append(k)
            if "lyrics" in t["has"]:
                l = {"wer": 1.0, "lines_within_1s": 0.0} if bad else SR.lyrics_scores(t, p)
                wers.append(min(1.0, l["wer"])); within.append(l["lines_within_1s"])
                detail["lyrics"].setdefault(sid, []).append(R4(1 - min(1.0, l["wer"])))

    m = lambda xs: R4(np.mean(xs)) if xs else None
    res = dict(synthetic_chords=m(sc), synthetic_key=m(sk), synthetic_instruments=m(si),
               famous_chords=m(groups["famous_chords"]), obscure_chords=m(groups["obscure_chords"]),
               famous_key=m(groups["famous_key"]), obscure_key=m(groups["obscure_key"]), probe_key=m(groups["probe_key"]),
               lyrics_wer=R4(statistics.median(wers)) if wers else None, lyrics_within_1s=m(within),
               refusals=refusals, unparsed=unparsed,
               output_tokens_per_song=R4(np.mean([x for x in toks if x is not None])) if any(x is not None for x in toks) else None)
    parts = [res[k] if hib else 1 - res[k] for k, _, hib, inc in METRICS if inc and res[k] is not None]
    res["overall"] = R4(np.mean(parts))
    detail["songs"] = {k: R4(np.mean(v)) for k, v in detail["songs"].items()}
    detail["lyrics"] = {k: R4(np.mean(v)) for k, v in detail["lyrics"].items()}
    return dict(slug=md.name, model=meta.get("model"), provider=meta.get("provider"), date=meta.get("date"),
                runs=runs, notes=meta.get("notes", ""), submitted_by=meta.get("submitted_by", ""),
                scores=res, detail=detail), problems


def pct(v): return "–" if v is None else f"{v*100:.0f}%"


def markdown(board):
    head = "| # | Model | Overall | " + " | ".join(l for _, l, _, _ in METRICS) + " | Failed | Tokens/song | Date |"
    sep = "|" + "---|" * (head.count("|") - 1)
    rows = []
    for i, e in enumerate(board["models"], 1):
        s = e["scores"]
        tok = "–" if s["output_tokens_per_song"] is None else f'{s["output_tokens_per_song"]/1000:.1f}k'
        rows.append(f'| {i} | {e["model"]} | **{pct(s["overall"])}** | ' +
                    " | ".join(pct(s[k]) for k, *_ in METRICS) + f' | {s["refusals"] + s["unparsed"]} | {tok} | {e["date"]} |')
    return ("# Leaderboard\n\nGenerated by `uv run python -m bench.leaderboard` from the raw answers in `results/`. "
            "Don't edit by hand.\n\n**Overall** is the plain average of: " +
            ", ".join(l for _, l, hib, inc in METRICS if inc) +
            ". Higher is better except word error. Failed = answers that were refused, rejected by the API, "
            "empty or not JSON; each scores zero.\n\n" +
            head + "\n" + sep + "\n" + "\n".join(rows) + "\n")


def build():
    entries, problems = [], []
    for md in sorted(p for p in RESULTS.iterdir() if p.is_dir()):
        if not (md / "meta.json").exists(): problems.append(f"{md.name}: missing meta.json"); continue
        e, pr = score_model(md)
        entries.append(e); problems += [f"{md.name}: missing {x}" for x in pr]
    entries.sort(key=lambda e: -(e["scores"]["overall"] or 0))
    return {"metrics": [dict(key=k, label=l, higher_is_better=h, in_overall=i) for k, l, h, i in METRICS],
            "models": entries}, problems


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--check", action="store_true"); a = ap.parse_args()
    if not (REAL / "zw_akne.json").exists():
        sys.exit("ground truth for the real set is missing: run `uv run python -m bench.real truth`")
    board, problems = build()
    js = json.dumps(board, indent=1, ensure_ascii=False) + "\n"
    md = markdown(board)
    jf, mf = RESULTS / "leaderboard.json", ROOT / "LEADERBOARD.md"
    if a.check:
        stale = [f.name for f, new in ((jf, js), (mf, md)) if not f.exists() or f.read_text() != new]
        for p in problems: print("INCOMPLETE", p)
        for f in stale: print(f"STALE {f}: run `uv run python -m bench.leaderboard` and commit the result")
        if problems or stale: sys.exit(1)
        print("leaderboard is complete and up to date"); return
    for p in problems: print("warning:", p)
    jf.write_text(js); mf.write_text(md)
    print(md)


if __name__ == "__main__":
    main()
