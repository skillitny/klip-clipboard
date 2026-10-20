"""Surveille le dossier des captures d'écran macOS.

Quand l'utilisateur fait ``Cmd+Shift+3/4/5`` (et que la capture est sauvegardée
en fichier — comportement par défaut), un nouveau PNG apparaît dans son dossier
de captures (par défaut le Bureau). Ce watcher détecte ces fichiers et émet
un signal pour que l'app les ajoute à l'historique et au presse-papier système.

Du coup l'utilisateur n'a pas à se souvenir du combo ``Ctrl+Cmd+Shift+4`` pour
"copier dans le presse-papier" : tout screenshot enregistré devient
automatiquement collable et apparaît dans Klip.

Logs : tout passe par le logger ``clipboard_pro.screenshot_watcher`` configuré
dans ``clipboard_pro.log``. Pour voir les logs en temps réel :
``tail -f ~/Library/Logs/Klip/app.log`` (ou lancer avec ``--debug``).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QTimer, pyqtSignal

from .log import get_logger

log = get_logger(__name__)


# Patterns de nom de fichier des screenshots macOS, dans les langues système
# les plus courantes. On veut rester strict (préfixe localisé) tout en étant
# tolérant aux variations (apostrophe droite ' ou typographique ', accent é).
#
# Pour le français, on accepte "Capture d'écran" ET "Capture d’écran" :
#   - 'd' + n'importe quel caractère (',', '’') + 'écran' (avec accent)
#   - ou repli plus permissif : "Capture d" + au moins un autre caractère.
_PATTERNS = (
    re.compile(r"^Screen Shot \d.*\.png$", re.IGNORECASE),               # en (avant Sonoma)
    re.compile(r"^Screenshot \d.*\.png$", re.IGNORECASE),                # en (Sonoma+)
    re.compile(r"^Capture d['’]écran .*\.png$",
               re.IGNORECASE),                                            # fr (Capture d'écran ou d’écran)
    re.compile(r"^Capture d.+\d{4}.*\.png$", re.IGNORECASE),             # fr (repli : "Capture d…" + année)
    re.compile(r"^Bildschirmfoto .*\.png$", re.IGNORECASE),              # de
    re.compile(r"^Captura de pantalla .*\.png$", re.IGNORECASE),         # es
    re.compile(r"^Captura de tela .*\.png$", re.IGNORECASE),             # pt
    re.compile(r"^Schermafbeelding .*\.png$", re.IGNORECASE),            # nl
    re.compile(r"^Schermata .*\.png$", re.IGNORECASE),                   # it
    re.compile(r"^Snimak ekrana .*\.png$", re.IGNORECASE),               # hr/sr
    re.compile(r"^Zrzut ekranu .*\.png$", re.IGNORECASE),                # pl
)


def is_screenshot_filename(name: str) -> bool:
    return any(p.match(name) for p in _PATTERNS)


def _log(msg: str) -> None:
    """Wrapper historique → logger structuré ``clipboard_pro.screenshot_watcher``.

    L'ancien helper écrivait sur ``stderr`` + ``~/.clipboard_pro/screenshot.log``
    avec une rotation manuelle. Maintenant on délègue au logger central
    configuré dans ``log.py`` (rotation rotative dans ~/Library/Logs/Klip/).
    Le helper reste sous ce nom pour ne pas réécrire tous les callers.
    """
    log.info(msg)


def default_screenshot_folder() -> Path:
    """Renvoie le dossier où macOS sauvegarde actuellement les screenshots.

    On lit la préférence ``com.apple.screencapture.location`` (modifiable via
    l'outil Capture d'écran ⌘⇧5 → Options → Enregistrer dans). À défaut on
    retombe sur ``~/Desktop`` qui est le réglage d'usine.
    """
    try:
        out = subprocess.check_output(
            ["defaults", "read", "com.apple.screencapture", "location"],
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode().strip()
        if out:
            p = Path(out).expanduser()
            if p.is_dir():
                return p
    except Exception:
        # defaults read échoue si la clé n'a jamais été set → silence normal
        log.debug("`defaults read screencapture.location` indisponible — fallback Desktop")
    return Path.home() / "Desktop"


class ScreenshotWatcher(QObject):
    """Polle périodiquement le dossier des screenshots et émet ``new_screenshot``
    avec le chemin complet de chaque nouveau fichier détecté.

    Conçu pour vivre sur la boucle d'événements Qt — les signaux émis arrivent
    donc sur le thread principal, le récepteur peut appeler la DB et l'UI
    sans verrou particulier.

    Émet aussi ``error_message(str)`` quand l'accès au dossier est refusé,
    pour que l'UI puisse afficher un message clair à l'utilisateur.
    """

    new_screenshot = pyqtSignal(str)
    error_message = pyqtSignal(str)

    POLL_INTERVAL_MS = 1500     # un screenshot apparaît rarement plus vite
    STABILITY_DELAY_MS = 400    # laisse macOS finir d'écrire le PNG sur disque

    def __init__(self, folder: Optional[Path] = None) -> None:
        super().__init__()
        self.folder = folder or default_screenshot_folder()
        _log(f"folder = {self.folder}")
        # États pour éviter de re-logger 10x la même erreur
        self._permission_denied = False
        self._other_error_logged = False
        # Snapshot initial (ce qui est déjà là au démarrage)
        self._known: set[str] = self._snapshot_dir()
        _log(f"snapshot initial : {len(self._known)} fichier(s) déjà présent(s)")
        self._timer = QTimer(self)
        self._timer.setInterval(self.POLL_INTERVAL_MS)
        self._timer.timeout.connect(self._scan)

    # --- public API ---------------------------------------------------------

    def start(self) -> None:
        self._timer.start()
        _log(f"démarré (poll toutes les {self.POLL_INTERVAL_MS} ms)")

    def stop(self) -> None:
        self._timer.stop()

    # --- internals ----------------------------------------------------------

    def _snapshot_dir(self) -> set[str]:
        try:
            files = {f.name for f in self.folder.iterdir() if f.is_file()}
            if self._permission_denied:
                _log(f"accès rétabli sur {self.folder}")
                self._permission_denied = False
            return files
        except PermissionError as e:
            if not self._permission_denied:
                self._permission_denied = True
                _log(f"PERMISSION REFUSÉE sur {self.folder} ({e})")
                self.error_message.emit(
                    f"Accès refusé au dossier {self.folder}. "
                    f"Allez dans Réglages Système → Confidentialité et sécurité "
                    f"→ Fichiers et dossiers, et autorisez Klip sur "
                    f"« Dossier Bureau »."
                )
            return set()
        except Exception as e:
            if not self._other_error_logged:
                self._other_error_logged = True
                _log(f"erreur lecture {self.folder} : {e!r}")
            return set()

    def _scan(self) -> None:
        if not self.folder.is_dir():
            return
        try:
            entries = list(self.folder.iterdir())
        except PermissionError as e:
            if not self._permission_denied:
                self._permission_denied = True
                _log(f"PERMISSION REFUSÉE pendant scan ({e})")
                self.error_message.emit(
                    f"Accès refusé au dossier {self.folder}. "
                    f"Autorisez Klip dans Réglages Système → "
                    f"Confidentialité et sécurité → Fichiers et dossiers."
                )
            return
        except Exception:
            return
        if self._permission_denied:
            _log(f"accès rétabli sur {self.folder}")
            self._permission_denied = False

        current: set[str] = set()
        fresh: list[Path] = []
        ignored_pngs: list[str] = []
        for f in entries:
            try:
                if not f.is_file():
                    continue
            except Exception:
                continue
            current.add(f.name)
            if f.name in self._known:
                continue
            # Nouveau fichier — match ?
            if is_screenshot_filename(f.name):
                fresh.append(f)
            elif f.name.lower().endswith(".png"):
                ignored_pngs.append(f.name)
        self._known = current

        if ignored_pngs:
            _log(f"nouveau(x) PNG ignoré(s) (regex non matchée) : {ignored_pngs}")
        if fresh:
            _log(f"{len(fresh)} screenshot(s) détecté(s) : "
                 f"{[f.name for f in fresh]}")

        # On laisse macOS finir d'écrire avant de relayer le fichier — les PNG
        # peuvent transiter par un ".inProgress" momentané.
        for f in fresh:
            path_str = str(f)
            QTimer.singleShot(
                self.STABILITY_DELAY_MS,
                lambda p=path_str: self._emit_if_ready(p),
            )

    def _emit_if_ready(self, path: str) -> None:
        try:
            p = Path(path)
            if p.exists() and p.stat().st_size > 0:
                _log(f"émission new_screenshot → {path}")
                self.new_screenshot.emit(path)
            else:
                _log(f"fichier pas encore prêt : {path}")
        except Exception as e:
            _log(f"erreur _emit_if_ready : {e!r}")
