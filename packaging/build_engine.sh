#!/bin/sh
# Construit le moteur pkdisk en binaire autonome (PyInstaller).
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$ROOT"

if [ ! -d .venv-build ]; then
  python3 -m venv .venv-build
fi
# shellcheck disable=SC1091
. .venv-build/bin/activate
python -m pip install --quiet --upgrade pip pyinstaller

pyinstaller --noconfirm --clean --onefile \
  --name pkdisk \
  --paths engine \
  --add-data "report/style.css:." \
  --add-data "report/rooms.js:." \
  --exclude-module tkinter \
  engine/pkdisk_entry.py

rm -f pkdisk.spec
rm -rf build
echo "Built $ROOT/dist/pkdisk"
