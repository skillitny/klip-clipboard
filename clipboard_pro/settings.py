"""Gestion des préférences utilisateur — stockées en JSON, journalisées en DB.

Le fichier vit dans ``~/.clipboard_pro/settings.json``. Chaque appel à
``set(key, value)`` :

  1. Lit l'ancienne valeur,
  2. Écrit la nouvelle dans le JSON,
  3. Trace le changement dans la table ``settings_log`` de la DB (avec
     date, ancienne/nouvelle valeur, note libre optionnelle).

Pour consulter l'historique des changements : ``Database.list_settings_log()``.

Conçu pour être appelé depuis le thread Qt principal. Les écritures JSON
sont atomiques (write to temp + os.replace).
"""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .db import Database

SETTINGS_PATH = Path.home() / ".clipboard_pro" / "settings.json"

# Raccourcis par défaut adaptés à l'OS. Sur Windows, ⌘ n'existe pas et Win+V
# est pris par l'historique natif → on utilise Ctrl+Alt. (pynput mappe <cmd>
# vers la touche Windows, à éviter ici.)
_IS_WINDOWS = sys.platform == "win32"
_DEFAULT_HOTKEY_MAIN = "<ctrl>+<alt>+v" if _IS_WINDOWS else "<alt>+<cmd>+v"
_DEFAULT_HOTKEY_CAPTURE = (
    "<ctrl>+<alt>+<shift>+s" if _IS_WINDOWS else "<alt>+<cmd>+<shift>+s"
)

# ----------------------------------------------------------------------------
# Valeurs par défaut. Toute clé ajoutée ici hérite automatiquement de sa
# valeur si elle n'est pas dans le fichier (rétro-compat). Pour exposer une
# nouvelle option en UI : ajouter ici + utiliser ``settings.get("ma.cle")``.
# ----------------------------------------------------------------------------

DEFAULTS: dict[str, Any] = {
    # --- Rétention par âge (cf. AUDIT §15) ------------------------------
    # 0 = supprime tout / -1 ou None = pas de purge par âge / N>0 = N jours.
    # Les favoris et snippets sont TOUJOURS préservés.
    "retention.text_days":  90,
    "retention.image_days": 30,

    # Cap classique (en plus de la rétention par âge).
    "retention.max_items":  5000,

    # --- Expander snippets (cf. AUDIT §0.8 et §6.1) ----------------------
    # ⚠️ L'expander écoute le clavier global. OPT-IN explicite.
    "expander.enabled":     False,

    # --- Hotkey -----------------------------------------------------------
    "hotkey.combo":         _DEFAULT_HOTKEY_MAIN,

    # --- Capture ----------------------------------------------------------
    "capture.max_text_bytes":  5 * 1024 * 1024,        # 5 Mo
    "capture.max_image_bytes": 50 * 1024 * 1024,       # 50 Mo
    "screenshot_watcher.enabled": True,
    # Détection automatique de secrets (clés API, tokens, mots de passe…).
    # Quand True (défaut), un secret détecté n'est **PAS enregistré** dans
    # l'historique. Le clipboard système n'est jamais affecté — ⌘V colle
    # toujours le secret normalement, on évite juste de le mémoriser.
    "capture.detect_secrets":  True,
    # Masquage des captures (v2.5). Quand True, toute image qui SORT de
    # Klip (copier, glisser, mini-fenêtre) a ses secrets (clés API, tokens,
    # cartes, IBAN) recouverts d'une barre pleine. L'original reste intact
    # dans l'historique. Si l'analyse échoue, rien n'est copié. Opt-in.
    "capture.mask_secrets_in_images": False,
    # Raccourci global pour la capture instantanée (session 5 v2).
    # Lance `screencapture -i -c` qui prend une capture interactive et
    # met directement le PNG dans le presse-papiers — court-circuite le
    # piège de la vignette macOS qui n'écrit pas sur disque.
    # Format pynput, ex. "<alt>+<cmd>+<shift>+s".
    "capture.hotkey":          _DEFAULT_HOTKEY_CAPTURE,

    # --- OCR --------------------------------------------------------------
    # Reconnaissance de texte dans les images via Vision (macOS).
    # `ocr.enabled` False = on ne lance plus l'OCR sur les nouvelles images
    # (mais le texte déjà extrait reste). `ocr.languages` = codes ISO type
    # "fr-FR", "en-US" ; ordre important (langue primaire en premier).
    "ocr.enabled":          True,
    "ocr.languages":        ["fr-FR", "en-US"],

    # --- Onboarding -------------------------------------------------------
    "onboarded":            False,

    # --- Smart folders (filtres sauvegardés, session 5) -------------------
    # Liste de dicts : [{name, kind, favorites_only, snippets_only,
    #                    since_ts, source_app, query}, ...]
    # Permet de sauvegarder une combinaison de filtres+recherche sous un
    # nom pour la rappliquer d'un clic. UI : rangée de chips sous les
    # filtres standards dans la MainWindow.
    "smart_folders":        [],

    # --- UI ---------------------------------------------------------------
    "ui.theme":             "auto",   # 'auto' | 'dark' | 'light' (Phase 2)
    "ui.accent":            "#7c5cff",

    # --- Mini-fenêtre flottante (Phase 6, session 5) ---------------------
    # Petite fenêtre frameless toujours visible qui montre les N derniers
    # items capturés. Clic = copier + coller dans l'app précédente. Très
    # pratique pour les workflows répétitifs (copier-coller en rafale).
    "floating.enabled":     False,    # opt-in
    "floating.x":           -1,       # -1 = pas encore positionnée
    "floating.y":           -1,
    "floating.item_count":  5,        # nombre d'items affichés
}


class Settings:
    """API simple ``get(key, default=None)`` / ``set(key, value, note=None)``.

    Thread-safe (RLock interne, plus le lock DB de log_setting_change).
    """

    def __init__(self, db: Optional["Database"] = None, path: Path = SETTINGS_PATH):
        self.path = path
        self.db = db
        self._lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = dict(DEFAULTS)
        self._load()

    # --- IO ----------------------------------------------------------------

    def _load(self) -> None:
        try:
            if self.path.exists():
                with self.path.open("r", encoding="utf-8") as f:
                    on_disk = json.load(f)
                if isinstance(on_disk, dict):
                    # Merge : les défauts viennent en premier, écrasés par disque.
                    self._data.update(on_disk)
        except Exception:
            # Fichier corrompu → on garde les défauts. Pas de crash app.
            pass

    def _save(self) -> None:
        """Écriture atomique : tmp + os.replace pour pas perdre le fichier
        en cas de crash pendant l'écriture."""
        tmp = self.path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, self.path)

    # --- API publique ------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            if key in self._data:
                return self._data[key]
            if key in DEFAULTS:
                return DEFAULTS[key]
            return default

    def set(self, key: str, value: Any, *, note: Optional[str] = None, source: str = "ui") -> None:
        """Modifie un paramètre et trace le changement dans `settings_log`.

        Si la nouvelle valeur est identique à l'ancienne, ne rien faire
        (pas d'entrée dans le journal pour les no-ops).
        """
        with self._lock:
            old = self._data.get(key, DEFAULTS.get(key))
            if old == value:
                return
            self._data[key] = value
            self._save()
            # On trace même les options dont la valeur initiale était le default
            if self.db is not None:
                try:
                    self.db.log_setting_change(
                        key=key,
                        old_value=_stringify(old),
                        new_value=_stringify(value),
                        note=note,
                        source=source,
                    )
                except Exception:
                    # On ne casse jamais le set() à cause du log.
                    pass

    def setdefault(self, key: str, value: Any) -> Any:
        """Comme dict.setdefault : ne touche pas si déjà set."""
        with self._lock:
            if key in self._data:
                return self._data[key]
            self._data[key] = value
            self._save()
            return value

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data)


def _stringify(v: Any) -> Optional[str]:
    """Convertit une valeur en string pour le journal (None → None)."""
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float, str)):
        return str(v)
    try:
        return json.dumps(v, ensure_ascii=False)
    except Exception:
        return repr(v)
