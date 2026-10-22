"""Génération du rapport HTML autonome à partir du JSON pkdisk."""

from __future__ import annotations

import html
import json
import os
import sys
from collections import OrderedDict

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
REPORT_DIR = os.path.join(ROOT, "report")


def load_asset(name, env_var=None):
    """Charge un fichier de `report/`, que le moteur soit dans le dépôt ou
    empaqueté par PyInstaller. Le contenu est inliné : le rapport reste
    autonome, sans requête réseau ni fichier voisin."""
    candidates = []
    override = os.environ.get(env_var) if env_var else None
    if override:
        candidates.append(override)
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, name))
    candidates.append(os.path.join(REPORT_DIR, name))
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            with open(candidate, encoding="utf-8") as f:
                return f.read()
    return ""


def load_css():
    return load_asset("style.css", "PKDISKAUDIT_CSS")


def load_js():
    return load_asset("rooms.js", "PKDISKAUDIT_JS")


# --------------------------------------------------------------------------
# Formatage

def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def gb(n):
    n = float(n or 0)
    if n >= 1024 ** 3:
        return ("%.1f Go" % (n / 1024 ** 3)).replace(".", ",")
    if n >= 1024 ** 2:
        return ("%.0f Mo" % (n / 1024 ** 2))
    return ("%.0f Ko" % (n / 1024))


def gb_short(n):
    return gb(n).replace(" Go", "").replace(" Mo", "")


def num(n):
    return f"{int(n or 0):,}".replace(",", " ")


def pct(part, total):
    if not total:
        return 0
    return max(0.0, min(100.0, part * 100.0 / total))


def human_date(value):
    if not value:
        return "—"
    return str(value)[:10]


# --------------------------------------------------------------------------
# Treemap

COLORS = {
    "dev": "#333b46",
    "apps": "#3d382f",
    "system": "#2b2b30",
    "media": "#2f3b35",
    "cache": "#3a2f36",
    "models": "#3b3542",
}


def binary_treemap(items, x, y, w, h):
    if len(items) == 1:
        return [(x, y, w, h, items[0])]
    total = sum(i["bytes"] for i in items)
    best = None
    for k in range(1, len(items)):
        a = sum(i["bytes"] for i in items[:k])
        b = total - a
        if w >= h:
            wa, wb = w * a / total, w * b / total
            ratio = max(wa / h, h / wa, wb / h, h / wb)
        else:
            ha, hb = h * a / total, h * b / total
            ratio = max(w / ha, ha / w, w / hb, hb / w)
        if best is None or ratio < best[0]:
            best = (ratio, k)
    k = best[1]
    a = sum(i["bytes"] for i in items[:k])
    frac = a / total
    if w >= h:
        return (binary_treemap(items[:k], x, y, w * frac, h)
                + binary_treemap(items[k:], x + w * frac, y, w * (1 - frac), h))
    return (binary_treemap(items[:k], x, y, w, h * frac)
            + binary_treemap(items[k:], x, y + h * frac, w, h * (1 - frac)))


def treemap_cells(entries, report=None):
    report = report or {}
    hints = {
        "Documents": "GitHub + projets",
        "Desktop": "PKadmin",
        "Library": "Application Support",
        "/opt": "Homebrew",
    }
    # Notes dynamiques quand les données sont disponibles
    items_all = report.get("items") or []
    models = report.get("models") or []
    db = next((i for i in items_all if (i.get("path") or "").endswith("opencode.db")), None)
    if db:
        meta = db.get("meta") or {}
        total_db = (meta.get("live_bytes") or 0) + (meta.get("dead_bytes") or 0)
        hints[".local"] = "opencode.db %s" % gb(total_db)
    hf = [m for m in models if "/huggingface/" in (m.get("path") or "")]
    if hf:
        hints[".cache"] = "Hugging Face %s" % gb(sum(m["bytes"] for m in hf))
    apps = report.get("apps") or []
    if apps:
        hints["/Applications"] = "%d apps" % len(apps)
    var_cache = sum(i["bytes"] for i in items_all if (i.get("path") or "").startswith("/private/var"))
    if var_cache:
        hints["/private/var"] = "temporaires %s" % gb(var_cache)

    items = []
    for e in entries:
        if e["bytes"] < 50 * 1024 * 1024:
            continue
        note = hints.get(e.get("label")) or hints.get(e.get("name")) or ""
        if not note:
            note = {
                "apps": "Applications installées",
                "dev": "Projets et outils",
                "system": "Système et données",
                "media": "Documents et médias",
                "cache": "Caches",
                "models": "Modèles locaux",
            }.get(e.get("kind"), "")
        items.append({
            "name": e.get("label") or e.get("name"),
            "bytes": e["bytes"],
            "kind": e.get("kind", "system"),
            "note": note,
            "path": e.get("path", ""),
        })
    items.sort(key=lambda i: -i["bytes"])
    if len(items) > 12:
        rest = items[11:]
        items = items[:11] + [{
            "name": "Autres",
            "bytes": sum(i["bytes"] for i in rest),
            "kind": "system",
            "note": "%d dossiers" % len(rest),
            "path": "",
        }]
    return items


def render_treemap(items, width=1000, height=440):
    if not items:
        return ""
    total = sum(i["bytes"] for i in items)
    rects = binary_treemap(sorted(items, key=lambda i: -i["bytes"]), 0, 0, width, height)
    out = []
    for (x, y, w, h, item) in rects:
        pad = 3
        big = w > 150 and h > 78
        small = w > 92 and h > 46
        label = ""
        if big:
            label = (f'<span class="tm-name">{esc(item["name"])}</span>'
                     f'<span class="tm-gb">{gb(item["bytes"])}</span>'
                     f'<span class="tm-note">{esc(item["note"])}</span>')
        elif small:
            label = (f'<span class="tm-name sm">{esc(item["name"])}</span>'
                     f'<span class="tm-gb sm">{gb(item["bytes"])}</span>')
        title = "%s — %s · %s" % (item["name"], gb(item["bytes"]), item["note"])
        out.append(
            f'<div class="tm-cell" title="{esc(title)}" '
            f'style="left:calc({x / width * 100}% + {pad}px);top:calc({y / height * 100}% + {pad}px);'
            f'width:calc({w / width * 100}% - {pad * 2}px);height:calc({h / height * 100}% - {pad * 2}px);'
            f'background:{COLORS.get(item["kind"], COLORS["system"])}">{label}</div>')
    return "\n".join(out)


# --------------------------------------------------------------------------
# Rooms

def icon(paths):
    return (
        '<svg viewBox="0 0 24 24" width="24" height="24" fill="none" '
        'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
        'stroke-linejoin="round" aria-hidden="true">%s</svg>' % paths
    )


ROOMS = [
    ("overview", "Carte", icon(
        '<circle cx="12" cy="12" r="9"/><path d="M12 3v9h9"/>')),
    ("findings", "Gisement", icon(
        '<path d="M12 3 3 7.4l9 4.4 9-4.4L12 3Z"/>'
        '<path d="m3 12.2 9 4.4 9-4.4"/><path d="m3 16.8 9 4.4 9-4.4"/>')),
    ("items", "Détail", icon(
        '<path d="M8.5 6h12M8.5 12h12M8.5 18h12"/>'
        '<circle cx="3.6" cy="6" r="1.1"/><circle cx="3.6" cy="12" r="1.1"/>'
        '<circle cx="3.6" cy="18" r="1.1"/>')),
    ("apps", "Apps", icon(
        '<rect x="3" y="3" width="7.5" height="7.5" rx="1.6"/>'
        '<rect x="13.5" y="3" width="7.5" height="7.5" rx="1.6"/>'
        '<rect x="3" y="13.5" width="7.5" height="7.5" rx="1.6"/>'
        '<rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.6"/>')),
    ("models", "Modèles", icon(
        '<path d="M12 3 4 7.5v9L12 21l8-4.5v-9L12 3Z"/>'
        '<path d="m4 7.5 8 4.5 8-4.5"/><path d="M12 12v9"/>')),
    ("zombies", "Zombies", icon(
        '<path d="M5 20V11a7 7 0 0 1 14 0v9l-2.3-1.6L14.4 20 12 18.4 9.6 20 7.3 18.4 5 20Z"/>'
        '<circle cx="9.3" cy="10.5" r=".9"/><circle cx="14.7" cy="10.5" r=".9"/>')),
    ("plan", "Plan", icon(
        '<path d="M9 6h12M9 12h12M9 18h12"/>'
        '<path d="m3 6 1.6 1.6L7 5"/><path d="m3 12 1.6 1.6L7 11"/>'
        '<path d="m3 18 1.6 1.6L7 17"/>')),
]


def render_rooms_nav():
    tabs = []
    for index, (rid, label, svg) in enumerate(ROOMS, 1):
        active = index == 1
        tabs.append(
            f'<button class="room-tab" type="button" role="tab" id="tab-{rid}" '
            f'data-room="{rid}" aria-controls="{rid}" aria-selected="{str(active).lower()}" '
            f'tabindex="{0 if active else -1}" title="Raccourci : {index}">'
            f'{svg}<span>{esc(label)}</span></button>'
        )
    hint = "1–%d" % len(ROOMS)
    return f"""
  <nav class="rooms" aria-label="Sections du rapport">
    <div class="rooms-in">
      <div class="rooms-scroll" role="tablist" aria-label="Sections du rapport">
        {''.join(tabs)}
      </div>
      <div class="rooms-side">
        <span class="rooms-hint" aria-hidden="true">{hint}</span>
        <button class="rooms-all" type="button" aria-pressed="false">Tout déplier</button>
      </div>
    </div>
  </nav>"""


# --------------------------------------------------------------------------
# Sections

def render_groups(groups):
    if not groups:
        return '<p class="s-sub">Aucun poste récupérable détecté.</p>'
    max_bytes = max(g["bytes"] for g in groups)
    rows = []
    for g in groups:
        kind = g.get("safety", "review")
        apparent = bool(g.get("apparent"))
        badge = "APPARENT" if apparent else {"safe": "SANS RISQUE", "review": "À ARBITRER", "protected": "PROTÉGÉ"}.get(kind, "À ARBITRER")
        badge_class = "review" if apparent else kind
        count = g.get("count", 0)
        count_txt = ("%s élément%s" % (num(count), "s" if count > 1 else "")) if count else ""
        size_txt = ("≈ " if apparent else "") + gb(g.get("bytes"))
        rows.append(f"""
      <div class="group">
        <div class="g-head">
          <span class="g-name">{esc(g.get("title"))}</span>
          <span class="g-count">{esc(count_txt)}</span>
          <span class="badge {badge_class}">{badge}</span>
          <span class="g-gb">{size_txt}</span>
        </div>
        <div class="g-bar"><i class="{badge_class}" style="width:{g['bytes'] / max_bytes * 100:.1f}%"></i></div>
        <p class="g-detail">{esc(g.get("reason"))}</p>
      </div>""")
    return "".join(rows)


ACTION_LABELS = {
    "delete": "Supprimer",
    "vacuum": "VACUUM",
    "uninstall": "Désinstaller",
    "reveal": "Révéler",
    "brew_cleanup": "brew cleanup",
    "empty_trash": "Vider",
}


def render_items(items, limit=60):
    if not items:
        return ""
    rows = []
    for it in items[:limit]:
        kind = it.get("safety", "review")
        badge = {"safe": "SÛR", "review": "À VOIR", "protected": "PROTÉGÉ"}.get(kind, "À VOIR")
        action = ACTION_LABELS.get(it.get("action"), it.get("action") or "")
        meta = it.get("meta") or {}
        note = it.get("reason", "")
        if meta.get("project"):
            note = os.path.basename(meta["project"]) + " · " + note
        rows.append(f"""
        <tr data-search="{esc((it.get('title') or '') + ' ' + (it.get('path') or '') + ' ' + (note or '')).lower()}">
          <td class="name">{esc(it.get("title"))}</td>
          <td class="path" title="{esc(it.get('path'))}">{esc(it.get("path"))}</td>
          <td class="num">{gb(it.get("bytes"))}</td>
          <td><span class="badge {kind}">{badge}</span></td>
          <td class="num">{esc(action)}</td>
        </tr>""")
    more = len(items) - limit
    note = (f'<p class="s-note" style="padding:12px 14px">+ {more} autres postes dans le JSON.</p>'
            if more > 0 else "")
    return f"""
    <div class="toolbar">
      <input class="search" id="items-search" placeholder="Filtrer les postes (chemin, nom, catégorie)…" oninput="filterTable('items-search','items-table')">
    </div>
    <div class="table-wrap">
      <table id="items-table">
        <thead><tr><th>Poste</th><th>Chemin</th><th>Taille</th><th>Risque</th><th>Action</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
      {note}
    </div>"""


def render_apps(apps):
    if not apps:
        return '<p class="s-sub">Inventaire des applications désactivé (mode rapide).</p>'
    rows = []
    for a in apps:
        days = a.get("days_since_use")
        use = a.get("use_count") or 0
        last = human_date(a.get("last_used"))
        if a.get("last_used") and days is not None:
            if days <= 30:
                pill = '<span class="pill recent">récent</span>'
            elif days > 365:
                pill = '<span class="pill unknown">&gt; 1 an</span>'
            else:
                pill = ""
            last_txt = "%s" % last
        else:
            pill = '<span class="pill unknown">inconnu</span>'
            last_txt = "—"
        source = {
            "apple": "Apple",
            "mac_app_store": "App Store",
            "identified_developer": "Tiers",
            "unknown": "—",
        }.get(a.get("source"), a.get("source") or "—")
        rows.append(f"""
        <tr data-search="{esc((a.get('name') or '') + ' ' + (a.get('bundle_id') or '') + ' ' + (a.get('path') or '')).lower()}">
          <td class="name">{esc(a.get("name"))}</td>
          <td class="num">{gb(a.get("bytes"))}</td>
          <td>{last_txt} {pill}</td>
          <td class="num">{num(use)}</td>
          <td>{esc(source)}</td>
        </tr>""")
    return f"""
    <div class="toolbar">
      <input class="search" id="apps-search" placeholder="Chercher une application…" oninput="filterTable('apps-search','apps-table')">
      <button class="btn" onclick="toggleTable('apps-table', this)">Tout afficher</button>
    </div>
    <div class="table-wrap">
      <table id="apps-table">
        <thead><tr><th>Application</th><th>Taille</th><th>Dernière utilisation</th><th>Lancements</th><th>Source</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>"""


def render_models(models):
    if not models:
        return '<p class="s-sub">Aucun modèle local détecté.</p>'
    rows = []
    for m in models:
        rows.append(f"""
        <tr>
          <td class="name">{esc(m.get("name"))}</td>
          <td>{esc(m.get("kind") or "Modèle local")}</td>
          <td class="num">{gb(m.get("bytes"))}</td>
          <td>{human_date(m.get("last_modified"))}</td>
          <td>{esc(m.get("source") or "—")}</td>
        </tr>""")
    return f"""
    <div class="table-wrap">
      <table>
        <thead><tr><th>Modèle</th><th>Usage</th><th>Taille</th><th>Téléchargé</th><th>Source</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>"""


def render_zombies(z, fast=False):
    dash = "—"
    cards = [
        (dash if fast else num(z.get("apps")), "applications", "%s au total. %s sans trace d'utilisation." % (gb(z.get("apps_bytes")), num(z.get("apps_unknown")))),
        (num(z.get("cache_dirs")), "caches", "%s de caches et temporaires." % gb(z.get("cache_bytes"))),
        (dash if fast else num(z.get("artifacts")), "artefacts de build", "%s de node_modules, target, build…" % gb(z.get("artifacts_bytes"))),
        (dash if fast else num(z.get("models")), "modèles IA", "%s de poids locaux." % gb(z.get("models_bytes"))),
        (num(z.get("sessions")), "sessions OpenCode", "%s messages, %s parties." % (num(z.get("messages")), num(z.get("parts")))),
        (gb(z.get("db_dead_bytes")), "pages mortes SQLite", "Récupérables par VACUUM, sans perdre une session."),
        (gb(z.get("chrome_clone_bytes")), "clones de signature", "Taille apparente : blocs APFS partagés avec l'app d'origine."),
        (num(z.get("vms")), "machines virtuelles", "%s d'images disque." % gb(z.get("vm_bytes"))),
    ]
    return "\n".join(f"""
      <div class="z-card">
        <div class="z-num">{esc(n)}</div>
        <div class="z-label">{esc(l)}</div>
        <p>{esc(d)}</p>
      </div>""" for n, l, d in cards)


def render_plan(groups):
    safe = [g for g in groups if g.get("safety") == "safe"]
    db = [g for g in groups if g.get("id") == "database"]
    review = [g for g in groups if g.get("safety") == "review" and g.get("id") != "database" and not g.get("apparent")]
    phase1 = sum(g["bytes"] for g in safe)
    phase2 = sum(g["bytes"] for g in db)
    phase3 = sum(g["bytes"] for g in review)

    def list_items(items, limit=5):
        out = []
        for g in items[:limit]:
            out.append("<li><b>%s</b> — %s</li>" % (esc(g["title"]), gb(g["bytes"])))
        if len(items) > limit:
            out.append("<li>+ %d autres postes</li>" % (len(items) - limit))
        return "".join(out)

    return f"""
      <div class="step">
        <div class="n">PHASE 01</div>
        <h3>Le cleanup évident</h3>
        <div class="gain">+{gb(phase1)}</div>
        <ul>{list_items(safe)}</ul>
      </div>
      <div class="step">
        <div class="n">PHASE 02</div>
        <h3>La base OpenCode</h3>
        <div class="gain">+{gb(phase2) if phase2 else "—"}</div>
        <ul>
          <li>Fermer OpenCode</li>
          <li><b>VACUUM</b> de opencode.db</li>
          <li>Compacte sans supprimer de session</li>
          <li>Vérifier l'intégrité après coup</li>
        </ul>
      </div>
      <div class="step">
        <div class="n">PHASE 03</div>
        <h3>Les arbitrages</h3>
        <div class="gain">+{gb(phase3)}</div>
        <ul>{list_items(review)}</ul>
      </div>"""


# --------------------------------------------------------------------------
# Assemblage

def render(report, out_path):
    disk = report.get("disk") or {}
    summary = report.get("summary") or {}
    host = report.get("host") or {}
    tree = report.get("tree") or []
    groups = report.get("groups") or []
    items = report.get("items") or []
    apps = report.get("apps") or []
    models = report.get("models") or []
    zombies = report.get("zombies") or {}
    partial = report.get("partial_sections") or []
    fast = bool(report.get("fast"))

    total = disk.get("total") or 1
    used = disk.get("used") or 0
    free = disk.get("free") or 0
    reserved = max(0, total - used - free)
    used_pct = disk.get("percent") or pct(used, total)

    # Segments du disque
    home = sum(e["bytes"] for e in tree if e.get("path", "").startswith(os.path.expanduser("~")))
    apps_b = sum(e["bytes"] for e in tree if e.get("path") == "/Applications")
    var_b = sum(e["bytes"] for e in tree if e.get("path") == "/private/var")
    opt_b = sum(e["bytes"] for e in tree if e.get("path") == "/opt")
    lib_b = sum(e["bytes"] for e in tree if e.get("path") in ("/Library", "/Users/Shared"))
    measured = home + apps_b + var_b + opt_b + lib_b
    other = max(0, used - measured)
    system_b = lib_b + other

    def w(part):
        return pct(part, total)

    safe = summary.get("safe_bytes") or 0
    review = summary.get("review_bytes") or 0
    projected = summary.get("projected_free_bytes") or free

    scan_note = ""
    if partial or not report.get("fda_likely_granted", True):
        missing = ", ".join(partial) if partial else "permissions"
        scan_note = f"""
    <div class="banner">
      <div>
        <b>Scan partiel.</b> Certains dossiers n'ont pas pu être lus ({esc(missing)}).
        Donne <b>Full Disk Access</b> à l'app dans Réglages Système → Confidentialité et sécurité
        pour un inventaire complet. Les tailles affichées restent des minimums.
      </div>
    </div>"""

    treemap_items = treemap_cells(tree, report)
    # Ajoute la part non attribuée pour que la carte couvre le disque utilisé
    unattributed = max(0, used - sum(e["bytes"] for e in tree))
    if unattributed > 100 * 1024 * 1024:
        treemap_items.append({
            "name": "Non attribué",
            "bytes": unattributed,
            "kind": "system",
            "note": "Volumes système, métadonnées APFS",
            "path": "",
        })
    treemap_items.sort(key=lambda i: -i["bytes"])

    rank_rows = "".join(
        f'<div class="rank-row"><div class="rank-top"><span>{esc(e.get("label") or e.get("name"))}</span>'
        f'<span>{gb(e["bytes"])}</span></div>'
        f'<div class="rank-bar"><i style="width:{e["bytes"] / max(1, tree[0]["bytes"]) * 100:.1f}%"></i></div></div>'
        for e in tree[:8]
    )

    body = f"""
  <div class="eyebrow">Audit disque — <b>{esc(host.get("model"))}</b> · macOS {esc(host.get("os_version"))} · {gb(total)} · {esc(human_date(report.get("generated_at")))}</div>
  <h1>{gb(total).replace(" Go", " Go.")}<br><em>{gb(free)} libres.</em></h1>
  <p class="lede">Ce disque n'est pas plein de tes documents. Il est plein de <strong>caches, de builds et de bases de données qui n'ont jamais rendu la place</strong>.
  Voici la carte, et les <strong>{gb(safe)}</strong> qu'on peut récupérer sans risquer un seul fichier.</p>
  {scan_note}

  <div class="pledges">
    <div class="pledge">
      <h3>{icon('<path d="M12 3 5 6v6c0 4.2 2.9 7.6 7 9 4.1-1.4 7-4.8 7-9V6l-7-3Z"/><path d="m9 12 2.2 2.2L15.5 10"/>')}Rien n'est supprimé.</h3>
      <p>Chaque action est décrite puis soumise à ta revue. Ce rapport <b>n'exécute rien</b> :
      il mesure, classe, et laisse la décision ouverte.</p>
    </div>
    <div class="pledge">
      <h3>{icon('<rect x="4" y="10" width="16" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>')}Rien ne sort du Mac.</h3>
      <p>Mesure, classification et inventaire se font <b>en local</b>. Aucun nom de fichier
      n'est envoyé, aucun compte à créer : ce HTML s'ouvre hors ligne.</p>
    </div>
  </div>

  <div class="hero">
    <div class="diskbar">
      <div class="stack">
        <i class="s-home" style="width:{w(home):.2f}%"></i>
        <i class="s-apps" style="width:{w(apps_b):.2f}%"></i>
        <i class="s-var" style="width:{w(var_b):.2f}%"></i>
        <i class="s-opt" style="width:{w(opt_b):.2f}%"></i>
        <i class="s-sys" style="width:{w(system_b):.2f}%"></i>
        <i class="s-reserved" style="width:{w(reserved):.2f}%"></i>
        <i class="s-free" style="width:{w(free):.2f}%"></i>
      </div>
      <div class="legend">
        <span><i class="s-home"></i>Dossier perso {gb(home)}</span>
        <span><i class="s-apps"></i>Applications {gb(apps_b)}</span>
        <span><i class="s-var"></i>Système / var {gb(var_b)}</span>
        <span><i class="s-opt"></i>Homebrew {gb(opt_b)}</span>
        <span><i class="s-sys"></i>Système / non attribué {gb(system_b)}</span>
        <span><i class="s-reserved"></i>Réservé {gb(reserved)}</span>
        <span><i class="s-free"></i>Libre {gb(free)}</span>
      </div>
    </div>
    <div class="gauge">
      <svg width="260" height="260" viewBox="0 0 260 260">
        <circle class="track" cx="130" cy="130" r="112" fill="none" stroke-width="14"></circle>
        <circle class="val" cx="130" cy="130" r="112" fill="none" stroke-width="14"
          stroke-dasharray="{used_pct / 100 * 703.7:.1f} 703.7"></circle>
      </svg>
      <div class="center">
        <div class="big">{used_pct:.0f}%</div>
        <div class="cap">occupé</div>
      </div>
    </div>
  </div>

  <div class="kpis">
    <div class="kpi"><div class="n danger">{gb(free)}</div><div class="l">espace libre</div></div>
    <div class="kpi"><div class="n safe">{gb(safe)}</div><div class="l">récupérables sans risque</div></div>
    <div class="kpi"><div class="n warn">{gb(review)}</div><div class="l">à arbitrer ensemble</div></div>
    <div class="kpi"><div class="n">{"—" if fast else num(zombies.get("apps"))}</div><div class="l">{"inventaire désactivé" if fast else "applications · " + gb(zombies.get("apps_bytes"))}</div></div>
  </div>

  <p class="rule">
    <span><i class="sw-grey"></i>Le gris, c'est ce que tu gardes.</span>
    <span><i class="sw-safe"></i>Le vert se reconstruit tout seul.</span>
    <span><i class="sw-warn"></i>L'ambre demande une décision.</span>
  </p>

  {render_rooms_nav()}

  <section class="room is-active" id="overview" role="tabpanel" aria-labelledby="tab-overview">
    <div class="s-head">
      <h2>La carte du disque</h2>
      <div class="s-note">{gb(sum(e["bytes"] for e in tree))} attribués sur {gb(used)}</div>
    </div>
    <p class="s-sub">Surface proportionnelle à l'espace occupé. Les volumes système partagés
    (Preboot, VM, Recovery) et les métadonnées APFS expliquent le reste.</p>
    <div class="grid2">
      <div class="treemap">
        {render_treemap(treemap_items)}
      </div>
      <div class="rank">
        {rank_rows}
      </div>
    </div>
  </section>

  <section class="room" id="findings" role="tabpanel" aria-labelledby="tab-findings">
    <div class="s-head">
      <h2>Le gisement</h2>
      <div class="s-note">classé par taille</div>
    </div>
    <p class="s-sub">Les plus gros postes ne touchent ni tes documents, ni tes photos :
    ce sont des artefacts reconstruisibles ou des restes d'outils.</p>
    {render_groups(groups)}
    <div class="total">
      <div class="big">{gb(safe)}</div>
      <div class="txt">récupérables <b>sans risque</b> — de quoi passer de {gb(free)} à ~{gb(projected)} libres.
      Les {gb(review)} « à arbitrer » peuvent doubler la mise.</div>
    </div>
  </section>

  <section class="room" id="items" role="tabpanel" aria-labelledby="tab-items">
    <div class="s-head">
      <h2>Le détail</h2>
      <div class="s-note">chemins et actions</div>
    </div>
    <p class="s-sub">Chaque ligne est un chemin réel mesuré sur ce Mac. Les actions ne sont
    pas exécutées par ce rapport : elles sont proposées à la revue.</p>
    {render_items(items)}
  </section>

  <section class="room" id="apps" role="tabpanel" aria-labelledby="tab-apps">
    <div class="s-head">
      <h2>Les applications</h2>
      <div class="s-note">{num(len(apps))} apps · {gb(sum(a.get("bytes") or 0 for a in apps))}</div>
    </div>
    <p class="s-sub">Dernière utilisation et nombre de lancements viennent de Spotlight.
    <b>« Inconnu » ne veut pas dire « jamais utilisée »</b> : Spotlight ne trace pas tout
    (VS Code, Cursor ou ChatGPT peuvent sortir à zéro). À croiser avec ton usage réel.</p>
    {"<p class='s-sub'>Inventaire désactivé en mode rapide. Relance sans <code>--fast</code> pour le voir.</p>" if fast else render_apps(apps)}
  </section>

  <section class="room" id="models" role="tabpanel" aria-labelledby="tab-models">
    <div class="s-head">
      <h2>Les modèles</h2>
      <div class="s-note">{num(len(models))} modèles · {gb(sum(m.get("bytes") or 0 for m in models))}</div>
    </div>
    <p class="s-sub">Poids locaux téléchargeables à nouveau. Garde ceux qui servent
    réellement dans tes projets ; les autres sont des candidats évidents.</p>
    {"<p class='s-sub'>Inventaire désactivé en mode rapide.</p>" if fast else render_models(models)}
  </section>

  <section class="room" id="zombies" role="tabpanel" aria-labelledby="tab-zombies">
    <div class="s-head">
      <h2>Les zombies</h2>
      <div class="s-note">ce qui s'accumule sans qu'on le voie</div>
    </div>
    <p class="s-sub">Le vrai problème n'est pas un gros fichier : c'est la somme de petits
    restes laissés par des outils essayés puis abandonnés.</p>
    <div class="z-grid">
      {render_zombies(zombies, fast)}
    </div>
  </section>

  <section class="room" id="plan" role="tabpanel" aria-labelledby="tab-plan">
    <div class="s-head">
      <h2>Le plan</h2>
      <div class="s-note">dans cet ordre</div>
    </div>
    <p class="s-sub">On commence par ce qui ne demande aucune décision, on libère de la place,
    puis on compacte la base — qui a justement besoin d'espace temporaire.</p>
    <div class="plan">
      {render_plan(groups)}
    </div>
  </section>

  <footer>
    <b>Moteur</b> — {esc(report.get("engine"))} · schéma {report.get("schema")} · {esc(report.get("duration_seconds"))} s · {esc(report.get("generated_at"))}<br>
    <b>Méthode</b> — du -x · find · sqlite3 dbstat · mdls · system_profiler · brew cleanup -n · diskutil · tmutil<br>
    <b>Navigation</b> — onglets 1–7, ou « Tout déplier » pour lire le rapport d'un seul tenant.<br>
    <b>Note</b> — Les montages réseau (DesktopArchive) et les volumes cloud sont exclus. Aucune suppression n'a été effectuée.<br>
    <b>Sécurité</b> — « sans risque » = reconstruisible automatiquement (cache, build, dépendances).
  </footer>"""

    css = load_css()
    js = load_js()
    data_json = json.dumps(report, ensure_ascii=False, default=str)
    html_doc = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PKDiskAudit — où est passée la place</title>
<style>
{css}
</style>
</head>
<body>
<div class="wrap">
{body}
</div>
<script id="pkdisk-data" type="application/json">{data_json}</script>
<script>
{js}
</script>
<script>
function filterTable(inputId, tableId) {{
  const q = (document.getElementById(inputId).value || '').toLowerCase();
  const rows = document.querySelectorAll('#' + tableId + ' tbody tr');
  rows.forEach(r => {{
    const hay = (r.getAttribute('data-search') || r.textContent || '').toLowerCase();
    r.style.display = hay.includes(q) ? '' : 'none';
  }});
}}
function toggleTable(tableId, btn) {{
  const wrap = document.getElementById(tableId).closest('.table-wrap');
  const expanded = wrap.style.maxHeight === 'none';
  wrap.style.maxHeight = expanded ? '620px' : 'none';
  btn.textContent = expanded ? 'Tout afficher' : 'Réduire';
}}
</script>
</body>
</html>"""

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    return out_path
