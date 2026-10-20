#!/usr/bin/env bash
# =============================================================================
#  build_release.sh — Construit Klip.app + le DMG distribuable, en une commande.
#
#  À LANCER SUR UN MAC (Apple Silicon). Pas de signature Apple payante requise :
#  l'app est signée ad-hoc. Tes amis verront un avertissement Gatekeeper la
#  première fois → voir INSTALL-AMIS.txt pour la marche à suivre (clic droit →
#  Ouvrir). Le DMG produit s'envoie tel quel (WhatsApp, AirDrop, mail…).
#
#  Usage :
#     chmod +x build_release.sh
#     ./build_release.sh
#
#  Résultat : Klip-<version>.dmg à la racine du dossier.
# =============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

# ---- 0. Garde-fous ----------------------------------------------------------
if [[ "$(uname)" != "Darwin" ]]; then
  echo "✗ Ce script doit tourner sur macOS (besoin de py2app + frameworks Apple)."
  exit 1
fi

VERSION="$(python3 -c "import re,io; print(re.search(r'__version__\s*=\s*\"([^\"]+)\"', io.open('clipboard_pro/__init__.py').read()).group(1))")"
APP_NAME="Klip"
APP_PATH="dist/${APP_NAME}.app"
DMG_NAME="${APP_NAME}-${VERSION}.dmg"
VENV="$HERE/.venv"

echo "→ Build Klip v${VERSION}"

# ---- 1. venv + dépendances --------------------------------------------------
if [[ ! -d "$VENV" ]]; then
  echo "→ Création du venv"
  python3 -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
echo "→ Installation des dépendances (peut prendre quelques minutes la 1ère fois)"
pip install --upgrade pip wheel >/dev/null
pip install -r clipboard_pro/requirements.txt >/dev/null
# setuptools<72 : py2app 0.28 plante sinon (Popen() « verbose »).
pip install py2app dmgbuild "setuptools<72" >/dev/null

# ---- 2. Vérif icône ---------------------------------------------------------
if [[ ! -r icon.icns ]]; then
  echo "✗ icon.icns introuvable. Build annulé."
  exit 1
fi

# ---- 3. Clean + build de l'app ---------------------------------------------
echo "→ Nettoyage des builds précédents"
rm -rf build dist

echo "→ Build du .app via py2app (1–2 min)…"
python setup_app.py py2app

if [[ ! -d "$APP_PATH" ]]; then
  echo "✗ Build échoué : $APP_PATH introuvable."
  exit 1
fi

# Garde-fou : sans PyRuntimeLocations dans l'Info.plist, le bundle plante au
# lancement chez tes amis. On refuse de produire un DMG cassé.
if ! /usr/libexec/PlistBuddy -c "Print :PyRuntimeLocations" \
     "$APP_PATH/Contents/Info.plist" >/dev/null 2>&1; then
  echo "✗ Build invalide : PyRuntimeLocations absent de l'Info.plist."
  echo "  Le DMG n'a pas été créé (il aurait planté chez tes amis)."
  exit 1
fi

# ---- 4. Signature ---------------------------------------------------------
# py2app signe déjà chaque binaire/dylib en ad-hoc pendant le build. On NE
# refait PAS de `codesign --force --deep` : sur certaines dylibs (liblzma) il
# échoue ("invalid or unsupported format") et CASSE la signature du bundle.
# On laisse donc la signature produite par py2app telle quelle.
echo "→ Signature : laissée à py2app (pas de re-signature --deep)"

# ---- 5. Construction du DMG -------------------------------------------------
echo "→ Construction du DMG : $DMG_NAME"
rm -f "$DMG_NAME"
dmgbuild -s dmg_settings.py -D app="$APP_PATH" "$APP_NAME" "$DMG_NAME"

if [[ ! -f "$DMG_NAME" ]]; then
  echo "✗ Échec de la création du DMG."
  exit 1
fi

SIZE="$(du -h "$DMG_NAME" | cut -f1)"

cat <<MSG

✔ Terminé : $DMG_NAME ($SIZE)

ARCHITECTURE : ce build est arm64 (Apple Silicon : M1/M2/M3/M4).
  Les amis sur Mac Intel (avant ~2020) ne pourront pas le lancer.
  La quasi-totalité des Mac récents sont compatibles.

À VÉRIFIER AVANT D'ENVOYER (sur ce Mac, 3 min) :
  1. Double-clique $DMG_NAME → glisse Klip dans Applications.
  2. Clic droit sur Klip → Ouvrir (1ère fois, contourne Gatekeeper).
  3. L'app s'ouvre directement (accès libre, pas de clé de licence).
  4. Copie un texte ailleurs → ⌥⌘V → l'historique apparaît.
  5. Autorise Accessibilité + Surveillance des entrées si demandé.
  6. Ouvre une capture → ✎ Éditer → masque une ligne → Copier.
  7. Confirme qu'aucun crash dans ~/.clipboard_pro/stderr.log

PUBLICATION : release GitHub sur skillitny/klip-app + lien du site (index.html).
MSG
