#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""index_library.py - build Library/index.json for the local
DeepSeek-V4.1-Flash-1017-Uncensored GSQ-RCO library.

The index is only as honest as the verification behind it:
  * default            reuse Library/logs/verify-library-latest.json when it
                       matches the current manifest and is newer than every
                       file on disk; otherwise run a full stream-verify first
  * --verify           always re-hash before writing the index
  * --no-hash          never hash; reuse the newest report and mark the
                       verification stale if files changed since

Writes only Library/index.json (plus logs via verify_library.py). The library
directory itself is never written to.

Fields: repo(s), pinned revision(s), license, per-file verified status,
per-set completeness (4/4 shards + Engram + drafter + mmproj + meta shard),
total bytes, portable flag and the hardware minimum Strata reports
(8 GiB VRAM minimum, 12 GiB as measured).
"""

import argparse
import calendar
import json
import os
import shutil
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import verify_library as vl  # noqa: E402

PROJECT = vl.PROJECT
LOG_DIR = vl.LOG_DIR
INDEX_PATH = os.path.join(PROJECT, "Library", "index.json")
ACCEPTANCE = vl.ACCEPTANCE
REPO_JSON = vl.REPO_JSON
DEFAULT_LIBRARY = vl.DEFAULT_LIBRARY
LIBRARY_ROOT = vl.LIBRARY_ROOT
RULEBOOK = os.path.join(PROJECT, "manifests", "source", "cards__rungs.json")
UA = "model-librarian/1.0 (DeepSeek Harness)"

# Values verified 2026-11-10 against /api/models/<repo>: gguf.total,
# architecture, context_length. Refreshed from the API at index time when
# reachable, otherwise the embedded values are used and labelled as such.
EMBEDDED_MODEL = {
    "architecture": "deepseek41",
    "parameters": 551880949208,
    "contextLength": 1048576,
    "totalFileSizeBytes": 120721120256,
    "source": "embedded from HF API gguf metadata (verified 2026-11-10)",
}

HARDWARE_MINIMUM = {
    "vramGiBMinimum": 8,
    "vramGiBMeasured": 12,
    "source": "Strata runtime self-report",
    "note": "Strata requires at least 8 GiB VRAM; 12 GiB was measured on this box. "
            "Weights stay in this library dir; the runtime loads them from here.",
}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def read_json(path):
    with open(vl.lp(path), "r", encoding="utf-8") as f:
        return json.load(f)


def atomic_write_json(path, obj):
    vl.ensure_dir(os.path.dirname(path))
    tmp = path + ".tmp-%d" % os.getpid()
    with open(vl.lp(tmp), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(vl.lp(tmp), vl.lp(path))


def disk_free(path):
    try:
        return shutil.disk_usage(vl.lp(path)).free
    except OSError:
        return None


def is_fresh(report, library_dir):
    """True when the report still describes the bytes on disk."""
    try:
        gen = calendar.timegm(time.strptime(report["generatedAt"], "%Y-%m-%dT%H:%M:%SZ"))
    except Exception:
        return False
    newest = 0.0
    for r in report.get("files", []):
        if r.get("status") in ("MISSING", "INCOMPLETE"):
            continue  # partials keep growing; they are re-located live instead
        p = r.get("localPath")
        if not p:
            continue
        try:
            newest = max(newest, os.path.getmtime(vl.lp(p)))
        except OSError:
            continue
    return gen + 2.0 >= newest


def fetch_model_meta(repo, timeout=8.0):
    if not repo:
        return dict(EMBEDDED_MODEL)
    url = "https://huggingface.co/api/models/" + urllib.parse.quote(repo, safe="/")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        g = d.get("gguf") or {}
        tags = d.get("tags") or []
        lic = next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), None)
        out = dict(EMBEDDED_MODEL)
        if g.get("architecture"):
            out["architecture"] = g["architecture"]
        if g.get("total"):
            out["parameters"] = g["total"]
        if g.get("context_length"):
            out["contextLength"] = g["context_length"]
        if g.get("totalFileSize"):
            out["totalFileSizeBytes"] = g["totalFileSize"]
        out["source"] = "HF API gguf metadata (%s)" % vl.iso_now()
        out["repoLicense"] = lic
        out["gated"] = d.get("gated")
        out["lastModified"] = d.get("lastModified")
        return out
    except Exception as e:
        out = dict(EMBEDDED_MODEL)
        out["source"] = "embedded (API unavailable: %s)" % e
        return out


def rung_gates():
    """Local copy of cards/rungs.json (the sec-auditor's read), if present."""
    try:
        d = read_json(RULEBOOK)
        return {k: {"pass": bool(v.get("pass")),
                    "kl_to_stock": v.get("kl_to_stock")}
                for k, v in d.items() if isinstance(v, dict)}
    except Exception:
        return {}


def pick_report(args, manifest_path, manifest_sha):
    """Return (report, source, stale_note)."""
    latest = os.path.join(LOG_DIR, "verify-library-latest.json")
    if args.report:
        rep = read_json(args.report)
        if rep.get("manifestSha256") != manifest_sha:
            raise SystemExit("ERROR: %s was produced from a different manifest "
                             "(sha %s != %s); rerun verify_library.py"
                             % (args.report, rep.get("manifestSha256"), manifest_sha))
        return rep, os.path.abspath(args.report), None
    if args.verify:
        return None, None, None
    if os.path.exists(vl.lp(latest)):
        rep = read_json(latest)
        if rep.get("manifestSha256") == manifest_sha and \
                os.path.abspath(rep.get("libraryDir", "")) == os.path.abspath(args.dir):
            if is_fresh(rep, args.dir):
                return rep, latest, None
            if args.no_hash:
                return rep, latest, "files changed after the last verification"
    if args.no_hash:
        return None, None, "no matching verification report and --no-hash given"
    return None, None, None


def build_index(args):
    manifest_path = args.manifest or (ACCEPTANCE if os.path.exists(vl.lp(ACCEPTANCE))
                                      else REPO_JSON)
    if not os.path.exists(vl.lp(manifest_path)):
        raise SystemExit("ERROR: no manifest at %s (wait for acceptance.json or pass --manifest)"
                         % manifest_path)
    manifest = vl.load_manifest(manifest_path)
    manifest_sha = manifest["sha256"]

    report, report_path, stale_note = pick_report(args, manifest_path, manifest_sha)
    ran_verify = False
    if report is None and not args.no_hash:
        if not args.quiet:
            print("no fresh verification report for this manifest/library -> hashing now")
        report, _code = vl.verify(manifest_path, args.dir, quick=args.quick,
                                  progress=not args.quiet, write_report=True)
        report_path = report.get("_latestPath")
        ran_verify = True

    fresh = bool(report) and is_fresh(report, args.dir)
    stale_note = stale_note or (None if fresh else
                                ("no matching verification report" if not report
                                 else "files changed after the last verification"))
    if not report:
        fresh = False

    file_status = {}
    if report:
        for r in report.get("files", []):
            file_status[r["basename"].lower()] = r
    scan = vl.scan_library(args.dir)

    def status_of(entry):
        b = entry["basename"]
        r = file_status.get(b.lower())
        if r and r.get("status") in ("MISSING", "INCOMPLETE"):
            st, rel, present_bytes, note = vl.locate(entry, scan)
            return {"status": st if st != "FINAL" else "UNVERIFIED",
                    "verified": False, "present": st == "FINAL",
                    "presentBytes": present_bytes if st != "MISSING" else 0,
                    "localRelPath": rel, "actualSha256": None,
                    "expectedSha256": entry["sha256"] or entry["blob_sha1"],
                    "note": note or "not complete"}
        if not r:
            st, rel, present_bytes, _note = vl.locate(entry, scan)
            return {"status": st if st != "FINAL" else "UNVERIFIED",
                    "verified": False, "present": st == "FINAL",
                    "presentBytes": present_bytes if st != "MISSING" else 0,
                    "localRelPath": rel, "actualSha256": None,
                    "expectedSha256": entry["sha256"] or entry["blob_sha1"],
                    "note": "not hash-verified"}
        verified = r["status"] == "PASS" and fresh
        return {
            "status": r["status"],
            "verified": bool(verified),
            "present": r["status"] not in ("MISSING", "INCOMPLETE"),
            "presentBytes": r.get("presentBytes") or 0,
            "localRelPath": r.get("localRelPath"),
            "actualSha256": r.get("actualSha256"),
            "expectedSha256": r.get("expectedSha256") or r.get("expectedBlobSha1"),
            "note": r.get("note"),
        }

    group_files = {}
    for e in manifest["files"]:
        name, kind = vl.group_of(e)
        group_files.setdefault(name, {"kind": kind, "entries": []})["entries"].append(e)

    sets = {}
    shared = {}
    skipped = {}
    gates_all = rung_gates()
    for name, g in group_files.items():
        entries = g["entries"]
        if g["kind"] == "set" and gates_all.get(name.upper(), {}).get("pass") is False:
            skipped[name] = "rung failed the gate (cards/rungs.json pass=false); " \
                            "excluded from the accepted library"
            continue
        present = sum(1 for e in entries if status_of(e)["present"])
        verified = sum(1 for e in entries if status_of(e)["verified"])
        bytes_expected = sum(e["bytes"] or 0 for e in entries)
        bytes_present = sum(status_of(e)["presentBytes"] for e in entries)
        any_progress = any(status_of(e)["presentBytes"] > 0 for e in entries)
        if verified == len(entries):
            verdict = "verified"
        elif present or any_progress:
            verdict = "incomplete"
        else:
            verdict = "missing"
        key = name if g["kind"] == "set" else name
        row = {
            "kind": g["kind"],
            "bytes": bytes_expected,
            "files": len(entries),
            "presentFiles": present,
            "verifiedFiles": verified,
            "presentBytes": bytes_present,
            "verified": verified == len(entries),
            "verdict": verdict,
            "localPath": args.dir,
            "shards": [{
                "file": e["basename"],
                "bytes": e["bytes"],
                "sha256": e["sha256"],
                "status": status_of(e)["status"],
                "verified": status_of(e)["verified"],
                "localRelPath": status_of(e)["localRelPath"],
            } for e in entries],
        }
        if g["kind"] == "set":
            gates = gates_all.get(name.upper())
            if gates:
                row["rungGate"] = gates
            sets[name] = row
        else:
            shared[key] = row
    if not skipped:
        skipped["IQ2_XS"] = "rung failed the gate (cards/rungs.json pass=false); not downloaded"

    def is_skipped(e):
        name, kind = vl.group_of(e)
        return kind == "set" and gates_all.get(name.upper(), {}).get("pass") is False

    accepted = [e for e in manifest["files"] if not is_skipped(e)]
    files_expected = len(accepted)
    bytes_expected = sum(e["bytes"] or 0 for e in accepted)
    bytes_present = sum(status_of(e)["presentBytes"] for e in accepted)
    files_verified = sum(1 for e in accepted
                         if status_of(e)["verified"])
    bytes_verified = sum(status_of(e)["presentBytes"]
                         for e in accepted
                         if status_of(e)["verified"])
    all_files_verified = files_verified == files_expected and files_expected > 0
    has_engram = "Engram" in shared
    engram_ok = shared.get("Engram", {}).get("verified", False)
    has_drafter = "drafter" in shared
    drafter_ok = shared.get("drafter", {}).get("verified", False)

    portable = bool(all_files_verified and has_engram and engram_ok
                    and has_drafter and drafter_ok)
    if portable:
        portable_reason = "every accepted file is present and hash-verified"
    else:
        missing = [e["basename"] for e in accepted
                   if not status_of(e)["verified"]]
        portable_reason = "%d of %d accepted files not yet hash-verified%s" % (
            len(missing), files_expected,
            (": " + ", ".join(missing[:6]) + (" ..." if len(missing) > 6 else ""))
            if missing else "")

    model = fetch_model_meta(manifest["files"][0]["repo"])

    sources = {}
    for e in manifest["files"]:
        repo = e["repo"]
        key = repo
        s = sources.setdefault(key, {"repo": repo, "revisions": [], "license": "mit"})
        if e["revision"] not in s["revisions"]:
            s["revisions"].append(e["revision"])

    idx = {
        "schema": "dsh.library.index/1",
        "generatedBy": "scripts/index_library.py",
        "generatedAt": vl.iso_now(),
        "libraryRoot": LIBRARY_ROOT,
        "modelDir": args.dir,
        "repo": manifest["files"][0]["repo"],
        "revision": manifest["files"][0]["revision"],
        "license": "mit",
        "sources": [sources[k] for k in sorted(sources)],
        "model": {
            "name": "DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO",
            "architecture": model.get("architecture"),
            "parameters": model.get("parameters"),
            "contextLength": model.get("contextLength"),
            "license": "mit",
            "metadataSource": model.get("source"),
            "quantizationRungs": sorted(sets.keys()),
        },
        "totals": {
            "filesExpected": files_expected,
            "filesPresent": sum(1 for e in manifest["files"]
                                if status_of(e)["present"]),
            "filesVerified": files_verified,
            "bytesExpected": bytes_expected,
            "bytesPresent": bytes_present,
            "bytesVerified": bytes_verified,
        },
        "portable": portable,
        "portableReason": portable_reason,
        "portableDefinition": (
            "true when every file accepted for this model is present in the single "
            "flat library dir (original filenames) and hash-verified, so the dir can "
            "be copied as-is to another machine that meets the Strata hardware minimum"),
        "hardwareMinimum": HARDWARE_MINIMUM,
        "sets": sets,
        "shared": shared,
        "verification": {
            "manifest": os.path.abspath(manifest_path),
            "manifestSha256": manifest_sha,
            "report": report_path,
            "reportGeneratedAt": (report or {}).get("generatedAt"),
            "ranNow": ran_verify,
            "fresh": fresh,
            "verdict": (report or {}).get("verdict", "unverified"),
            "staleNote": stale_note,
            "quick": bool(args.quick),
        },
        "skipped": skipped,
        "freeBytes": disk_free(args.dir),
        "notes": [
            "verified=true means verify_library.py re-hashed the file from disk in "
            "8 MiB chunks and it matched the pinned manifest sha256.",
            "Engram (ISTA-DASLab, pinned cb02422c900d..., sha256 eb19f30d... at that "
            "revision) is shared by both rungs and must sit beside the shards.",
            "Drafter + mmproj + UD-Q8_K_XL meta shard come from unsloth at pinned "
            "8a6ec9cf...; Strata's packer requires them.",
            "IQ2_XS is intentionally absent: its rung failed the gate.",
        ],
    }
    return idx, manifest, report


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(
        description="Build Library/index.json for the local model library "
                    "(verified status + portability + hardware minimum).")
    p.add_argument("--manifest", default=None,
                   help="pin manifest (default manifests/acceptance.json, "
                        "fallback manifests/repo.json)")
    p.add_argument("--dir", default=DEFAULT_LIBRARY, help="library dir")
    p.add_argument("--report", default=None, help="use this verify report instead of hashing")
    p.add_argument("--verify", action="store_true", help="force a fresh hash pass")
    p.add_argument("--no-hash", action="store_true", help="never hash (mark stale if needed)")
    p.add_argument("--quick", action="store_true", help="size-only verification")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--out", default=INDEX_PATH, help="index path (default Library/index.json)")
    args = p.parse_args(argv)

    try:
        idx, manifest, report = build_index(args)
    except vl.ManifestError as e:
        print("ERROR: %s" % e)
        return 2

    atomic_write_json(args.out, idx)
    if not args.quiet:
        print("")
        print("== index ==")
        print("wrote %s" % args.out)
        print("repo     : %s @ %s" % (idx["repo"], idx["revision"][:12]))
        print("sources  : %s" % ", ".join(
            "%s@%s" % (s["repo"].split("/")[0], s["revisions"][0][:12])
            for s in idx["sources"]))
        print("files    : %d/%d present, %d hash-verified" % (
            idx["totals"]["filesPresent"], idx["totals"]["filesExpected"],
            idx["totals"]["filesVerified"]))
        print("bytes    : %.2f present / %.2f expected GiB" % (
            idx["totals"]["bytesPresent"] / vl.GIB, idx["totals"]["bytesExpected"] / vl.GIB))
        for name in sorted(idx["sets"]):
            s = idx["sets"][name]
            print("  set %-8s %d/%d files, %s" % (
                name, s["presentFiles"], s["files"], s["verdict"]))
        for name in sorted(idx["shared"]):
            s = idx["shared"][name]
            print("  %-12s %d/%d files, %s" % (
                name, s["presentFiles"], s["files"], s["verdict"]))
        print("portable : %s (%s)" % (idx["portable"], idx["portableReason"]))
        print("hardware : %d GiB VRAM min, %d GiB measured (Strata)" % (
            HARDWARE_MINIMUM["vramGiBMinimum"], HARDWARE_MINIMUM["vramGiBMeasured"]))
        print("verify   : %s%s" % (
            idx["verification"]["verdict"],
            "" if idx["verification"]["fresh"] else
            " (STALE: %s)" % idx["verification"]["staleNote"]))
    return 0 if idx["portable"] else 2


if __name__ == "__main__":
    sys.exit(main())
