#!/usr/bin/env python3
"""Nettoyage contrôlé phase 1 : caches, temporaires et artefacts reconstructibles.

Par défaut : dry-run. `--apply` exécute réellement les suppressions.
Le script refuse tout chemin hors des racines autorisées et conserve les
modèles (`huggingface`), le binaire Homebrew, Playwright et le build de
PKDiskAudit lui-même.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shutil
import subprocess
import time

HOME = os.path.expanduser("~")
TMP = os.environ.get("TMPDIR", "").rstrip("/")
TMP_PARENT = os.path.dirname(TMP) if TMP else ""
REPORT = os.path.expanduser("~/Library/Application Support/PKDiskAudit/report.json")
LOG_DIR = os.path.expanduser("~/Library/Logs/PKDiskAudit")

ALLOWED_ROOTS = [
    HOME + "/Library/Caches",
    HOME + "/.cache",
    TMP,
    TMP_PARENT + "/C" if TMP_PARENT else "",
    HOME + "/Documents",
    HOME + "/Desktop",
    HOME + "/Projects",
    HOME + "/Code",
    HOME + "/dev",
    HOME + "/Workspace",
    HOME + "/.npm/_cacache",
    HOME + "/.local/share/pnpm/store",
]

EXCLUDE_PATHS = {
    HOME + "/.cache/huggingface",
    HOME + "/Library/Caches/ms-playwright",
    HOME + "/Library/Caches/Homebrew",
    HOME + "/Documents/GitHub/PROJECTS/Macos_PKdiskAudit",
}
if TMP:
    EXCLUDE_PATHS.add(os.path.join(TMP, "opencode"))

CACHE_ROOTS = [
    HOME + "/Library/Caches",
    HOME + "/.cache",
    TMP,
    TMP_PARENT + "/C" if TMP_PARENT else "",
]
TEMP_ROOTS = {TMP, (TMP_PARENT + "/C") if TMP_PARENT else ""}


def du_bytes(path):
    try:
        out = subprocess.check_output(["du", "-sk", path], stderr=subprocess.DEVNULL)
        return int(out.split()[0]) * 1024
    except Exception:
        return 0


def free_bytes():
    """Espace libre réel du volume Data (mêmes chiffres que Finder)."""
    try:
        out = subprocess.check_output(["df", "-kP", "/System/Volumes/Data"]).decode()
        parts = out.strip().splitlines()[-1].split()
        return int(parts[3]) * 1024
    except Exception:
        return 0


def allowed(path):
    real = os.path.realpath(path)
    if real in EXCLUDE_PATHS:
        return False
    for excluded in EXCLUDE_PATHS:
        if real == excluded or real.startswith(excluded + os.sep):
            return False
    if real in ALLOWED_ROOTS:
        return False
    if not any(real.startswith(root + os.sep) for root in ALLOWED_ROOTS if root):
        return False
    base = os.path.basename(real)
    if base in ("huggingface", "opencode"):
        return False
    return True


def old_enough(path, hours):
    try:
        age = time.time() - os.stat(path).st_mtime
    except OSError:
        return False
    return age >= hours * 3600


def collect(report, include_clones, temp_hours):
    targets = {}
    for item in report.get("items", []):
        category = item.get("category")
        safety = item.get("safety")
        path = item.get("path")
        if not path:
            continue
        if category == "cache" and safety == "safe":
            targets[path] = "cache"
        elif category == "artifact" and safety == "safe":
            targets[path] = "artifact"
        elif category == "clone" and include_clones:
            targets[path] = "clone"

    # Complète avec tous les enfants des racines de cache (pas seulement le top 50)
    for root in CACHE_ROOTS:
        if not root or not os.path.isdir(root):
            continue
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in names:
            path = os.path.join(root, name)
            if not os.path.isdir(path) and not os.path.isfile(path):
                continue
            if du_bytes(path) < 2 * 1024 * 1024:
                continue
            if root in TEMP_ROOTS and not old_enough(path, temp_hours):
                continue
            targets.setdefault(path, "temp" if root in TEMP_ROOTS else "cache")

    rows = []
    for path, kind in targets.items():
        if not os.path.exists(path) or not allowed(path):
            continue
        rows.append({
            "path": path,
            "kind": kind,
            "bytes": du_bytes(path),
            "age_days": int((time.time() - os.stat(path).st_mtime) / 86400) if os.path.exists(path) else 0,
        })
    rows.sort(key=lambda r: -r["bytes"])
    return rows


def human(n):
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if n < 1024 or unit == "To":
            return "%.1f %s" % (n, unit)
        n /= 1024


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="exécuter les suppressions")
    parser.add_argument("--clones", action="store_true", help="inclure les clones de signature")
    parser.add_argument("--temp-hours", type=int, default=24, help="âge minimum des temporaires")
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    with open(REPORT, encoding="utf-8") as f:
        report = json.load(f)

    rows = collect(report, args.clones, args.temp_hours)
    total = sum(r["bytes"] for r in rows)
    by_kind = {}
    for row in rows:
        by_kind[row["kind"]] = by_kind.get(row["kind"], 0) + row["bytes"]
    detail = " · ".join("%s %s" % (kind, human(size)) for kind, size in sorted(by_kind.items(), key=lambda kv: -kv[1]))
    print("%d cibles · %s  (%s)" % (len(rows), human(total), detail))
    for row in rows[:40]:
        print("  %8s  %-9s  %s" % (human(row["bytes"]), row["kind"], row["path"]))
    if len(rows) > 40:
        print("  … +%d autres" % (len(rows) - 40))

    if not args.apply:
        print("\nDry-run. Relance avec --apply pour supprimer.")
        return 0

    os.makedirs(LOG_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    log_path = os.path.join(LOG_DIR, "cleanup-%s.log" % stamp)
    free_before = free_bytes()
    freed = 0
    removed = 0
    errors = []
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("# Nettoyage PKDiskAudit %s\n" % stamp)
        for row in rows:
            path = row["path"]
            size = du_bytes(path)
            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path)
                else:
                    os.remove(path)
                freed += size
                removed += 1
                log.write("OK\t%s\t%s\n" % (human(size), path))
                print("supprimé  %8s  %s" % (human(size), path))
            except Exception as exc:
                errors.append((path, str(exc)))
                log.write("ERR\t%s\t%s\n" % (path, exc))
        log.write("\nTotal: %s · %d cibles · %d erreurs\n" % (human(freed), removed, len(errors)))

    free_after = free_bytes()
    print("\nTerminé : %s libérés (mesure du volume : %s) · %d cibles · %d erreurs"
          % (human(freed), human(max(0, free_after - free_before)), removed, len(errors)))
    print("Journal : %s" % log_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
