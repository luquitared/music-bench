"""Ask a model for a music timeline of every song, twice, and save the raw answers.

    uv run python -m bench.run --provider gemini --model gemini-4-neon
    uv run python -m bench.run --provider openai --model openai/gpt-audio --base-url https://openrouter.ai/api/v1
    uv run python -m bench.run ... --set synthetic   (or real, or all; default all)

Answers go to results/<slug>/{synthetic,real}/<song>.r<k>.json (slug defaults to the model name) with a
meta.json. Existing answers are skipped, so an interrupted run resumes.

Providers:
  gemini   Google Gemini API. Key: GEMINI_API_KEY.
  openai   Any OpenAI-compatible Chat Completions endpoint that accepts `input_audio` content parts
           (OpenAI audio models, OpenRouter, vLLM, ...). Key: OPENAI_API_KEY, or --key-env NAME.
To add another, write a function (audio_bytes, prompt) -> (text, usage dict) and register it in PROVIDERS.
"""
import argparse, base64, concurrent.futures as cf, datetime, json, os, re, sys
from .common import PROMPT, RESULTS, REAL, SYNTH, RUNS_PER_SONG


def gemini(args):
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options={"api_version": "v1beta", "timeout": 900_000})  # ms

    def call(audio, prompt):
        r = client.models.generate_content(
            model=args.model, contents=[types.Part.from_bytes(data=audio, mime_type="audio/mpeg"), prompt],
            config=types.GenerateContentConfig(response_mime_type="application/json"))
        u = r.usage_metadata
        usage = {"output_tokens": (u.candidates_token_count or 0) + (u.thoughts_token_count or 0),
                 "input_tokens": u.prompt_token_count} if u else None
        if not r.text and r.prompt_feedback and r.prompt_feedback.block_reason:
            return None, dict(usage or {}, refused=str(r.prompt_feedback.block_reason))
        return r.text, usage
    return call


def openai_compat(args):
    import httpx
    base = (args.base_url or "https://api.openai.com/v1").rstrip("/")
    key = os.environ[args.key_env or "OPENAI_API_KEY"]

    def call(audio, prompt):
        body = {"model": args.model, "messages": [{"role": "user", "content": [
            {"type": "input_audio", "input_audio": {"data": base64.b64encode(audio).decode(), "format": "mp3"}},
            {"type": "text", "text": prompt}]}]}
        r = httpx.post(f"{base}/chat/completions", json=body, timeout=900,
                       headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        d = r.json()
        u = d.get("usage") or {}
        return d["choices"][0]["message"]["content"], {"output_tokens": u.get("completion_tokens"),
                                                      "input_tokens": u.get("prompt_tokens")}
    return call


PROVIDERS = {"gemini": gemini, "openai": openai_compat}


def parse(text):
    if text is None: return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except Exception:
        m = re.search(r"\{.*\}", t, re.S)
        try: return json.loads(m.group(0)) if m else None
        except Exception: return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", required=True, choices=PROVIDERS)
    ap.add_argument("--model", required=True)
    ap.add_argument("--slug", help="results folder name (default: the model name)")
    ap.add_argument("--base-url"); ap.add_argument("--key-env")
    ap.add_argument("--set", default="all", choices=["synthetic", "real", "all"])
    ap.add_argument("--runs", type=int, default=RUNS_PER_SONG)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--notes", default="", help="settings worth knowing (thinking level, temperature...)")
    args = ap.parse_args()
    slug = args.slug or re.sub(r"[^a-zA-Z0-9._-]+", "-", args.model).strip("-")
    out = RESULTS / slug
    call = PROVIDERS[args.provider](args)

    sets = ["synthetic", "real"] if args.set == "all" else [args.set]
    jobs = []
    for s in sets:
        src = SYNTH if s == "synthetic" else REAL
        songs = sorted(src.glob("*.mp3"))
        if s == "real" and len(songs) < 20:
            sys.exit("data/real has no audio yet: run `uv run python -m bench.real` first")
        (out / s).mkdir(parents=True, exist_ok=True)
        jobs += [(p, out / s / f"{p.stem}.r{k}.json") for p in songs for k in range(args.runs)]

    meta_f = out / "meta.json"
    meta = json.loads(meta_f.read_text()) if meta_f.exists() else {}
    meta.update(model=args.model, provider=args.provider, base_url=args.base_url, runs=args.runs,
                prompt="bench/common.py PROMPT", date=datetime.date.today().isoformat(), notes=args.notes or meta.get("notes", ""))
    meta_f.write_text(json.dumps(meta, indent=1))

    def one(p, dst):
        if dst.exists(): return f"skip {dst.name}"
        try:
            text, usage = call(p.read_bytes(), PROMPT)
        except Exception as e:  # a permanent rejection (4xx except 429) is the model's answer: it scores zero
            code = getattr(getattr(e, "response", None), "status_code", None) or getattr(e, "code", None)
            if not (isinstance(code, int) and 400 <= code < 500 and code != 429): raise
            body = getattr(getattr(e, "response", None), "text", "") or str(e)
            body = re.sub(r"\"user_id\"\s*:\s*\"[^\"]*\"", "\"user_id\":\"…\"", body)
            text, usage = None, {"error": f"{code}: {body[:300]}"}
        data = parse(text)
        if data is None or not isinstance(data, dict):
            data = {"_raw": text}
        data["_usage"] = usage
        dst.write_text(json.dumps(data, indent=1))
        return f"done {dst.parent.name}/{dst.name}"

    with cf.ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(one, p, d): d for p, d in jobs}
        for f in cf.as_completed(futs):
            try: print(f.result())
            except Exception as e: print(f"ERROR {futs[f].name}: {e}")
    print(f"\nanswers in {out}. Score them with: uv run python -m bench.leaderboard")


if __name__ == "__main__":
    main()
