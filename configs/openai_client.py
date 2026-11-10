#!/usr/bin/env python3
"""Minimal OpenAI-compatible client for a local DeepSeek-V4.1-Flash server.

    python configs/openai_client.py "explain MoE routing in 3 sentences"
    python configs/openai_client.py --thinking max "prove sqrt(2) is irrational"
    python configs/openai_client.py --stream "write a haiku about NVMe"

No dependencies. Works against Strata (default http://127.0.0.1:8080/v1) and any
other OpenAI Chat Completions endpoint.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt", nargs="+", help="the user message")
    ap.add_argument("--url", default="http://127.0.0.1:8080/v1")
    ap.add_argument("--model", default="deepseek-v4.1-flash")
    ap.add_argument("--key", default=None)
    ap.add_argument("--system", default=None)
    ap.add_argument("--thinking", default="high", choices=["none", "low", "medium", "high", "max"],
                    help="maps to reasoning_effort; 'none' disables the thinking block")
    ap.add_argument("--temperature", type=float, default=0.6)
    ap.add_argument("--top-p", type=float, default=0.95)
    ap.add_argument("--max-tokens", type=int, default=2048)
    ap.add_argument("--stream", action="store_true")
    args = ap.parse_args()

    messages = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": " ".join(args.prompt)})

    body = {
        "model": args.model,
        "messages": messages,
        "temperature": args.temperature,
        "top_p": args.top_p,
        "max_tokens": args.max_tokens,
        "reasoning_effort": args.thinking,
        "stream": args.stream,
    }
    req = urllib.request.Request(
        args.url.rstrip("/") + "/chat/completions",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json",
                 **({"Authorization": "Bearer " + args.key} if args.key else {})},
    )

    with urllib.request.urlopen(req, timeout=3600) as r:
        if not args.stream:
            obj = json.loads(r.read())
            msg = obj["choices"][0]["message"]
            reasoning = msg.get("reasoning_content")
            if reasoning:
                print("--- thinking ---\n" + reasoning.strip() + "\n--- answer ---")
            print(msg.get("content", "").strip())
            u = obj.get("usage") or {}
            if u:
                print(f"\n[tokens: prompt {u.get('prompt_tokens')}, "
                      f"completion {u.get('completion_tokens')}]", file=sys.stderr)
            return 0

        thinking_open = False
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            obj = json.loads(payload)
            delta = (obj.get("choices") or [{}])[0].get("delta") or {}
            reason = delta.get("reasoning_content")
            content = delta.get("content")
            if reason:
                if not thinking_open:
                    print("--- thinking ---", file=sys.stderr)
                    thinking_open = True
                print(reason, end="", flush=True, file=sys.stderr)
            if content:
                if thinking_open:
                    print("\n--- answer ---", file=sys.stderr)
                    thinking_open = False
                print(content, end="", flush=True)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
