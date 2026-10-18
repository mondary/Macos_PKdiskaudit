#!/bin/sh
# Assemble dist/PKDiskAudit.app (SwiftPM + moteur embarqué si présent).
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
VERSION=$(sed -nE 's/^##? \[([0-9]+\.[0-9]+\.[0-9]+)\].*/\1/p' "$ROOT/CHANGELOG.md" | sed -n '1p')
test -n "$VERSION" || { echo "Version introuvable dans CHANGELOG.md" >&2; exit 1; }

APP="$ROOT/dist/PKDiskAudit.app"

swift build --package-path "$ROOT" -c release --disable-index-store
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/engine"

cp "$ROOT/.build/release/PKDiskAudit" "$APP/Contents/MacOS/PKDiskAudit"

if [ -x "$ROOT/dist/pkdisk" ]; then
  cp "$ROOT/dist/pkdisk" "$APP/Contents/Resources/engine/pkdisk"
  echo "Moteur embarqué : dist/pkdisk"
else
  echo "Moteur absent : lance packaging/build_engine.sh avant pour un bundle autonome."
fi
cp "$ROOT/report/style.css" "$APP/Contents/Resources/engine/style.css"
cp "$ROOT/packaging/icons/icon.icns" "$APP/Contents/Resources/icon.icns"

cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleExecutable</key><string>PKDiskAudit</string>
  <key>CFBundleIdentifier</key><string>com.mondary.pkdiskaudit</string>
  <key>CFBundleName</key><string>PKDiskAudit</string>
  <key>CFBundleDisplayName</key><string>PK Disk Audit</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.utilities</string>
  <key>NSHumanReadableCopyright</key><string>PKDiskAudit — audit disque en lecture seule</string>
</dict></plist>
EOF

codesign --force --sign - --timestamp=none "$APP"
echo "Built $APP ($VERSION)"
