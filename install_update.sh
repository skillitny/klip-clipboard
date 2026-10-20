#!/usr/bin/env bash
# =============================================================================
#  install_update.sh — Met à jour Klip SUR TON MAC, en une commande.
#
#  • SAUVEGARDE d'abord tout ton historique + tes réglages (rien n'est perdu).
#  • Construit la nouvelle version.
#  • Supprime proprement l'ANCIENNE version (app + ancien démarrage auto).
#  • Installe la NOUVELLE dans ~/Applications (dossier Applications de
#    TON compte : /Applications est bloqué par « Gestion des apps » et
#    partagé avec les autres comptes macOS du Mac).
#  • Configure : démarrage automatique au login + relance auto si crash.
#  • Vérifie à la fin que tout est en place et que tes données sont intactes.
#
#  Tes données (historique, favoris, snippets, préférences) vivent dans
#  ~/.clipboard_pro/ et NE SONT PAS touchées par la mise à jour — elles sont
#  en plus sauvegardées par sécurité avant toute opération.
#
#  Usage :
#     cd ~/clipboard_history_app
#     chmod +x install_update.sh
#     ./install_update.sh
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "✗ À lancer sur macOS."
  exit 1
fi

APP_NAME="Klip"
APP_PATH="dist/${APP_NAME}.app"
DEST_APP="$HOME/Applications/${APP_NAME}.app"
DATA="$HOME/.clipboard_pro"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$HOME/.clipboard_pro.backup-$STAMP"
LA_DIR="$HOME/Library/LaunchAgents"
NEW_PLIST="$LA_DIR/com.user.klip.plist"
OLD_PLIST="$LA_DIR/com.user.clipboardpro.plist"
VENV="$HERE/.venv"

VERSION="$(python3 -c "import re,io; print(re.search(r'__version__\s*=\s*\"([^\"]+)\"', io.open('clipboard_pro/__init__.py').read()).group(1))")"
echo "→ Mise à jour vers Klip v${VERSION}"

# ---- 1. SAUVEGARDE des données (priorité absolue) --------------------------
if [[ -d "$DATA" ]]; then
  echo "→ Sauvegarde de tes données : $BACKUP"
  cp -R "$DATA" "$BACKUP"
else
  echo "→ Aucune donnée existante (première install) — rien à sauvegarder."
fi
mkdir -p "$DATA"

# ---- 2. Build de la nouvelle app -------------------------------------------
if [[ ! -d "$VENV" ]]; then
  echo "→ Création du venv"
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
echo "→ Dépendances + build (1–2 min)…"
pip install --upgrade pip wheel >/dev/null
pip install -r clipboard_pro/requirements.txt >/dev/null
# setuptools<72 : py2app 0.28 plante sinon (Popen() « verbose »).
pip install py2app "setuptools<72" >/dev/null
rm -rf build dist
python setup_app.py py2app
if [[ ! -d "$APP_PATH" ]]; then
  echo "✗ Build échoué. Tes données sont intactes ($BACKUP). Rien d'autre n'a été modifié."
  exit 1
fi

# Garde-fou : le stub py2app plante au lancement si Info.plist n'a pas de
# PyRuntimeLocations. On vérifie AVANT de toucher à l'app actuelle, pour ne
# jamais remplacer une version qui marche par une version cassée.
if ! /usr/libexec/PlistBuddy -c "Print :PyRuntimeLocations" \
     "$APP_PATH/Contents/Info.plist" >/dev/null 2>&1; then
  echo "✗ Build invalide : PyRuntimeLocations absent de l'Info.plist."
  echo "  L'ancienne version n'a PAS été touchée. Données sauvegardées : $BACKUP"
  echo "  (Lance l'app depuis les sources en attendant :"
  echo "   .venv/bin/python -m clipboard_pro.main )"
  exit 1
fi

# Pas de re-signature --deep : py2app a déjà signé en ad-hoc, et un
# `codesign --deep` casse certaines dylibs (liblzma → "invalid format").

# ---- 3. Arrêt + suppression de l'ANCIENNE version --------------------------
echo "→ Arrêt des instances en cours"
pkill -f "clipboard_pro.main" 2>/dev/null || true   # ancien mode venv
pkill -x "Klip" 2>/dev/null || true
pkill -x "Clipboard Pro" 2>/dev/null || true

echo "→ Retrait de l'ancien démarrage automatique"
# Ancien LaunchAgent (mode venv v1)
if [[ -f "$OLD_PLIST" ]]; then
  launchctl unload "$OLD_PLIST" 2>/dev/null || true
  rm -f "$OLD_PLIST"
fi
# Anciens Login Items (mode bundle)
osascript -e 'tell application "System Events" to if exists login item "Klip" then delete login item "Klip"' 2>/dev/null || true
osascript -e 'tell application "System Events" to if exists login item "Clipboard Pro" then delete login item "Clipboard Pro"' 2>/dev/null || true

echo "→ Suppression des anciennes apps"
# On ne touche PAS à /Applications : d'autres comptes macOS du Mac
# peuvent y faire tourner leur propre Klip.
rm -rf "$HOME/Applications/Clipboard Pro.app"
mkdir -p "$HOME/Applications"

# ---- 4. Installation de la NOUVELLE version --------------------------------
echo "→ Installation dans ~/Applications"
rm -rf "$DEST_APP" 2>/dev/null || true
# ditto gère mieux les bundles .app que cp -R. Pas de re-signature (py2app
# a déjà signé ; un --deep casserait liblzma).
if ! ditto "$APP_PATH" "$DEST_APP" 2>/dev/null; then
  echo ""
  echo "⚠ macOS a bloqué l'installation dans ~/Applications (« Operation not permitted »)."
  echo "  C'est la protection « Gestion des apps » de macOS."
  echo "  → Solution simple : ouvre le Finder, va dans le dossier dist/, et"
  echo "    GLISSE Klip.app dans Applications toi-même (macOS te demandera d'autoriser)."
  echo "  → Ou autorise ton Terminal dans : Réglages Système → Confidentialité"
  echo "    et sécurité → « Gestion des apps », puis relance ce script."
  echo ""
  echo "  En attendant, ta nouvelle app marche déjà via :"
  echo "    .venv/bin/python -m clipboard_pro.main"
  open "$HERE/dist" 2>/dev/null || true
  exit 1
fi

# Rafraîchit LaunchServices + le cache d'icônes : sinon, après une
# réinstallation au même chemin, le Dock garde une icône générique/vide.
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Versions/A/Frameworks/LaunchServices.framework/Versions/A/Support/lsregister"
[ -x "$LSREGISTER" ] && "$LSREGISTER" -f "$DEST_APP" 2>/dev/null || true
touch "$DEST_APP" 2>/dev/null || true
killall Dock 2>/dev/null || true

# ---- 5. Démarrage auto au login + relance auto si crash --------------------
echo "→ Configuration démarrage auto + relance si crash"
mkdir -p "$LA_DIR"
cat > "$NEW_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>             <string>com.user.klip</string>
  <key>ProgramArguments</key>
  <array>
    <string>$DEST_APP/Contents/MacOS/$APP_NAME</string>
  </array>
  <key>RunAtLoad</key>         <true/>
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>  <false/>
  </dict>
  <key>ProcessType</key>       <string>Interactive</string>
  <key>StandardOutPath</key>   <string>$DATA/stdout.log</string>
  <key>StandardErrorPath</key> <string>$DATA/stderr.log</string>
</dict>
</plist>
PLIST

# Valider le plist avant chargement
plutil -lint "$NEW_PLIST" >/dev/null
# macOS récent (Ventura+/Tahoe) : `launchctl load` est obsolète → on utilise
# bootout/bootstrap dans le domaine GUI de l'utilisateur, avec repli legacy.
UID_NUM="$(id -u)"
launchctl bootout "gui/$UID_NUM/com.user.klip" 2>/dev/null || true
launchctl bootout "gui/$UID_NUM" "$NEW_PLIST" 2>/dev/null || true
if ! launchctl bootstrap "gui/$UID_NUM" "$NEW_PLIST" 2>/dev/null; then
  echo "  (bootstrap indisponible, repli sur launchctl load)"
  launchctl load "$NEW_PLIST" 2>/dev/null || true
fi
launchctl enable "gui/$UID_NUM/com.user.klip" 2>/dev/null || true
launchctl kickstart "gui/$UID_NUM/com.user.klip" 2>/dev/null || true

# ---- 6. VÉRIFICATIONS -------------------------------------------------------
echo
echo "──────── Vérifications ────────"
FAIL=0

if [[ -d "$DEST_APP" ]]; then echo "✓ App installée : $DEST_APP"; else echo "✗ App manquante"; FAIL=1; fi

if [[ -f "$DATA/history.db" ]]; then
  echo "✓ Base d'historique présente : $DATA/history.db"
else
  echo "ℹ Pas encore de history.db (normal si tu n'avais rien copié avant)."
fi

if launchctl print "gui/$UID_NUM/com.user.klip" >/dev/null 2>&1 \
   || launchctl list 2>/dev/null | grep -q "com.user.klip"; then
  echo "✓ Démarrage auto + relance-si-crash actifs (launchd)."
else
  echo "✗ LaunchAgent non chargé."; FAIL=1
fi

sleep 2
if pgrep -x "$APP_NAME" >/dev/null; then
  echo "✓ Klip tourne ($(pgrep -x "$APP_NAME" | tr '\n' ' '))."
else
  echo "ℹ Klip ne semble pas encore lancé — il devrait démarrer sous peu (launchd)."
fi

echo "✓ Sauvegarde de sécurité : ${BACKUP:-aucune (1ère install)}"
echo "───────────────────────────────"

if [[ "$FAIL" -eq 0 ]]; then
  cat <<MSG

✔ Klip v${VERSION} installée. Ton historique et tes réglages sont conservés.
  • Démarrage automatique au login : activé
  • Relance automatique en cas de crash : activée (pas sur quit volontaire)
  • Raccourci : ⌥⌘V

Au 1er lancement de cette version, Klip demandera ta CLÉ DE LICENCE
(elle t'a été fournie). Colle-la, c'est à usage unique.

Si un jour tu veux revenir en arrière, ta sauvegarde est dans :
  $BACKUP
MSG
else
  echo
  echo "⚠ Une vérification a échoué (voir ci-dessus). Tes données restent"
  echo "  sauvegardées dans : $BACKUP"
  exit 1
fi
