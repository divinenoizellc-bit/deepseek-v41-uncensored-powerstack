#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_library.py - stream-verify the local DeepSeek-V4.1-Flash library
against an accepted-pin manifest.

Reads (read-only) `manifests/acceptance.json` by default; any manifest shape
can be supplied with --manifest (it also understands the sec-auditor's
`manifests/repo.json`).  Streams SHA-256 over the local library in 8 MiB
chunks, so a 40 GB shard never lands in memory.

Status per file
  PASS        size matches and the manifest sha256 matches (or git-blob sha1
              for non-LFS text artifacts)
  PASS-SIZE   size matches and the manifest carries no hash
  INCOMPLETE  final file absent; a .part/.incomplete blob or a download lock
              is present (bytes downloaded are reported)
  MISSING     final file absent and nothing in progress
  FAIL        final file present but size or hash does not match

Exit codes
  0  every manifest file present and matching
  1  at least one FAIL (corrupt / wrong bytes)
  2  no FAIL but at least one INCOMPLETE or MISSING

Writes a JSON report to Library/logs (my write scope) and the latest copy to
Library/logs/verify-library-latest.json; never writes into the library dir.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

# --------------------------------------------------------------------------
# Paths / constants (edit only if the layout moves)
# --------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
LOG_DIR = os.path.join(PROJECT, "Library", "logs")
MANIFESTS = os.path.join(PROJECT, "manifests")
ACCEPTANCE = os.path.join(MANIFESTS, "acceptance.json")
REPO_JSON = os.path.join(MANIFESTS, "repo.json")

LIBRARY_ROOT = os.environ.get("HF_LIBRARY_ROOT") or r"C:\Users\psand\Models\huggingface"
DEFAULT_LIBRARY = os.path.join(
    LIBRARY_ROOT, "AtomicChat--DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF"
)

GIB = 1 << 30
MIB = 1 << 20
CHUNK = 8 * MIB
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
SHARD_RE = re.compile(
    r"(?P<base>.+?)-(?P<rung>IQ1_M|IQ2_XS|IQ2_XXS)-(?P<idx>\d{5})-of-(?P<n>\d{5})\.gguf$",
    re.I,
)

STATUS_RANK = {"FAIL": 3, "MISSING": 2, "INCOMPLETE": 2, "PASS-SIZE": 1, "PASS": 0}


# --------------------------------------------------------------------------
# Generic helpers
# --------------------------------------------------------------------------

def lp(path):
    p = os.path.abspath(str(path))
    if os.name != "nt" or p.startswith("\\\\?\\"):
        return p
    if len(p) < 240:
        return p
    if p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p


def ensure_dir(path):
    if path:
        os.makedirs(lp(path), exist_ok=True)


def human(n):
    n = float(n or 0)
    if n >= GIB:
        return "%.2f GiB" % (n / GIB)
    if n >= MIB:
        return "%.1f MiB" % (n / MIB)
    if n >= 1024:
        return "%.1f KiB" % (n / 1024.0)
    return "%d B" % int(n)


def human_bytes(n):
    return human(n)


def fmt_dur(sec):
    sec = int(max(0, sec or 0))
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m, s = divmod(r, 60)
    if d:
        return "%dd%02dh" % (d, h)
    if h:
        return "%dh%02dm" % (h, m)
    if m:
        return "%dm%02ds" % (m, s)
    return "%ds" % s


def iso_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def file_size(path):
    try:
        return os.path.getsize(lp(path))
    except OSError:
        return -1


def sha256_file(path):
    h = hashlib.sha256()
    n = 0
    with open(lp(path), "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
            n += len(b)
    return h.hexdigest(), n


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def git_blob_sha1(path):
    """Git blob id == sha1(b"blob %d\\0" + content). Matches tree-entry git_oid."""
    size = file_size(path)
    h = hashlib.sha1()
    h.update(b"blob %d\x00" % size)
    with open(lp(path), "rb") as f:
        while True:
            b = f.read(CHUNK)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# --------------------------------------------------------------------------
# Manifest loading (tolerant: acceptance.json or repo.json shapes)
# --------------------------------------------------------------------------

class ManifestError(Exception):
    pass


def _first(d, keys, default=None):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, "", []):
            return d[k]
    return default


def _norm_hash(value):
    """Return (sha256, blob_sha1) from a hash-ish string."""
    if not isinstance(value, str):
        return None, None
    v = value.strip().strip('"').lower()
    if SHA256_RE.match(v):
        return v, None
    if SHA1_RE.match(v):
        return None, v
    return None, None


def _norm_entry(raw, defaults):
    if not isinstance(raw, dict):
        return None
    filename = _first(raw, ("path", "filename", "file", "name", "local", "localPath"))
    if isinstance(filename, dict):
        return None
    if not isinstance(filename, str) or not filename.strip():
        return None
    filename = filename.strip().replace("\\", "/")

    size = _first(raw, ("bytes", "size", "byte_size", "length"))
    try:
        size = int(size) if size is not None else None
    except (TypeError, ValueError):
        size = None

    sha256 = blob = None
    for key in ("sha256", "sha256sum", "lfs_oid", "oid", "hash", "sha", "blob_sha1",
                "git_oid", "git_blob_sha1", "blob"):
        if raw.get(key):
            a, b = _norm_hash(raw.get(key))
            if a and not sha256:
                sha256 = a
            if b and not blob:
                blob = b
    # explicit blob field wins over an ambiguous sha1 in sha256
    if raw.get("blob_sha1"):
        _, blob = _norm_hash(raw.get("blob_sha1"))
    if raw.get("git_oid"):
        _, blob2 = _norm_hash(raw.get("git_oid"))
        blob = blob or blob2

    alts = []
    for alt in (raw.get("accepted_sha256_alternates") or []):
        a, _b = _norm_hash(alt)
        if a:
            alts.append(a)

    repo = _first(raw, ("repo", "repo_id", "repository", "source_repo")) or defaults.get("repo")
    if isinstance(repo, dict):
        repo = repo.get("id")
    rev = _first(raw, ("revision", "rev", "commit", "pinned_revision")) or defaults.get("revision")
    if isinstance(rev, dict):
        rev = rev.get("sha")

    kind = _first(raw, ("kind", "role", "type")) or ""
    required = raw.get("required", True)

    return {
        "filename": filename,
        "basename": filename.rsplit("/", 1)[-1],
        "bytes": size,
        "sha256": sha256,
        "sha256_alternates": alts,
        "blob_sha1": blob,
        "repo": repo or "?",
        "revision": (rev or "?"),
        "kind": kind,
        "required": bool(required) if required is not None else True,
        "raw_keys": sorted(raw.keys()),
    }


def _collect_entries(obj, defaults, out, depth=0):
    if depth > 6 or out is None:
        return
    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict):
                if isinstance(item.get("files"), list) and not _first(
                        item, ("path", "filename", "file", "name")):
                    local_def = dict(defaults)
                    local_def["repo"] = _first(item, ("repo", "repo_id", "id")) or defaults.get("repo")
                    local_def["revision"] = _first(item, ("revision", "rev", "sha")) or defaults.get("revision")
                    _collect_entries(item["files"], local_def, out, depth + 1)
                else:
                    e = _norm_entry(item, defaults)
                    if e:
                        out.append(e)
        return
    if isinstance(obj, dict):
        handled = False
        if isinstance(obj.get("files"), list):
            _collect_entries(obj["files"], defaults, out, depth + 1)
            handled = True
        if isinstance(obj.get("external_dependencies"), list):
            _collect_entries(obj["external_dependencies"], defaults, out, depth + 1)
            handled = True
        if handled:
            return
        for key in ("accept", "accepted", "items", "entries", "artifacts", "sources",
                    "models", "downloads", "objects"):
            if isinstance(obj.get(key), list):
                _collect_entries(obj[key], defaults, out, depth + 1)
                return
        # mapping filename -> spec
        looks_like_map = all(isinstance(v, (dict, int)) for v in obj.values()) and obj
        if looks_like_map:
            for name, spec in obj.items():
                if isinstance(spec, int):
                    out.append({"filename": name, "basename": name.rsplit("/", 1)[-1],
                                "bytes": spec, "sha256": None, "blob_sha1": None,
                                "repo": defaults.get("repo"), "revision": defaults.get("revision"),
                                "kind": "", "required": True, "raw_keys": []})
                elif isinstance(spec, dict):
                    merged = dict(spec)
                    merged.setdefault("filename", name)
                    e = _norm_entry(merged, defaults)
                    if e:
                        out.append(e)


def load_manifest(path):
    """Load and normalize a pin manifest. Returns dict with files/sets/meta."""
    path = os.path.abspath(path)
    if not os.path.exists(lp(path)):
        raise ManifestError(
            "manifest not found: %s\n"
            "  expected the Lead's acceptance.json (repo, revision, filename, bytes, sha256).\n"
            "  You can point at the audit manifest instead: --manifest manifests/repo.json" % path)
    with open(lp(path), "rb") as f:
        raw_bytes = f.read()
    try:
        obj = json.loads(raw_bytes.decode("utf-8"))
    except Exception as e:
        raise ManifestError("manifest is not valid JSON: %s (%s)" % (path, e))

    defaults = {"repo": None, "revision": None}
    sets_declared = {}
    if isinstance(obj, dict):
        repo = obj.get("repo")
        if isinstance(repo, dict):
            repo = repo.get("id")
        defaults["repo"] = repo if isinstance(repo, str) else None
        rev = _first(obj, ("pinned_revision", "revision", "rev"))
        defaults["revision"] = rev if isinstance(rev, str) else None
        if isinstance(obj.get("model"), dict):
            defaults["repo"] = defaults["repo"] or obj["model"].get("repo")
            defaults["revision"] = defaults["revision"] or obj["model"].get("revision")
        if isinstance(obj.get("repositories"), list):
            for r in obj["repositories"]:
                if isinstance(r, dict) and r.get("repo"):
                    defaults["repo"] = defaults["repo"] or r.get("repo")
                    defaults["revision"] = defaults["revision"] or r.get("revision")
        if isinstance(obj.get("sets"), dict):
            for name, spec in obj["sets"].items():
                if isinstance(spec, dict):
                    sets_declared[name.upper()] = {
                        "count": int(spec.get("count") or len(spec.get("shards") or []) or 0),
                        "bytes": spec.get("bytes"),
                        "shards": [s for s in (spec.get("shards") or []) if isinstance(s, str)],
                    }

    entries = []
    _collect_entries(obj, defaults, entries)

    # dedupe by (repo, filename) preserving order
    seen = set()
    files = []
    for e in entries:
        key = (str(e["repo"]).lower(), e["filename"].lower())
        if key in seen:
            continue
        seen.add(key)
        files.append(e)
    if not files:
        raise ManifestError("no file entries found in %s" % path)

    # derive/merge set groups from filenames
    sets = {}
    for name, spec in sets_declared.items():
        sets[name] = {"count": spec["count"], "shards": list(spec["shards"]),
                      "declared": True}
    for e in files:
        m = SHARD_RE.search(e["basename"])
        if not m:
            continue
        name = m.group("rung").upper()
        n = int(m.group("n"))
        s = sets.setdefault(name, {"count": 0, "shards": [], "declared": False})
        s["count"] = max(s["count"], n)
        if e["basename"] not in s["shards"]:
            s["shards"].append(e["basename"])

    expected = sum((e["bytes"] or 0) for e in files)
    return {
        "path": path,
        "sha256": sha256_bytes(raw_bytes),
        "loadedAt": iso_now(),
        "files": files,
        "sets": sets,
        "defaults": defaults,
        "expectedBytes": expected,
        "raw": obj,
    }


# --------------------------------------------------------------------------
# Library scan / locate
# --------------------------------------------------------------------------

def scan_library(root):
    finals = {}
    by_base = {}
    partials = []
    locks = {}
    metadata = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            p = os.path.join(dirpath, fn)
            rel = os.path.relpath(p, root)
            low = fn.lower()
            try:
                sz = os.path.getsize(p)
            except OSError:
                sz = -1
            if low.endswith(".incomplete") or low.endswith(".part"):
                partials.append({"rel": rel, "size": sz, "name": low})
                continue
            if low.endswith(".lock"):
                locks[low[:-5]] = rel
                continue
            if low.endswith(".metadata"):
                metadata.append({"rel": rel, "size": sz})
                continue
            if rel.split(os.sep)[0].lower() == ".cache":
                continue
            finals[rel] = sz
            by_base.setdefault(low, []).append((rel, sz))
    return {"root": root, "finals": finals, "by_base": by_base,
            "partials": partials, "locks": locks, "metadata": metadata}


def locate(entry, scan):
    """Find a manifest entry on disk. Returns (status, relpath, bytes, note)."""
    base = entry["basename"].lower()
    want_rel = entry["filename"].replace("/", os.sep).lower()
    want_flat = entry["basename"].lower()

    # exact manifest path, then flat original filename at the library root
    for rel, sz in scan["finals"].items():
        if rel.lower() == want_rel:
            return "FINAL", rel, max(0, sz), ""
    for rel, sz in scan["finals"].items():
        if rel.lower() == want_flat:
            return "FINAL", rel, max(0, sz), ""

    # same basename anywhere (hf keeps UD-Q8_K_XL/ subdir)
    cands = scan["by_base"].get(base) or []
    if cands:
        rel, sz = sorted(cands, key=lambda t: (t[0].count(os.sep), len(t[0])))[0]
        return "FINAL", rel, max(0, sz), ""

    # in-progress blob: hf-xet names it with the sha256, older .part keeps name
    sha = entry.get("sha256") or ""
    for p in scan["partials"]:
        if sha and sha[:32] in p["name"]:
            return "INCOMPLETE", p["rel"], max(0, p["size"]), "partial (sha256 named)"
    for p in scan["partials"]:
        if base in p["name"]:
            return "INCOMPLETE", p["rel"], max(0, p["size"]), "partial"

    if base in scan["locks"]:
        return "INCOMPLETE", None, 0, "download lock present"
    return "MISSING", None, 0, ""


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

def verify_file(entry, scan, quick=False, progress=True):
    t0 = time.time()
    status, rel, present, note = locate(entry, scan)
    res = {
        "filename": entry["filename"], "basename": entry["basename"],
        "repo": entry["repo"], "revision": entry["revision"],
        "expectedBytes": entry["bytes"], "expectedSha256": entry["sha256"],
        "expectedBlobSha1": entry["blob_sha1"],
        "localPath": (os.path.join(scan["root"], rel) if rel else None),
        "localRelPath": rel, "presentBytes": present,
        "actualSha256": None, "actualBlobSha1": None,
        "status": None, "note": note, "seconds": 0.0, "mbps": None,
    }
    if status in ("MISSING", "INCOMPLETE"):
        res["status"] = status
        res["seconds"] = round(time.time() - t0, 2)
        return res

    final_path = os.path.join(scan["root"], rel)
    if entry["bytes"] is not None and present != entry["bytes"]:
        res["status"] = "FAIL"
        res["note"] = "size %d != expected %d" % (present, entry["bytes"])
        res["seconds"] = round(time.time() - t0, 2)
        return res

    if quick or (not entry["sha256"] and not entry["blob_sha1"]):
        res["status"] = "PASS-SIZE"
        if quick:
            res["note"] = "size-only (--quick)"
        else:
            res["note"] = "manifest carries no hash"
        res["seconds"] = round(time.time() - t0, 2)
        return res

    last = [time.time()]

    def tick(done, total, _name=entry["basename"]):
        now = time.time()
        if now - last[0] >= 10:
            last[0] = now
            rate = done / 1e6 / max(0.001, now - t0)
            sys.stdout.write("  hashing %-58s %8.2f/%-8.2f GiB %8.1f MB/s\r" % (
                _name[:58], done / GIB, total / GIB, rate))
            sys.stdout.flush()

    if entry["sha256"]:
        if progress and (entry["bytes"] or 0) > GIB:
            h = hashlib.sha256()
            done = 0
            with open(lp(final_path), "rb") as f:
                while True:
                    b = f.read(CHUNK)
                    if not b:
                        break
                    h.update(b)
                    done += len(b)
                    if time.time() - last[0] >= 10:
                        tick(done, entry["bytes"])
            actual = h.hexdigest()
            if progress and (entry["bytes"] or 0) > GIB:
                sys.stdout.write(" " * 118 + "\r")
        else:
            actual, _ = sha256_file(final_path)
        res["actualSha256"] = actual
        ok = actual.lower() == entry["sha256"].lower()
        if not ok and entry.get("sha256_alternates"):
            ok = actual.lower() in entry["sha256_alternates"]
            if ok:
                res["note"] = "matched accepted alternate sha256"
        res["status"] = "PASS" if ok else "FAIL"
        if not ok:
            res["note"] = "sha256 mismatch"
    else:
        actual = git_blob_sha1(final_path)
        res["actualBlobSha1"] = actual
        ok = actual.lower() == (entry["blob_sha1"] or "").lower()
        res["status"] = "PASS" if ok else "FAIL"
        if not ok:
            res["note"] = "git blob sha1 mismatch"
        else:
            res["note"] = "git blob sha1"

    secs = time.time() - t0
    res["seconds"] = round(secs, 2)
    sz = entry["bytes"] or present or 0
    res["mbps"] = round(sz / 1e6 / secs, 1) if secs > 0.05 and sz else None
    return res


def group_of(entry):
    b = entry["basename"]
    low = b.lower()
    if "engram" in low:
        return "Engram", "engram"
    if "dspark" in low or "drafter" in low:
        return "drafter", "drafter"
    if low.startswith("mmproj"):
        return "mmproj", "mmproj"
    if "ud-q8_k_xl" in low or "ud_q8_k_xl" in low:
        return "metaShard", "meta"
    m = SHARD_RE.search(b)
    if m:
        return m.group("rung").upper(), "set"
    if not low.endswith(".gguf"):
        return "text", "text"
    return "other", "other"


def summarize_sets(manifest, entries, results, use_declared=True):
    groups = {}
    for entry in entries:
        name, kind = group_of(entry)
        g = groups.setdefault(name, {"kind": kind, "files": [], "expectedCount": 0,
                                     "bytesExpected": 0, "bytesPresent": 0,
                                     "verified": 0, "present": 0, "status": "PASS"})
        g["files"].append(entry["basename"])
        g["expectedCount"] += 1
        g["bytesExpected"] += entry["bytes"] or 0

    by_base = {r["basename"].lower(): r for r in results}
    for name, g in groups.items():
        worst = "PASS"
        for base in g["files"]:
            r = by_base.get(base.lower())
            if not r:
                continue
            g["bytesPresent"] += r.get("presentBytes") or 0
            if r["status"] in ("PASS", "PASS-SIZE"):
                g["present"] += 1
                g["verified"] += 1
            elif r["status"] == "FAIL":
                worst = "FAIL"
            elif r["status"] in ("MISSING", "INCOMPLETE") and worst != "FAIL":
                worst = "INCOMPLETE"
        g["status"] = worst
        # declared shard count from the manifest sets block, if any
        decl = manifest["sets"].get(name.upper())
        if use_declared and decl and decl.get("count"):
            g["expectedCount"] = max(g["expectedCount"], decl["count"])
        g["verdict"] = ("PASS" if worst == "PASS" and g["present"] == g["expectedCount"]
                        else ("FAIL" if worst == "FAIL" else "INCOMPLETE"))
    return groups


def verify(manifest_path, library_dir, only=None, quick=False, progress=True,
           write_report=True, jobs=1):
    manifest = load_manifest(manifest_path)
    scan = scan_library(library_dir)
    entries = manifest["files"]
    if only:
        rx = re.compile(only, re.I)
        entries = [e for e in entries if rx.search(e["filename"])]

    if progress:
        print("== verify library ==")
        print("library : %s" % library_dir)
        print("manifest: %s" % manifest["path"])
        print("          sha256 %s  %d files  %s expected" % (
            manifest["sha256"][:16], len(manifest["files"]),
            human_bytes(manifest["expectedBytes"])))
        print("scan    : %d complete files, %d partial, %d locks" % (
            len(scan["finals"]), len(scan["partials"]), len(scan["locks"])))
        print("")

    results = []
    if jobs and jobs > 1 and len(entries) > 1:
        with ThreadPoolExecutor(max_workers=min(jobs, 8)) as ex:
            futs = {ex.submit(verify_file, e, scan, quick, False): e for e in entries}
            for fut in as_completed(futs):
                results.append(fut.result())
        order = {e["filename"]: i for i, e in enumerate(entries)}
        results.sort(key=lambda r: order.get(r["filename"], 999))
    else:
        for e in entries:
            results.append(verify_file(e, scan, quick=quick, progress=progress))

    if progress:
        print("%-11s %-58s %9s  %-17s %-7s %8s" % (
            "status", "file", "GiB", "sha256(prefix)", "secs", "MB/s"))
        for r in results:
            print("[%-9s] %-58s %9.2f  %-17s %-7.1f %8s" % (
                r["status"], r["basename"][:58], (r["presentBytes"] or 0) / GIB,
                (r["actualSha256"] or r["actualBlobSha1"] or r["expectedSha256"]
                 or r["expectedBlobSha1"] or "-")[:16],
                r["seconds"], r["mbps"] if r["mbps"] is not None else "-"))
            if r["status"] == "FAIL":
                print("             expected %s" % (r["expectedSha256"]
                                                     or r["expectedBlobSha1"]))
                print("             actual   %s" % (r["actualSha256"]
                                                     or r["actualBlobSha1"]))
            if r["note"] and r["status"] not in ("PASS",):
                print("             note: %s" % r["note"])

    groups = summarize_sets(manifest, entries, results, use_declared=not only)

    counts = {"PASS": 0, "PASS-SIZE": 0, "FAIL": 0, "INCOMPLETE": 0, "MISSING": 0}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    present_bytes = sum((r["presentBytes"] or 0) for r in results)
    verified_bytes = sum((r["presentBytes"] or 0) for r in results
                         if r["status"] in ("PASS", "PASS-SIZE"))
    if counts["FAIL"]:
        verdict = "fail"
    elif counts["INCOMPLETE"] or counts["MISSING"] or counts["PASS-SIZE"]:
        verdict = "incomplete" if (counts["INCOMPLETE"] or counts["MISSING"]) else "pass"
    else:
        verdict = "pass"

    missing = [r for r in results if r["status"] in ("MISSING", "INCOMPLETE")]
    if progress:
        print("")
        if missing:
            print("still missing / in progress:")
            for r in missing:
                print("  - %-56s %s" % (r["basename"][:56],
                                        "%s, %s present" % (r["status"],
                                                            human_bytes(r["presentBytes"]))
                                        if r["presentBytes"] else r["status"]))
        print("")
        print("per set:")
        print("  %-10s %-11s %6s  %12s  %12s  %s" % (
            "set", "kind", "files", "expected GiB", "present GiB", "verdict"))
        for name in sorted(groups, key=lambda n: (groups[n]["kind"] != "set", n)):
            g = groups[name]
            print("  %-10s %-11s %3d/%-3d %12.2f  %12.2f  %s" % (
                name, g["kind"], g["present"], g["expectedCount"],
                g["bytesExpected"] / GIB, g["bytesPresent"] / GIB, g["verdict"]))
        print("")
        print("summary: PASS %d (%d size-only), FAIL %d, INCOMPLETE %d, MISSING %d" % (
            counts["PASS"], counts["PASS-SIZE"], counts["FAIL"],
            counts["INCOMPLETE"], counts["MISSING"]))
        print("         present %s / expected %s, %s verified -> %s" % (
            human_bytes(present_bytes), human_bytes(manifest["expectedBytes"]),
            human_bytes(verified_bytes), verdict.upper()))

    unexpected = []
    known = set()
    for e in manifest["files"]:
        known.add(e["basename"].lower())
        known.add(e["filename"].replace("/", os.sep).lower())
    for rel, sz in scan["finals"].items():
        base = os.path.basename(rel).lower()
        if base in known or rel.lower() in known:
            continue
        if base.endswith(".gguf"):
            unexpected.append({"relPath": rel, "bytes": sz})

    report = {
        "schema": "dsh.library.verify/1",
        "generatedAt": iso_now(),
        "generatedBy": "scripts/verify_library.py",
        "libraryDir": library_dir,
        "manifest": manifest["path"],
        "manifestSha256": manifest["sha256"],
        "quick": bool(quick),
        "only": only,
        "verdict": verdict,
        "totals": {
            "filesExpected": len(manifest["files"]),
            "filesChecked": len(results),
            "bytesExpected": manifest["expectedBytes"],
            "bytesPresent": present_bytes,
            "bytesVerified": verified_bytes,
            "pass": counts["PASS"], "passSizeOnly": counts["PASS-SIZE"],
            "fail": counts["FAIL"], "incomplete": counts["INCOMPLETE"],
            "missing": counts["MISSING"],
        },
        "files": results,
        "sets": groups,
        "unexpected": unexpected,
        "scan": {"completeFiles": len(scan["finals"]),
                 "partials": [{"rel": p["rel"], "bytes": p["size"]}
                              for p in scan["partials"]],
                 "locks": sorted(scan["locks"].keys())},
    }
    if write_report:
        ensure_dir(LOG_DIR)
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        path = os.path.join(LOG_DIR, "verify-library-%s.json" % ts)
        with open(lp(path), "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        latest = os.path.join(LOG_DIR, "verify-library-latest.json")
        tmp = latest + ".tmp"
        with open(lp(tmp), "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(lp(tmp), lp(latest))
        report["_reportPath"] = path
        report["_latestPath"] = latest

    exit_code = 0
    if counts["FAIL"]:
        exit_code = 1
    elif counts["INCOMPLETE"] or counts["MISSING"]:
        exit_code = 2
    return report, exit_code


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def default_manifest():
    if os.path.exists(lp(ACCEPTANCE)):
        return ACCEPTANCE, None
    if os.path.exists(lp(REPO_JSON)):
        return REPO_JSON, ("acceptance.json not found; falling back to the audit "
                           "manifest manifests/repo.json (AtomicChat + Engram only)")
    return ACCEPTANCE, None


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Stream-verify the local DeepSeek-V4.1-Flash GGUF library "
                    "against accepted pins.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="exit: 0 all present+verified, 1 hash/size FAIL, 2 INCOMPLETE/MISSING")
    p.add_argument("--manifest", default=None,
                   help="pin manifest (default manifests/acceptance.json, "
                        "falls back to manifests/repo.json)")
    p.add_argument("--dir", default=None, help="library dir (default %s)" % DEFAULT_LIBRARY)
    p.add_argument("--only", default=None, help="regex filter on filename")
    p.add_argument("--quick", action="store_true", help="size-only, skip hashing")
    p.add_argument("--jobs", type=int, default=1, help="parallel hash jobs (default 1)")
    p.add_argument("--no-progress", action="store_true", help="suppress the table")
    p.add_argument("--no-report", action="store_true", help="do not write a JSON report")
    args = p.parse_args(argv)

    manifest = args.manifest
    fallback_note = None
    if not manifest:
        manifest, fallback_note = default_manifest()
    if fallback_note:
        print("NOTE: %s" % fallback_note)
        print("")
    library = args.dir or DEFAULT_LIBRARY

    try:
        report, code = verify(manifest, library, only=args.only, quick=args.quick,
                              progress=not args.no_progress, write_report=not args.no_report,
                              jobs=args.jobs)
    except ManifestError as e:
        print("ERROR: %s" % e)
        return 2
    if not args.no_progress:
        print("")
        print("report: %s" % report.get("_reportPath", "(not written)"))
    return code


if __name__ == "__main__":
    sys.exit(main())
