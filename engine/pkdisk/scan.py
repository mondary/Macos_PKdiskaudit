"""Scanner PKDiskAudit — lecture seule, sortie JSON.

Le scanner ne supprime jamais rien. Il mesure, classe et explique. Les actions
sont décrites dans le JSON, mais exécutées plus tard par l'app, après revue.
"""

from __future__ import annotations

import glob
import os
import time
from collections import OrderedDict

from . import util

SCHEMA_VERSION = 1
ENGINE_VERSION = "2026.10.2"

HOME = util.HOME


def scan(options, progress=None):
    """Lance un scan complet et retourne un rapport sérialisable en JSON."""
    t0 = time.time()
    warnings = []
    partial_sections = []

    def emit(phase, pct, label=""):
        if progress:
            progress(phase, pct, label)

    roots = options.get("roots") or [HOME]
    include_apps = options.get("apps", True)
    include_models = options.get("models", True)
    include_artifacts = options.get("artifacts", True)
    include_large = options.get("large", False)
    fast = options.get("fast", False)
    timings = {}

    def timed(name, fn):
        started = time.time()
        result = fn()
        timings[name] = round(time.time() - started, 1)
        return result

    emit("disk", 2, "Lecture du disque")
    disk = util.disk_info()
    volume = util.volume_info("/")
    snaps = util.local_snapshots()
    host = util.host_info()

    # ---------------------------------------------------------------- arbre
    emit("tree", 8, "Mesure des grands dossiers")
    tree_roots = list(roots)
    for system_root in ("/Applications", "/Library", "/opt", "/private/var", "/Users/Shared"):
        if os.path.isdir(system_root) and system_root not in tree_roots:
            tree_roots.append(system_root)
    tree, tree_partial = timed("tree", lambda: scan_tree(tree_roots, emit))
    if tree_partial:
        partial_sections.append("tree")

    # ---------------------------------------------------------------- apps
    apps = []
    apps_summary = {}
    if include_apps and not fast:
        emit("apps", 45, "Inventaire des applications")
        apps = timed("apps", lambda: scan_apps(emit))
        apps_summary = summarise_apps(apps)
        if apps_summary.get("partial"):
            partial_sections.append("apps")

    # ---------------------------------------------------------------- modèles
    models = []
    if include_models and not fast:
        emit("models", 58, "Modèles et poids locaux")
        models = timed("models", scan_models)
        models.sort(key=lambda r: -r["bytes"])

    # ---------------------------------------------------------------- caches
    emit("caches", 64, "Caches et temporaires")
    caches, cache_partial = timed("caches", scan_caches)
    if cache_partial:
        partial_sections.append("caches")

    # ---------------------------------------------------------------- artefacts
    artifacts = []
    if include_artifacts and not fast:
        emit("artifacts", 74, "Artefacts de build")
        artifacts = timed("artifacts", scan_artifacts)
        if any(a.get("partial") for a in artifacts):
            partial_sections.append("artifacts")

    # ---------------------------------------------------------------- système
    emit("system", 84, "Base OpenCode, clones, VM, corbeille")
    system = timed("system", scan_system)
    if system.get("partial"):
        partial_sections.append("system")

    # ---------------------------------------------------------------- gros fichiers
    large = []
    installers = []
    if include_large and not fast:
        emit("large", 92, "Fichiers volumineux et anciens")
        large = timed("large", scan_large)
        installers = timed("installers", scan_installers)
        if any(a.get("partial") for a in large):
            partial_sections.append("large")

    # ---------------------------------------------------------------- groupes
    emit("summary", 97, "Synthèse")
    groups, items = build_findings(
        apps, apps_summary, models, caches, artifacts, system, large, installers
    )
    summary = summarise(disk, groups, tree, apps, models, caches, artifacts)
    zombies = zombie_stats(apps, apps_summary, caches, artifacts, models, system)

    report = OrderedDict([
        ("schema", SCHEMA_VERSION),
        ("engine", "pkdisk " + ENGINE_VERSION),
        ("fast", fast),
        ("generated_at", util.iso(time.time())),
        ("duration_seconds", round(time.time() - t0, 1)),
        ("timings", timings),
        ("host", host),
        ("disk", disk),
        ("volume", volume),
        ("snapshots", snaps),
        ("fda_likely_granted", util.fda_likely_granted()),
        ("partial_sections", partial_sections),
        ("warnings", warnings),
        ("summary", summary),
        ("tree", tree),
        ("groups", groups),
        ("items", items),
        ("apps", apps),
        ("apps_summary", apps_summary),
        ("models", models),
        ("system", system),
        ("zombies", zombies),
    ])
    emit("done", 100, "Terminé")
    return report


# --------------------------------------------------------------------------
# Arbre

KIND_RULES = [
    ("/Applications", "apps"),
    ("/Library", "system"),
    ("/private/var", "system"),
    ("/opt", "dev"),
    ("/usr/local", "dev"),
    ("/Users/Shared", "system"),
]


def kind_for(path):
    for prefix, kind in KIND_RULES:
        if path == prefix or path.startswith(prefix + "/"):
            return kind
    low = path.lower()
    if "/huggingface" in low or "/models" in low or ".gguf" in low:
        return "models"
    if "/.cache" in low or "/caches" in low or "/tmp" in low or "/temporaires" in low:
        return "cache"
    if "/documents/github" in low or "/projects" in low or "/.local" in low:
        return "dev"
    if "/desktop" in low or "/documents" in low or "/movies" in low or "/pictures" in low:
        return "media"
    if low.startswith(HOME):
        rel = low[len(HOME):]
        if rel.startswith("/."):
            return "dev"
    return "system"


def scan_tree(roots, emit):
    """Mesure les enfants de chaque racine, sans traverser les montages."""
    entries = []
    partial = False
    for root_index, root in enumerate(roots):
        root = os.path.expanduser(root)
        if not os.path.isdir(root):
            continue
        # Pour le home, on détaille chaque enfant. Pour les racines système,
        # on garde une seule entrée : sinon /Applications produirait 313 lignes.
        if root != HOME:
            size, part = util.du_bytes(root, timeout=900)
            partial = partial or part
            entries.append({
                "name": os.path.basename(root),
                "label": root,
                "path": root,
                "bytes": size,
                "kind": kind_for(root),
                "partial": part,
                "children": [],
            })
            continue
        root_dev = util.st_dev(root)
        try:
            names = sorted(os.listdir(root))
        except PermissionError:
            partial = True
            continue
        candidates = []
        for name in names:
            p = os.path.join(root, name)
            if os.path.islink(p) or not os.path.isdir(p):
                continue
            try:
                if util.st_dev(p) != root_dev:
                    continue
            except OSError:
                continue
            # Évite les volumes cloud/NFS qui ne sont pas sur le disque local
            if name in ("DesktopArchive", "CloudStorage", "Mobile Documents"):
                continue
            candidates.append((name, p))

        # Mesure groupée : un seul `du` pour plusieurs chemins, au lieu d'un
        # processus par dossier. C'est ce qui fait passer le scan de 7 min à
        # un ordre de grandeur raisonnable.
        sizes, part = util.du_sizes([p for _, p in candidates], timeout=900)
        partial = partial or part
        for i, (name, p) in enumerate(candidates):
            entries.append({
                "name": name,
                "label": name,
                "path": p,
                "bytes": sizes.get(p, 0),
                "kind": kind_for(p),
                "partial": part,
                "children": [],
            })
            if i % 10 == 0:
                emit("tree", 8 + int(30 * (i + 1) / max(1, len(candidates))), name)

    entries.sort(key=lambda e: -e["bytes"])
    return entries, partial


# --------------------------------------------------------------------------
# Applications

def scan_apps(emit):
    raw = util.system_apps()
    paths = [a["path"] for a in raw]
    sizes, partial = util.parallel_du_sizes(paths, workers=4, timeout=900)
    emit("apps", 50, "Tailles mesurées")

    # `mdls` est le point lent : on le parallélise modérément (8 workers).
    from concurrent.futures import ThreadPoolExecutor
    metas = []
    if paths:
        with ThreadPoolExecutor(max_workers=8) as pool:
            metas = list(pool.map(util.mdls_meta, paths))
    emit("apps", 56, "Dates d'utilisation")

    rows = []
    for a, meta in zip(raw, metas):
        days = None
        if meta.get("last_used"):
            try:
                import datetime
                d = datetime.datetime.fromisoformat(meta["last_used"])
                if d.tzinfo:
                    d = d.replace(tzinfo=None)
                days = (datetime.datetime.now() - d).days
            except Exception:
                days = None
        rows.append({
            "name": a["name"],
            "path": a["path"],
            "bundle_id": meta.get("bundle_id", ""),
            "bytes": sizes.get(a["path"], 0),
            "version": a.get("version", ""),
            "modified": a.get("modified", ""),
            "source": a.get("source", ""),
            "last_used": meta.get("last_used"),
            "use_count": meta.get("use_count", 0),
            "days_since_use": days,
            "partial": partial,
        })
    rows.sort(key=lambda r: -r["bytes"])
    return rows


def summarise_apps(apps):
    if not apps:
        return {"count": 0, "bytes": 0, "unknown_usage": 0, "stale_180": 0,
                "stale_365": 0, "never_count": 0, "never_bytes": 0, "partial": False}
    unknown = [a for a in apps if not a.get("last_used") and not a.get("use_count")]
    stale180 = [a for a in apps if a.get("days_since_use") is not None and a["days_since_use"] > 180]
    stale365 = [a for a in apps if a.get("days_since_use") is not None and a["days_since_use"] > 365]
    never = [a for a in apps if a.get("use_count") == 0]
    return {
        "count": len(apps),
        "bytes": sum(a["bytes"] for a in apps),
        "unknown_usage": len(unknown),
        "stale_180": len(stale180),
        "stale_365": len(stale365),
        "never_count": len(never),
        "never_bytes": sum(a["bytes"] for a in never),
        "partial": any(a.get("partial") for a in apps),
    }


# --------------------------------------------------------------------------
# Modèles

def scan_models():
    rows = util.huggingface_models() + util.other_models()
    seen = set()
    out = []
    for r in rows:
        real = os.path.realpath(r["path"])
        if real in seen:
            continue
        seen.add(real)
        out.append(r)
    return out


# --------------------------------------------------------------------------
# Caches

def scan_caches():
    rows = []
    partial = False
    for label, path in (("Caches utilisateur", os.path.expanduser("~/Library/Caches")),
                        ("Caches ~/.cache", os.path.expanduser("~/.cache"))):
        rows += util.scan_cache_dir(path, label, limit=40)
    for label, path in util.temp_roots():
        # Les clones de signature sont traités à part (scan_system) pour éviter
        # de compter deux fois les mêmes 19 Go.
        if "Clones" in label:
            continue
        rows += util.scan_cache_dir(path, label, limit=40)
    # Hugging Face est traité dans le groupe "Modèles", pas dans les caches.
    rows = [r for r in rows if r.get("name") != "huggingface"]
    for r in rows:
        r["safety"] = "safe"
        r["reason"] = cache_reason(r)
    rows.sort(key=lambda r: -r["bytes"])
    return rows, partial


def cache_reason(r):
    label = r.get("label", "")
    name = r.get("name", "")
    if "Clones" in label:
        return "Clone de signature laissé par une mise à jour ; régénéré."
    if "Temporaires" in label:
        return "Fichier temporaire ; peut être supprimé sans risque."
    if "Caches système" in label:
        return "Cache système régénéré automatiquement."
    if name in ("Google", "com.google.Chrome"):
        return "Cache de navigateur ; régénéré au prochain lancement."
    if name in ("Homebrew",):
        return "Téléchargements Homebrew ; `brew cleanup` peut les retirer."
    return "Cache applicatif ; régénéré automatiquement."


# --------------------------------------------------------------------------
# Artefacts

def scan_artifacts():
    roots = [
        os.path.expanduser("~/Documents/GitHub"),
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Projects"),
        os.path.expanduser("~/Code"),
        os.path.expanduser("~/dev"),
        os.path.expanduser("~/Workspace"),
    ]
    roots = list(dict.fromkeys([r for r in roots if os.path.isdir(r)]))
    rows = util.find_artifacts(roots)
    for r in rows:
        r["category"] = "artifact"
        r["action"] = "delete"
    return rows


# --------------------------------------------------------------------------
# Système

def scan_system():
    out = {
        "opencode": None,
        "chrome_clone": [],
        "chrome_running": False,
        "brew": None,
        "trash": None,
        "vms": [],
        "partial": False,
    }
    # Base OpenCode
    db = os.path.expanduser("~/.local/share/opencode/opencode.db")
    if os.path.exists(db):
        pragmas = util.sqlite_pragmas(db)
        if pragmas:
            counts = util.sqlite_counts(db, ["session", "message", "part", "session_message"])
            out["opencode"] = {
                "path": db,
                "bytes": util.file_bytes(db),
                "pragmas": pragmas,
                "counts": counts,
                "wal_bytes": util.file_bytes(db + "-wal"),
                "app_running": bool(util.run(["pgrep", "-x", "opencode"], timeout=10)[0] == 0),
            }

    # Clones de signature (Chrome et autres)
    for label, path in util.temp_roots():
        if "Clones" not in label:
            continue
        try:
            names = sorted(os.listdir(path))
        except OSError:
            continue
        for name in names:
            p = os.path.join(path, name)
            if not os.path.isdir(p):
                continue
            size, _ = util.du_bytes(p)
            if size < 100 * 1024 * 1024:
                continue
            out["chrome_clone"].append({
                "name": name,
                "path": p,
                "bytes": size,
                "age_days": util.age_days(p),
            })
    code, _, _ = util.run(["pgrep", "-f", "Google Chrome.app/Contents/MacOS/Google Chrome"], timeout=10)
    out["chrome_running"] = code == 0

    # Homebrew (lecture seule)
    if util.which("brew"):
        code, txt, _ = util.run(["brew", "cleanup", "-n"], timeout=120)
        if code == 0:
            import re
            m = re.search(r"approximately\s+([0-9.]+)\s*([KMGT])B", txt, re.I)
            bytes_ = 0
            if m:
                mult = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4}[m.group(2).upper()]
                bytes_ = int(float(m.group(1)) * mult)
            code2, cache, _ = util.run(["brew", "--cache"], timeout=30)
            cache_path = cache.strip() if code2 == 0 else ""
            cache_size = util.du_bytes(cache_path)[0] if cache_path and os.path.isdir(cache_path) else 0
            out["brew"] = {"cleanup_bytes": bytes_, "cache_bytes": cache_size, "cache_path": cache_path}

    # Corbeille
    trash = os.path.expanduser("~/.Trash")
    if os.path.isdir(trash):
        size, _ = util.du_bytes(trash)
        count = 0
        try:
            count = len(os.listdir(trash))
        except OSError:
            pass
        out["trash"] = {"path": trash, "bytes": size, "count": count}

    # VM / images disque
    out["vms"] = scan_vms()
    return out


def scan_vms():
    rows = []
    seen = set()
    candidates = []
    # On cible les emplacements connus : parcourir tout le home pour trouver
    # des VM coûtait plusieurs minutes et ne trouvait presque rien de plus.
    patterns = [
        "~/Library/Application Support/*/VM",
        "~/Library/Application Support/*/VMs",
        "~/Library/Application Support/*/Virtual Machines",
        "~/Library/Containers/com.utmapp.UTM/Data/Documents",
        "~/.utm",
        "~/Virtual Machines.localized",
        "~/Parallels/*.pvm",
        "~/.vagrant.d/boxes",
    ]
    for pattern in patterns:
        for p in glob.glob(os.path.expanduser(pattern)):
            if os.path.isdir(p):
                candidates.append(p)
    for p in candidates:
        real = os.path.realpath(p)
        if real in seen or not os.path.exists(real):
            continue
        seen.add(real)
        size, _ = util.du_bytes(real)
        if size < 1024 ** 3:
            continue
        rows.append({
            "name": os.path.basename(real),
            "path": real,
            "bytes": size,
            "last_modified": util.iso(util.dir_mtime(real)),
        })
    rows.sort(key=lambda r: -r["bytes"])
    return rows


# --------------------------------------------------------------------------
# Gros fichiers / installeurs

def scan_large():
    roots = [
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Desktop"),
        os.path.expanduser("~/Downloads"),
        os.path.expanduser("~/Movies"),
        os.path.expanduser("~/Pictures"),
        os.path.expanduser("~/Music"),
    ]
    rows = util.large_old_files([r for r in roots if os.path.isdir(r)])
    for r in rows:
        r["category"] = "large"
        r["safety"] = "review"
        r["reason"] = "Fichier volumineux et ancien : à vérifier avant de déplacer."
    return rows


def scan_installers():
    roots = [os.path.expanduser("~/Downloads"), os.path.expanduser("~/Desktop")]
    rows = util.installers([r for r in roots if os.path.isdir(r)])
    for r in rows:
        r["category"] = "installer"
        r["safety"] = "review"
        r["reason"] = "Installeur téléchargé : souvent supprimable après installation."
    return rows


# --------------------------------------------------------------------------
# Groupes & items

def build_findings(apps, apps_summary, models, caches, artifacts, system, large, installers):
    groups = []
    items = []

    # Applications
    if apps:
        groups.append({
            "id": "apps", "title": "Applications", "bytes": sum(a["bytes"] for a in apps),
            "safety": "review", "count": len(apps),
            "reason": "Applications installées. Désinstaller les inutilisées libère leur bundle et leurs données.",
            "section": "apps",
        })
        # Top 30 applications seulement dans les items détaillés
        for a in apps[:30]:
            items.append({
                "id": "app:" + a["path"], "category": "app", "title": a["name"],
                "path": a["path"], "bytes": a["bytes"], "safety": "review",
                "action": "uninstall",
                "reason": app_reason(a),
                "last_modified": a.get("modified"),
                "meta": {"use_count": a.get("use_count"), "last_used": a.get("last_used")},
            })

    # Modèles
    if models:
        groups.append({
            "id": "models", "title": "Modèles IA", "bytes": sum(m["bytes"] for m in models),
            "safety": "review", "count": len(models),
            "reason": "Poids téléchargeables à nouveau. Garder ceux utilisés par les projets actifs.",
            "section": "models",
        })
        for m in models:
            items.append({
                "id": "model:" + m["path"], "category": "model", "title": m["name"],
                "path": m["path"], "bytes": m["bytes"], "safety": "review",
                "action": "delete", "reason": m.get("kind", "Modèle local"),
                "last_modified": m.get("last_modified"),
            })

    # Caches
    if caches:
        groups.append({
            "id": "caches", "title": "Caches et temporaires", "bytes": sum(c["bytes"] for c in caches),
            "safety": "safe", "count": len(caches),
            "reason": "Caches applicatifs, fichiers temporaires et clones de signature. Régénérés automatiquement.",
            "section": "items",
        })
        for c in caches[:50]:
            items.append({
                "id": "cache:" + c["path"], "category": "cache", "title": c["name"],
                "path": c["path"], "bytes": c["bytes"], "safety": "safe",
                "action": "delete", "reason": c.get("reason", "Cache régénéré."),
                "last_modified": None,
            })

    # Artefacts
    if artifacts:
        safe_bytes = sum(a["bytes"] for a in artifacts if a["safety"] == "safe")
        review_bytes = sum(a["bytes"] for a in artifacts if a["safety"] != "safe")
        if safe_bytes:
            groups.append({
                "id": "artifacts_safe", "title": "Artefacts de build", "bytes": safe_bytes,
                "safety": "safe", "count": sum(1 for a in artifacts if a["safety"] == "safe"),
                "reason": "Dépendances et sorties de compilation reconstructibles (node_modules, target, .build…).",
                "section": "items",
            })
        if review_bytes:
            groups.append({
                "id": "artifacts_review", "title": "Builds à vérifier", "bytes": review_bytes,
                "safety": "review", "count": sum(1 for a in artifacts if a["safety"] != "safe"),
                "reason": "Dossiers build/dist/vendor : souvent reconstructibles, mais à inspecter.",
                "section": "items",
            })
        for a in artifacts[:80]:
            items.append({
                "id": "artifact:" + a["path"], "category": "artifact", "title": a["name"],
                "path": a["path"], "bytes": a["bytes"], "safety": a["safety"],
                "action": "delete", "reason": a.get("reason", "Artefact de build."),
                "last_modified": None,
                "meta": {"project": a.get("project"), "age_days": a.get("age_days")},
            })

    # Base OpenCode
    oc = system.get("opencode")
    if oc and oc["pragmas"].get("dead_bytes", 0) > 100 * 1024 * 1024:
        groups.append({
            "id": "database", "title": "Base OpenCode", "bytes": oc["pragmas"]["dead_bytes"],
            "safety": "review", "count": 1,
            "reason": "Pages libres dans le fichier SQLite. Un VACUUM rend la place sans supprimer de session.",
            "section": "items",
        })
        items.append({
            "id": "db:opencode", "category": "database", "title": "opencode.db — pages libres",
            "path": oc["path"], "bytes": oc["pragmas"]["dead_bytes"], "safety": "review",
            "action": "vacuum", "reason": "VACUUM SQLite : compacte le fichier, conserve toutes les lignes. Fermer OpenCode.",
            "last_modified": None,
            "meta": {"live_bytes": oc["pragmas"]["live_bytes"], "dead_bytes": oc["pragmas"]["dead_bytes"],
                     "counts": oc.get("counts", {}), "app_running": oc.get("app_running")},
        })

    # Clones Chrome
    if system.get("chrome_clone"):
        total = sum(c["bytes"] for c in system["chrome_clone"])
        groups.append({
            "id": "chrome_clone", "title": "Clones de signature", "bytes": total,
            "safety": "review", "count": len(system["chrome_clone"]), "apparent": True,
            "reason": "Taille apparente : les clones APFS partagent des blocs avec l'app d'origine. "
                      "Le gain réel est mesuré au moment de la suppression, souvent bien inférieur.",
            "section": "items",
        })
        for c in system["chrome_clone"]:
            items.append({
                "id": "clone:" + c["path"], "category": "clone", "title": c["name"],
                "path": c["path"], "bytes": c["bytes"], "safety": "review",
                "action": "delete",
                "reason": "Clone de signature temporaire. Taille apparente (blocs APFS partagés)."
                          + (" Quitter Chrome avant suppression." if system.get("chrome_running") else ""),
                "last_modified": None,
            })

    # Homebrew
    brew = system.get("brew")
    if brew and (brew.get("cleanup_bytes") or brew.get("cache_bytes")):
        total = (brew.get("cleanup_bytes") or 0) + (brew.get("cache_bytes") or 0)
        groups.append({
            "id": "brew", "title": "Homebrew", "bytes": total, "safety": "review", "count": 1,
            "reason": "Anciennes versions et cache de téléchargement. Vérifier la liste avant de nettoyer.",
            "section": "items",
        })
        items.append({
            "id": "brew:cache", "category": "brew", "title": "Cache et anciennes versions Homebrew",
            "path": brew.get("cache_path") or "brew --cache", "bytes": total,
            "safety": "review", "action": "brew_cleanup",
            "reason": "`brew cleanup -n` estime %.1f Go. À lancer après revue." % (total / 1024 ** 3),
            "last_modified": None,
        })

    # Corbeille
    trash = system.get("trash")
    if trash and trash.get("bytes"):
        groups.append({
            "id": "trash", "title": "Corbeille", "bytes": trash["bytes"], "safety": "review",
            "count": trash.get("count", 0), "reason": "Éléments déjà mis à la corbeille. Les vider libère la place.",
            "section": "items",
        })
        items.append({
            "id": "trash", "category": "trash", "title": "Corbeille",
            "path": trash["path"], "bytes": trash["bytes"], "safety": "review",
            "action": "empty_trash", "reason": "Vider la corbeille est définitif.",
            "last_modified": None,
        })

    # VM
    if system.get("vms"):
        total = sum(v["bytes"] for v in system["vms"])
        groups.append({
            "id": "vm", "title": "Machines virtuelles", "bytes": total, "safety": "review",
            "count": len(system["vms"]),
            "reason": "Images disque de VM. À supprimer seulement si la VM n'est plus utilisée.",
            "section": "items",
        })
        for v in system["vms"]:
            items.append({
                "id": "vm:" + v["path"], "category": "vm", "title": v["name"],
                "path": v["path"], "bytes": v["bytes"], "safety": "review",
                "action": "delete", "reason": "Image de machine virtuelle.",
                "last_modified": v.get("last_modified"),
            })

    # Gros fichiers
    if large:
        total = sum(f["bytes"] for f in large)
        groups.append({
            "id": "large", "title": "Fichiers anciens", "bytes": total, "safety": "review",
            "count": len(large), "reason": "Fichiers de plus de 500 Mo non modifiés depuis un an.",
            "section": "items",
        })
        for f in large[:40]:
            items.append({
                "id": "large:" + f["path"], "category": "large", "title": f["name"],
                "path": f["path"], "bytes": f["bytes"], "safety": "review",
                "action": "reveal", "reason": f.get("reason", "À vérifier."),
                "last_modified": f.get("last_modified"),
            })

    # Installeurs
    if installers:
        total = sum(f["bytes"] for f in installers)
        groups.append({
            "id": "installers", "title": "Installeurs", "bytes": total, "safety": "review",
            "count": len(installers), "reason": "DMG/PKG/ISO téléchargés. Supprimables après installation.",
            "section": "items",
        })
        for f in installers[:40]:
            items.append({
                "id": "installer:" + f["path"], "category": "installer", "title": f["name"],
                "path": f["path"], "bytes": f["bytes"], "safety": "review",
                "action": "delete", "reason": f.get("reason", "Installeur téléchargé."),
                "last_modified": f.get("last_modified"),
            })

    groups.sort(key=lambda g: -g["bytes"])
    items.sort(key=lambda i: -i["bytes"])
    return groups, items


def app_reason(a):
    if a.get("last_used"):
        return "Dernière utilisation : %s (%s lancements)." % (a["last_used"][:10], a.get("use_count", 0))
    if a.get("use_count"):
        return "%s lancements enregistrés." % a["use_count"]
    return "Aucune trace d'utilisation dans Spotlight : à confirmer."


# --------------------------------------------------------------------------
# Synthèse

def summarise(disk, groups, tree, apps, models, caches, artifacts):
    # Les groupes `apparent` (clones APFS) ne sont pas comptés dans le
    # récupérable : `du` additionne des blocs partagés, le gain réel est
    # mesuré à la suppression.
    safe = sum(g["bytes"] for g in groups if g["safety"] == "safe" and not g.get("apparent"))
    review = sum(g["bytes"] for g in groups if g["safety"] == "review" and not g.get("apparent"))
    apparent = sum(g["bytes"] for g in groups if g.get("apparent"))
    measured = sum(t["bytes"] for t in tree)
    return {
        "total_bytes": disk["total"],
        "used_bytes": disk["used"],
        "free_bytes": disk["free"],
        "percent_used": disk["percent"],
        "measured_bytes": measured,
        "unattributed_bytes": max(0, disk["used"] - measured),
        "safe_bytes": safe,
        "review_bytes": review,
        "apparent_bytes": apparent,
        "recoverable_bytes": safe + review,
        "projected_free_bytes": disk["free"] + safe,
        "groups": len(groups),
        "items": len(apps) + len(models) + len(caches) + len(artifacts),
    }


def zombie_stats(apps, apps_summary, caches, artifacts, models, system):
    oc = system.get("opencode") or {}
    return {
        "apps": apps_summary.get("count", 0),
        "apps_bytes": apps_summary.get("bytes", 0),
        "apps_unknown": apps_summary.get("unknown_usage", 0),
        "apps_stale_365": apps_summary.get("stale_365", 0),
        "cache_dirs": len(caches),
        "cache_bytes": sum(c["bytes"] for c in caches),
        "artifacts": len(artifacts),
        "artifacts_bytes": sum(a["bytes"] for a in artifacts),
        "models": len(models),
        "models_bytes": sum(m["bytes"] for m in models),
        "sessions": (oc.get("counts") or {}).get("session", 0),
        "messages": (oc.get("counts") or {}).get("message", 0),
        "parts": (oc.get("counts") or {}).get("part", 0),
        "db_dead_bytes": (oc.get("pragmas") or {}).get("dead_bytes", 0),
        "chrome_clone_bytes": sum(c["bytes"] for c in system.get("chrome_clone", [])),
        "vms": len(system.get("vms", [])),
        "vm_bytes": sum(v["bytes"] for v in system.get("vms", [])),
    }
