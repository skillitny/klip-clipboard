#!/usr/bin/env bash
# Désinstalle proprement le LaunchAgent et arrête le processus.
# (Garde la base de données pour ne pas perdre l'historique — supprimez
#  ~/.clipboard_pro/ vous-même si vous voulez tout effacer.)
set -euo pipefail

PLIST_PATH="$HOME/Library/LaunchAgents/com.user.clipboardpro.plist"

if [ -f "$PLIST_PATH" ]; then
  launchctl unload "$PLIST_PATH" 2>/dev/null || true
  rm -f "$PLIST_PATH"
  echo "✔ LaunchAgent supprimé."
else
  echo "Aucun LaunchAgent trouvé."
fi

pkill -f "clipboard_pro.main" 2>/dev/null || true
echo "✔ Processus arrêté."
echo
echo "Vos données sont conservées dans ~/.clipboard_pro/."
echo "Pour tout supprimer : rm -rf ~/.clipboard_pro/"
