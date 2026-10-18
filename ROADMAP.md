# Roadmap

## 2026.10 — Fondations (fait)

- Moteur `pkdisk` en lecture seule : arbre, caches, base OpenCode, clones, Homebrew, corbeille, VM, modèles, artefacts, applications.
- Rapport HTML autonome et interactif (treemap, groupes, détail, applications, modèles, plan).
- App SwiftUI : progression en direct, WebView, export, réglages, détection Full Disk Access.
- Packaging : moteur PyInstaller, bundle `.app` signé ad-hoc, icône.

## 2026.11 — Nettoyage contrôlé

- **Actions confirmées** : suppression vers la corbeille, `VACUUM` SQLite avec app fermée, `brew cleanup` avec revue.
- **Simulation** : aperçu du gain avant exécution, journal des opérations, historique avant/après.
- **Liste d'ignorés** : protéger un chemin pour toujours (comme `cleanmymac ignore add`).
- **Sélection par lot** : cocher des items, voir le total, confirmer.

## 2026.12 — Intégration macOS

- Sparkle (build Dev à chaque push, Stable au tag), DMG stylé, cask Homebrew.
- Onboarding Full Disk Access pas à pas, avec vérification en direct.
- Scan planifié (quotidien/hebdo) et notification de résultat.
- Historique des scans avec courbe d'évolution.

## 2027 — Aller plus loin

- Détection de doublons (photos, vidéos, documents) avec empreinte partielle.
- Désinstalleur d'applications avec restes (LaunchAgents, préférences, conteneurs).
- Navigateur de gros fichiers intégré (équivalent du drill-down du rapport).
- Mode menu bar : état du disque + lancement d'un scan rapide.
- Scanner natif Swift pour les volumes réseau et les très gros disques.
