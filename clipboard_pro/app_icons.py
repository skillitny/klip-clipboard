"""Cache d'icônes d'applications macOS (v2.3).

Permet d'afficher dans la liste l'icône réelle de l'app source d'un item
(Chrome, Claude, VSCode, WhatsApp, etc.) au lieu d'un badge générique.

Utilise NSWorkspace pour résoudre le path de l'app puis récupère son
icône via iconForFile. Conversion NSImage → QPixmap via TIFF.

Cache LRU borné pour éviter de re-résoudre 1000 fois la même app.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from typing import Optional

from PyQt6.QtCore import QSize, Qt
from PyQt6.QtGui import QImage, QPixmap

log = logging.getLogger("klip.app_icons")

# Imports macOS — protégés pour ne pas casser le build/import sur non-Mac.
try:
    from AppKit import NSWorkspace  # type: ignore
    _NSWORKSPACE_AVAILABLE = True
except Exception:  # pragma: no cover
    _NSWORKSPACE_AVAILABLE = False
    log.warning("AppKit.NSWorkspace indisponible — pas d'icônes d'apps")


class AppIconCache:
    """Cache LRU des icônes d'apps, indexées par nom d'app.

    L'entrée peut être :
      - QPixmap si l'icône a été récupérée
      - None si l'app n'a pas été trouvée (mémorisé pour éviter de
        retenter à chaque rendu)
    """

    def __init__(self, max_size: int = 64, icon_size: int = 32) -> None:
        self._cache: OrderedDict[str, Optional[QPixmap]] = OrderedDict()
        self._max = max_size
        self._size = icon_size

    def get(self, app_name: Optional[str]) -> Optional[QPixmap]:
        if not app_name or not _NSWORKSPACE_AVAILABLE:
            return None
        key = app_name.strip()
        if not key:
            return None
        if key in self._cache:
            # LRU bump
            self._cache.move_to_end(key)
            return self._cache[key]
        pix = self._resolve(key)
        # Évict si plein
        if len(self._cache) >= self._max:
            self._cache.popitem(last=False)
        self._cache[key] = pix
        return pix

    def clear(self) -> None:
        self._cache.clear()

    def _resolve(self, app_name: str) -> Optional[QPixmap]:
        """Résout l'icône d'une app par son nom (sans .app).

        Stratégie : on essaie plusieurs variantes du nom car les apps
        copient parfois des sources annotées (« Klip (édition) »,
        « Chrome - Profil 1 ») non résolvables tel quel.
        """
        try:
            ws = NSWorkspace.sharedWorkspace()
            import re

            # Construire la liste des candidats à tester
            candidates: list[str] = [app_name]

            # Strip "(...)" → "Klip (édition)" devient "Klip"
            stripped = re.sub(r"\s*\([^)]*\)\s*", "", app_name).strip()
            if stripped and stripped not in candidates:
                candidates.append(stripped)

            # Strip après " - " ou " – " → "Chrome - Profil 1" → "Chrome"
            for sep in (" - ", " – ", " — "):
                if sep in app_name:
                    head = app_name.split(sep, 1)[0].strip()
                    if head and head not in candidates:
                        candidates.append(head)

            # Pour chaque candidat, essayer avec et sans suffixe .app
            path = None
            for name in candidates:
                path = ws.fullPathForApplication_(name)
                if not path:
                    path = ws.fullPathForApplication_(f"{name}.app")
                if path:
                    break

            if not path:
                return None
            ns_image = ws.iconForFile_(path)
            if ns_image is None:
                return None
            return self._ns_image_to_pixmap(ns_image)
        except Exception as e:
            log.debug("Icon resolution failed for %r: %s", app_name, e)
            return None

    def _ns_image_to_pixmap(self, ns_image) -> Optional[QPixmap]:
        """Convertit NSImage en QPixmap via TIFF (le format pivot le plus
        fiable sur macOS, supporte la transparence et le multi-rep)."""
        try:
            ns_image.setSize_((self._size, self._size))
            tiff = ns_image.TIFFRepresentation()
            if tiff is None:
                return None
            data = bytes(tiff)
            img = QImage()
            if not img.loadFromData(data, "TIFF"):
                return None
            # Resize lisse à la taille cible pour éviter les rendus
            # baveux quand l'icône native est plus grande/petite.
            pix = QPixmap.fromImage(img)
            if pix.isNull():
                return None
            if pix.size() != QSize(self._size, self._size):
                pix = pix.scaled(
                    self._size,
                    self._size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            return pix
        except Exception as e:
            log.debug("NSImage→QPixmap failed: %s", e)
            return None


# Singleton module-level — partagé par tous les delegates.
_GLOBAL_CACHE: Optional[AppIconCache] = None


def app_icon_cache(icon_size: int = 32) -> AppIconCache:
    """Renvoie le cache global (créé au premier appel)."""
    global _GLOBAL_CACHE
    if _GLOBAL_CACHE is None:
        _GLOBAL_CACHE = AppIconCache(max_size=128, icon_size=icon_size)
    return _GLOBAL_CACHE
