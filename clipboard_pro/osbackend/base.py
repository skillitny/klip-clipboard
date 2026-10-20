"""Contrat commun à tous les backends plateforme.

Définit les dataclasses de payload partagées. Chaque backend doit fournir :
- une classe ``ClipboardWatcher`` avec ``poll() -> CapturedText|CapturedImage|None``
- ``write_text(text)`` / ``write_image(png_bytes)``
- ``png_dimensions(png_bytes) -> (width, height)``
- une classe ``AutoPaste`` avec ``remember_front_app()`` et ``restore_and_paste() -> bool``
- ``recognize_text(png_bytes, languages=None) -> str | None``
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class CapturedText:
    text: str
    source_app: Optional[str]


@dataclass
class CapturedImage:
    png: bytes
    width: int
    height: int
    source_app: Optional[str]
