"""Configuration centralisée du logger Klip.

Tous les modules de l'app utilisent ``get_logger(__name__)`` pour récupérer
un logger enfant du logger racine ``clipboard_pro``. La configuration est
appliquée une seule fois au démarrage par ``setup_logging()`` depuis
``main.py``.

Sortie :
  • Fichier rotatif :  ~/Library/Logs/Klip/app.log  (1 Mo × 3 archives)
  • Console (stderr) : WARNING+ par défaut, DEBUG si ``--debug``

Le logger ne crash JAMAIS l'app : si la création du dossier de logs échoue
(disk full, permissions, sandbox…), on retombe silencieusement sur la console
seule. Un logger qui plante au démarrage serait un comble.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

# ⚠️ Pas d'``import logging.handlers``. py2app fait une analyse statique des
# imports pour décider quels modules embarquer dans le bundle ; comme
# ``logging.handlers`` n'était utilisé nulle part dans le code historique,
# py2app ne l'inclut pas → ``ModuleNotFoundError`` au lancement du .app.
# On utilise donc ``logging.FileHandler`` (présent dans le module ``logging``
# de base) + une rotation manuelle minimaliste.


ROOT_LOGGER_NAME = "clipboard_pro"

# Format compact mais lisible. On garde le nom du logger pour pouvoir
# filtrer par module dans ``grep``.
_FMT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATEFMT = "%H:%M:%S"


def _log_dir() -> Path:
    """~/Library/Logs/Klip — dossier macOS standard pour les logs apps."""
    return Path.home() / "Library" / "Logs" / "Klip"


def _rotate_if_needed(path: Path, max_bytes: int) -> None:
    """Rotation minimaliste sans dépendre de ``logging.handlers``.

    Si ``path`` existe et dépasse ``max_bytes``, on le renomme en
    ``path.with_suffix('.1')`` (en écrasant l'ancien .1 s'il existe) et
    le caller crée un nouveau fichier vide. Pas de rotation au cours de
    l'exécution — au pire on dépasse ``max_bytes`` jusqu'au prochain
    redémarrage de Klip.
    """
    try:
        if not path.exists():
            return
        if path.stat().st_size < max_bytes:
            return
        backup = path.with_name(path.name + ".1")
        try:
            if backup.exists():
                backup.unlink()
        except Exception:
            pass
        path.rename(backup)
    except Exception:
        # Si la rotation échoue, on s'en moque — on continuera à écrire
        # dans le fichier existant (au pire un peu trop gros).
        pass


def setup_logging(debug: bool = False) -> Path | None:
    """Configure le logger racine. Idempotent — appel multiple sans risque.

    Renvoie le chemin du fichier de log si écrit avec succès, sinon None.
    """
    root = logging.getLogger(ROOT_LOGGER_NAME)
    # Si déjà configuré (appel répété), on ne double pas les handlers.
    if getattr(root, "_klip_configured", False):
        return getattr(root, "_klip_logfile", None)

    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.propagate = False  # on ne pollue pas le root logger Python

    fmt = logging.Formatter(_FMT, datefmt=_DATEFMT)

    # --- Console (stderr) -----------------------------------------------
    console = logging.StreamHandler(stream=sys.stderr)
    console.setLevel(logging.DEBUG if debug else logging.WARNING)
    console.setFormatter(fmt)
    root.addHandler(console)

    # --- Fichier (rotation manuelle) -------------------------------------
    # On utilise FileHandler standard. Rotation maison : si le fichier
    # dépasse 1 Mo au démarrage, on le rename en .1 et on repart d'un
    # fichier vide. Pas de rotation continue en cours d'exécution (le
    # process Klip tourne longtemps mais loggue peu en INFO normal — pas
    # un risque sérieux de dépasser 10 Mo avant un redémarrage).
    logfile: Optional[Path] = None
    try:
        log_dir = _log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        logfile = log_dir / "app.log"
        _rotate_if_needed(logfile, max_bytes=1 * 1024 * 1024)
        fh = logging.FileHandler(logfile, mode="a", encoding="utf-8")
        fh.setLevel(logging.DEBUG if debug else logging.INFO)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except Exception as e:
        # Pas de log file → on continue avec console seule, et on l'indique
        # bruyamment pour qu'on s'en rende compte en dev.
        root.warning("Impossible d'ouvrir le fichier de log : %s", e)
        logfile = None

    # Marqueurs pour idempotence.
    setattr(root, "_klip_configured", True)
    setattr(root, "_klip_logfile", logfile)

    root.info(
        "Logger initialisé (debug=%s, file=%s)",
        debug,
        logfile if logfile else "(console seule)",
    )
    return logfile


def get_logger(name: str) -> logging.Logger:
    """Retourne un logger enfant de ``clipboard_pro``.

    Convention : appeler ``get_logger(__name__)`` dans chaque module.
    ``clipboard_pro.hotkey``, ``clipboard_pro.capture``, etc.
    """
    # Si on appelle get_logger("clipboard_pro.hotkey"), getLogger fera
    # automatiquement l'héritage de niveau et handlers depuis ``clipboard_pro``.
    # Si on appelle get_logger("hotkey") (sans préfixe), on le préfixe pour
    # qu'il hérite quand même.
    if name == ROOT_LOGGER_NAME or name.startswith(ROOT_LOGGER_NAME + "."):
        return logging.getLogger(name)
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


def is_debug() -> bool:
    """``True`` si ``--debug`` est dans sys.argv ou KLIP_DEBUG dans l'env."""
    if "--debug" in sys.argv:
        return True
    val = os.environ.get("KLIP_DEBUG", "").strip().lower()
    return val in ("1", "true", "yes", "on")
