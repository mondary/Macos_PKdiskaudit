# PKDiskAudit

![Icône PKDiskAudit](icon.png)

[🇫🇷 FR](README.md) · [🇬🇧 EN](README_en.md)

❤️ [Soutenir PK Disk Audit sur Ko-fi](https://ko-fi.com/pouark)

**Audit disque macOS en lecture seule.** Il mesure, classe et explique où est passée la place — puis te laisse décider. Aucune suppression dans cette version.

Version `2026.10.5` · [Changelog](CHANGELOG.md)

## ✅ Ce que ça fait

- **Mesure réelle** : tailles allouées sur le disque (comme `du`), fichiers sparse et clones APFS gérés, montages réseau exclus.
- **Carte du disque** : treemap des grands postes, jauge du volume Data, répartition dossier perso / applications / système.
- **Le gisement** : chaque poste classé `sans risque` (cache, build, dépendances), `à arbitrer` (modèles, VM, applications) ou ignoré.
- **Détail par chemin** : taille, âge, projet d'origine, action proposée — jamais exécutée sans revue.
- **Applications** : 345 apps mesurées, dernière utilisation et nombre de lancements via Spotlight, avec la mention explicite des usages inconnus.
- **Modèles IA** : Hugging Face, Ollama, LM Studio et dossiers `models` des apps tierces.
- **Zombies** : base OpenCode (pages libres SQLite), clones de signature Chrome, caches, artefact de build, VM.
- **Rapport HTML autonome** : sept onglets — carte, gisement, détail, apps, modèles, zombies, plan — exportable, lisible hors ligne, sans dépendance.

## 🚀 Utilisation

```sh
# Audit complet + rapport HTML
PYTHONPATH=engine python3 -m pkdisk run --out ~/Desktop/pkdisk-rapport

# Scan rapide (caches, base OpenCode, clones, VM, corbeille)
PYTHONPATH=engine python3 -m pkdisk run --fast --out ~/Desktop/pkdisk-rapport

# Ajouter la recherche des gros fichiers anciens (plus lent)
PYTHONPATH=engine python3 -m pkdisk run --large --out ~/Desktop/pkdisk-rapport

# Vérifier l'environnement (droits, outils, disque)
PYTHONPATH=engine python3 -m pkdisk doctor
```

### Application macOS

```sh
./packaging/run.sh              # build + lancement depuis le dépôt
./packaging/build_engine.sh     # moteur autonome (PyInstaller)
./packaging/build_app.sh        # dist/PKDiskAudit.app
```

L'app SwiftUI affiche le rapport dans une `WKWebView`, lance le moteur, suit la progression en direct et exporte le HTML.

## 🧱 Architecture

| Couche | Rôle | Fichier |
|---|---|---|
| Moteur | mesure, classification, JSON | `engine/pkdisk/` |
| Rapport | HTML autonome depuis le JSON | `report/style.css` + `engine/pkdisk/report.py` |
| App | fenêtre native, progression, export | `src/macos/PKDiskAuditApp.swift` |

Le moteur ne supprime jamais rien. Il produit un JSON versionné (`schema: 1`) que l'app et le rapport consomment.

## 🔒 Sécurité

- Lecture seule par défaut ; aucune commande destructive exécutée.
- Racines imbriquées dédupliquées, montages réseau et volumes cloud exclus.
- Chaque scan indique s'il est **complet** ou **partiel** (`partial_sections`) — un dossier illisible n'est jamais compté comme vide.
- Les actions proposées (supprimer, VACUUM, désinstaller) sont décrites, pas exécutées.

## 📝 Notes

- **`useCount = 0` ne signifie pas « jamais utilisée »** : Spotlight ne trace pas toutes les apps. Le rapport le dit explicitement.
- Un `VACUUM` SQLite compacte le fichier sans supprimer la moindre session ; il faut simplement fermer OpenCode.
- Les clones APFS (`code_sign_clone`) partagent leurs blocs avec l'app d'origine : leur taille `du` est **apparente** et n'est pas comptée dans l'espace récupérable. Le gain réel est mesuré à la suppression.
- L'inspiration vient de [Mole](https://github.com/tw93/Mole) (GPL-3.0) et de CleanMyMac CLI pour le modèle « scan → revue → confirmation ». Aucun code de ces projets n'est réutilisé.

## 📄 Licence

MIT — voir [LICENSE](LICENSE).
