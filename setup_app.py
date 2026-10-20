"""Build a standalone Klip.app via py2app.

Usage :
    python setup_app.py py2app           # build
    python setup_app.py py2app --alias   # dev mode (lien vers les sources)
"""
import os
import sys
from setuptools import setup

APP = ["app_main.py"]
APP_NAME = "Klip"
VERSION = "2.5.1"

# Version Python du venv qui exécute ce build (ex. "3.14"). Sert à pointer
# explicitement le Python embarqué dans le bundle (cf. PyRuntimeLocations).
PYVER = f"{sys.version_info.major}.{sys.version_info.minor}"

PLIST = {
    "CFBundleName":               APP_NAME,
    "CFBundleDisplayName":        APP_NAME,
    "CFBundleIdentifier":         "com.user.clipboardpro",
    "CFBundleVersion":            VERSION,
    "CFBundleShortVersionString": VERSION,
    # FIX py2app + Python récent : sans cette clé, le stub du bundle plante au
    # lancement ("Info.plist must have a PyRuntimeLocations array"). On pointe
    # explicitement le Python embarqué (et des replis hors-bundle).
    "PyRuntimeLocations": [
        f"@executable_path/../Frameworks/Python.framework/Versions/{PYVER}/Python",
        f"~/Library/Frameworks/Python.framework/Versions/{PYVER}/Python",
        f"/Library/Frameworks/Python.framework/Versions/{PYVER}/Python",
    ],
    # v2.3 — l'app apparaît dans le Dock (en plus du menubar tray).
    # Choix utilisateur : conserver les deux pour ne pas perdre les
    # notifications + menu contextuel rapide en haut, tout en ayant
    # une icône cliquable en bas (comme une vraie app).
    "LSUIElement":             False,
    "LSMinimumSystemVersion":  "11.0",
    "NSHumanReadableCopyright": "(c) 2026",
    "NSAccessibilityUsageDescription":
        "Klip a besoin d'accéder à l'accessibilité pour intercepter "
        "le raccourci Option+Cmd+V et coller automatiquement dans l'app précédente.",
    "NSAppleEventsUsageDescription":
        "Pour activer l'app frontale précédente lors du collage automatique.",
    "NSInputMonitoringUsageDescription":
        "Pour le raccourci global Option+Cmd+V et l'expander de snippets.",
    "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": False},
}

OPTIONS = {
    "argv_emulation": False,
    "plist": PLIST,
    # packages = copie complete des packages (plus robuste qu'includes)
    "packages": ["clipboard_pro", "pynput"],
    "includes": [
        "pynput.keyboard",
        "pynput.mouse",
        # Backends macOS de pynput (sinon ImportError silencieux au runtime)
        "pynput.keyboard._darwin",
        "pynput.mouse._darwin",
    ],
    "excludes": ["tkinter", "test", "unittest"],
    # Icone : on assume qu'elle est presente; le build echouera explicitement sinon
    "iconfile": "icon.icns",
    # On reste en arm64 pour ce build : universal2 demanderait des wheels
    # universelles pour PyQt6/pyobjc qui ne sont pas disponibles.
    "arch": "arm64",
    # Pas de log de debug verbeux
    "optimize": 2,
}

# Verification pre-build : iconfile doit etre lisible
if not os.access(OPTIONS["iconfile"], os.R_OK):
    raise SystemExit(
        f"Erreur : {OPTIONS['iconfile']} est introuvable ou non lisible. "
        "Verifie les permissions."
    )

setup(
    app=APP,
    name=APP_NAME,
    version=VERSION,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
