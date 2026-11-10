#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch.py - SUPERSEDED / NOT THE ACTIVE DOWNLOADER.

The Lead now owns downloading (Tools/runtime/fetch-library.ps1 writes the
library dir); running this script would race it for the same files. This file
is kept only as a historical resumable-downloader reference and its pin set
predates the accepted manifest - use scripts/check_pins.py,
scripts/verify_library.py and scripts/index_library.py against
manifests/acceptance.json instead.

--- original header ---

fetch.py - resumable, verified, dependency-free mirror of the
DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO GGUF rungs plus the shared
Engram file, into the local model library.

Sources (both pinned to exact commit SHAs, MIT licensed):
  primary : AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF
            @ 4f1d2f730cff977961db81789e81bfc0d3e6dd2e
  engram  : ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF
            @ cb02422c900df489cea5833e8a92171224059b3c

Download order (mandated):
  smalls  -> engram  -> IQ2_XXS -> IQ1_M
  IQ2_XS is intentionally NOT downloaded: its rung FAILED the gate
  (cards/rungs.json "pass": false) and it would add ~144.6 GiB.

Subcommands
  plan      show units, shard sizes, disk math and download order.
            Exit 0 ok, 1 if projected free space < 40 GiB floor, 2 manifest error.
  fetch     resumable HTTP Range download, at most 3 concurrent files,
            progress every 5 s, per-unit JSONL logs, verifies each finished
            unit and updates Library/index.json only on PASS.
            Exit 0 all selected units verified, 3 space abort, 4 download failure.
  verify    re-hash every completed file from disk against the pinned
            manifest and print a PASS/FAIL table.
            Exit 0 verified, 1 mismatch/corrupt, 2 incomplete only.
  index     rebuild Library/index.json + Library/models/README.md from disk
            state and the recorded verify results (never invents a PASS).
  selftest  probe API, pinned revisions, manifest shape and HTTP Range
            support without downloading a shard.

Partial downloads live in "<name>.part" and resume through a validated
HTTP Range request; if a server ignores Range the file restarts from 0.
Kill it at any moment and rerun the same command.

stdlib only. Windows long-path safe.
"""

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed

# --------------------------------------------------------------------------
# Pinned facts / paths
# --------------------------------------------------------------------------

PRIMARY_REPO = "AtomicChat/DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF"
PRIMARY_REV = "4f1d2f730cff977961db81789e81bfc0d3e6dd2e"
ENGRAM_REPO = "ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF"
ENGRAM_REV = "cb02422c900df489cea5833e8a92171224059b3c"
ENGRAM_FILE = "DeepSeek-V4.1-Flash-Engram-IQ4_NL.gguf"

DOWNLOAD_ORDER = ["smalls", "engram", "IQ2_XXS", "IQ1_M"]
SKIPPED_SETS = {
    "IQ2_XS": "rung FAILED gate (cards/rungs.json: pass=false); +144.6 GiB, skipped by design",
}

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = os.path.dirname(HERE)
LOG_DIR = os.path.join(PROJECT, "Library", "logs")
INDEX_PATH = os.path.join(PROJECT, "Library", "index.json")
MODELS_README = os.path.join(PROJECT, "Library", "models", "README.md")
LIBRARY_ROOT = os.environ.get("HF_LIBRARY_ROOT") or r"C:\Users\psand\Models\huggingface"
DEST = os.path.join(
    LIBRARY_ROOT, "AtomicChat--DeepSeek-V4.1-Flash-1017-Uncensored-GSQ-RCO-GGUF"
)
META_DIR = os.path.join(DEST, "meta")

GIB = 1 << 30
MIB = 1 << 20
RESERVE = 40 * GIB          # never let free space drop below this
PART = ".part"
UA = "model-librarian/1.0 (DeepSeek Harness; python-urllib)"
GGUF_RE = re.compile(r"-(IQ1_M|IQ2_XS|IQ2_XXS)-(\d{5})-of-(\d{5})\.gguf$", re.I)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

API = "https://huggingface.co/api/models/%s"
RESOLVE = "https://huggingface.co/%s/resolve/%s/%s?download=true"


# --------------------------------------------------------------------------
# Small utilities
# --------------------------------------------------------------------------

def lp(path):
    """Return a Windows long-path-safe absolute path, otherwise the path."""
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
    n = float(n)
    if n >= GIB:
        return "%.2f GiB" % (n / GIB)
    if n >= MIB:
        return "%.1f MiB" % (n / MIB)
    if n >= 1024:
        return "%.1f KiB" % (n / 1024.0)
    return "%d B" % int(n)


def mbps(bps):
    return "%.1f MB/s" % (bps / 1e6)


def fmt_dur(sec):
    if sec is None or sec != sec or sec < 0 or sec > 10 * 365 * 86400:
        return "--"
    sec = int(sec)
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


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def quote_path(path):
    return urllib.parse.quote(path, safe="/")


def file_size(path):
    try:
        return os.path.getsize(lp(path))
    except OSError:
        return -1


def disk_free(path):
    ensure_dir(path)
    return shutil.disk_usage(lp(path)).free


def atomic_write_json(path, obj):
    ensure_dir(os.path.dirname(path))
    tmp = "%s.tmp-%d" % (path, os.getpid())
    with open(lp(tmp), "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, sort_keys=False)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(lp(tmp), lp(path))


def read_json(path):
    with open(lp(path), "r", encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path, chunk=8 * MIB, progress=None, tick=8.0):
    h = hashlib.sha256()
    total = file_size(path)
    done = 0
    t0 = time.time()
    last = t0
    with open(lp(path), "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
            done += len(b)
            if progress and time.time() - last >= tick:
                progress(done, total)
                last = time.time()
    return h.hexdigest(), time.time() - t0


def git_blob_sha1(path, chunk=8 * MIB):
    """Git blob id: sha1(b"blob <len>\\0" + content). Matches tree-entry `oid`."""
    size = file_size(path)
    h = hashlib.sha1()
    h.update(b"blob %d\x00" % size)
    with open(lp(path), "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest(), size


# --------------------------------------------------------------------------
# Logging (console + optional tee file, thread safe)
# --------------------------------------------------------------------------

class Log:
    def __init__(self):
        self.lock = threading.Lock()
        self.fh = None
        self.path = None

    def open(self, path):
        if not path:
            return
        ensure_dir(os.path.dirname(path))
        self.fh = open(lp(path), "a", encoding="utf-8", buffering=1)
        self.path = path

    def close(self):
        if self.fh:
            try:
                self.fh.close()
            finally:
                self.fh = None

    def say(self, line=""):
        with self.lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
            if self.fh:
                self.fh.write(line + "\n")
                self.fh.flush()


LOG = Log()


def jsonl(path, obj):
    with LOG.lock:
        ensure_dir(os.path.dirname(path))
        with open(lp(path), "a", encoding="utf-8") as f:
            f.write(json.dumps(obj, sort_keys=False) + "\n")


def unit_log_path(unit_name):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", unit_name)
    return os.path.join(LOG_DIR, "fetch-%s.jsonl" % safe)


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def _headers(extra=None):
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "identity"}
    tok = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    if tok:
        h["Authorization"] = "Bearer " + tok
    if extra:
        h.update(extra)
    return h


OPENER = urllib.request.build_opener()


class Retryable(Exception):
    def __init__(self, msg, delay=None):
        Exception.__init__(self, msg)
        self.delay = delay


class Fatal(Exception):
    pass


class Aborted(Exception):
    pass


def http_open(url, headers=None, timeout=60):
    req = urllib.request.Request(url, headers=_headers(headers))
    return OPENER.open(req, timeout=timeout)


def http_json(url, retries=4, timeout=60):
    last = None
    for attempt in range(retries + 1):
        try:
            with http_open(url, timeout=timeout) as r:
                raw = r.read()
            return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            if e.code in (408, 425, 429) or 500 <= e.code < 600:
                last = "http %d for %s %s" % (e.code, url, body)
                time.sleep(min(60, 2 ** attempt))
                continue
            raise Fatal("http %d for %s %s" % (e.code, url, body))
        except (urllib.error.URLError, OSError) as e:
            last = "%s for %s" % (e, url)
            time.sleep(min(60, 2 ** attempt))
    raise Fatal("giving up: %s" % last)


def resolve_revision(repo, rev):
    """Resolve any revision string (branch, tag, short sha) to a full commit sha."""
    info = http_json(API % (urllib.parse.quote(repo, safe="/") + "/revision/" + urllib.parse.quote(rev, safe="")), retries=4)
    sha = (info.get("sha") or "").strip().lower()
    if not SHA256_RE.match(sha) and not re.match(r"^[0-9a-f]{40}$", sha):
        raise Fatal("could not resolve revision %r of %s (got sha=%r)" % (rev, repo, sha))
    return sha, info


def _next_link(header):
    if not header:
        return None
    m = re.search(r'<([^>]+)>\s*;\s*rel="?next"?', header)
    return m.group(1) if m else None


def fetch_tree(repo, sha):
    url = (API % (urllib.parse.quote(repo, safe="/") + "/tree/main")) + \
        "?recursive=true&revision=" + urllib.parse.quote(sha, safe="")
    out = []
    while url:
        with http_open(url) as r:
            data = json.loads(r.read().decode("utf-8"))
            nxt = _next_link(r.headers.get("Link"))
        if not isinstance(data, list):
            raise Fatal("unexpected tree payload for %s: %r" % (repo, data))
        out.extend(data)
        url = nxt
    return out


def manifest_path(repo, sha):
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "--", repo)
    return os.path.join(LOG_DIR, "manifest-%s-%s.json" % (slug, sha[:12]))


def get_manifest(repo, rev, refresh=False):
    """Return pinned manifest: {"repo","rev","info","tree","fetchedAt"}."""
    sha, info = resolve_revision(repo, rev)
    path = manifest_path(repo, sha)
    if os.path.exists(lp(path)) and not refresh:
        try:
            m = read_json(path)
            if m.get("rev") == sha and m.get("tree"):
                return m
        except Exception:
            pass
    tree = fetch_tree(repo, sha)
    trim = {
        "sha": sha,
        "lastModified": info.get("lastModified"),
        "gated": info.get("gated"),
        "private": info.get("private"),
        "downloads": info.get("downloads"),
        "likes": info.get("likes"),
        "usedStorage": info.get("usedStorage"),
        "tags": info.get("tags") or [],
        "gguf": info.get("gguf") or {},
        "cardData": info.get("cardData") or {},
    }
    m = {"repo": repo, "rev": sha, "revRequested": rev, "fetchedAt": iso_now(),
         "info": trim, "tree": tree}
    atomic_write_json(path, m)
    return m


def get_rungs(refresh=False):
    """cards/rungs.json (gate results per rung), cached next to the manifest."""
    path = os.path.join(LOG_DIR, "rungs-%s.json" % PRIMARY_REV[:12])
    if os.path.exists(lp(path)) and not refresh:
        try:
            return read_json(path)
        except Exception:
            pass
    url = RESOLVE % (PRIMARY_REPO, PRIMARY_REV, "cards/rungs.json")
    with http_open(url) as r:
        data = json.loads(r.read().decode("utf-8"))
    atomic_write_json(path, data)
    return data


# --------------------------------------------------------------------------
# Manifest -> units
# --------------------------------------------------------------------------

def entry_sha256(e):
    lfs = e.get("lfs") or {}
    oid = (lfs.get("oid") or "").lower()
    if oid and SHA256_RE.match(oid):
        return oid
    return None


def entry_size(e):
    n = e.get("size")
    return int(n) if isinstance(n, int) and n > 0 else 0


def build_units(only=None, refresh=False, repo_override=None, rev_override=None,
                allow_failed=False, extra_file=None):
    """Build the ordered, fully described download units."""
    primary_repo = repo_override or PRIMARY_REPO
    primary_rev = rev_override or PRIMARY_REV

    pm = get_manifest(primary_repo, primary_rev, refresh=refresh)
    tree = [e for e in pm["tree"] if e.get("type") == "file"]
    ggufs = [e for e in tree if e["path"].lower().endswith(".gguf")]
    smalls = [e for e in tree if not e["path"].lower().endswith(".gguf")]

    sets = {}
    for e in ggufs:
        m = GGUF_RE.search(e["path"])
        if not m:
            continue
        name = m.group(1).upper()
        sets.setdefault(name, []).append((int(m.group(2)), e))
    for name in sets:
        sets[name].sort(key=lambda t: t[0])

    rungs = {}
    try:
        rungs = get_rungs(refresh=refresh)
    except Exception:
        rungs = {}

    def set_files(name):
        files = []
        for idx, e in sets[name]:
            files.append({
                "path": e["path"],
                "size": entry_size(e),
                "sha256": entry_sha256(e),
                "blob_sha1": e.get("oid"),
                "repo": primary_repo,
                "rev": pm["rev"],
                "dest": os.path.join(DEST, os.path.basename(e["path"])),
            })
        return files

    units = []
    # 1) small provenance files -> meta/
    small_files = []
    for e in sorted(smalls, key=lambda x: x["path"]):
        rel = e["path"].replace("\\", "/")
        small_files.append({
            "path": rel,
            "size": entry_size(e),
            "sha256": None,
            "blob_sha1": e.get("oid"),
            "repo": primary_repo,
            "rev": pm["rev"],
            "dest": os.path.join(META_DIR, *rel.split("/")),
        })
    units.append({
        "name": "smalls",
        "kind": "meta",
        "repo": primary_repo,
        "rev": pm["rev"],
        "license": "mit",
        "files": small_files,
        "localPath": META_DIR,
        "notes": ["provenance: .gitattributes, LICENSE, README.md, cards/rungs.json"],
    })

    # 2) shared Engram file from the base repo (same dir as the shards)
    em = get_manifest(ENGRAM_REPO, ENGRAM_REV, refresh=refresh)
    efile = None
    for e in em["tree"]:
        if e.get("type") == "file" and e["path"] == ENGRAM_FILE:
            efile = e
            break
    if efile is None:
        raise Fatal("engram file %s not found in %s@%s" % (ENGRAM_FILE, ENGRAM_REPO, em["rev"]))
    units.append({
        "name": "engram",
        "kind": "engram",
        "repo": ENGRAM_REPO,
        "rev": em["rev"],
        "sourceRepo": ENGRAM_REPO,
        "license": "mit",
        "sharedByRungs": ["IQ2_XXS", "IQ1_M"],
        "files": [{
            "path": efile["path"],
            "size": entry_size(efile),
            "sha256": entry_sha256(efile),
            "blob_sha1": efile.get("oid"),
            "repo": ENGRAM_REPO,
            "rev": em["rev"],
            "dest": os.path.join(DEST, os.path.basename(efile["path"])),
        }],
        "localPath": DEST,
        "notes": ["shared Engram asset; Strata runtime needs it beside the shards"],
    })

    # 3) rung sets in mandated order
    for name in [n for n in DOWNLOAD_ORDER if n in sets]:
        if name in SKIPPED_SETS and not allow_failed:
            continue
        files = set_files(name)
        rung = (rungs or {}).get(name) or {}
        units.append({
            "name": name,
            "kind": "set",
            "repo": primary_repo,
            "rev": pm["rev"],
            "license": "mit",
            "files": files,
            "rung": rung,
            "rungPass": rung.get("pass"),
            "localPath": DEST,
            "notes": [],
        })

    # 4) explicit failed rung, only when asked for
    if allow_failed:
        for name in sorted(sets):
            if name in DOWNLOAD_ORDER:
                continue
            if name in SKIPPED_SETS:
                files = set_files(name)
                rung = (rungs or {}).get(name) or {}
                units.append({
                    "name": name, "kind": "set", "repo": primary_repo, "rev": pm["rev"],
                    "license": "mit", "files": files, "rung": rung,
                    "rungPass": rung.get("pass"), "localPath": DEST,
                    "notes": ["EXPLICITLY requested despite failed gate"],
                })

    # 5) ad-hoc single file
    if extra_file:
        found = None
        for e in tree:
            if e["path"] == extra_file:
                found = e
                break
        if found is None:
            raise Fatal("file %r not in %s@%s" % (extra_file, primary_repo, pm["rev"]))
        units = [{
            "name": "custom-" + os.path.basename(extra_file).split(".")[0][:40],
            "kind": "custom",
            "repo": primary_repo,
            "rev": pm["rev"],
            "license": "mit",
            "files": [{
                "path": found["path"],
                "size": entry_size(found),
                "sha256": entry_sha256(found),
                "blob_sha1": found.get("oid"),
                "repo": primary_repo,
                "rev": pm["rev"],
                "dest": os.path.join(DEST, os.path.basename(found["path"])),
            }],
            "localPath": DEST,
            "notes": ["ad-hoc single file"],
        }]

    if only and only not in ("all",):
        units = [u for u in units if u["name"].lower() == only.lower()]
        if not units:
            raise Fatal("unit %r not found (available: %s)" % (
                only, ", ".join([u["name"] for u in units]) or "none"))
    return units


def unit_total(unit):
    return sum(f["size"] for f in unit["files"])


def unit_present(unit):
    """Bytes already on disk for this unit (complete + .part), capped per file."""
    total = 0
    for f in unit["files"]:
        n = file_size(f["dest"])
        if n > 0:
            total += min(n, f["size"])
            continue
        n = file_size(f["dest"] + PART)
        if n > 0:
            total += min(n, f["size"])
    return total


def unit_complete_files(unit):
    return sum(1 for f in unit["files"] if file_size(f["dest"]) == f["size"])


def unit_remaining(unit):
    return sum(max(0, f["size"] - max(0, max(file_size(f["dest"]),
                                                file_size(f["dest"] + PART))))
               for f in unit["files"])


# --------------------------------------------------------------------------
# Progress accounting + monitor
# --------------------------------------------------------------------------

class Progress:
    def __init__(self, units):
        self.lock = threading.Lock()
        self.units = units
        self.bytes = {}
        self.done = {}
        self.error = {}
        self.started_units = set()
        self.abort = threading.Event()
        self.abort_reason = None
        self.t0 = time.time()

    def start(self, unit_name):
        with self.lock:
            self.started_units.add(unit_name)

    def set(self, unit_name, path, n):
        with self.lock:
            self.bytes[(unit_name, path)] = n
            self.started_units.add(unit_name)

    def add(self, unit_name, path, n):
        with self.lock:
            key = (unit_name, path)
            self.bytes[key] = self.bytes.get(key, 0) + n
            self.started_units.add(unit_name)

    def mark_done(self, unit_name, path):
        with self.lock:
            self.done[(unit_name, path)] = True
            self.started_units.add(unit_name)

    def mark_error(self, unit_name, path, msg):
        with self.lock:
            self.error[(unit_name, path)] = msg

    def snapshot(self):
        with self.lock:
            return (dict(self.bytes), dict(self.done), dict(self.error),
                    set(self.started_units), self.abort.is_set(), self.abort_reason)


def monitor_loop(prog, units, cfg, stop):
    prev = {}
    ema = {}
    last = time.time()

    def unit_bytes(snap, name):
        return sum(v for (un, _p), v in snap.items() if un == name)

    while not stop.wait(cfg.interval):
        now = time.time()
        dt = max(0.2, now - last)
        last = now
        snap, done, errors, started, aborted, reason = prog.snapshot()
        free = disk_free(DEST)
        total_all = sum(unit_total(u) for u in units)
        cur_all = 0
        rate_all = 0.0
        for u in units:
            name = u["name"]
            if name not in started:
                continue
            total = unit_total(u)
            cur = min(unit_bytes(snap, name), total)
            cur_all += cur
            inst = max(0.0, (cur - prev.get(name, 0)) / dt)
            rate = inst if name not in ema else (0.75 * ema[name] + 0.25 * inst)
            ema[name] = rate
            prev[name] = cur
            rate_all += rate
            active = sum(1 for f in u["files"] if not done.get((name, f["path"])))
            errs = sum(1 for f in u["files"] if (name, f["path"]) in errors)
            pct = (100.0 * cur / total) if total else 100.0
            eta = (total - cur) / rate if rate > 0.05e6 else None
            LOG.say("[%-7s] %s/%s %5.1f%% %10s ETA %6s  %d/%d active%s  free %.2f GiB" % (
                name, human(cur), human(total), pct, mbps(rate), fmt_dur(eta),
                active, len(u["files"]), (" err=%d" % errs) if errs else "",
                free / GIB))
            jsonl(unit_log_path(name), {
                "ts": iso_now(), "event": "progress", "unit": name,
                "repo": u["repo"], "rev": u["rev"],
                "bytes": cur, "total": total, "pct": round(pct, 3),
                "mbps": round(rate / 1e6, 3), "eta_s": None if eta is None else int(eta),
                "active_files": active, "errors": errs,
                "free_bytes": free, "aborted": aborted,
            })

        if started:
            pct = (100.0 * cur_all / total_all) if total_all else 100.0
            eta = (total_all - cur_all) / rate_all if rate_all > 0.5e6 else None
            LOG.say("[ALL    ] %s/%s %5.1f%% %10s ETA %6s  free %.2f GiB" % (
                human(cur_all), human(total_all), pct, mbps(rate_all),
                fmt_dur(eta), free / GIB))

        if free < RESERVE and not aborted:
            reason = ("free space %.2f GiB < %.2f GiB reserve"
                      % (free / GIB, RESERVE / GIB))
            prog.abort_reason = reason
            prog.abort.set()
            LOG.say("!! ABORT: %s -- stopping cleanly, .part files kept" % reason)
            for u in units:
                jsonl(unit_log_path(u["name"]), {
                    "ts": iso_now(), "event": "abort_space", "unit": u["name"],
                    "free_bytes": free, "reserve_bytes": RESERVE, "reason": reason,
                })


# --------------------------------------------------------------------------
# Download engine
# --------------------------------------------------------------------------

class Task:
    def __init__(self, unit, f, prog):
        self.unit = unit
        self.f = f
        self.prog = prog
        self.part = f["dest"] + PART
        self.h = hashlib.sha256()
        self.h_upto = 0
        self.key = (unit["name"], f["path"])

    def log(self, event, **kw):
        rec = {"ts": iso_now(), "event": event, "unit": self.unit["name"],
               "repo": self.f["repo"], "rev": self.f["rev"],
               "file": self.f["path"], "size": self.f["size"]}
        rec.update(kw)
        jsonl(unit_log_path(self.unit["name"]), rec)

    def _reset_hash(self):
        self.h = hashlib.sha256()
        self.h_upto = 0

    def truncate(self, why=""):
        with open(lp(self.part), "wb"):
            pass
        self._reset_hash()
        self.prog.set(self.unit["name"], self.f["path"], 0)
        if why:
            self.log("truncate", why=why)

    def sync_hash(self):
        """Hash any bytes present in .part that are not hashed yet (resume seed)."""
        size = max(0, file_size(self.part))
        if size < self.h_upto:
            self._reset_hash()
        if size > self.h_upto:
            remaining = size - self.h_upto
            self.log("resume_hash_start", hashed=self.h_upto, file_bytes=size)
            last = time.time()
            with open(lp(self.part), "rb") as fh:
                fh.seek(self.h_upto)
                while True:
                    b = fh.read(8 * MIB)
                    if not b:
                        break
                    self.h.update(b)
                    self.h_upto += len(b)
                    self.prog.set(self.unit["name"], self.f["path"], self.h_upto)
                    if time.time() - last >= 5:
                        LOG.say("  [%s] pre-hashing partial %.2f/%.2f GiB (%.0f MB/s)" % (
                            self.unit["name"], self.h_upto / GIB, size / GIB,
                            (size - remaining + self.h_upto - (size - remaining)) / 1e6 /
                            max(0.001, time.time() - last)))
                        last = time.time()
            self.prog.set(self.unit["name"], self.f["path"], self.h_upto)
            self.log("resume_hash_done", hashed=self.h_upto)

    def promote(self):
        os.replace(lp(self.part), lp(self.f["dest"]))
        self.prog.mark_done(self.unit["name"], self.f["path"])
        self.log("complete", sha256=self.h.hexdigest() if self.h_upto == self.f["size"] else None,
                 dest=self.f["dest"])

    # -- one network attempt -------------------------------------------------
    def attempt(self, cfg):
        f = self.f
        total = f["size"]
        expected = f["sha256"]
        ensure_dir(os.path.dirname(self.part))

        have = max(0, file_size(self.part))
        if have > total:
            self.truncate("partial larger than manifest size")
            have = 0
        if have == total:
            self.sync_hash()
            actual = self.h.hexdigest()
            if expected and actual.lower() != expected:
                self.truncate("complete .part failed sha256; restarting")
                have = 0
            else:
                self.log("verify_partial_ok", sha256=actual)
                self.promote()
                return "ok"

        self.sync_hash()
        if self.f["sha256"] is None and not hasattr(self, "_blob"):
            pass

        url = RESOLVE % (urllib.parse.quote(f["repo"], safe="/"),
                         urllib.parse.quote(f["rev"], safe=""),
                         quote_path(f["path"]))
        headers = {}
        if have:
            headers["Range"] = "bytes=%d-" % have
        self.log("http_get", url=url, resume_from=have)
        try:
            resp = http_open(url, headers=headers, timeout=cfg.timeout)
        except urllib.error.HTTPError as e:
            if e.code == 416:
                if have == total:
                    self.sync_hash()
                    self.promote()
                    return "ok"
                self.truncate("http 416 range unsatisfiable; restarting")
                raise Retryable("http 416 -> restart", delay=2)
            if e.code in (408, 425, 429) or 500 <= e.code < 600:
                ra = e.headers.get("Retry-After") if e.headers else None
                delay = None
                try:
                    delay = min(120, int(ra)) if ra else None
                except Exception:
                    delay = None
                raise Retryable("http %d" % e.code, delay=delay)
            if e.code in (401, 403):
                raise Fatal("http %d (auth/gated?) for %s" % (e.code, url))
            if e.code == 404:
                raise Fatal("http 404 (bad repo/rev/path) for %s" % url)
            raise Fatal("http %d for %s" % (e.code, url))
        except (urllib.error.URLError, OSError) as e:
            raise Retryable("connection: %s" % e)

        with resp:
            status = getattr(resp, "status", None) or resp.getcode()
            if status == 206:
                cr = resp.headers.get("Content-Range") or ""
                m = re.match(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", cr.strip())
                if not m:
                    raise Retryable("bad Content-Range %r" % cr)
                start = int(m.group(1))
                if start != have:
                    raise Retryable("Content-Range start %d != local %d" % (start, have))
                if m.group(3) != "*" and int(m.group(3)) != total:
                    raise Fatal("Content-Range total %s != manifest %d" % (m.group(3), total))
            elif status == 200:
                if have:
                    self.log("server_ignored_range_restart", had=have)
                    self.truncate()
                    have = 0
            else:
                raise Retryable("unexpected status %s" % status)

            mode = "ab" if have else "wb"
            with open(lp(self.part), mode) as fh:
                while have < total:
                    if self.prog.abort.is_set():
                        fh.flush()
                        os.fsync(fh.fileno())
                        raise Aborted()
                    want = min(cfg.chunk, total - have)
                    b = resp.read(want)
                    if not b:
                        fh.flush()
                        os.fsync(fh.fileno())
                        raise Retryable("short read at %d/%d bytes" % (have, total))
                    fh.write(b)
                    self.h.update(b)
                    have += len(b)
                    self.h_upto = have
                    self.prog.set(self.unit["name"], f["path"], have)
                fh.flush()
                os.fsync(fh.fileno())

        if have != total:
            raise Retryable("stopped at %d/%d" % (have, total))
        actual = self.h.hexdigest()
        if expected and actual.lower() != expected.lower():
            self.truncate("sha256 mismatch after download; restarting from 0")
            raise Retryable("sha256 mismatch: got %s want %s" % (actual[:16], expected[:16]))
        self.promote()
        return "ok"


def run_task(task, cfg, prog):
    prog.start(task.unit["name"])
    attempts = 0
    while True:
        if prog.abort.is_set():
            task.log("aborted", reason=prog.abort_reason)
            raise Aborted()
        try:
            return task.attempt(cfg)
        except Aborted:
            task.log("aborted", reason=prog.abort_reason)
            raise
        except Retryable as e:
            attempts += 1
            if attempts > cfg.retries:
                task.log("failed", error=str(e), attempts=attempts)
                prog.mark_error(task.unit["name"], task.f["path"], str(e))
                raise RuntimeError(str(e))
            base = e.delay if e.delay else cfg.backoff * (1.7 ** attempts)
            delay = min(cfg.max_backoff, base) + random.uniform(0, 1.0)
            task.log("retry", attempt=attempts, wait_s=round(delay, 2), error=str(e))
            LOG.say("  [%s] retry %d/%d in %.1fs: %s" % (
                task.unit["name"], attempts, cfg.retries, delay, e))
            if prog.abort.wait(delay):
                task.log("aborted", reason=prog.abort_reason)
                raise Aborted()
        except Fatal as e:
            task.log("failed", error=str(e))
            prog.mark_error(task.unit["name"], task.f["path"], str(e))
            raise RuntimeError(str(e))


# --------------------------------------------------------------------------
# Verification
# --------------------------------------------------------------------------

def verify_record_path(unit_name):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", unit_name)
    return os.path.join(LOG_DIR, "verify-%s.json" % safe)


def verify_unit(unit, quiet=False, write_record=True):
    rows = []
    all_ok = True
    any_missing = False
    parts = 0
    t0 = time.time()
    for f in unit["files"]:
        path = f["dest"]
        name = os.path.basename(f["path"])
        if not os.path.exists(lp(path)):
            if os.path.exists(lp(path + PART)):
                parts += 1
            rows.append({"file": name, "size": f["size"], "present": False,
                         "status": "MISSING", "sha256_actual": None, "seconds": 0})
            all_ok = False
            any_missing = True
            continue
        size = file_size(path)
        if size != f["size"]:
            rows.append({"file": name, "size": size, "expected_size": f["size"],
                         "present": True, "status": "SIZE", "sha256_actual": None,
                         "seconds": 0})
            all_ok = False
            continue
        if f.get("sha256"):
            last = [0.0]

            def cb(done, total, _n=name):
                now = time.time()
                if now - last[0] >= 8:
                    last[0] = now
                    LOG.say("  [%s] hashing %s: %.2f/%.2f GiB" % (
                        unit["name"], _n, done / GIB, total / GIB))

            actual, secs = sha256_file(path, progress=cb)
            ok = actual.lower() == f["sha256"].lower()
            rows.append({"file": name, "size": size, "present": True,
                         "status": "OK" if ok else "MISMATCH",
                         "sha256_expected": f["sha256"], "sha256_actual": actual,
                         "seconds": round(secs, 2),
                         "mbps": round(size / 1e6 / secs, 1) if secs else None})
        else:
            actual, _ = git_blob_sha1(path)
            ok = (actual.lower() == (f.get("blob_sha1") or "").lower())
            rows.append({"file": name, "size": size, "present": True,
                         "status": "OK" if ok else "MISMATCH",
                         "blob_sha1_expected": f.get("blob_sha1"),
                         "blob_sha1_actual": actual, "seconds": 0})
        if not ok:
            all_ok = False

    verdict = "verified" if all_ok else ("incomplete" if any_missing else "failed")
    elapsed = time.time() - t0

    if not quiet:
        LOG.say("")
        LOG.say("== verify %s (%s@%s) ==" % (unit["name"], unit["repo"], unit["rev"][:12]))
        LOG.say("  %-52s %12s %10s %-9s %8s" % ("file", "bytes", "GiB", "result", "secs"))
        for r in rows:
            LOG.say("  %-52s %12d %10.2f %-9s %8.1f" % (
                r["file"][:52], r.get("size") or 0,
                (r.get("size") or 0) / GIB if r.get("size") else 0.0,
                r["status"], r.get("seconds") or 0))
            if r["status"] == "MISMATCH":
                LOG.say("    expected sha256: %s" % (r.get("sha256_expected")
                                                     or r.get("blob_sha1_expected")))
                LOG.say("    actual   sha256: %s" % (r.get("sha256_actual")
                                                     or r.get("blob_sha1_actual")))
        complete = sum(1 for r in rows if r["status"] == "OK")
        LOG.say("  verdict: %s  (%d/%d files ok, %.1fs%s)" % (
            verdict.upper(), complete, len(rows), elapsed,
            ", %d .part in progress" % parts if parts else ""))
        LOG.say("")

    rec = {
        "unit": unit["name"], "kind": unit["kind"],
        "repo": unit["repo"], "rev": unit["rev"], "license": unit.get("license"),
        "verdict": verdict, "verifiedAt": iso_now(),
        "elapsed_s": round(elapsed, 2),
        "files": rows,
        "partFiles": parts,
        "allHashed": all(r["status"] in ("OK", "MISMATCH") for r in rows),
        "source": "scripts/fetch.py verify",
    }
    if write_record:
        atomic_write_json(verify_record_path(unit["name"]), rec)
    return verdict


def load_verify_record(unit_name):
    path = verify_record_path(unit_name)
    if not os.path.exists(lp(path)):
        return None
    try:
        return read_json(path)
    except Exception:
        return None


def presence(unit):
    """(complete_files, present_bytes, part_files) for a unit."""
    complete = 0
    present = 0
    parts = 0
    for f in unit["files"]:
        n = file_size(f["dest"])
        if n == f["size"]:
            complete += 1
            present += n
        elif n > 0:
            present += min(n, f["size"])
        else:
            p = file_size(f["dest"] + PART)
            if p > 0:
                parts += 1
                present += min(p, f["size"])
    return complete, present, parts


# --------------------------------------------------------------------------
# Index + Library README
# --------------------------------------------------------------------------

def build_index(units=None):
    units = units if units is not None else build_units()
    pm = get_manifest(PRIMARY_REPO, PRIMARY_REV)
    gguf_info = (pm.get("info", {}).get("gguf") or {})
    now = iso_now()
    free = disk_free(DEST)

    sets = {}
    engram = None
    meta = {"localPath": META_DIR, "files": []}
    for u in units:
        complete, present, parts = presence(u)
        rec = load_verify_record(u["name"])
        verified = bool(
            rec and rec.get("verdict") == "verified"
            and rec.get("rev") == u["rev"]
            and complete == len(u["files"])
        )
        total = unit_total(u)
        if u["kind"] == "set":
            rung = u.get("rung") or {}
            sets[u["name"]] = {
                "repo": u["repo"], "revision": u["rev"], "license": u.get("license"),
                "bytes": total, "files": len(u["files"]),
                "presentFiles": complete, "presentBytes": present,
                "partialFiles": parts,
                "verified": verified,
                "verdict": "verified" if verified else ("incomplete" if complete < len(u["files"]) else "unverified"),
                "verifiedAt": (rec or {}).get("verifiedAt"),
                "rungPass": bool(rung.get("pass")),
                "rungMetrics": {k: rung.get(k) for k in ("kl_to_stock", "pass")} if rung else {},
                "localPath": u["localPath"],
                "shards": [{
                    "file": os.path.basename(f["path"]), "bytes": f["size"],
                    "sha256": f["sha256"],
                    "present": file_size(f["dest"]) == f["size"],
                } for f in u["files"]],
            }
        elif u["kind"] == "engram":
            f = u["files"][0]
            engram = {
                "repo": u["repo"], "revision": u["rev"], "license": u.get("license"),
                "file": f["path"], "bytes": f["size"], "sha256": f["sha256"],
                "present": file_size(f["dest"]) == f["size"],
                "verified": verified, "verdict": "verified" if verified else "incomplete",
                "verifiedAt": (rec or {}).get("verifiedAt"),
                "sharedByRungs": u.get("sharedByRungs"),
                "localPath": f["dest"],
            }
        elif u["kind"] == "meta":
            meta["files"] = [{
                "path": f["path"], "bytes": f["size"],
                "blob_sha1": f.get("blob_sha1"),
                "present": file_size(f["dest"]) == f["size"],
                "sha256Recorded": None,
            } for f in u["files"]]
            meta["verified"] = verified
            meta["verdict"] = "verified" if verified else "incomplete"
            meta["verifiedAt"] = (rec or {}).get("verifiedAt")
            for row, f in zip(meta["files"], u["files"]):
                if rec:
                    for r in rec.get("files", []):
                        if os.path.basename(f["path"]) == r["file"]:
                            row["sha256Recorded"] = r.get("sha256_actual") or row.get("sha256Recorded")

    idx = {
        "schema": 1,
        "generatedBy": "scripts/fetch.py index",
        "generatedAt": now,
        "repo": PRIMARY_REPO,
        "revision": PRIMARY_REV,
        "repoUrl": "https://huggingface.co/" + PRIMARY_REPO,
        "libraryRoot": LIBRARY_ROOT,
        "modelDir": DEST,
        "metaDir": META_DIR,
        "license": "mit",
        "model": {
            "architecture": gguf_info.get("architecture"),
            "parameters": gguf_info.get("total"),
            "contextLength": gguf_info.get("context_length"),
            "fileSizeBytes": gguf_info.get("totalFileSize"),
            "lastModified": pm.get("info", {}).get("lastModified"),
            "usedStorageBytes": pm.get("info", {}).get("usedStorage"),
        },
        "sources": {
            "primary": {"repo": PRIMARY_REPO, "revision": PRIMARY_REV, "license": "mit"},
            "engram": {"repo": ENGRAM_REPO, "revision": ENGRAM_REV, "license": "mit",
                        "note": "shared Engram asset required by the Strata runtime; "
                                "same file for both rungs",
                        "sharedByRungs": ["IQ2_XXS", "IQ1_M"]},
        },
        "sets": sets,
        "engram": engram,
        "meta": meta,
        "skipped": {k: v for k, v in SKIPPED_SETS.items()},
        "reserveBytes": RESERVE,
        "freeBytes": free,
        "totalLibraryBytes": sum(s["bytes"] for s in sets.values())
                              + (engram["bytes"] if engram else 0),
        "allVerified": bool(sets) and all(s["verified"] for s in sets.values())
                       and bool(engram and engram["verified"])
                       and bool(meta.get("verified")),
        "notes": [
            "Download order: smalls -> engram -> IQ2_XXS -> IQ1_M.",
            "IQ2_XS intentionally not downloaded (gate failed).",
            "verified=true only when scripts/fetch.py verify re-hashed the file "
            "from disk and it matched the pinned manifest.",
        ],
    }
    atomic_write_json(INDEX_PATH, idx)
    write_models_readme(idx)
    return idx


def write_models_readme(idx):
    lines = []
    a = lines.append
    a("# Local HF model library")
    a("")
    a("Generated by `scripts/fetch.py index` at **%s**. Do not hand-edit; rerun the script." % idx["generatedAt"])
    a("")
    a("## %s" % idx["repo"])
    a("")
    a("| field | value |")
    a("| --- | --- |")
    a("| pinned revision | `%s` |" % idx["revision"])
    a("| license | %s |" % idx["license"])
    a("| architecture | %s |" % idx["model"].get("architecture"))
    a("| parameters | %s |" % idx["model"].get("parameters"))
    a("| context length | %s |" % idx["model"].get("contextLength"))
    a("| local dir | `%s` |" % idx["modelDir"])
    a("| free space now | %.2f GiB |" % (idx["freeBytes"] / GIB))
    a("| reserve floor | %.2f GiB |" % (idx["reserveBytes"] / GIB))
    a("")
    a("### Provenance (first downloaded)")
    a("")
    a("`meta/` holds the small files fetched from the pinned revision before any shard:")
    a("")
    for f in idx["meta"]["files"]:
        a("- `meta/%s` (%d B, %s)" % (f["path"], f["bytes"],
                                      "present" if f["present"] else "MISSING"))
    a("")
    a("### Engram (shared, from the base repo)")
    a("")
    e = idx.get("engram") or {}
    a("- repo: `%s`" % e.get("repo"))
    a("- revision: `%s`" % e.get("revision"))
    a("- license: %s" % e.get("license"))
    a("- file: `%s` (%s bytes)" % (e.get("file"), e.get("bytes")))
    a("- sha256: `%s`" % e.get("sha256"))
    a("- shared by both rungs (IQ2_XXS, IQ1_M) - the Strata runtime needs it beside the shards")
    a("- verification: **%s**" % ("VERIFIED" if e.get("verified") else "not yet verified"))
    a("")
    a("### Rungs")
    a("")
    a("| set | GiB | files | verified | rung gate |")
    a("| --- | --- | --- | --- | --- |")
    for name, s in idx["sets"].items():
        a("| %s | %.2f | %d/%d | %s | %s |" % (
            name, s["bytes"] / GIB, s["presentFiles"], s["files"],
            "YES" if s["verified"] else "no", "pass" if s["rungPass"] else "FAIL"))
    a("")
    for name in idx.get("skipped", {}):
        a("Skipped: **%s** - %s" % (name, idx["skipped"][name]))
        a("")
    a("### Verification rule")
    a("")
    a("`Library/index.json` sets `verified: true` only after `scripts/fetch.py verify`")
    a("re-hashed a complete set from disk and matched the pinned manifest sha256.")
    a("Incomplete downloads are reported as `incomplete`, never as verified.")
    a("")
    a("### Commands")
    a("")
    a("```")
    a("python scripts/fetch.py plan")
    a("python scripts/fetch.py fetch --set all")
    a("python scripts/fetch.py verify --set all")
    a("python scripts/fetch.py index")
    a("```")
    a("")
    a("JSONL download logs: `Library/logs/fetch-*.jsonl`. Verify records: `Library/logs/verify-*.json`.")
    ensure_dir(os.path.dirname(MODELS_README))
    tmp = MODELS_README + ".tmp"
    with open(lp(tmp), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(lp(tmp), lp(MODELS_README))


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_plan(args):
    LOG.say("NOTE: fetch.py is SUPERSEDED - the Lead owns downloading "
            "(Tools/runtime/fetch-library.ps1). This plan predates "
            "manifests/acceptance.json and its pin set; use scripts/check_pins.py.")
    LOG.say("")
    units = build_units(only=args.set, refresh=args.refresh,
                        repo_override=args.repo, rev_override=args.rev,
                        allow_failed=args.allow_failed, extra_file=args.file)
    pm = get_manifest(args.repo or PRIMARY_REPO, args.rev or PRIMARY_REV)
    em = get_manifest(ENGRAM_REPO, ENGRAM_REV)
    info = pm["info"]
    gguf = info.get("gguf") or {}
    rungs = {}
    try:
        rungs = get_rungs()
    except Exception:
        pass

    LOG.say("== SOURCES ==")
    LOG.say("primary : %s" % pm["repo"])
    LOG.say("          rev %s  license mit  gated=%s  lastModified=%s" % (
        pm["rev"], info.get("gated"), info.get("lastModified")))
    if gguf:
        LOG.say("          arch=%s params=%s ctx=%s" % (
            gguf.get("architecture"), gguf.get("total"), gguf.get("context_length")))
    LOG.say("engram  : %s" % em["repo"])
    LOG.say("          rev %s  license mit  file %s" % (em["rev"], ENGRAM_FILE))
    LOG.say("")

    LOG.say("== DOWNLOAD UNITS (order respected) ==")
    LOG.say(" #  %-9s %-8s %5s %16s %10s %10s %10s %-8s %-9s" % (
        "unit", "repo", "files", "bytes", "GiB", "present", "remaining", "rung", "eta@50"))
    need = 0
    for i, u in enumerate(units, 1):
        total = unit_total(u)
        present = unit_present(u)
        rem = unit_remaining(u)
        need += rem
        rung = u.get("rungPass")
        rung_s = "-" if rung is None else ("PASS" if rung else "FAIL")
        if u["kind"] == "engram":
            rung_s = "shared"
        eta = fmt_dur(rem / 50e6) if 50e6 else "--"
        LOG.say("%2d  %-9s %-8s %5d %16d %10.2f %10.2f %10.2f %-8s %-9s" % (
            i, u["name"], ("ista" if u["kind"] == "engram" else "atomic"),
            len(u["files"]), total, total / GIB, present / GIB, rem / GIB,
            rung_s, eta))
    for name, why in SKIPPED_SETS.items():
        if not args.allow_failed:
            LOG.say("    skipped: %-8s %s" % (name, why))
    LOG.say("")

    LOG.say("== SHARDS ==")
    for u in units:
        for f in u["files"]:
            present = max(0, file_size(f["dest"]))
            if present <= 0:
                present = max(0, file_size(f["dest"] + PART))
            LOG.say("  %-10s %-58s %10.2f GiB  sha256 %s  present %.2f" % (
                u["name"], os.path.basename(f["path"])[:58], f["size"] / GIB,
                (f["sha256"] or "-")[:16], min(present, f["size"]) / GIB))
    LOG.say("")

    free = disk_free(DEST)
    projected = free - need
    LOG.say("== DISK MATH ==")
    LOG.say("free now            : %10.2f GiB" % (free / GIB))
    LOG.say("needed (remaining)  : %10.2f GiB" % (need / GIB))
    LOG.say("projected free after: %10.2f GiB" % (projected / GIB))
    LOG.say("floor reserve       : %10.2f GiB" % (RESERVE / GIB))
    fit = projected >= RESERVE
    LOG.say("verdict             : %s" % ("FIT" if fit else "NO-FIT (would breach the 40 GiB floor)"))
    if not fit:
        LOG.say("ABORT: projected free space %.2f GiB < %.2f GiB reserve" % (
            projected / GIB, RESERVE / GIB))
        return 1
    return 0


def cmd_selftest(args):
    ok = True
    def check(label, cond, detail=""):
        nonlocal ok
        LOG.say("%-4s %-46s %s" % ("PASS" if cond else "FAIL", label, detail))
        if not cond:
            ok = False

    free = disk_free(DEST)
    check("library dir writable/free", free > RESERVE,
          "free %.2f GiB" % (free / GIB))

    for repo, rev in ((PRIMARY_REPO, PRIMARY_REV), (ENGRAM_REPO, ENGRAM_REV)):
        try:
            sha, info = resolve_revision(repo, rev)
            check("revision %s" % repo.split("/")[0], sha == rev.lower(),
                  "%s -> %s" % (rev[:12], sha[:12]))
            check("gated=false %s" % repo.split("/")[0], info.get("gated") is False)
            check("license mit %s" % repo.split("/")[0],
                  any(t == "license:mit" for t in (info.get("tags") or [])))
        except Exception as e:
            check("revision %s" % repo, False, str(e))

    m = get_manifest(PRIMARY_REPO, PRIMARY_REV)
    files = [e for e in m["tree"] if e.get("type") == "file"]
    ggufs = [e for e in files if e["path"].lower().endswith(".gguf")]
    sets = {}
    for e in ggufs:
        mm = GGUF_RE.search(e["path"])
        if mm:
            sets.setdefault(mm.group(1).upper(), []).append(e)
    check("primary tree shards", len(ggufs) == 12, "%d gguf" % len(ggufs))
    check("primary tree sets", sorted(sets) == ["IQ1_M", "IQ2_XXS", "IQ2_XS"],
          ", ".join(sorted(sets)))
    for name, lst in sorted(sets.items()):
        check("set %s 4 shards + lfs sha256" % name,
              len(lst) == 4 and all(entry_sha256(e) for e in lst),
              "%.2f GiB" % (sum(entry_size(e) for e in lst) / GIB))
    check("small files present", len([e for e in files if not e["path"].lower().endswith(".gguf")]) >= 4,
          "%d files" % len([e for e in files if not e["path"].lower().endswith(".gguf")]))

    em = get_manifest(ENGRAM_REPO, ENGRAM_REV)
    ef = [e for e in em["tree"] if e.get("path") == ENGRAM_FILE]
    check("engram file exists", len(ef) == 1)
    if ef:
        e = ef[0]
        check("engram size", entry_size(e) == 110595290816, "%d" % entry_size(e))
        check("engram sha256", entry_sha256(e) ==
              "3dac4c54893ad7aa89103c0028500eadc78e74112cef3a2930a97e67dc9fb4f3",
              entry_sha256(e)[:16])
    r = get_rungs()
    check("rung gate IQ2_XXS=pass", (r.get("IQ2_XXS") or {}).get("pass") is True)
    check("rung gate IQ1_M=pass", (r.get("IQ1_M") or {}).get("pass") is True)
    check("rung gate IQ2_XS=fail (skipped)", (r.get("IQ2_XS") or {}).get("pass") is False)

    # HTTP Range probe on a 1 MiB window of the first IQ2_XXS shard
    target = [e for e in sets.get("IQ2_XXS", [])][0]
    url = RESOLVE % (PRIMARY_REPO, PRIMARY_REV, quote_path(target["path"]))
    try:
        req = urllib.request.Request(url, headers=_headers({"Range": "bytes=0-1048575"}))
        with OPENER.open(req, timeout=90) as resp:
            body = resp.read()
            cr = resp.headers.get("Content-Range") or ""
        check("range GET -> 206", resp.status == 206, "status=%s cr=%r" % (resp.status, cr))
        check("range bytes == 1 MiB", len(body) == 1048576, "%d bytes" % len(body))
    except urllib.error.HTTPError as e:
        check("range GET -> 206", False, "http %d" % e.code)
    except Exception as e:
        check("range GET -> 206", False, str(e))

    LOG.say("")
    LOG.say("SELFTEST %s" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


def cmd_fetch(args):
    if args.parallel > 3:
        args.parallel = 3
    LOG.say("== fetch %s ==" % (args.set or args.file))
    LOG.say("started %s  dest=%s" % (iso_now(), DEST))
    units = build_units(only=args.set, refresh=args.refresh,
                        repo_override=args.repo, rev_override=args.rev,
                        allow_failed=args.allow_failed, extra_file=args.file)
    ensure_dir(DEST)
    ensure_dir(META_DIR)
    ensure_dir(LOG_DIR)

    # preflight disk budget for the selected units
    need = sum(unit_remaining(u) for u in units)
    free = disk_free(DEST)
    projected = free - need
    LOG.say("space preflight: free %.2f GiB, need %.2f GiB, projected %.2f GiB, floor %.2f GiB" % (
        free / GIB, need / GIB, projected / GIB, RESERVE / GIB))
    if projected < RESERVE:
        LOG.say("ABORT: projected free space %.2f GiB < %.2f GiB floor. Nothing started." % (
            projected / GIB, RESERVE / GIB))
        for u in units:
            jsonl(unit_log_path(u["name"]), {
                "ts": iso_now(), "event": "abort_space_preflight",
                "unit": u["name"], "free_bytes": free, "need_bytes": need,
                "reserve_bytes": RESERVE,
            })
        return 3

    prog = Progress(units)
    stop = threading.Event()
    mon = threading.Thread(target=monitor_loop, args=(prog, units, args, stop),
                           name="monitor", daemon=True)
    mon.start()

    results = {}
    verified_units = []
    failed_units = []
    try:
        tasks = []
        for u in units:
            LOG.say("queued %-8s %d files %10.2f GiB  %s@%s" % (
                u["name"], len(u["files"]), unit_total(u) / GIB, u["repo"], u["rev"][:12]))
            for f in u["files"]:
                tasks.append(Task(u, f, prog))
        LOG.say("")

        with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as ex:
            futs = {ex.submit(run_task, t, args, prog): t for t in tasks}
            for fut in as_completed(futs):
                t = futs[fut]
                u = t.unit
                try:
                    res = fut.result()
                except Aborted:
                    res = "aborted"
                except Exception as e:
                    res = "failed"
                    LOG.say("  [%s] FAILED %s: %s" % (u["name"], t.f["path"], e))
                results[(u["name"], t.f["path"])] = res
                if res == "ok":
                    LOG.say("  [%s] done %s (%.2f GiB)" % (
                        u["name"], os.path.basename(t.f["path"]), t.f["size"] / GIB))

                if all(results.get((u["name"], f["path"])) == "ok" for f in u["files"]):
                    LOG.say("  [%s] unit complete -> verifying from disk" % u["name"])
                    verdict = verify_unit(u, write_record=True)
                    if verdict == "verified":
                        verified_units.append(u["name"])
                        LOG.say("  [%s] VERIFIED -> updating Library/index.json" % u["name"])
                        try:
                            build_index(build_units())
                        except Exception as e:
                            LOG.say("  [%s] index update failed (non-fatal): %s" % (u["name"], e))
                    else:
                        failed_units.append(u["name"])
                        LOG.say("  [%s] verification says %s (index left unverified)" % (
                            u["name"], verdict.upper()))
    except KeyboardInterrupt:
        LOG.say("!! interrupted -- aborting workers, .part files kept for resume")
        prog.abort.set()
        prog.abort_reason = "interrupted by user"
    finally:
        stop.set()
        mon.join(timeout=15)
        prog.abort.set()

    LOG.say("")
    LOG.say("== fetch summary (%s) ==" % iso_now())
    for u in units:
        done = sum(1 for f in u["files"]
                   if results.get((u["name"], f["path"])) == "ok")
        complete, present, parts = presence(u)
        LOG.say("  %-8s %d/%d shards complete  %6.2f/%6.2f GiB  %s" % (
            u["name"], complete, len(u["files"]), present / GIB, unit_total(u) / GIB,
            "VERIFIED" if u["name"] in verified_units else "not verified"))
    free = disk_free(DEST)
    LOG.say("  free now: %.2f GiB" % (free / GIB))
    all_ok = all(u["name"] in verified_units for u in units)
    LOG.say("  result: %s" % ("ALL SELECTED UNITS VERIFIED" if all_ok else "INCOMPLETE"))
    return 0 if all_ok else (3 if prog.abort_reason else 4)


def cmd_verify(args):
    units = build_units(only=args.set, refresh=args.refresh,
                        repo_override=args.repo, rev_override=args.rev,
                        allow_failed=args.allow_failed, extra_file=args.file)
    verdicts = {}
    for u in units:
        verdicts[u["name"]] = verify_unit(u, write_record=True)
    LOG.say("== verify summary ==")
    any_fail = False
    any_incomplete = False
    for name, v in verdicts.items():
        LOG.say("  %-8s %s" % (name, v.upper()))
        if v == "failed":
            any_fail = True
        elif v == "incomplete":
            any_incomplete = True
    try:
        build_index()
        LOG.say("  Library/index.json updated")
    except Exception as e:
        LOG.say("  index update failed: %s" % e)
    if any_fail:
        return 1
    if any_incomplete:
        return 2
    return 0


def cmd_index(args):
    idx = build_index()
    LOG.say("wrote %s" % INDEX_PATH)
    LOG.say("wrote %s" % MODELS_README)
    for name, s in idx["sets"].items():
        LOG.say("  %-8s %6.2f GiB  %d/%d files  verified=%s" % (
            name, s["bytes"] / GIB, s["presentFiles"], s["files"], s["verified"]))
    e = idx.get("engram") or {}
    LOG.say("  %-8s %6.2f GiB  present=%s verified=%s" % (
        "engram", (e.get("bytes") or 0) / GIB, e.get("present"), e.get("verified")))
    LOG.say("  free %.2f GiB" % (idx["freeBytes"] / GIB))
    LOG.say("  allVerified=%s" % idx["allVerified"])
    return 0 if idx["allVerified"] else 2


def build_parser():
    p = argparse.ArgumentParser(
        prog="fetch.py",
        description="Resumable verified mirror of the DeepSeek-V4.1-Flash GSQ-RCO GGUF rungs + shared Engram.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "download order: smalls -> engram -> IQ2_XXS -> IQ1_M (IQ2_XS skipped: gate failed)\n"
            "exit codes: plan 0/1/2, fetch 0/3/4, verify 0/1/2, index 0/2\n"
        ))
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--set", default="all",
                        help="smalls|engram|IQ2_XXS|IQ1_M|IQ2_XS|all (default all)")
        sp.add_argument("--repo", default=None, help="override repo for the selected unit(s)")
        sp.add_argument("--rev", default=None, help="override revision/sha for the selected unit(s)")
        sp.add_argument("--file", default=None, help="ad-hoc single manifest path (with --repo/--rev)")
        sp.add_argument("--allow-failed", action="store_true",
                        help="include rungs whose gate failed (IQ2_XS)")
        sp.add_argument("--refresh", action="store_true", help="refresh manifest/API cache")

    sp = sub.add_parser("plan")
    common(sp)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("fetch")
    common(sp)
    sp.add_argument("--parallel", type=int, default=3, help="concurrent files (max 3, default 3)")
    sp.add_argument("--retries", type=int, default=8, help="retries per file (default 8)")
    sp.add_argument("--chunk", type=int, default=4 * MIB, help="read chunk bytes (default 4 MiB)")
    sp.add_argument("--timeout", type=float, default=120.0, help="socket timeout seconds")
    sp.add_argument("--interval", type=float, default=5.0, help="progress interval seconds (default 5)")
    sp.add_argument("--backoff", type=float, default=3.0, help="retry backoff base seconds")
    sp.add_argument("--max-backoff", type=float, default=90.0, dest="max_backoff")
    sp.add_argument("--log-file", default=os.path.join(LOG_DIR, "fetch-all.log"),
                    help="tee console output to this file")
    sp.set_defaults(func=cmd_fetch)

    sp = sub.add_parser("verify")
    common(sp)
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("index")
    common(sp)
    sp.set_defaults(func=cmd_index)

    sp = sub.add_parser("selftest")
    sp.set_defaults(func=cmd_selftest)
    return p


def main(argv):
    args = build_parser().parse_args(argv)
    if getattr(args, "log_file", None):
        LOG.open(os.path.join(LOG_DIR, args.log_file) if not os.path.isabs(args.log_file)
                 else args.log_file)
    ensure_dir(LOG_DIR)
    ensure_dir(DEST)
    ensure_dir(META_DIR)
    try:
        return args.func(args)
    finally:
        LOG.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
