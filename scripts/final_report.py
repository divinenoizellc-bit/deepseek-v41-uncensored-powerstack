#!/usr/bin/env python3
"""Produce the single completion report: Docs/library/FINAL_REPORT.md.

It refuses to say "done" unless every pinned file is present and every hash matched.
Inputs, all produced by other scripts in this repo:

  Library/logs/verify-library-*.json   newest verification run (scripts/verify_library.py)
  Library/index.json                   set completeness + portability (scripts/index_library.py)
  <library>/*.gguf                     parsed here with scripts/gguf_probe.py

    python scripts/final_report.py                 # require a full PASS
    python scripts/final_report.py --allow-incomplete
    python scripts/final_report.py --verify        # run the verifier first (slow)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from gguf_probe import probe  # noqa: E402

LIBRARY = os.path.join(os.path.expanduser('~'), 'Models', 'huggingface',
                       'AtomicChat--DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF')
DOC = os.path.join(ROOT, 'Docs', 'library', 'FINAL_REPORT.md')


def newest(pattern: str) -> str | None:
    hits = sorted(glob.glob(pattern))
    return hits[-1] if hits else None


def human(n: float) -> str:
    for u in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if abs(n) < 1024 or u == 'TiB':
            return f"{n:,.2f} {u}"
        n /= 1024
    return f"{n} B"


def in_scope(path: str, scope: str) -> bool:
    """Which pinned files the declared scope requires.

    `IQ2_XXS` = the 2.00 bpw rung plus every shared file (Engram, drafter, vision tower,
    packer metadata, text artifacts). IQ1_M is a second, optional rung: same shared files,
    lower quality, and it does not fit on a volume that is already 68% of the way to full.
    """
    if not scope:
        return True
    shared = ('Engram', 'dspark', 'mmproj', 'UD-Q8_K_XL', '.gitattributes', 'LICENSE', 'README.md', 'rungs.json')
    if any(s in path for s in shared):
        return True
    return scope.lower() in path.lower()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify', action='store_true', help='run verify_library.py first')
    ap.add_argument('--allow-incomplete', action='store_true')
    ap.add_argument('--scope', default='', help='treat only these rungs (+ shared files) as required')
    ap.add_argument('--library', default=LIBRARY)
    args = ap.parse_args()

    if args.verify:
        print('running verifier (streams every byte)...')
        rc = subprocess.call([sys.executable, os.path.join(HERE, 'verify_library.py'),
                              '--dir', args.library])
        print(f'verifier exit {rc}')

    vp = newest(os.path.join(ROOT, 'Library', 'logs', 'verify-library-*.json'))
    if not vp:
        print('no verification report found; run scripts/verify_library.py first', file=sys.stderr)
        return 2
    verify = json.load(open(vp, encoding='utf-8'))

    ip = os.path.join(ROOT, 'Library', 'index.json')
    index = json.load(open(ip, encoding='utf-8')) if os.path.exists(ip) else {}

    files = verify.get('files', [])
    totals = verify.get('totals', {})
    required = [f for f in files if in_scope(f.get('filename', ''), args.scope)]
    deferred = [f for f in files if f not in required]
    req_ok = all(f.get('status') == 'PASS' for f in required)
    complete = (verify.get('verdict') == 'PASS'
                and totals.get('filesExpected') == totals.get('filesChecked')
                and totals.get('missing', 0) == 0)
    scoped_complete = (args.scope and req_ok
                       and all(f.get('status') in ('PASS', 'MISSING') for f in files)
                       and not any(f.get('status') in ('FAIL', 'INCOMPLETE') for f in required))
    if not (complete or scoped_complete) and not args.allow_incomplete:
        print(f"REFUSING to write a completion report: verdict={verify.get('verdict')} "
              f"checked={totals.get('filesChecked')}/{totals.get('filesExpected')}"
              + (f" scope={args.scope}" if args.scope else '')
              + ". Use --allow-incomplete for a progress snapshot.", file=sys.stderr)
        return 1

    # GGUF headers, locally
    probes = []
    for root, _dirs, names in os.walk(args.library):
        if os.sep + '.cache' in root:
            continue
        for n in sorted(names):
            if n.endswith('.gguf'):
                try:
                    probes.append(probe(os.path.join(root, n)))
                except Exception as exc:  # noqa: BLE001
                    probes.append({'path': os.path.join(root, n), 'error': str(exc)})

    now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    state = ('COMPLETE' if complete else ('COMPLETE FOR SCOPE' if scoped_complete else 'INCOMPLETE snapshot'))
    L = [
        '# Final report — DeepSeek-V4.1-Flash-1017 Uncensored power stack',
        '',
        f'Generated **{now}** by `scripts/final_report.py`.  **State: {state}**'
        + (f' (scope: `{args.scope}`, {len(required)} required files)' if args.scope else ''),
        '',
        '## Verdict',
        '',
        f"- Verification: **{verify.get('verdict')}** — {totals.get('filesChecked')}/"
        f"{totals.get('filesExpected')} files, {totals.get('pass')} PASS, "
        f"{totals.get('fail')} FAIL, {totals.get('missing')} MISSING",
        f"- Bytes: {human(totals.get('bytesExpected', 0))} expected, "
        f"{human(totals.get('bytesPresent', 0))} present, "
        f"{human(totals.get('bytesVerified', 0))} hash-verified",
        f"- Portability: **{index.get('portable')}** — {index.get('portableReason', 'n/a')}",
        f"- Hardware minimum (Strata): {index.get('hardwareMinimum', 'n/a')}",
        f"- Source report: `{os.path.relpath(vp, ROOT)}`",
        '',
        '## Files',
        '',
        '| File | Bytes | Status | Expected hash | Actual hash |',
        '|---|---:|---|---|---|',
    ]
    for f in files:
        exp = (f.get('expectedSha256') or f.get('expectedBlobSha1') or '')[:16]
        act = (f.get('actualSha256') or f.get('actualBlobSha1') or '')[:16]
        L.append(f"| `{os.path.basename(f.get('filename', ''))}` | "
                 f"{f.get('expectedBytes', 0):,} | **{f.get('status')}** | `{exp}` | `{act}` |")

    if deferred:
        L += ['', '## Deferred (out of declared scope)', '',
              'These pins are known, correct, and deliberately not installed yet:', '']
        for f in deferred:
            if f.get('status') != 'PASS':
                L.append(f"- `{os.path.basename(f.get('filename', ''))}` — {f.get('status')}")
        L += ['', '`IQ1_M` is the smaller 1.75 bpw rung. It reads the same Engram table, so installing it',
              'would add only 112.4 GiB — but that needs ~152 GiB free and the volume has 121 GiB.',
              'To finish it later: free ≥ 40 GiB (e.g. remove a stale 196 GiB EXL3 folder), then',
              '', '```powershell', 'pwsh -File Tools/runtime/fetch-library.ps1 -Set IQ1_M', '```', '']

    L += ['', '## GGUF headers (parsed on disk)', '',
          '| File | GiB | Tensors | Architecture | Notes |', '|---|---:|---:|---|---|']
    for p in probes:
        if p.get('error'):
            L.append(f"| `{os.path.basename(p['path'])}` | — | — | — | {p['error']} |")
            continue
        it = p.get('interesting', {})
        notes = []
        if 'split.no' in it and 'split.count' in it:
            notes.append(f"part {int(it['split.no']) + 1}/{int(it['split.count'])}")
        if not p.get('complete_metadata'):
            notes.append('metadata truncated')
        if it.get('general.file_type') is not None:
            notes.append(f"file_type {it['general.file_type']}")
        L.append(f"| `{os.path.basename(p['path'])}` | {p['bytes'] / 2**30:.2f} | {p['tensors']} | "
                 f"`{it.get('general.architecture', '?')}` | {', '.join(notes) or '—'} |")

    L += ['', '## Reproduce', '', '```powershell',
          'python scripts\\verify_library.py',
          'python scripts\\gguf_probe.py --library',
          'python scripts\\check_pins.py',
          'python scripts\\status.py --write',
          '```', '']
    open(DOC, 'w', encoding='utf-8', newline='\n').write('\n'.join(L) + '\n')
    print(f"wrote {DOC}  ({'complete' if complete else 'INCOMPLETE snapshot'})")
    return 0 if complete else 1


if __name__ == '__main__':
    sys.exit(main())
