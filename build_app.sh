#!/usr/bin/env bash
# Construit Clipboard Pro.app via py2app et l'installe dans /Applications.
# Demande la permission Accessibilité une seule fois (par bundle) au premier
# lancement, plus jamais besoin d'autoriser tout Python.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/.venv"
APP_NAME="Clipboard Pro"
BUILT_APP="$HERE/dist/$APP_NAME.app"
DEST_APP="/Applications/$APP_NAME.app"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
PLIST_NAME="com.user.clipboardpro.plist"
PLIST_PATH="$LAUNCH_AGENTS/$PLIST_NAME"

# 1. venv + deps
if [ ! -d "$VENV" ]; then
  echo "→ Création du venv"
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --upgrade pip wheel >/dev/null
"$VENV/bin/pip" install -r "$HERE/clipboard_pro/requirements.txt"
"$VENV/bin/pip" install py2app

# 2. clean + build
echo "→ Build du .app (peut prendre 1–2 min)"
rm -rf "$HERE/build" "$HERE/dist"
cd "$HERE"
"$VENV/bin/python" setup_app.py py2app

if [ ! -d "$BUILT_APP" ]; then
  echo "✗ Build échoué : $BUILT_APP introuvable."
  exit 1
fi

# 3. Désactiver le LaunchAgent v1 (script Python via pip) pour éviter le doublon
if [ -f "$PLIST_PATH" ]; then
  echo "→ Désactivation du LaunchAgent v1"
  launchctl unload "$PLIST_PATH" 2>/dev/null || true
  rm -f "$PLIST_PATH"
fi

# 4. Stopper toute instance Python en cours
pkill -f "clipboard_pro.main" 2>/dev/null || true

# 5. Installation dans /Applications
echo "→ Installation dans /Applications"
rm -rf "$DEST_APP"
cp -R "$BUILT_APP" "$DEST_APP"

# 6. Ad-hoc signature pour stabiliser l'identité du bundle
codesign --force --deep --sign - "$DEST_APP" || true

# 7. Démarrage automatique au login (Login Items)
osascript <<EOF || true
tell application "System Events"
    if not (exists login item "$APP_NAME") then
        make login item at end with properties {path:"$DEST_APP", hidden:true}
    end if
end tell
EOF

# 8. Premier lancement
open -g "$DEST_APP"

cat <<MSG

✔ Clipboard Pro installée dans $DEST_APP
  • Démarrage automatique : activé via Login Items
  • Raccourci : ⌥⌘V (Option + Cmd + V)

À la première utilisation, macOS va demander deux autorisations :
  • Surveillance des entrées (pour ⌥⌘V et le développement de texte)
  • Accessibilité (pour l'auto-paste)
Cochez Clipboard Pro dans Réglages Système → Confidentialité et sécurité.
Cette fois, c'est le bundle "Clipboard Pro.app" qui est autorisé,
pas "Python" — beaucoup plus propre.

MSG
