#!/usr/bin/env python3
"""Live acquisition status for the DeepSeek-V4.1-Flash-1017 library.

Reads manifests/acceptance.json, measures the library on disk, and prints (or writes)
a status page: what is complete, what is in flight, how much is left, and the last
verification verdict. Nothing is hashed here - use verify_library.py for proof.

    python scripts/status.py                # human table
    python scripts/status.py --json         # machine readable
    python scripts/status.py --write        # refresh STATUS.md at the repo root
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCEPTANCE = os.path.join(ROOT, 'manifests', 'acceptance.json')
LIBRARY = os.path.join(os.path.expanduser('~'), 'Models', 'huggingface',
                       'AtomicChat--DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF')

GROUPS = [
    ('Engram', lambda p: p.endswith('Engram-IQ4_NL.gguf')),
    ('Drafter', lambda p: os.path.basename(p).startswith('dspark-')),
    ('Vision', lambda p: os.path.basename(p) == 'mmproj-BF16.gguf'),
    ('Packer metadata', lambda p: 'UD-Q8_K_XL' in p),
    ('IQ2_XXS', lambda p: 'IQ2_XXS' in p),
    ('IQ1_M', lambda p: 'IQ1_M' in p),
    ('Text', lambda p: p.rsplit('.', 1)[-1] in ('md', 'json', 'gitattributes') or p == 'LICENSE'),
]


def human(n: float) -> str:
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB'):
        if abs(n) < 1024 or unit == 'TiB':
            return f"{n:,.2f} {unit}"
        n /= 1024
    return f"{n} B"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--write', action='store_true')
    ap.add_argument('--library', default=LIBRARY)
    args = ap.parse_args()

    manifest = json.load(open(ACCEPTANCE, encoding='utf-8'))
    files = [f for s in manifest['sources'] for f in s['files']]
    expected = {f['path']: f for f in files}

    present, present_bytes = set(), 0
    for root, _dirs, names in os.walk(args.library):
        if os.sep + '.cache' in root:
            continue
        for n in names:
            p = os.path.join(root, n)
            rel = os.path.relpath(p, args.library).replace('\\', '/')
            if rel in expected:
                present.add(rel)
                present_bytes += os.path.getsize(p)

    total_bytes = sum(f['bytes'] for f in files)
    groups = []
    for label, match in GROUPS:
        members = [f for f in files if match(f['path'])]
        if not members:
            continue
        done = [f for f in members if f['path'] in present]
        gb = sum(f['bytes'] for f in members)
        groups.append({
            'name': label, 'files': len(members), 'done': len(done),
            'bytes': gb, 'done_bytes': sum(f['bytes'] for f in done),
            'state': 'complete' if len(done) == len(members) else ('in flight' if done else 'pending'),
        })

    free = shutil.disk_usage(os.path.splitdrive(args.library)[0] + os.sep).free
    report = {
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'library': args.library,
        'expected_bytes': total_bytes,
        'present_bytes': present_bytes,
        'percent': round(100.0 * present_bytes / total_bytes, 2) if total_bytes else 0.0,
        'files_expected': len(files),
        'files_present': len(present),
        'free_bytes': free,
        'groups': groups,
        'portable': True,
        'runnable_here': False,
        'runnable_here_reason': '6 GiB VRAM against a documented 8 GiB floor (12 measured); 39.4 GiB RAM',
    }

    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    lines = [
        '# Acquisition status',
        '',
        f'Generated {report["generated_at"]} by `scripts/status.py`.',
        '',
        f'**{report["files_present"]}/{report["files_expected"]} files · '
        f'{report["percent"]}% · {human(present_bytes)} of {human(total_bytes)}** · '
        f'free disk {human(free)}',
        '',
        '| Component | Files | Complete | Size | State |',
        '|---|---:|---:|---:|---|',
    ]
    for g in groups:
        lines.append(f'| {g["name"]} | {g["files"]} | {g["done"]}/{g["files"]} | {human(g["bytes"])} | {g["state"]} |')
    lines += [
        '',
        '`runnable_here: false` — 6 GiB VRAM against a documented 8 GiB floor (12 GiB measured),',
        '39.4 GiB RAM. The library is portable: copy it to a machine with a real card, re-run',
        '`scripts/verify_library.py`, then `Tools/runtime/import-verified.ps1`.',
        '',
    ]

    pending = [g for g in groups if g['state'] != 'complete']
    if pending:
        need = sum(g['bytes'] for g in pending)
        lines += [
            f'**Not installed: {pending[0]["name"]} ({human(need)}).** It needs roughly '
            f'{human(need)} free plus 40 GiB headroom; {human(free)} is free now.',
            'To finish it after freeing space: `pwsh -File Tools/runtime/fetch-library.ps1 -Set '
            + pending[0]['name'] + '`',
            '',
        ]

    lines += [
        'Hashes are not evidence of freshness: run `python scripts/verify_library.py` for the',
        'byte-level verdict, and `python scripts/gguf_probe.py --library` for the headers.',
        '',
    ]
    text = '\n'.join(lines)

    if args.write:
        out = os.path.join(ROOT, 'STATUS.md')
        open(out, 'w', encoding='utf-8', newline='\n').write(text + '\n')
        print(f'wrote {out}')
    else:
        print(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())
