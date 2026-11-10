#!/usr/bin/env python3
"""Parse a GGUF file's header and metadata locally, without loading the weights.

The security audit proved the twelve AtomicChat shards over HTTP range requests.
This is the local counterpart: it reads the first few MB of a file on disk and
prints what the GGUF itself declares - version, tensor count, and every scalar
metadata key - so the shared Engram table and the vision tower can be checked
against what they claim to be.

    python scripts/gguf_probe.py <file.gguf>
    python scripts/gguf_probe.py --library          # every .gguf in the library
    python scripts/gguf_probe.py --json <file>      # machine-readable

Standard library only. Never executes or trust anything inside the file.
"""
from __future__ import annotations

import argparse
import json
import os
import struct
import sys

GGUF_MAGIC = b"GGUF"

# gguf metadata value types
(U8, I8, U16, I16, U32, I32, F32, BOOL, STRING, ARRAY, U64, I64, F64) = range(13)
SCALARS = {U8: '<B', I8: '<b', U16: '<H', I16: '<h', U32: '<I', I32: '<i',
           F32: '<f', BOOL: '<?', U64: '<Q', I64: '<q', F64: '<d'}


class Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.p = 0

    def take(self, n: int) -> bytes:
        if self.p + n > len(self.d):
            raise EOFError(f"needed {n} bytes at offset {self.p}, only {len(self.d) - self.p} left")
        b = self.d[self.p:self.p + n]
        self.p += n
        return b

    def unpack(self, fmt: str):
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))[0]

    def string(self) -> str:
        n = self.unpack('<Q')
        if n > 64 * 1024 * 1024:
            raise ValueError(f"implausible string length {n}")
        return self.take(n).decode('utf-8', 'replace')

    def value(self, vtype: int):
        if vtype in SCALARS:
            return self.unpack(SCALARS[vtype])
        if vtype == STRING:
            return self.string()
        if vtype == ARRAY:
            itype = self.unpack('<I')
            count = self.unpack('<Q')
            if count > 5_000_000:
                raise ValueError(f"implausible array count {count}")
            # arrays of strings/arrays are the tokenizer; keep a summary, not the payload
            if itype in SCALARS:
                fmt = SCALARS[itype]
                step = struct.calcsize(fmt)
                self.take(step * count)
                return f"<array {count} x scalar {itype}>"
            out = []
            for _ in range(min(count, 3)):
                out.append(self.value(itype))
            for _ in range(count - len(out)):
                self.value(itype)
            return f"<array {count} x {itype}, first={out[:2]}>"
        raise ValueError(f"unknown value type {vtype}")


INTERESTING = {
    'general.architecture', 'general.name', 'general.file_type', 'general.quantization_version',
    'general.size_label', 'general.license', 'general.license.name', 'general.basename',
    'deepseek41.context_length', 'deepseek41.embedding_length', 'deepseek41.block_count',
    'deepseek41.expert_count', 'deepseek41.expert_used_count', 'deepseek41.attention.head_count',
    'llama.context_length', 'llama.embedding_length', 'llama.block_count',
    'split.no', 'split.count', 'split.tensors.count',
    'tokenizer.ggml.model', 'tokenizer.ggml.tokens',
}


def probe(path: str, prefix_mb: int = 64) -> dict:
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        head = f.read(prefix_mb * 1024 * 1024)
    out = {'path': path, 'bytes': size}
    if len(head) < 8 or head[:4] != GGUF_MAGIC:
        out['error'] = 'not a GGUF file (bad magic)'
        return out

    r = Reader(head)
    r.take(4)
    version = r.unpack('<I')
    n_tensors = r.unpack('<Q')
    n_kv = r.unpack('<Q')
    out.update({'gguf_version': version, 'tensors': n_tensors, 'kv_count': n_kv})

    kvs = {}
    truncated_at = None
    for _ in range(n_kv):
        try:
            key = r.string()
            vtype = r.unpack('<I')
            val = r.value(vtype)
        except (EOFError, ValueError) as e:
            truncated_at = str(e)
            break
        if isinstance(val, str) and len(val) > 160:
            val = val[:157] + '...'
        kvs[key] = val

    out['metadata'] = kvs
    out['interesting'] = {k: kvs[k] for k in INTERESTING if k in kvs}
    if truncated_at:
        out['truncated_at'] = truncated_at
        out['complete_metadata'] = False
    else:
        out['complete_metadata'] = True
    return out


def summarize(p: dict) -> str:
    if p.get('error'):
        return f"FAIL  {os.path.basename(p['path'])}: {p['error']}"
    it = p.get('interesting', {})
    arch = it.get('general.architecture') or '?'
    name = it.get('general.name') or ''
    split = ''
    if 'split.no' in it and 'split.count' in it:
        split = f" part {int(it['split.no']) + 1}/{int(it['split.count'])}"
    meta = 'metadata complete' if p.get('complete_metadata') else f"metadata truncated ({p.get('truncated_at')})"
    lines = [
        f"PASS  {os.path.basename(p['path'])}",
        f"      {p['bytes'] / 2**30:8.2f} GiB · GGUF v{p.get('gguf_version')} · "
        f"{p.get('tensors')} tensors · {p.get('kv_count')} metadata keys{split}",
        f"      arch={arch!r} name={name!r}",
    ]
    for k in ('general.file_type', 'general.quantization_version', 'deepseek41.context_length',
              'llama.context_length', 'deepseek41.expert_count', 'deepseek41.expert_used_count',
              'tokenizer.ggml.model', 'split.tensors.count'):
        if k in it:
            lines.append(f"      {k} = {it[k]}")
    lines.append(f"      {meta}")
    return '\n'.join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('files', nargs='*')
    ap.add_argument('--library', action='store_true', help='probe every .gguf in the default library')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--prefix-mb', type=int, default=64)
    args = ap.parse_args()

    targets = list(args.files)
    if args.library:
        lib = os.path.join(os.path.expanduser('~'), 'Models', 'huggingface',
                           'AtomicChat--DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF')
        for root, _dirs, files in os.walk(lib):
            for f in files:
                if f.endswith('.gguf'):
                    targets.append(os.path.join(root, f))
    if not targets:
        ap.error('give at least one .gguf path or --library')

    results = [probe(t, args.prefix_mb) for t in targets]
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            print(summarize(r))
            print()
    bad = [r for r in results if r.get('error')]
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
