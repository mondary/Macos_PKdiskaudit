#!/bin/sh
# Compacte la base SQLite d'OpenCode sans perdre une seule session.
#
# À lancer OpenCode FERMÉ (l'app et son service). Le script :
#   1. vérifie l'intégrité de la base source ;
#   2. crée une copie compacte avec VACUUM INTO ;
#   3. vérifie l'intégrité et les compteurs (sessions, messages, parties) ;
#   4. remplace la base et conserve l'ancienne à côté.
#
# Suppression de l'ancienne base après vérification : relancer avec --purge-old.
set -eu

DB="${PKDISK_OPENCODE_DB:-$HOME/.local/share/opencode/opencode.db}"
COMPACT="$DB.compact"
OLD="$DB.old"

if [ "${1:-}" = "--purge-old" ]; then
  rm -f "$OLD" "$COMPACT"
  echo "Ancienne base supprimée : $OLD"
  exit 0
fi

if [ ! -f "$DB" ]; then
  echo "Base introuvable : $DB" >&2
  exit 1
fi

if pgrep -x opencode >/dev/null 2>&1 || pgrep -f "opencode.*(serve|server)" >/dev/null 2>&1; then
  echo "OpenCode tourne encore. Quitte l'application et son service, puis relance ce script." >&2
  exit 1
fi

command -v sqlite3 >/dev/null 2>&1 || { echo "sqlite3 est requis." >&2; exit 1; }

before_kb=$(du -sk "$DB" | awk '{print $1}')

echo "→ Vérification de la base source…"
integrity=$(sqlite3 "$DB" "PRAGMA integrity_check;")
if [ "$integrity" != "ok" ]; then
  echo "Intégrité source : $integrity" >&2
  exit 1
fi
counts_before=$(sqlite3 "$DB" "select (select count(*) from session)||'/'||(select count(*) from message)||'/'||(select count(*) from part);")
echo "  sessions/messages/parties : $counts_before"

rm -f "$COMPACT"
echo "→ Compactage (VACUUM INTO)…"
sqlite3 "$DB" "VACUUM INTO '$COMPACT';"

echo "→ Vérification de la copie…"
integrity2=$(sqlite3 "$COMPACT" "PRAGMA integrity_check;")
if [ "$integrity2" != "ok" ]; then
  echo "Intégrité copie : $integrity2" >&2
  rm -f "$COMPACT"
  exit 1
fi
counts_after=$(sqlite3 "$COMPACT" "select (select count(*) from session)||'/'||(select count(*) from message)||'/'||(select count(*) from part);")
if [ "$counts_before" != "$counts_after" ]; then
  echo "Compteurs différents : $counts_before vs $counts_after" >&2
  rm -f "$COMPACT"
  exit 1
fi

mv "$DB" "$OLD"
mv "$COMPACT" "$DB"
rm -f "$DB-wal" "$DB-shm"

after_kb=$(du -sk "$DB" | awk '{print $1}')
echo "✓ Base compactée : $((before_kb / 1024)) Mo → $((after_kb / 1024)) Mo"
echo "  Ancienne base conservée : $OLD"
echo "  Après avoir vérifié qu'OpenCode fonctionne : sh scripts/vacuum-opencode.sh --purge-old"
