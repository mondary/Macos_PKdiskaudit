#!/usr/bin/env python3
"""Suppression contrôlée d'une liste de chemins générés (mode review).

Chaque chemin est vérifié :
  - existe ;
  - se trouve sous une racine autorisée ;
  - n'est pas dans la liste de protection ;
  - n'est pas suivi par Git (sinon on refuse : c'est du source).

Dry-run par défaut. `--apply` exécute. Journal dans ~/Library/Logs/PKDiskAudit.
"""

from __future__ import annotations

import argparse
import datetime
import os
import subprocess
import sys

HOME = os.path.expanduser("~")
LOG_DIR = os.path.expanduser("~/Library/Logs/PKDiskAudit")

ALLOWED_ROOTS = [
    HOME + "/Documents",
    HOME + "/Desktop",
    HOME + "/Library",
    HOME + "/.cache",
    HOME + "/.local",
    "/Applications",
]

PROTECTED = [
    HOME + "/Documents/GitHub/PROJECTS/Macos_PKdiskaudit",
    HOME + "/Documents/GitHub/PROJECTS/Macos_PKmotion/vendor",
    HOME + "/Documents/GitHub/PROJECTS/Macos_PKvoicecloner/node_modules",
    HOME + "/Documents/GitHub/PROJECTS/Macos_PKmonitor/dist",
]


def du_bytes(path):
    try:
        out = subprocess.check_output(["du", "-sk", path], stderr=subprocess.DEVNULL)
        return int(out.split()[0]) * 1024
    except Exception:
        return 0


def free_bytes():
    try:
        out = subprocess.check_output(["df", "-kP", "/System/Volumes/Data"]).decode()
        return int(out.strip().splitlines()[-1].split()[3]) * 1024
    except Exception:
        return 0


def human(n):
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if n < 1024 or unit == "To":
            return "%.1f %s" % (n, unit)
        n /= 1024


def real(path):
    return os.path.realpath(path)


def is_protected(path):
    realpath = real(path)
    return any(realpath == p or realpath.startswith(p + os.sep) for p in PROTECTED)


def is_allowed(path):
    realpath = real(path)
    if realpath in ALLOWED_ROOTS:
        return False
    return any(realpath.startswith(root + os.sep) for root in ALLOWED_ROOTS if root)


def git_repo(path):
    probe = path if os.path.isdir(path) else os.path.dirname(path)
    result = subprocess.run(
        ["git", "-C", probe, "rev-parse", "--show-toplevel"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        return None
    return result.stdout.decode().strip()


def is_tracked(path):
    root = git_repo(path)
    if not root:
        return False
    rel = os.path.relpath(real(path), root)
    result = subprocess.run(
        ["git", "-C", root, "ls-files", "--", rel],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    return bool(result.stdout.decode().strip())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", required=True, help="fichier de chemins, un par ligne")
    parser.add_argument("--apply", action="store_true", help="exécuter les suppressions")
    args = parser.parse_args()

    with open(os.path.expanduser(args.list), encoding="utf-8") as f:
        paths = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    paths = [os.path.expanduser(p) for p in paths]

    rows = []
    skipped = []
    for path in paths:
        if not os.path.exists(path):
            skipped.append((path, "introuvable"))
            continue
        if not is_allowed(path):
            skipped.append((path, "hors racine autorisée"))
            continue
        if is_protected(path):
            skipped.append((path, "protégé"))
            continue
        if is_tracked(path):
            skipped.append((path, "suivi par Git (source)"))
            continue
        rows.append({"path": path, "bytes": du_bytes(path)})
    rows.sort(key=lambda r: -r["bytes"])

    total = sum(r["bytes"] for r in rows)
    print("%d cibles · %s" % (len(rows), human(total)))
    for row in rows:
        print("  %9s  %s" % (human(row["bytes"]), row["path"]))
    for path, reason in skipped:
        print("  ignoré (%s) : %s" % (reason, path))

    if not args.apply:
        print("\nDry-run. Relance avec --apply pour supprimer.")
        return 0

    os.makedirs(LOG_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M")
    log_path = os.path.join(LOG_DIR, "cleanup-review-%s.log" % stamp)
    before = free_bytes()
    freed = 0
    removed = 0
    errors = []
    with open(log_path, "w", encoding="utf-8") as log:
        log.write("# Nettoyage review PKDiskAudit %s\n" % stamp)
        for row in rows:
            path = row["path"]
            size = du_bytes(path)
            result = subprocess.run(["rm", "-rf", path], stderr=subprocess.PIPE)
            if result.returncode == 0 and not os.path.exists(path):
                freed += size
                removed += 1
                log.write("OK\t%s\t%s\n" % (human(size), path))
                print("supprimé  %9s  %s" % (human(size), path))
            else:
                errors.append((path, result.stderr.decode()[:120]))
                log.write("ERR\t%s\t%s\n" % (path, result.stderr.decode()[:120]))
        log.write("\nTotal: %s · %d cibles · %d erreurs\n" % (human(freed), removed, len(errors)))

    after = free_bytes()
    print("\nTerminé : %s libérés (volume : %s) · %d cibles · %d erreurs"
          % (human(freed), human(max(0, after - before)), removed, len(errors)))
    print("Journal : %s" % log_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
