"""Point d'entrée CLI de PKDiskAudit."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

from . import report as report_mod
from . import scan as scan_mod
from . import util

DEFAULT_OUT = os.path.expanduser("~/Library/Application Support/PKDiskAudit")


def progress(phase, pct, label=""):
    print("PHASE %s %d %s" % (phase, int(pct), label), flush=True)


def cmd_scan(args):
    options = {
        "roots": [os.path.expanduser(r) for r in (args.roots.split(",") if args.roots else [util.HOME])],
        "apps": not args.no_apps,
        "models": not args.no_models,
        "artifacts": not args.no_artifacts,
        "large": args.large,
        "fast": args.fast,
    }
    data = scan_mod.scan(options, progress=progress if not args.quiet else None)
    out = args.json or os.path.join(args.out, "report.json")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, default=str)
    print("DONE %s" % out, flush=True)
    return 0


def cmd_report(args):
    with open(args.data, encoding="utf-8") as f:
        data = json.load(f)
    out = args.html or os.path.join(os.path.dirname(os.path.abspath(args.data)), "report.html")
    report_mod.render(data, out)
    print("DONE %s" % out, flush=True)
    return 0


def cmd_run(args):
    options = {
        "roots": [os.path.expanduser(r) for r in (args.roots.split(",") if args.roots else [util.HOME])],
        "apps": not args.no_apps,
        "models": not args.no_models,
        "artifacts": not args.no_artifacts,
        "large": args.large,
        "fast": args.fast,
    }
    os.makedirs(args.out, exist_ok=True)
    data = scan_mod.scan(options, progress=progress if not args.quiet else None)
    json_path = args.json or os.path.join(args.out, "report.json")
    html_path = args.html or os.path.join(args.out, "report.html")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1, default=str)
    report_mod.render(data, html_path)
    if args.open:
        util.run(["open", html_path], timeout=30)
    print("DONE %s %s" % (json_path, html_path), flush=True)
    return 0


def cmd_doctor(args):
    info = {
        "engine": scan_mod.ENGINE_VERSION,
        "home": util.HOME,
        "fda_likely_granted": util.fda_likely_granted(),
        "disk": util.disk_info(),
        "volume": util.volume_info("/"),
        "tools": {name: util.which(name) for name in ("du", "find", "sqlite3", "mdls", "system_profiler", "brew", "tmutil", "diskutil")},
        "out": DEFAULT_OUT,
    }
    print(json.dumps(info, ensure_ascii=False, indent=1))
    return 0


def cmd_version(args):
    print("pkdisk %s" % scan_mod.ENGINE_VERSION)
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="pkdisk", description="Audit disque macOS en lecture seule.")
    p.add_argument("--version", action="version", version="pkdisk %s" % scan_mod.ENGINE_VERSION)
    sub = p.add_subparsers(dest="command")

    def add_common(sp):
        sp.add_argument("--out", default=DEFAULT_OUT, help="dossier de sortie")
        sp.add_argument("--json", help="chemin du JSON")
        sp.add_argument("--html", help="chemin du HTML")
        sp.add_argument("--roots", help="racines à scanner, séparées par des virgules")
        sp.add_argument("--fast", action="store_true", help="scan rapide (sans apps/modèles/artefacts)")
        sp.add_argument("--no-apps", action="store_true")
        sp.add_argument("--no-models", action="store_true")
        sp.add_argument("--no-artifacts", action="store_true")
        sp.add_argument("--large", action="store_true",
                        help="chercher aussi les gros fichiers anciens (plus lent)")
        sp.add_argument("--quiet", action="store_true")

    sp = sub.add_parser("scan", help="scanner et écrire le JSON")
    add_common(sp)
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("report", help="générer le HTML depuis un JSON")
    sp.add_argument("data", help="fichier report.json")
    sp.add_argument("--html", help="fichier HTML de sortie")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("run", help="scanner puis générer le rapport")
    add_common(sp)
    sp.add_argument("--open", action="store_true", help="ouvrir le rapport dans le navigateur")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("doctor", help="vérifier l'environnement")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("version", help="afficher la version")
    sp.set_defaults(func=cmd_version)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("interrompu", file=sys.stderr)
        return 130
    except Exception as exc:
        print("ERREUR %s: %s" % (type(exc).__name__, exc), file=sys.stderr, flush=True)
        return 1
