#!/usr/bin/env bash
# Installeur Clipboard Pro — crée un venv, installe les dépendances,
# enregistre un LaunchAgent pour démarrage automatique.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HERE"
VENV="$APP_DIR/.venv"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
PLIST_NAME="com.user.clipboardpro.plist"
PLIST_PATH="$LAUNCH_AGENTS/$PLIST_NAME"
PYTHON_BIN="${PYTHON_BIN:-python3}"

echo "→ Création du venv dans $VENV"
"$PYTHON_BIN" -m venv "$VENV"
"$VENV/bin/pip" install --upgrade pip wheel >/dev/null
"$VENV/bin/pip" install -r "$APP_DIR/clipboard_pro/requirements.txt"

mkdir -p "$LAUNCH_AGENTS"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>             <string>com.user.clipboardpro</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV/bin/python</string>
    <string>-m</string>
    <string>clipboard_pro.main</string>
  </array>
  <key>WorkingDirectory</key>  <string>$APP_DIR</string>
  <key>RunAtLoad</key>         <true/>
  <key>KeepAlive</key>         <true/>
  <key>ProcessType</key>       <string>Interactive</string>
  <key>StandardOutPath</key>   <string>$HOME/.clipboard_pro/stdout.log</string>
  <key>StandardErrorPath</key> <string>$HOME/.clipboard_pro/stderr.log</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key>      <string>$APP_DIR</string>
  </dict>
</dict>
</plist>
EOF

mkdir -p "$HOME/.clipboard_pro"

# (Re)charger le LaunchAgent
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load   "$PLIST_PATH"

echo
echo "✔ Installation terminée."
echo "  • L'app démarre maintenant et au prochain login."
echo "  • Raccourci global : ⌥⌘V (Option + Cmd + V)."
echo "  • Si le raccourci ne marche pas, autorisez l'app dans :"
echo "    Réglages Système → Confidentialité et sécurité → Surveillance des entrées."
echo
echo "Pour désinstaller : ./uninstall.sh"
