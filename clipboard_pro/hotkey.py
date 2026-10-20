"""Raccourci global ⌥⌘V via pynput.

pynput est la solution la plus fiable et la plus simple pour intercepter une
combinaison de touches partout sur macOS. Elle nécessite que l'utilisateur
accorde l'autorisation « Surveillance des entrées » dans
Réglages Système → Confidentialité et sécurité → Surveillance des entrées.

Si l'autorisation n'est pas donnée, l'app reste utilisable via l'icône de la
barre de menu — on n'empêche pas le démarrage.
"""
from __future__ import annotations

from typing import Callable, Optional

from .log import get_logger

log = get_logger(__name__)

try:
    from pynput import keyboard  # type: ignore[import]
    PYNPUT_AVAILABLE = True
    # Compat pynput 1.8.x (macOS) : régression où GlobalHotKeys._on_press /
    # _on_release sont parfois appelés SANS l'argument `injected` qu'ils
    # exigent → TypeError, et le raccourci global ne se déclenche jamais.
    # On rend `injected` optionnel pour tolérer les deux formes d'appel.
    try:
        import inspect as _inspect

        for _meth in ("_on_press", "_on_release"):
            _fn = getattr(keyboard.GlobalHotKeys, _meth, None)
            if _fn is not None and "injected" in _inspect.signature(_fn).parameters:
                def _make(orig):
                    def _wrapped(self, key, injected=False):
                        return orig(self, key, injected)
                    return _wrapped
                setattr(keyboard.GlobalHotKeys, _meth, _make(_fn))
    except Exception:  # pragma: no cover
        pass
except Exception:  # pragma: no cover
    PYNPUT_AVAILABLE = False
    keyboard = None  # type: ignore[assignment]
    log.warning("pynput indisponible — le raccourci global sera désactivé")


import sys as _sys
# ⌘ n'existe pas sur Windows ; Win+V est réservé par l'OS → Ctrl+Alt+V.
DEFAULT_HOTKEY = "<ctrl>+<alt>+v" if _sys.platform == "win32" else "<alt>+<cmd>+v"


class HotkeyManager:
    def __init__(self, callback: Callable[[], None], combo: str = DEFAULT_HOTKEY) -> None:
        self.callback = callback
        self.combo = combo
        self._listener: Optional["keyboard.GlobalHotKeys"] = None
        self.error: Optional[str] = None

    def install(self) -> bool:
        if not PYNPUT_AVAILABLE:
            self.error = (
                "pynput n'est pas installé. Le raccourci global est désactivé."
            )
            return False
        try:
            def _wrapped() -> None:
                try:
                    self.callback()
                except Exception:
                    # On ne laisse pas une erreur du callback tuer le listener.
                    log.exception("Callback hotkey %r a levé une exception", self.combo)
            self._listener = keyboard.GlobalHotKeys({self.combo: _wrapped})
            self._listener.daemon = True
            self._listener.start()
            log.info("Hotkey installé : %s", self.combo)
            return True
        except Exception as e:  # pragma: no cover
            self.error = (
                "Impossible d'installer le raccourci global. "
                "Autorisez Klip dans Réglages Système → Confidentialité "
                f"et sécurité → Surveillance des entrées. ({e})"
            )
            log.warning("Échec install hotkey %r : %s", self.combo, e)
            return False

    def stop(self) -> None:
        if self._listener:
            try:
                self._listener.stop()
            except Exception:
                log.exception("Erreur en stoppant le listener pynput")
            # On nettoie la référence pour qu'un install() ultérieur crée
            # un nouveau Listener proprement.
            self._listener = None

    def set_combo(self, combo: str) -> bool:
        """Change le combo à chaud (stop + recharge).

        Renvoie True si le nouveau combo est actif, False en cas d'échec
        (auquel cas on tente un rollback vers le combo précédent pour ne
        pas laisser l'app sans raccourci global).
        """
        old_combo = self.combo
        self.stop()
        self.combo = combo
        self.error = None
        if self.install():
            return True
        # Rollback best-effort
        self.combo = old_combo
        self.install()  # on ignore le résultat ici — au pire l'erreur reste
        return False
