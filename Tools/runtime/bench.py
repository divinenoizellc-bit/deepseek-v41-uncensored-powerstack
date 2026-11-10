#!/usr/bin/env python3
"""Benchmark a running Strata (or any OpenAI-compatible) server.

Measures, per prompt size: time-to-first-token, prompt tokens/s, decode tokens/s.
Standard library only.

    python Tools/runtime/bench.py --url http://127.0.0.1:8080/v1 --runs 3
    python Tools/runtime/bench.py --url http://127.0.0.1:8080/v1 --contexts 1024,4096,16384

Why TTFT separately: on this model prompt processing and decoding hit completely
different hardware (chunked prefill vs per-token expert/Engram reads). One number
would hide that.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request


def post(url: str, body: dict, key: str | None = None, timeout: float = 1800):
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if key:
        req.add_header("Authorization", "Bearer " + key)
    return urllib.request.urlopen(req, timeout=timeout)


def make_prompt(words: int) -> str:
    filler = ("The quick brown fox jumps over the lazy dog. "
              "A measured system is a trusted system. ")
    return (filler * max(1, words // 12))[: words * 6]


def bench_stream(url: str, model: str, prompt: str, max_tokens: int, key: str | None):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.2,
        "stream": True,
        "reasoning_effort": "none",   # isolate raw throughput from thinking length
    }
    t0 = time.perf_counter()
    first = None
    chunks = 0
    text = []
    try:
        with post(url.rstrip("/") + "/chat/completions", body, key) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                try:
                    obj = json.loads(payload)
                except json.JSONDecodeError:
                    continue
                delta = (obj.get("choices") or [{}])[0].get("delta") or {}
                piece = delta.get("content") or delta.get("reasoning_content") or ""
                if piece:
                    if first is None:
                        first = time.perf_counter() - t0
                    chunks += 1
                    text.append(piece)
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read()[:300].decode('utf-8','replace')}"}
    total = time.perf_counter() - t0
    decode_s = total - (first or 0)
    return {
        "ttft_s": round(first, 3) if first is not None else None,
        "decode_tok_s": round(chunks / decode_s, 2) if decode_s > 0.05 and chunks else None,
        "total_s": round(total, 2),
        "chunks": chunks,
    }


def usage_tokens(url: str, model: str, prompt: str, key: str | None):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1, "temperature": 0, "reasoning_effort": "none",
    }
    try:
        with post(url.rstrip("/") + "/chat/completions", body, key) as r:
            obj = json.loads(r.read())
            return (obj.get("usage") or {}).get("prompt_tokens")
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8080/v1")
    ap.add_argument("--model", default="deepseek-v4.1-flash")
    ap.add_argument("--key", default=None, help="API key, or omit for --access local")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--max-tokens", type=int, default=128)
    ap.add_argument("--contexts", default="256,1024,4096,16384", help="approx prompt sizes in words")
    args = ap.parse_args()

    print(f"endpoint : {args.url}")
    print(f"model    : {args.model}")
    print(f"runs     : {args.runs} per size, {args.max_tokens} output tokens, thinking off")
    print()
    print(f"{'prompt':>8} {'tok':>7} {'ttft s':>8} {'decode tok/s':>14} {'total s':>9}")
    print("-" * 52)

    results = []
    for words in [int(x) for x in args.contexts.split(",") if x.strip()]:
        prompt = make_prompt(words)
        tokens = usage_tokens(args.url, args.model, prompt, args.key)
        rows = []
        for _ in range(args.runs):
            rows.append(bench_stream(args.url, args.model, prompt, args.max_tokens, args.key))
        ok = [r for r in rows if "error" not in r and r.get("decode_tok_s")]
        err = [r for r in rows if "error" in r]
        if err:
            print(f"{words:>8}  ERROR {err[0]['error']}")
            continue
        ttft = statistics.median([r["ttft_s"] for r in ok if r["ttft_s"]] or [0])
        dec = statistics.median([r["decode_tok_s"] for r in ok]) if ok else 0
        tot = statistics.median([r["total_s"] for r in ok or rows])
        print(f"{words:>8} {tokens if tokens else '-':>7} {ttft:>8.2f} {dec:>14.2f} {tot:>9.2f}")
        results.append({"prompt_words": words, "prompt_tokens": tokens,
                        "ttft_s": ttft, "decode_tok_s": dec, "total_s": tot})

    if not results:
        print("\nno successful runs - is the server up? strata launch --status", file=sys.stderr)
        return 2
    print()
    best = max(results, key=lambda r: r["decode_tok_s"] or 0)
    print(f"best decode: {best['decode_tok_s']:.2f} tok/s at ~{best['prompt_tokens'] or best['prompt_words']} prompt tokens")
    print("Record the launch flags beside these numbers; they are meaningless without them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
