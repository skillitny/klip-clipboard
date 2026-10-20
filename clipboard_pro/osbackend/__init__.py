"""Couche d'abstraction plateforme de Klip.

Sélectionne le backend système (capture du presse-papiers, collage, OCR…)
selon l'OS. Le reste du code importe d'ici plutôt que des modules macOS en
dur, ce qui permet de fournir une implémentation Windows sans toucher au
reste.

Nommé `osbackend` (et non `platform`) pour ne pas masquer le module standard
Python `platform`.

API exposée (identique quelle que soit la plateforme) :
    CapturedText, CapturedImage      — dataclasses de payload
    ClipboardWatcher                 — .poll() -> CapturedText|CapturedImage|None
    write_text(text), write_image(blob)
    png_dimensions(blob) -> (w, h)
    AutoPaste                        — .remember_front_app(), .restore_and_paste()
    recognize_text(blob, languages=None) -> str|None
"""
from __future__ import annotations

import sys

if sys.platform == "darwin":
    from . import macos as _backend
elif sys.platform == "win32":
    from . import windows as _backend
else:  # pragma: no cover
    raise RuntimeError(
        f"Klip ne supporte pas encore la plateforme '{sys.platform}'."
    )

CapturedText = _backend.CapturedText
CapturedImage = _backend.CapturedImage
ClipboardWatcher = _backend.ClipboardWatcher
write_text = _backend.write_text
write_image = _backend.write_image
png_dimensions = _backend.png_dimensions
AutoPaste = _backend.AutoPaste
recognize_text = _backend.recognize_text

__all__ = [
    "CapturedText",
    "CapturedImage",
    "ClipboardWatcher",
    "write_text",
    "write_image",
    "png_dimensions",
    "AutoPaste",
    "recognize_text",
]
