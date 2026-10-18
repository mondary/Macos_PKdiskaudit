"""Primitives de mesure pour PKDiskAudit.

Toutes les tailles sont des octets alloués sur le disque (comme `du`), pas des
tailles logiques : c'est ce que macOS facture réellement, et ça évite de
compter deux fois les fichiers sparse ou les clones APFS.
"""

from __future__ import annotations

import datetime
import json
import os
import plistlib
import re
import shutil
import subprocess
import time
from pathlib import Path

HOME = str(Path.home())


# --------------------------------------------------------------------------
# Exécution de commandes

def run(cmd, timeout=900, cwd=None):
    """Exécute une commande et renvoie (code, stdout, stderr)."""
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            cwd=cwd,
            errors="replace",
        )
        return p.returncode, p.stdout, p.stderr
    except FileNotFoundError:
        return 127, "", "command not found: %s" % cmd[0]
    except subprocess.TimeoutExpired:
        return 124, "", "timeout after %ss" % timeout


def which(name):
    return shutil.which(name)


# --------------------------------------------------------------------------
# Tailles

def du_bytes(path, timeout=900):
    """Taille allouée d'un chemin, en octets. Retourne (bytes, partial)."""
    if not os.path.exists(path):
        return 0, False
    code, out, err = run(["du", "-sk", path], timeout=timeout)
    size = 0
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if not parts:
            continue
        try:
            size = int(parts[0]) * 1024
        except ValueError:
            continue
        break
    partial = code not in (0, 1) or _permission_error(err)
    return size, partial


def du_sizes(paths, timeout=900):
    """Mesure plusieurs chemins en un minimum de processus `du`.

    Retourne ({chemin: octets}, partial). Les chemins absents sont ignorés.
    """
    result = {}
    partial = False
    paths = [p for p in paths if p and os.path.exists(p)]
    if not paths:
        return result, partial
    for i in range(0, len(paths), 80):
        batch = paths[i:i + 80]
        code, out, err = run(["du", "-sk"] + batch, timeout=timeout)
        for line in out.splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            try:
                size = int(parts[0]) * 1024
            except ValueError:
                continue
            result[parts[1]] = size
        if code not in (0, 1) or _permission_error(err):
            partial = True
    return result, partial


def parallel_du_sizes(paths, workers=4, timeout=900):
    """Mesure en parallèle plusieurs chemins (répartis par interleaving).

    Sur SSD, plusieurs `du` concurrents exploitent mieux la bande passante que
    la mesure séquentielle, surtout quand quelques très gros dossiers dominent.
    """
    paths = [p for p in paths if p and os.path.exists(p)]
    if not paths:
        return {}, False
    if workers <= 1 or len(paths) < 8:
        return du_sizes(paths, timeout=timeout)
    chunks = [paths[i::workers] for i in range(workers)]
    chunks = [c for c in chunks if c]
    results = []
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=len(chunks)) as pool:
            futures = [pool.submit(du_sizes, chunk, timeout) for chunk in chunks]
            for future in futures:
                try:
                    results.append(future.result())
                except Exception:
                    results.append(({}, True))
    except Exception:
        return du_sizes(paths, timeout=timeout)
    merged = {}
    partial = False
    for sizes, part in results:
        merged.update(sizes)
        partial = partial or part
    return merged, partial


def normalize_roots(roots):
    """Supprime les racines imbriquées pour ne pas parcourir deux fois les
    mêmes fichiers (`~/Documents` contient `~/Documents/GitHub`)."""
    unique = sorted({os.path.realpath(os.path.expanduser(r)) for r in roots if r}, key=len)
    out = []
    for root in unique:
        if not any(root == kept or root.startswith(kept + os.sep) for kept in out):
            out.append(root)
    return out


def du_depth(path, depth=1, timeout=900):
    """Liste [(chemin, octets)] jusqu'à `depth`, avec statut partiel.

    `-x` évite de traverser un autre système de fichiers. Sur macOS, un montage
    NFS peut malgré tout être parcouru selon la version : on filtre ensuite par
    st_dev.
    """
    if not os.path.exists(path):
        return [], False
    code, out, err = run(["du", "-kx", "-d%d" % depth, path], timeout=timeout)
    root_dev = st_dev(path)
    rows = []
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        try:
            size = int(parts[0]) * 1024
        except ValueError:
            continue
        p = parts[1]
        try:
            if st_dev(p) != root_dev:
                continue
        except OSError:
            pass
        rows.append((p, size))
    partial = code not in (0, 1) or _permission_error(err)
    return rows, partial


def _permission_error(err):
    return any(
        s in (err or "")
        for s in ("Permission denied", "Operation not permitted", "not permitted")
    )


def st_dev(path):
    return os.stat(path, follow_symlinks=False).st_dev


def file_bytes(path):
    try:
        st = os.stat(path, follow_symlinks=False)
        return st.st_blocks * 512
    except OSError:
        return 0


def dir_mtime(path):
    try:
        return os.stat(path, follow_symlinks=False).st_mtime
    except OSError:
        return 0


def age_days(path):
    ts = dir_mtime(path)
    if not ts:
        return None
    return max(0, int((time.time() - ts) / 86400))


# --------------------------------------------------------------------------
# Système

def disk_info(path="/System/Volumes/Data"):
    """Capacité, utilisé, libre — les chiffres du volume Data, comme Finder.

    `statvfs("/")` renvoie l'usage du container APFS entier (volumes système
    compris). `df` sur /System/Volumes/Data isole les données utilisateur.
    """
    if not os.path.exists(path):
        path = "/"
    code, out, _ = run(["df", "-kP", path], timeout=30)
    if code == 0:
        lines = [l for l in out.splitlines() if l.strip()]
        if len(lines) >= 2:
            parts = lines[-1].split()
            if len(parts) >= 4:
                try:
                    total = int(parts[1]) * 1024
                    used = int(parts[2]) * 1024
                    free = int(parts[3]) * 1024
                    denom = used + free
                    return {
                        "total": total,
                        "used": used,
                        "free": free,
                        "percent": round(used * 100 / denom, 1) if denom else 0,
                    }
                except ValueError:
                    pass
    st = os.statvfs(path)
    total = st.f_blocks * st.f_frsize
    free = st.f_bavail * st.f_frsize
    used = total - free
    return {
        "total": total,
        "used": used,
        "free": free,
        "percent": round(used * 100 / total, 1) if total else 0,
    }


def volume_info(path="/"):
    code, out, _ = run(["diskutil", "info", "-plist", path], timeout=60)
    if code != 0:
        return {}
    try:
        data = plistlib.loads(out.encode("utf-8"))
    except Exception:
        return {}
    keys = [
        "VolumeName",
        "FilesystemName",
        "FilesystemType",
        "APFSContainerFree",
        "APFSContainerReference",
        "MountPoint",
        "SolidState",
    ]
    return {k: data.get(k) for k in keys if k in data}


def local_snapshots():
    code, out, _ = run(["tmutil", "listlocalsnapshots", "/"], timeout=60)
    if code != 0:
        return []
    return [l.strip() for l in out.splitlines() if l.strip().startswith("com.apple")]


def host_info():
    code, out, _ = run(["sw_vers"], timeout=30)
    os_name = os_version = os_build = ""
    for line in out.splitlines():
        if line.startswith("ProductName:"):
            os_name = line.split(":", 1)[1].strip()
        elif line.startswith("ProductVersion:"):
            os_version = line.split(":", 1)[1].strip()
        elif line.startswith("BuildVersion:"):
            os_build = line.split(":", 1)[1].strip()
    code, model, _ = run(["sysctl", "-n", "hw.model"], timeout=30)
    return {
        "hostname": os.uname().nodename,
        "os": os_name,
        "os_version": os_version,
        "os_build": os_build,
        "arch": os.uname().machine,
        "model": model.strip() if code == 0 else "",
        "user": os.environ.get("USER", ""),
    }


def fda_likely_granted():
    """Heuristique : peut-on lister un dossier protégé par TCC ?"""
    for path in ("~/Library/Mail", "~/Library/Safari", "~/Library/Messages"):
        p = os.path.expanduser(path)
        if not os.path.exists(p):
            continue
        try:
            os.listdir(p)
        except PermissionError:
            return False
        except OSError:
            continue
    return True


# --------------------------------------------------------------------------
# Applications

def system_apps():
    """Liste des applications de /Applications et ~/Applications."""
    code, out, _ = run(
        ["system_profiler", "SPApplicationsDataType", "-json"], timeout=300
    )
    apps = []
    if code == 0:
        try:
            data = json.loads(out)
            apps = data.get("SPApplicationsDataType", [])
        except Exception:
            apps = []
    rows = []
    seen = set()
    for a in apps:
        path = a.get("path", "")
        if not path.endswith(".app"):
            continue
        if not (path.startswith("/Applications/") or path.startswith(HOME + "/Applications/")):
            continue
        real = os.path.realpath(path)
        if real in seen:
            continue
        seen.add(real)
        rows.append({
            "name": a.get("_name") or os.path.basename(path)[:-4],
            "path": path,
            "version": a.get("version") or "",
            "modified": a.get("lastModified") or "",
            "source": a.get("obtained_from") or "",
        })
    if not rows:
        for root in ("/Applications", HOME + "/Applications"):
            if not os.path.isdir(root):
                continue
            for name in os.listdir(root):
                if name.endswith(".app"):
                    p = os.path.join(root, name)
                    rows.append({
                        "name": name[:-4],
                        "path": p,
                        "version": "",
                        "modified": "",
                        "source": "",
                    })
    return rows


def mdls_meta(path):
    """Métadonnées Spotlight d'une app : dernière utilisation, lancements."""
    code, out, _ = run(["mdls", "-plist", "-", path], timeout=30)
    if code != 0:
        return {}
    try:
        meta = plistlib.loads(out.encode("utf-8"))
    except Exception:
        return {}
    last_used = meta.get("kMDItemLastUsedDate")
    if not last_used:
        eng = meta.get("_kMDItemRecentOutOfSpotlightEngagementDates") or []
        if eng:
            last_used = max(eng)
    return {
        "bundle_id": meta.get("kMDItemCFBundleIdentifier") or "",
        "last_used": last_used.isoformat() if isinstance(last_used, datetime.datetime) else None,
        "use_count": int(meta.get("kMDItemUseCount") or 0),
    }


# --------------------------------------------------------------------------
# Modèles

MODEL_ROLES = {
    "whisper": "Transcription audio",
    "faster-whisper": "Transcription audio",
    "voxcpm": "Synthèse vocale (TTS)",
    "dots.tts": "Synthèse vocale (TTS)",
    "piper": "Synthèse vocale (TTS)",
    "pocket-tts": "Synthèse vocale (TTS)",
    "musetalk": "Avatar / lip-sync",
    "laya": "Classification / décision",
    "sd-vae": "VAE Stable Diffusion",
    "parakeet": "Transcription audio",
    "gemma": "LLM local",
    "llama": "LLM local",
    "qwen": "LLM local",
    "mistral": "LLM local",
}


def model_role(name):
    low = name.lower()
    for key, role in MODEL_ROLES.items():
        if key in low:
            return role
    return "Modèle local"


def huggingface_models():
    root = os.path.expanduser("~/.cache/huggingface/hub")
    if not os.path.isdir(root):
        return []
    rows = []
    for name in os.listdir(root):
        if not name.startswith("models--"):
            continue
        path = os.path.join(root, name)
        size, _ = du_bytes(path)
        label = name[len("models--"):].replace("--", "/")
        rows.append({
            "name": label,
            "path": path,
            "bytes": size,
            "last_modified": iso(dir_mtime(path)),
            "kind": model_role(label),
            "source": "Hugging Face",
        })
    return rows


def other_models():
    candidates = [
        ("~/.ollama/models", "Ollama"),
        ("~/.lmstudio/models", "LM Studio"),
        ("~/.cache/lm-studio/models", "LM Studio"),
        ("~/Library/Application Support/Ollama/models", "Ollama"),
    ]
    rows = []
    for raw, source in candidates:
        path = os.path.expanduser(raw)
        if os.path.isdir(path):
            size, _ = du_bytes(path)
            if size:
                rows.append({
                    "name": os.path.basename(path),
                    "path": path,
                    "bytes": size,
                    "last_modified": iso(dir_mtime(path)),
                    "kind": model_role(path),
                    "source": source,
                })
    # Dossiers `models` d'applications tierces (walkie, etc.)
    app_support = os.path.expanduser("~/Library/Application Support")
    if os.path.isdir(app_support):
        for name in os.listdir(app_support):
            p = os.path.join(app_support, name, "models")
            if not os.path.isdir(p):
                continue
            size, _ = du_bytes(p)
            if size >= 100 * 1024 * 1024:
                rows.append({
                    "name": name + " / models",
                    "path": p,
                    "bytes": size,
                    "last_modified": iso(dir_mtime(p)),
                    "kind": model_role(name),
                    "source": name,
                })
    return rows


# --------------------------------------------------------------------------
# Artefacts de développement

ARTIFACT_NAMES = [
    "node_modules", ".next", ".turbo", "target", ".build", "build", "dist",
    ".venv", "venv", "__pycache__", "Pods", "DerivedData", "vendor",
]

SAFE_ARTIFACTS = {
    "node_modules", ".next", ".turbo", "target", ".build", ".venv", "venv",
    "__pycache__", "Pods", "DerivedData",
}
REVIEW_ARTIFACTS = {"build", "dist", "vendor"}


def find_artifacts(roots, timeout=900):
    """Trouve les dossiers d'artefacts dans les racines de projets."""
    roots = normalize_roots(roots)
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        expr = ["(", "-name", ".git", "-o", "-name", ".hg", "-o", "-name", ".svn", ")", "-prune", "-o"]
        expr += ["-type", "d", "("]
        for i, name in enumerate(ARTIFACT_NAMES):
            if i:
                expr.append("-o")
            expr.append("-name")
            expr.append(name)
        expr += [")", "-prune", "-print0"]
        code, out, err = run(["find", root] + expr, timeout=timeout)
        for raw in out.split("\0"):
            if raw and os.path.isdir(raw):
                found.append(raw)
    # Dédoublonne (deux racines imbriquées peuvent trouver le même dossier)
    seen = set()
    paths = []
    for raw in found:
        real = os.path.realpath(raw)
        if real in seen:
            continue
        seen.add(real)
        paths.append(real)
    sizes, partial = parallel_du_sizes(paths, workers=4, timeout=600)

    rows = []
    for raw in paths:
        size = sizes.get(raw, 0)
        if size < 10 * 1024 * 1024:
            continue
        base = os.path.basename(raw)
        age = age_days(raw)
        rows.append({
            "name": base,
            "path": raw,
            "project": project_root(raw),
            "bytes": size,
            "age_days": age,
            "safety": artifact_safety(base, age),
            "reason": artifact_reason(base),
            "partial": partial,
        })
    rows.sort(key=lambda r: -r["bytes"])
    return rows


def artifact_safety(name, age):
    if name in REVIEW_ARTIFACTS:
        return "review"
    if name in SAFE_ARTIFACTS:
        return "safe" if age is None or age >= 7 else "review"
    return "review"


def artifact_reason(name):
    if name == "node_modules":
        return "Dépendances réinstallables avec pnpm/npm."
    if name in ("target", ".build"):
        return "Artefacts de compilation, régénérés au prochain build."
    if name in ("build", "dist"):
        return "Sortie de build ou de distribution : à vérifier avant suppression."
    if name in ("vendor",):
        return "Dépendances vendorisées : à vérifier (peut être nécessaire hors ligne)."
    if name in (".venv", "venv"):
        return "Environnement Python reconstruisible."
    if name == "__pycache__":
        return "Bytecode Python, régénéré automatiquement."
    if name == "Pods":
        return "Dépendances CocoaPods, réinstallables avec pod install."
    if name == "DerivedData":
        return "Cache Xcode, régénéré au prochain build."
    return "Artefact de build reconstructible."


def project_root(path):
    cur = os.path.dirname(path)
    markers = (".git", "package.json", "Cargo.toml", "pyproject.toml", "Package.swift", "Podfile")
    for _ in range(12):
        if any(os.path.exists(os.path.join(cur, m)) for m in markers):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.dirname(path)


# --------------------------------------------------------------------------
# Fichiers volumineux / anciens

def large_old_files(roots, min_size=500 * 1024 * 1024, older_days=365, timeout=900):
    rows = []
    roots = normalize_roots(roots)
    for root in roots:
        if not os.path.isdir(root):
            continue
        skip = ["Library", ".cache", "node_modules", ".git", "DesktopArchive", ".Trash",
                "build", "dist", "target", ".build"]
        expr = ["("]
        for i, name in enumerate(skip):
            if i:
                expr.append("-o")
            expr += ["-name", name]
        expr += [")", "-prune", "-o", "-type", "f", "-size", "+%dk" % (min_size // 1024), "-mtime", "+%d" % older_days, "-print0"]
        code, out, err = run(["find", root, "-xdev"] + expr, timeout=timeout)
        for raw in out.split("\0"):
            if not raw:
                continue
            size = file_bytes(raw)
            if size < min_size:
                continue
            rows.append({
                "name": os.path.basename(raw),
                "path": raw,
                "bytes": size,
                "age_days": age_days(raw),
                "last_modified": iso(dir_mtime(raw)),
            })
    # Dédoublonne par chemin réel
    seen = set()
    unique = []
    for row in sorted(rows, key=lambda r: -r["bytes"]):
        real = os.path.realpath(row["path"])
        if real in seen:
            continue
        seen.add(real)
        unique.append(row)
    return unique


def installers(roots, timeout=300):
    rows = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # on ne descend pas trop loin dans les projets
            depth = dirpath[len(root):].count(os.sep)
            if depth > 2:
                dirnames[:] = []
                continue
            for fn in filenames:
                low = fn.lower()
                if not low.endswith((".dmg", ".pkg", ".mpkg", ".iso", ".xip")):
                    continue
                p = os.path.join(dirpath, fn)
                size = file_bytes(p)
                if size < 50 * 1024 * 1024:
                    continue
                rows.append({
                    "name": fn,
                    "path": p,
                    "bytes": size,
                    "last_modified": iso(dir_mtime(p)),
                    "age_days": age_days(p),
                })
    rows.sort(key=lambda r: -r["bytes"])
    return rows


# --------------------------------------------------------------------------
# Caches / temporaires

def scan_cache_dir(path, label, limit=None):
    rows = []
    if not os.path.isdir(path):
        return rows
    try:
        names = os.listdir(path)
    except PermissionError:
        return rows
    paths = []
    for name in names:
        p = os.path.join(path, name)
        if os.path.isdir(p) and not os.path.islink(p):
            paths.append(p)
    sizes, _ = du_sizes(paths, timeout=600)
    for p in paths:
        size = sizes.get(p, 0)
        if size < 5 * 1024 * 1024:
            continue
        rows.append({
            "name": os.path.basename(p),
            "path": p,
            "bytes": size,
            "age_days": age_days(p),
            "category": "cache",
            "label": label,
        })
    rows.sort(key=lambda r: -r["bytes"])
    return rows[:limit] if limit else rows


def temp_roots():
    tmp = os.environ.get("TMPDIR", "").rstrip("/")
    if not tmp:
        return []
    # TMPDIR = /var/folders/xx/yyy/T ; C et X sont ses voisins
    parent = os.path.dirname(tmp)
    roots = [("Temporaires (T)", tmp)]
    for name, label in (("C", "Caches système (C)"), ("X", "Clones de signature (X)")):
        p = os.path.join(parent, name)
        if os.path.isdir(p):
            roots.append((label, p))
    return roots


# --------------------------------------------------------------------------
# SQLite

def sqlite_pragmas(path):
    if not os.path.exists(path):
        return {}
    code, out, _ = run(
        ["sqlite3", "file:%s?mode=ro" % path,
         "pragma page_size; pragma page_count; pragma freelist_count; pragma journal_mode;"],
        timeout=60,
    )
    if code != 0:
        return {}
    vals = [l.strip() for l in out.splitlines() if l.strip()]
    if len(vals) < 3:
        return {}
    try:
        page_size = int(vals[0])
        page_count = int(vals[1])
        freelist = int(vals[2])
    except ValueError:
        return {}
    return {
        "page_size": page_size,
        "page_count": page_count,
        "freelist_count": freelist,
        "live_bytes": (page_count - freelist) * page_size,
        "dead_bytes": freelist * page_size,
        "journal_mode": vals[3] if len(vals) > 3 else "",
    }


def sqlite_counts(path, tables):
    if not os.path.exists(path):
        return {}
    counts = {}
    for table in tables:
        code, out, _ = run(
            ["sqlite3", "file:%s?mode=ro" % path, "select count(*) from %s;" % table],
            timeout=60,
        )
        if code == 0:
            try:
                counts[table] = int(out.strip())
            except ValueError:
                pass
    return counts


# --------------------------------------------------------------------------
# Divers

def iso(ts):
    if not ts:
        return None
    return datetime.datetime.fromtimestamp(ts).astimezone().isoformat(timespec="seconds")


def human(n):
    units = ["o", "Ko", "Mo", "Go", "To"]
    v = float(n)
    for u in units:
        if v < 1024 or u == units[-1]:
            return ("%.1f %s" % (v, u)).replace(".0 ", " ")
        v /= 1024


def redact(path):
    home = HOME
    if path.startswith(home):
        return "~" + path[len(home):]
    return path


def safe_name(name):
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-") or "item"
