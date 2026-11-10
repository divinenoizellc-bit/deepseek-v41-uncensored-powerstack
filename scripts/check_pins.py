#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_pins.py - re-assert the accepted pins against the Hugging Face API.

For every file in the pin manifest (manifests/acceptance.json, or the audit
manifest manifests/repo.json) this resolves the pinned revision of its repo
and probes the authoritative per-revision metadata endpoint:

    HEAD https://huggingface.co/<repo>/resolve/<revision>/<file>?download=true

The response before the CDN redirect carries
    X-Linked-Size  : exact byte size at that revision
    X-Linked-ETag  : LFS sha256 (64 hex) or, for plain git files, the
                     git blob sha1 (40 hex)
which is the only reliable way to read per-revision pins: the tree API's
?revision= query parameter is silently ignored (it returns main) and
/api/models/<repo>/tree/<rev> returns 404, so the tree is NOT usable here.

Checks, per file
  PASS          size and (sha256|blob sha1) both match the manifest
  PASS-SIZE     size matches; manifest carries no comparable hash
  DRIFT_SIZE    size differs from the manifest
  DRIFT_SHA     hash differs from the manifest
  DRIFT_REV     repo revision does not resolve to the pinned sha
  ERROR         HTTP failure / no HTTP status

Exit 0 only when every file and every repo revision still matches; 1 on any
drift or error. Writes a JSON report to Library/logs (never touches the
library dir or manifests/).
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import verify_library as vl  # noqa: E402

PROJECT = vl.PROJECT
LOG_DIR = vl.LOG_DIR
ACCEPTANCE = vl.ACCEPTANCE
REPO_JSON = vl.REPO_JSON
GIB = vl.GIB

UA = "model-librarian/1.0 (DeepSeek Harness)"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SHA1_RE = re.compile(r"^[0-9a-f]{40}$")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    """Return None so the 3xx itself surfaces as HTTPError (headers intact)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def api_json(url, timeout=45):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def resolve_revision(repo, rev, timeout=45):
    url = "https://huggingface.co/api/models/%s/revision/%s" % (
        urllib.parse.quote(repo, safe="/"), urllib.parse.quote(str(rev), safe=""))
    d = api_json(url, timeout=timeout)
    return (d.get("sha") or "").lower(), d


def probe(repo, rev, path, timeout=60):
    url = "https://huggingface.co/%s/resolve/%s/%s?download=true" % (
        urllib.parse.quote(repo, safe="/"), urllib.parse.quote(str(rev), safe=""),
        urllib.parse.quote(path, safe="/"))
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"},
                                 method="HEAD")
    status = None
    headers = {}
    try:
        with OPENER.open(req, timeout=timeout) as r:
            status = r.status
            headers = {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        status = e.code
        headers = {k.lower(): v for k, v in (e.headers or {}).items()}
    except Exception as e:
        return {"status": None, "error": str(e), "url": url}

    size = headers.get("x-linked-size")
    if size is None and status == 200:
        size = headers.get("content-length")
    try:
        size = int(size) if size is not None else None
    except (TypeError, ValueError):
        size = None
    etag = (headers.get("x-linked-etag") or "").strip().strip('"').lower()
    sha256 = etag if SHA256_RE.match(etag) else None
    blob = etag if SHA1_RE.match(etag) and not sha256 else None
    return {
        "status": status,
        "size": size,
        "sha256": sha256,
        "blobSha1": blob,
        "xet": headers.get("x-xet-hash"),
        "url": url,
        "error": None,
    }


def check(manifest_path, only_repo=None, timeout=60, progress=True):
    manifest = vl.load_manifest(manifest_path)
    files = manifest["files"]
    if only_repo:
        rx = re.compile(only_repo, re.I)
        files = [f for f in files if rx.search(f["repo"])]

    # 1) resolve every distinct (repo, revision) once
    reps = {}
    for f in files:
        reps[(f["repo"], f["revision"])] = None
    rev_rows = {}
    for repo, rev in reps:
        try:
            sha, info = resolve_revision(repo, rev, timeout=timeout)
            ok = (sha == str(rev).lower()) or (str(rev).lower() in sha) or \
                 (SHA1_RE.match(str(rev).lower()) is None and len(str(rev)) >= 7
                  and sha.startswith(str(rev).lower()))
            rev_rows[(repo, rev)] = {
                "repo": repo, "requested": rev, "resolvedSha": sha,
                "immutablePin": bool(SHA1_RE.match(str(rev).lower())),
                "match": bool(ok),
                "gated": info.get("gated"),
                "lastModified": info.get("lastModified"),
                "status": "PASS" if ok else "DRIFT_REV",
            }
        except Exception as e:
            rev_rows[(repo, rev)] = {
                "repo": repo, "requested": rev, "resolvedSha": None,
                "immutablePin": bool(SHA1_RE.match(str(rev).lower())),
                "match": False, "status": "ERROR", "error": str(e),
            }

    # 2) probe every file at its pinned revision
    rows = []
    for f in files:
        rep = rev_rows.get((f["repo"], f["revision"])) or {}
        p = probe(f["repo"], f["revision"], f["filename"], timeout=timeout)
        row = {
            "repo": f["repo"], "revision": f["revision"], "filename": f["filename"],
            "manifestBytes": f["bytes"], "manifestSha256": f["sha256"],
            "manifestBlobSha1": f["blob_sha1"],
            "apiBytes": p.get("size"), "apiSha256": p.get("sha256"),
            "apiBlobSha1": p.get("blobSha1"), "httpStatus": p.get("status"),
            "sizeMatch": None, "shaMatch": None, "error": p.get("error"),
            "status": "PASS", "note": "",
        }
        if row["error"] or p.get("status") is None:
            row["status"] = "ERROR"
            row["note"] = row["error"] or "no HTTP status"
        elif p["status"] not in (200, 301, 302, 303, 307, 308):
            row["status"] = "ERROR"
            row["note"] = "http %s" % p["status"]
        else:
            if f["bytes"] is not None and row["apiBytes"] is not None:
                row["sizeMatch"] = row["apiBytes"] == f["bytes"]
                if not row["sizeMatch"]:
                    row["status"] = "DRIFT_SIZE"
                    row["note"] = "api %d != manifest %d" % (row["apiBytes"], f["bytes"])
            else:
                row["note"] = "size unavailable from API"
                row["status"] = "ERROR"
            if row["status"] == "PASS":
                if p.get("sha256") and f["sha256"]:
                    row["shaMatch"] = p["sha256"] == f["sha256"]
                    if not row["shaMatch"]:
                        row["status"] = "DRIFT_SHA"
                        row["note"] = "api %s != manifest %s" % (
                            p["sha256"][:16], f["sha256"][:16])
                    else:
                        row["note"] = "sha256"
                elif p.get("blobSha1") and f["blob_sha1"]:
                    row["shaMatch"] = p["blobSha1"] == f["blob_sha1"]
                    if not row["shaMatch"]:
                        row["status"] = "DRIFT_SHA"
                        row["note"] = "blob %s != manifest %s" % (
                            p["blobSha1"][:16], f["blob_sha1"][:16])
                    else:
                        row["note"] = "git blob sha1 (non-LFS; sha256 not exposed)"
                elif p.get("blobSha1"):
                    row["note"] = ("size checked; API exposes only git blob sha1 "
                                   "for this non-LFS file")
                elif p.get("sha256") and not f["sha256"]:
                    row["note"] = "api sha256 %s (manifest has none)" % p["sha256"][:16]
                else:
                    row["note"] = "no hash from API or manifest (size only)"
        rows.append(row)

    rev_fail = [r for r in rev_rows.values() if r["status"] != "PASS"]
    file_fail = [r for r in rows if r["status"] != "PASS"]
    drift = bool(rev_fail or file_fail)
    report = {
        "schema": "dsh.library.pins/1",
        "generatedAt": vl.iso_now(),
        "generatedBy": "scripts/check_pins.py",
        "manifest": manifest["path"],
        "manifestSha256": manifest["sha256"],
        "method": "HEAD resolve/<pinned revision>/<file>; X-Linked-Size + X-Linked-ETag",
        "revisions": [rev_rows[k] for k in
                      sorted(rev_rows, key=lambda t: (t[0], str(t[1])))],
        "files": rows,
        "summary": {
            "files": len(rows), "pass": len(rows) - len(file_fail),
            "fail": len(file_fail),
            "revisions": len(rev_rows), "revisionsFail": len(rev_fail),
            "drift": drift,
        },
        "verdict": "DRIFT" if drift else "PASS",
    }

    if progress:
        print("== check pins ==")
        print("manifest: %s" % manifest["path"])
        print("          sha256 %s, %d files" % (manifest["sha256"][:16], len(manifest["files"])))
        print("")
        print("pinned revisions:")
        for k in sorted(rev_rows, key=lambda t: (t[0], str(t[1]))):
            r = rev_rows[k]
            print("  [%-9s] %-58s %s -> %s%s" % (
                r["status"], r["repo"], str(r["requested"])[:12],
                (r["resolvedSha"] or "?")[:12],
                "" if r["immutablePin"] else "  (NOT a full sha: mutable pin)"))
        print("")
        print("%-11s %-60s %12s %-18s %s" % (
            "status", "file", "bytes", "api sha256(prefix)", "check"))
        for r in rows:
            print("[%-9s] %-60s %12s %-18s %s" % (
                r["status"], r["filename"][-60:], r["apiBytes"] if r["apiBytes"] is not None else "-",
                (r["apiSha256"] or r["apiBlobSha1"] or "-")[:16], r["note"]))
        print("")
        print("summary: %d/%d files PASS, %d/%d revisions PASS -> %s" % (
            report["summary"]["pass"], report["summary"]["files"],
            report["summary"]["revisions"] - report["summary"]["revisionsFail"],
            report["summary"]["revisions"], report["verdict"]))

    vl.ensure_dir(LOG_DIR)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = os.path.join(LOG_DIR, "check-pins-%s.json" % ts)
    with open(vl.lp(path), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    latest = os.path.join(LOG_DIR, "check-pins-latest.json")
    tmp = latest + ".tmp"
    with open(vl.lp(tmp), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(vl.lp(tmp), vl.lp(latest))
    if progress:
        print("report: %s" % path)
    return report, (1 if drift else 0)


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Re-assert accepted file pins against the HF API "
                    "(fails loudly on revision/size/sha256 drift).")
    p.add_argument("--manifest", default=None,
                   help="pin manifest (default manifests/acceptance.json, "
                        "fallback manifests/repo.json)")
    p.add_argument("--repo", default=None, help="regex filter on repo id")
    p.add_argument("--timeout", type=float, default=60.0)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args(argv)

    manifest = args.manifest
    if not manifest:
        if os.path.exists(vl.lp(ACCEPTANCE)):
            manifest = ACCEPTANCE
        elif os.path.exists(vl.lp(REPO_JSON)):
            manifest = REPO_JSON
            print("NOTE: acceptance.json not found; checking manifests/repo.json")
        else:
            print("ERROR: no manifest (expected manifests/acceptance.json)")
            return 2
    try:
        report, code = check(manifest, only_repo=args.repo, timeout=args.timeout,
                             progress=not args.quiet)
    except vl.ManifestError as e:
        print("ERROR: %s" % e)
        return 2
    except Exception as e:
        print("ERROR: %s" % e)
        return 1
    if code:
        print("")
        print("DRIFT DETECTED - do not treat the library as the pinned artifact.")
        for r in report["files"]:
            if r["status"] != "PASS":
                print("  %-10s %s: %s" % (r["status"], r["filename"], r["note"]))
        for r in report["revisions"]:
            if r["status"] != "PASS":
                print("  %-10s %s@%s: %s" % (r["status"], r["repo"],
                                             str(r["requested"])[:12],
                                             r.get("error") or "revision mismatch"))
    return code


if __name__ == "__main__":
    sys.exit(main())
