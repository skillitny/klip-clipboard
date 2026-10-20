# Plan de portage Windows — Klip

But : faire tourner Klip sur Windows 10/11 en réutilisant au maximum le code
existant, via une **couche d'abstraction plateforme**. Le build final (`.exe`)
se fait **sur une machine Windows** (PyInstaller).

---

## 1) Ce qui est déjà portable (≈ 60%)

Aucune dépendance macOS, fonctionne tel quel sur Windows :

- `ui.py`, `theme.py` (PyQt6 — cross-platform)
- `db.py` (SQLite), `classify.py`, `secrets.py`, `fuzzy.py`
- `expander.py`, `hotkey.py` (pynput — cross-platform)
- `licensing.py`, `_ed25519.py`, `activation.py` (seul `machine_id()` a une
  branche macOS, cf. §3)
- `onboarding.py`, `cheatsheet.py`, `about.py` (hors quelques appels pyobjc)

## 2) Ce qui doit être réécrit pour Windows

| Module macOS | Rôle | Équivalent Windows |
|---|---|---|
| `capture.py` (`NSPasteboard.changeCount`) | Détecter + lire le presse-papiers | `win32clipboard` + **`GetClipboardSequenceNumber`** (l'équivalent EXACT de `changeCount`) |
| `capture.py` (write text/image) | Écrire dans le presse-papiers | `win32clipboard.SetClipboardData` (CF_UNICODETEXT, CF_DIB) |
| `autopaste.py` (`CGEvent` ⌘V) | Coller dans l'app précédente | `SetForegroundWindow` + `SendInput` Ctrl+V (ctypes/pywin32) |
| `ocr.py` (Vision) | OCR images | **Windows.Media.Ocr** via `winsdk` (intégré, sans install) ou `pytesseract` (fallback) |
| `permissions.py` (AX/IOHID) | Permissions | **No-op** sur Windows (pas d'autorisation requise) → renvoie « accordé » |
| `app_icons.py` / app frontale | Nom + icône de l'app source | `GetForegroundWindow` → PID → nom via `psutil` ; icône via extraction exe (optionnel) |
| `screenshot_watcher.py` | Capturer les screenshots | Surveiller le dossier Captures, ou ignorer (Windows met déjà l'image au presse-papiers) |
| LaunchAgent (`install_update.sh`) | Démarrage auto | Raccourci dans `shell:startup` ou clé registre `Run` |

## 3) Architecture cible — couche plateforme

Créer un package `clipboard_pro/platform/` :

```
platform/
├── __init__.py        # sélectionne le backend selon sys.platform
├── base.py            # interfaces (Protocol) : Clipboard, Paste, Ocr, Sys
├── macos.py           # déplace le code actuel (capture/ocr/autopaste/perms/machine_id)
└── windows.py         # nouvelles implémentations Windows
```

`__init__.py` :
```python
import sys
if sys.platform == "darwin":
    from .macos import ClipboardBackend, PasteBackend, OcrBackend, SysBackend
elif sys.platform == "win32":
    from .windows import ClipboardBackend, PasteBackend, OcrBackend, SysBackend
else:
    raise RuntimeError("Plateforme non supportée")
```

Le reste du code appelle `from .platform import ClipboardBackend` au lieu des
fonctions macOS en dur. **Refactor sans changement de comportement sur Mac**
(étape 1, testable sur ton Mac).

`machine_id()` (licence) : branche Windows = `MachineGuid` du registre
(`HKLM\SOFTWARE\Microsoft\Cryptography`) ou `wmic csproduct get uuid`, hashé
comme sur macOS. Le reste de la licence est déjà portable.

## 4) Dépendances Windows (requirements-win.txt)

- `PyQt6` (déjà)
- `pywin32` (clipboard, fenêtres, SendInput)
- `psutil` (nom de l'app source)
- `Pillow` (conversion image DIB ↔ PNG)
- `pynput` (déjà — hotkey/expander)
- OCR : `winsdk` (Windows.Media.Ocr, recommandé) **ou** `pytesseract` + Tesseract installé
- Build : `pyinstaller`

## 5) Raccourci clavier

`⌥⌘V` n'existe pas sur Windows. **`Win+V`** est pris par l'historique natif
Windows → à éviter. Choisir **`Ctrl+Alt+V`** (libre, mnémotechnique). pynput
gère déjà ; il suffit d'adapter la combinaison par plateforme.

## 6) Packaging Windows (sur une machine Windows)

```bat
py -m venv .venv
.venv\Scripts\pip install -r clipboard_pro\requirements-win.txt pyinstaller
.venv\Scripts\pyinstaller --noconfirm --windowed --name Klip ^
  --icon klip.ico ^
  --add-data "clipboard_pro;clipboard_pro" ^
  app_main.py
```

- Icône : convertir l'orange Klip en **`.ico`** (multi-tailles) — `build_klip_icon.py` peut générer un PNG, puis Pillow → ICO.
- Résultat : `dist\Klip\Klip.exe` (+ dossier) → empaqueter en **installateur** avec **Inno Setup** (recommandé) pour un `.exe` d'install propre + démarrage auto + raccourci menu Démarrer.
- **Non signé** → SmartScreen affichera « Windows a protégé votre PC ». L'utilisateur clique **« Informations complémentaires » → « Exécuter quand même »** (équivalent du clic droit → Ouvrir sur Mac). À documenter dans la notice et la landing.

## 7) Risques / points d'attention

- **OCR `winsdk`** : API async (winrt) un peu velue à câbler. Repli simple : livrer la v1 Windows **sans OCR** (ou via Tesseract optionnel), l'ajouter ensuite.
- **Icône de l'app source** dans la liste : l'extraction d'icône exe est pénible → v1 sans icône d'app (juste le nom), polish plus tard.
- **Tray + autostart** : `QSystemTrayIcon` OK ; démarrage auto via Startup/registre.
- **Tests** : impossibles depuis l'environnement actuel (Linux) — tout le test Windows se fait sur ta machine Windows.
- **Signature** : pas de certif (comme sur Mac) → SmartScreen documenté.

## 8) Ordre de réalisation (jalons)

1. **Refactor abstraction** `platform/` + déplacer le code macOS dedans. *(testable sur Mac, zéro régression)*
2. **Backend Windows clipboard** : lecture + détection (`GetClipboardSequenceNumber`) + écriture texte/image. *(cœur)*
3. **Paste + hotkey Windows** (`SendInput` Ctrl+V, `Ctrl+Alt+V`).
4. **machine_id Windows** + tray + autostart.
5. **Packaging** PyInstaller + Inno Setup → `KlipSetup.exe`.
6. **OCR Windows** (winsdk ou Tesseract).
7. **Tests réels sur Windows** + ajustements.

## 9) Estimation honnête

- Parité **sans OCR ni icônes d'app** : ~2–3 jours de dev + 1 jour de tests sur Windows.
- Parité **complète** (OCR + icônes) : +1–2 jours.
- Je peux écrire tout le code de la couche Windows ici ; le **build et les tests se font sur ta machine Windows** (je ne peux pas les exécuter depuis mon environnement).

---

### Décision pour démarrer
Étape 1 (refactor `platform/`) est sans risque et améliore déjà le code même
côté Mac. C'est le point d'entrée recommandé : dis-moi « go étape 1 » et je
lance le refactor de l'abstraction plateforme (testable sur ton Mac), puis on
enchaîne sur le backend Windows.
