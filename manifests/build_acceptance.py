#!/usr/bin/env python3
"""Build manifests/acceptance.json from the Hugging Face API.

The manifest is derived from the Hub, never hand-typed: every size and SHA-256 is
the LFS object id the Hub itself serves. Re-run this any time to detect drift.

    python manifests/build_acceptance.py            # write acceptance.json
    python manifests/build_acceptance.py --check     # exit 1 if the Hub drifted

Dependency-free: Python 3.9+, urllib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# --- pins -------------------------------------------------------------------
# AtomicChat: the abliterated GGUF packaging. Both gate-passing rungs.
# ISTA-DASLab: the base quant + the single shared Engram table every rung reads.
# unsloth: the DSpark drafter, the vision tower and the metadata shard the
#          packer reads (all three are required to pack a Strata model).
PINS = [
    {
        "repo": "AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF",
        "revision": "4f1d2f730cff977961db81789e81bfc0d3e6dd2e",
        "why": "abliterated GSQ-RCO GGUF, refusal direction projected out of the dense residual writers",
        "allow": [r"IQ2_XXS", r"IQ1_M", r"^LICENSE$", r"^README\.md$", r"^\.gitattributes$", r"^cards/"],
        "skip": [r"IQ2_XS"],  # published gate failure (cards/rungs.json pass:false)
    },
    {
        "repo": "ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF",
        "revision": "cb02422c900df489cea5833e8a92171224059b3c",
        "why": "the shared 103 GiB Engram n-gram table; every rung reads this one file",
        "allow": [r"Engram-IQ4_NL"],
        "skip": [],
    },
    {
        "repo": "unsloth/DeepSeek-V4.1-Flash-1017-GGUF",
        "revision": "8a6ec9cf118e785a362ea94ee123c61c70553be6",
        "why": "DSpark drafter, vision tower and the metadata shard the packer's --engram-meta reads",
        "allow": [r"^dspark-DeepSeek-V4\.1-Flash-1017-Q8_0\.gguf$", r"^mmproj-BF16\.gguf$",
                  r"UD-Q8_K_XL-00001-of-00009\.gguf$"],
        "skip": [],
    },
]

# The Hub serves two byte-identical-data Engram variants under the same name: the
# pinned 4-shard-layout header and the later 6-shard-layout header. Strata accepts
# either (setup.py: DSV41_SHA_ALSO). Verification accepts the first hash as primary.
ENG_ALSO = {
    "DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf": [
        "eb19f30d368d393784e1fc54fdfaffc427ebb2110bf3762fdf5a8fbb9a2d740a",
        "3dac4c54893ad7aa89103c0028500eadc78e74112cef3a2930a97e67dc9fb4f3",
    ]
}


def api(path: str):
    url = "https://huggingface.co/api/" + path
    req = urllib.request.Request(url, headers={"User-Agent": "dsh-acceptance-manifest/1"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


def tree(repo: str, rev: str):
    out = []
    entries = api(f"models/{repo}/tree/{rev}?recursive=true")
    for e in entries:
        if e.get("type") != "file":
            continue
        lfs = e.get("lfs") or {}
        out.append({
            "path": e["path"],
            "bytes": int(lfs.get("size") or e.get("size") or 0),
            "sha256": lfs.get("oid"),
            "oid": e.get("oid"),
            "xetHash": e.get("xetHash"),
        })
    return out


def kind_of(path: str) -> str:
    p = path.lower()
    if p.endswith(".gguf"):
        if "engram" in p:
            return "engram"
        if "dspark" in p:
            return "drafter"
        if "mmproj" in p:
            return "vision"
        for q in ("iq1_m", "iq2_xxs", "iq2_xs"):
            if q in p:
                return "weights:" + q
        return "weights"
    return "text"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="compare against the committed manifest")
    ap.add_argument("--out", default=str(HERE / "acceptance.json"))
    args = ap.parse_args()

    sources = []
    for pin in PINS:
        rows = []
        for e in tree(pin["repo"], pin["revision"]):
            skipped = any(re.search(p, e["path"]) for p in pin["skip"])
            allowed = any(re.search(p, e["path"]) for p in pin["allow"])
            if not allowed or skipped:
                continue
            if e["sha256"]:
                row = {"path": e["path"], "bytes": e["bytes"], "sha256": e["sha256"],
                       "kind": kind_of(e["path"]), "required": True}
            else:
                # a text file has no LFS object: the tree oid is the git blob SHA-1
                row = {"path": e["path"], "bytes": e["bytes"], "blob_sha1": e["oid"],
                       "kind": kind_of(e["path"]), "required": True}
            if e.get("xetHash"):
                row["xetHash"] = e["xetHash"]
            alt = ENG_ALSO.get(e["path"])
            if alt:
                row["accepted_sha256_alternates"] = [h for h in alt if h != row["sha256"]]
            rows.append(row)
        rows.sort(key=lambda r: r["path"])
        sources.append({
            "repo": pin["repo"],
            "revision": pin["revision"],
            "why": pin["why"],
            "files": rows,
        })

    manifest = {
        "schema": "dsh.library.acceptance/1",
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generatedBy": "manifests/build_acceptance.py",
        "note": (
            "Every size and SHA-256 here is the Hub's own LFS object id for the pinned revision. "
            "A file that does not match is not accepted: weights are 40 GB blobs, so a silent "
            "corrupt shard is indistinguishable from a working model until it produces garbage."
        ),
        "libraryLayout": "flat, original filenames, Engram and drafter beside the shards",
        "excludedOnPurpose": {
            "DeepSeek-V4.1-Flash-1017-GSQ-RCO-IQ2_XS-0000N-of-00004.gguf": (
                "the 2.25 bpw rung is published with pass:false in cards/rungs.json "
                "(think_high 2/30, xstest 0.4%) and costs another 145 GiB"
            )
        },
        "sources": sources,
    }

    text = json.dumps(manifest, indent=2) + "\n"
    out = Path(args.out)

    if args.check:
        if not out.exists():
            print(f"FAIL: {out} does not exist")
            return 1
        old = json.loads(out.read_text(encoding="utf-8"))
        old_map = {(s["repo"], f["path"]): (f["bytes"], f["sha256"])
                   for s in old["sources"] for f in s["files"]}
        new_map = {(s["repo"], f["path"]): (f["bytes"], f["sha256"])
                   for s in sources for f in s["files"]}
        drift = [k for k in sorted(set(old_map) | set(new_map)) if old_map.get(k) != new_map.get(k)]
        if drift:
            print("FAIL: Hub drift detected on the pinned revisions:")
            for k in drift:
                print("  ", k, "old=", old_map.get(k), "new=", new_map.get(k))
            return 1
        print(f"OK: {len(new_map)} files match the committed manifest")
        return 0

    out.write_text(text, encoding="utf-8")
    total = sum(f["bytes"] for s in sources for f in s["files"])
    print(f"wrote {out}  ({sum(len(s['files']) for s in sources)} files, {total/2**30:.1f} GiB)")
    for s in sources:
        b = sum(f["bytes"] for f in s["files"])
        print(f"  {s['repo'].split('/')[-1]:52s} {len(s['files']):2d} files  {b/2**30:8.1f} GiB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
