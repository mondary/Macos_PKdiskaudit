# Changelog

Historique des évolutions de PKDiskAudit.

## [2026.10.6] - 2026-10-22
### Added
- Lien de soutien **Ko-fi** discret dans les réglages de l'app (`https://ko-fi.com/pouark`), sans SDK ni suivi.

## [2026.10.5] - 2026-10-22
### Added
- Le rapport HTML devient navigable par **rooms** : une barre d'onglets collante (carte, gisement, détail, apps, modèles, zombies, plan) n'affiche qu'une section à la fois, avec liens profonds (`#apps`), flèches clavier et raccourcis `1`–`7`.
- Bouton **Tout déplier** et feuille d'impression : le rapport reste lisible d'un seul tenant, et les sections restent toutes présentes sans JavaScript.
- Deux promesses en tête de rapport (« Rien n'est supprimé », « Rien ne sort du Mac ») et une règle de lecture couleur gris / vert / ambre.
### Changed
- `report/rooms.js` est inliné dans le HTML par le moteur (nouvel asset PyInstaller) ; le rapport reste autonome et hors ligne.

## [2026.10.4] - 2026-10-18
### Fixed
- Les garde-fous de `cleanup.py` et `cleanup_review.py` comparent désormais des chemins **réels** : `/var` étant un lien vers `/private/var`, les temporaires système étaient refusés à tort (et le nettoyage des caches sous-estimé).
- `cleanup.py` ignore les chemins disparus entre l'inventaire et la suppression (plus d'erreurs de course).

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
