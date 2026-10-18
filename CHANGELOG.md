# Changelog

Historique des évolutions de PKDiskAudit.

## [2026.10.1] - 2026-10-18
### Added
- Moteur `pkdisk` en lecture seule : arbre du disque, caches, base OpenCode (pages libres SQLite), clones de signature, Homebrew, corbeille, VM, modèles IA, artefacts de build, inventaire des applications avec dernière utilisation Spotlight.
- Rapport HTML autonome : treemap, jauge du volume Data, groupes « sans risque / à arbitrer », détail par chemin, tableaux applications et modèles, plan en trois phases.
- Application macOS SwiftUI : fenêtre native, sidebar, rapport en WKWebView, progression en direct depuis les phases du moteur, export HTML, écran d'accueil et réglages.
- Packaging : `build_engine.sh` (PyInstaller), `build_app.sh` (bundle signé ad-hoc), icône générée, `run.sh`.
- Détection explicite des scans partiels (permissions) et déduplication des racines imbriquées.
