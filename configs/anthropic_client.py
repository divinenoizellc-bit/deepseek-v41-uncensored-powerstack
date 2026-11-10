#!/usr/bin/env python3
"""Minimal Anthropic Messages client for a local DeepSeek-V4.1-Flash server.

Strata also speaks POST /v1/messages, which is the shape Claude Code uses, so this
is the quickest way to prove the Anthropic path before wiring a real client.

    python configs/anthropic_client.py "summarise this error: CUDA out of memory"
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt", nargs="+")
    ap.add_argument("--base", default="http://127.0.0.1:8080",
                    help="server root; the script appends /v1/messages")
    ap.add_argument("--model", default="deepseek-v4.1-flash")
    ap.add_argument("--key", default=None)
    ap.add_argument("--max-tokens", type=int, default=1024)
    ap.add_argument("--thinking", default="none", choices=["none", "low", "high", "max"])
    args = ap.parse_args()

    body = {
        "model": args.model,
        "max_tokens": args.max_tokens,
        "messages": [{"role": "user", "content": " ".join(args.prompt)}],
        "reasoning_effort": args.thinking,
    }
    req = urllib.request.Request(
        args.base.rstrip("/") + "/v1/messages",
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            **({"x-api-key": args.key} if args.key else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=3600) as r:
        obj = json.loads(r.read())

    for block in obj.get("content") or []:
        if block.get("type") == "text":
            print(block.get("text", ""))
        elif block.get("type") == "thinking":
            print("--- thinking ---\n" + block.get("thinking", ""), file=sys.stderr)
        elif block.get("type") == "tool_use":
            print(json.dumps(block, indent=2), file=sys.stderr)
    u = obj.get("usage") or {}
    if u:
        print(f"\n[tokens: in {u.get('input_tokens')}, out {u.get('output_tokens')}]", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
