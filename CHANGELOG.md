# Changelog

Historique des évolutions de PKDiskAudit.

## [2026.10.3] - 2026-10-18
### Added
- `scripts/cleanup_review.py` : suppression contrôlée d'une liste de chemins (dry-run par défaut, racines autorisées, refus des fichiers suivis par Git, liste de protection, journal et mesure réelle du volume avant/après).

## [2026.10.2] - 2026-10-18
### Fixed
- Les clones de signature APFS ne sont plus comptés dans l'espace récupérable : `du` additionne des blocs partagés avec l'app d'origine. Ils apparaissent désormais comme « apparents » et sont exclus des totaux « sans risque » et « à arbitrer » ; le gain réel est mesuré à la suppression.
### Added
- `scripts/cleanup.py` : nettoyage contrôlé (dry-run par défaut, garde-fous de chemins, journal, mesure réelle du volume avant/après).
- `scripts/vacuum-opencode.sh` : compactage SQLite par `VACUUM INTO`, avec vérification d'intégrité et comparaison des compteurs avant remplacement.

## [2026.10.1] - 2026-10-18
### Added
- Moteur `pkdisk` en lecture seule : arbre du disque, caches, base OpenCode (pages libres SQLite), clones de signature, Homebrew, corbeille, VM, modèles IA, artefacts de build, inventaire des applications avec dernière utilisation Spotlight.
- Rapport HTML autonome : treemap, jauge du volume Data, groupes « sans risque / à arbitrer », détail par chemin, tableaux applications et modèles, plan en trois phases.
- Application macOS SwiftUI : fenêtre native, sidebar, rapport en WKWebView, progression en direct depuis les phases du moteur, export HTML, écran d'accueil et réglages.
- Packaging : `build_engine.sh` (PyInstaller), `build_app.sh` (bundle signé ad-hoc), icône générée, `run.sh`.
- Détection explicite des scans partiels (permissions) et déduplication des racines imbriquées.
