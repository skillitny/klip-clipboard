"""Backend macOS — réexporte simplement l'implémentation existante.

Aucun changement de comportement : on pointe vers les modules historiques
(`capture`, `autopaste`, `ocr`) pour que le Mac reste strictement identique.
"""
from __future__ import annotations

from ..autopaste import AutoPaste
from ..capture import (
    CapturedImage,
    CapturedText,
    ClipboardWatcher,
    png_dimensions,
    write_image,
    write_text,
)
from ..ocr import recognize_text

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
