"""Text expander : ;name<délimiteur> → contenu du snippet.

Écoute le clavier global via pynput, maintient un petit buffer, et déclenche
l'expansion quand un délimiteur est tapé après une séquence `;name`.

Les snippets sont gérés depuis l'UI ; ce module ne fait que la détection +
le remplacement.
"""
from __future__ import annotations

import re
import threading
from typing import Callable, Optional

from .log import get_logger

log = get_logger(__name__)

try:
    from pynput import keyboard  # type: ignore[import]
    PYNPUT_AVAILABLE = True
except Exception:
    PYNPUT_AVAILABLE = False
    keyboard = None  # type: ignore[assignment]
    log.warning("pynput indisponible — expander snippets désactivé")


# Caractères qui clôturent un mot et déclenchent la vérification.
DELIMITERS = set(" \t\n\r.,;:!?)")
SNIPPET_RE = re.compile(r";([a-z0-9_\-]{1,40})$", re.IGNORECASE)
MAX_BUFFER = 80


class TextExpander:
    """Détecte ;name + délimiteur, remplace par le contenu du snippet.

    `lookup(name)` est appelé pour résoudre un nom en contenu (renvoie None
    si pas de snippet).
    """

    def __init__(self, lookup: Callable[[str], Optional[str]]) -> None:
        self.lookup = lookup
        self._buffer = ""
        self._lock = threading.Lock()
        self._listener = None
        self._controller = keyboard.Controller() if PYNPUT_AVAILABLE else None
        self._suppress_until = 0
        self._is_expanding = False

    # --- public API ---------------------------------------------------------

    def start(self) -> bool:
        if not PYNPUT_AVAILABLE:
            return False
        try:
            self._listener = keyboard.Listener(on_press=self._on_press)
            self._listener.daemon = True
            self._listener.start()
            log.info("Expander snippets démarré")
            return True
        except Exception:
            log.exception("Impossible de démarrer le listener pynput de l'expander")
            return False

    def stop(self) -> None:
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                log.exception("Erreur en stoppant le listener expander")

    # --- listener -----------------------------------------------------------

    def _char_for_key(self, key) -> Optional[str]:
        """Retourne le caractère correspondant ou un marqueur spécial."""
        try:
            if hasattr(key, "char") and key.char is not None:
                return key.char
        except Exception:
            return None
        # touches spéciales
        if key == keyboard.Key.space:
            return " "
        if key == keyboard.Key.enter:
            return "\n"
        if key == keyboard.Key.tab:
            return "\t"
        if key == keyboard.Key.backspace:
            return "\b"
        return None

    def _on_press(self, key, injected=False) -> None:
        if self._is_expanding:
            return
        ch = self._char_for_key(key)
        if ch is None:
            # touche modificatrice ou navigation : on remet à zéro le buffer
            with self._lock:
                self._buffer = ""
            return
        with self._lock:
            if ch == "\b":
                self._buffer = self._buffer[:-1]
                return
            if ch in DELIMITERS:
                self._maybe_expand(trailing=ch)
                self._buffer = ""
                return
            self._buffer = (self._buffer + ch)[-MAX_BUFFER:]

    def _maybe_expand(self, trailing: str) -> None:
        m = SNIPPET_RE.search(self._buffer)
        if not m:
            return
        name = m.group(1).lower()
        content = self.lookup(name)
        if content is None:
            return
        trigger_len = len(name) + 1  # ';' + name
        # Effacer ;name (et le trailing déjà tapé), retaper contenu (+ trailing optionnel).
        # On ré-injecte le délimiteur sauf s'il s'agit d'espace/tab/retour qui ferait
        # double saut : on le garde car c'est l'intention de l'utilisateur.
        self._is_expanding = True
        try:
            ctrl = self._controller
            if ctrl is None:
                return
            # Backspace pour effacer le trailing + ;name
            for _ in range(trigger_len + len(trailing)):
                ctrl.press(keyboard.Key.backspace)
                ctrl.release(keyboard.Key.backspace)
            ctrl.type(content)
            # Réinjecte le délimiteur s'il porte du sens (espace/ponctuation/tab/return)
            if trailing:
                ctrl.type(trailing)
        finally:
            self._is_expanding = False
