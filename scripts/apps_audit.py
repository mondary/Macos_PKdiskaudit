#!/usr/bin/env python3
"""Audit des applications : croise Spotlight avec les traces réelles dans ~/Library.

L'identifiant de bundle est lu dans l'Info.plist de l'app (Spotlight ne le donne
pas toujours). Le croisement se fait par identifiant exact, par préfixe
d'éditeur, puis par nom. Sortie : tableau console + apps-audit.html.
Lecture seule.
"""

from __future__ import annotations

import datetime
import html
import json
import os
import plistlib
import subprocess
import time

HOME = os.path.expanduser("~")
LIB = os.path.join(HOME, "Library")
REPORT = os.path.expanduser("~/Library/Application Support/PKDiskAudit/report.json")
OUT_HTML = os.path.expanduser("~/Library/Application Support/PKDiskAudit/apps-audit.html")
OUT_JSON = os.path.expanduser("~/Library/Application Support/PKDiskAudit/apps-audit.json")

INDEX_DIRS = [
    "Application Support", "Containers", "Group Containers", "Caches",
    "HTTPStorages", "WebKit", "Saved Application State", "Preferences", "Logs",
]
CONFIDENCE = {"direct": 3, "éditeur": 2, "nom": 1, "": 0}


def index_dir(name):
    path = os.path.join(LIB, name)
    out = {}
    try:
        for entry in os.listdir(path):
            try:
                out[entry.lower()] = os.stat(os.path.join(path, entry)).st_mtime
            except OSError:
                pass
    except OSError:
        pass
    return out


def bundle_id(path):
    plist = os.path.join(path, "Contents", "Info.plist")
    try:
        with open(plist, "rb") as f:
            data = plistlib.load(f)
        return data.get("CFBundleIdentifier") or ""
    except Exception:
        return ""


def running_apps():
    names = set()
    try:
        out = subprocess.check_output(["lsappinfo", "list"], stderr=subprocess.DEVNULL).decode()
        for line in out.splitlines():
            if '"' in line:
                names.add(line.split('"')[1].lower())
    except Exception:
        pass
    return names


def human(n):
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or unit == "Go":
            return "%.1f %s" % (n, unit)
        n /= 1024


def main():
    with open(REPORT, encoding="utf-8") as f:
        report = json.load(f)
    apps = report.get("apps") or []

    indexes = {name: index_dir(name) for name in INDEX_DIRS}
    running = running_apps()
    now = time.time()

    rows = []
    for app in apps:
        path = app.get("path") or ""
        name = app.get("name") or ""
        bid = (bundle_id(path) or app.get("bundle_id") or "").lower()
        vendor = ".".join(bid.split(".")[:2]) if bid.count(".") >= 1 else ""
        norm_name = name.lower().replace(" ", "").replace("-", "")
        best = (0, "", "")

        for dirname, index in indexes.items():
            for candidate, mtime in index.items():
                confidence = ""
                if bid and (candidate == bid or candidate == bid + ".plist" or candidate.startswith(bid + ".")):
                    confidence = "direct"
                elif vendor and vendor != "com.apple" and candidate.startswith(vendor + "."):
                    confidence = "éditeur"
                elif norm_name and len(norm_name) >= 4 and norm_name in candidate.replace(" ", "").replace("-", ""):
                    confidence = "nom"
                if not confidence:
                    continue
                score = (CONFIDENCE[confidence], mtime)
                if score > (CONFIDENCE[best[2]] if best[2] else 0, best[0]):
                    best = (mtime, "%s/%s" % (dirname, candidate), confidence)

        spotlight = 0
        if app.get("last_used"):
            try:
                spotlight = datetime.datetime.fromisoformat(app["last_used"]).timestamp()
            except ValueError:
                spotlight = 0
        last = max(best[0], spotlight)
        days = int((now - last) / 86400) if last else None
        if days is None:
            verdict = "aucune trace"
        elif days <= 90:
            verdict = "actif"
        elif days <= 365:
            verdict = "ancien"
        else:
            verdict = "inactif"
        rows.append({
            "name": name,
            "bytes": app.get("bytes") or 0,
            "verdict": verdict,
            "days": days,
            "last": datetime.datetime.fromtimestamp(last).strftime("%Y-%m-%d") if last else "—",
            "source": best[1],
            "confidence": best[2],
            "spotlight": app.get("last_used") or "",
            "use_count": app.get("use_count") or 0,
            "running": name.lower() in running,
            "bundle_id": bid,
        })

    rows.sort(key=lambda r: -r["bytes"])
    total = sum(r["bytes"] for r in rows)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print("%d apps · %s" % (len(rows), human(total)))
    print("%-27s %8s %6s %-12s %-9s %s" % ("application", "taille", "jours", "verdict", "fiabilité", "trace"))
    for row in rows[:45]:
        days = "—" if row["days"] is None else str(row["days"])
        print("%-27s %8s %6s %-12s %-9s %s" % (
            row["name"][:27], human(row["bytes"]), days, row["verdict"],
            row["confidence"] or "—", row["source"][:36]))

    colors = {"actif": "#8fbf9f", "ancien": "#d9b27c", "inactif": "#d98b8b", "aucune trace": "#5d5d65"}
    trs = []
    for row in rows:
        color = colors[row["verdict"]]
        trs.append(
            "<tr data-search=\"%s\"><td class='name'>%s</td><td class='num'>%s</td>"
            "<td>%s</td><td><span class='v' style='color:%s'>%s</span></td>"
            "<td class='num'>%s</td><td>%s</td><td class='path'>%s</td></tr>" % (
                html.escape((row["name"] + " " + row["bundle_id"] + " " + row["source"]).lower()),
                html.escape(row["name"]), human(row["bytes"]), row["last"], color, row["verdict"],
                row["use_count"], html.escape(row["confidence"] or "—"), html.escape(row["source"] or "—"),
            ))
    doc = """<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">
<title>Applications — audit des traces</title>
<style>
body{background:#0a0a0b;color:#ececee;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text",Helvetica,Arial,sans-serif;padding:40px 48px;margin:0}
h1{font-size:28px;letter-spacing:-.02em;margin:0 0 6px}p{color:#8b8b93;font-size:13px;margin:0 0 20px}
input{width:100%%;background:#101012;border:1px solid #232327;color:#ececee;font-family:ui-monospace,Menlo,monospace;font-size:12px;padding:10px 14px;margin-bottom:14px}
table{width:100%%;border-collapse:collapse;border:1px solid #232327}
th{position:sticky;top:0;background:#141416;color:#5d5d65;font-family:ui-monospace,Menlo,monospace;font-size:9px;letter-spacing:.12em;text-transform:uppercase;text-align:left;padding:10px 12px;border-bottom:1px solid #232327}
td{padding:9px 12px;border-bottom:1px solid #232327;font-size:12.5px}
td.num{font-family:ui-monospace,Menlo,monospace;text-align:right;color:#8b8b93}
td.name{font-weight:500}td.path{font-family:ui-monospace,Menlo,monospace;font-size:10px;color:#5d5d65}
.v{font-family:ui-monospace,Menlo,monospace;font-size:10px;letter-spacing:.08em;text-transform:uppercase}
</style></head><body>
<h1>Applications — traces réelles</h1>
<p>Identifiant lu dans l'Info.plist, croisé avec conteneurs, caches, préférences et saved state. « Aucune trace » = rien de visible depuis l'installation, à confirmer par ton usage.</p>
<input id="q" placeholder="Filtrer…" oninput="f()">
<table><thead><tr><th>Application</th><th>Taille</th><th>Dernière</th><th>Verdict</th><th>Lancements</th><th>Fiabilité</th><th>Trace</th></tr></thead>
<tbody>%s</tbody></table>
<script>function f(){var q=document.getElementById('q').value.toLowerCase();document.querySelectorAll('tbody tr').forEach(function(r){r.style.display=(r.getAttribute('data-search')||'').includes(q)?'':'none'})}</script>
</body></html>""" % "".join(trs)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(doc)
    print("\nHTML : %s" % OUT_HTML)


if __name__ == "__main__":
    main()
