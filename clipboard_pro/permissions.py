"""Détection live des permissions macOS + ouverture du bon panneau Réglages.

But ergonomique : au lieu de dire « va cocher Klip quelque part », l'app
sait si la permission est accordée et envoie l'utilisateur directement au
bon endroit. Tout est best-effort : si une API n'est pas dispo, on renvoie
None (inconnu) plutôt que de planter.
"""
from __future__ import annotations

import subprocess
import sys
from typing import Optional

# Windows (et autres non-macOS) n'ont pas le modèle de permissions
# Accessibilité / Surveillance des entrées de macOS : tout est considéré
# comme accordé, pour ne pas afficher de panneau d'autorisation inutile.
_IS_MACOS = sys.platform == "darwin"

# URLs des panneaux Réglages Système (Ventura+).
URL_ACCESSIBILITY = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
)
URL_INPUT_MONITORING = (
    "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"
)


def accessibility_ok() -> Optional[bool]:
    """True/False si l'app a la permission Accessibilité, None si indéterminable."""
    if not _IS_MACOS:
        return True  # pas de permission requise hors macOS
    try:
        from ApplicationServices import AXIsProcessTrusted
        return bool(AXIsProcessTrusted())
    except Exception:
        return None


def input_monitoring_ok() -> Optional[bool]:
    """True/False pour la Surveillance des entrées, None si indéterminable.

    Utilise IOHIDCheckAccess(kIOHIDRequestTypeListenEvent) ; renvoie True si
    l'accès est déjà accordé (valeur 0 = granted dans l'enum IOKit).
    """
    if not _IS_MACOS:
        return True  # pas de permission requise hors macOS
    try:
        import Quartz
        # kIOHIDRequestTypeListenEvent = 1 ; granted == kIOHIDAccessTypeGranted (0)
        access = Quartz.IOHIDCheckAccess(1)
        return access == 0
    except Exception:
        return None


def open_accessibility_settings() -> None:
    _open(URL_ACCESSIBILITY)


def open_input_monitoring_settings() -> None:
    _open(URL_INPUT_MONITORING)


def _open(url: str) -> None:
    try:
        subprocess.run(["open", url], check=False)
    except Exception:
        pass


def status_summary() -> dict:
    """Renvoie l'état des permissions, pour affichage."""
    return {
        "accessibility": accessibility_ok(),
        "input_monitoring": input_monitoring_ok(),
    }


def all_granted() -> bool:
    """True seulement si les deux permissions sont explicitement accordées."""
    s = status_summary()
    return s["accessibility"] is True and s["input_monitoring"] is True
