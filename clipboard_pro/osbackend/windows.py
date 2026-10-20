"""Backend Windows pour Klip.

Implémente la capture du presse-papiers, l'écriture, le collage automatique et
(à terme) l'OCR, avec les API Windows :
- détection de changement : ``GetClipboardSequenceNumber`` (équivalent exact du
  ``changeCount`` de NSPasteboard) ;
- lecture/écriture : ``win32clipboard`` (CF_UNICODETEXT, CF_DIB) ;
- conversion image DIB <-> PNG : Pillow ;
- collage : ``SetForegroundWindow`` + Ctrl+V via ``keybd_event`` ;
- app source : fenêtre au premier plan -> PID -> nom via ``psutil``.

⚠️ NON TESTÉ sur Windows depuis l'environnement de dev (macOS/Linux). À valider
sur une vraie machine Windows (étape 2 du portage).
"""
from __future__ import annotations

import ctypes
import io
import struct
import time
from ctypes import wintypes
from typing import Optional

from .base import CapturedImage, CapturedText

# --- Dépendances natives (présentes uniquement sur Windows) -----------------
try:
    import win32clipboard  # type: ignore[import]
    import psutil  # type: ignore[import]
    from PIL import Image  # type: ignore[import]
    _WIN_OK = True
except Exception:  # pragma: no cover
    _WIN_OK = False

try:
    _user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    _user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
except Exception:  # pragma: no cover
    _user32 = None

# Formats de presse-papiers signalant un contenu à NE PAS historiser
# (publiés par les gestionnaires de mots de passe et l'historique Windows).
_SECRET_FORMAT_NAMES = (
    "ExcludeClipboardContentFromMonitorProcessing",
    "CanIncludeInClipboardHistory",  # valeur 0 => exclure
)


def _front_app() -> Optional[str]:
    """Nom de l'application au premier plan (ex. 'Code', 'chrome')."""
    if _user32 is None or not _WIN_OK:
        return None
    try:
        hwnd = _user32.GetForegroundWindow()
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None
        name = psutil.Process(pid.value).name()
        if name.lower().endswith(".exe"):
            name = name[:-4]
        return name or None
    except Exception:
        return None


def _registered_format(name: str) -> int:
    try:
        return win32clipboard.RegisterClipboardFormat(name)
    except Exception:
        return 0


def _enum_formats() -> set[int]:
    fmts: set[int] = set()
    try:
        fmt = win32clipboard.EnumClipboardFormats(0)
        while fmt:
            fmts.add(fmt)
            fmt = win32clipboard.EnumClipboardFormats(fmt)
    except Exception:
        pass
    return fmts


def _looks_secret(formats: set[int]) -> bool:
    for nm in _SECRET_FORMAT_NAMES:
        fid = _registered_format(nm)
        if fid and fid in formats:
            return True
    return False


def _dib_to_png(dib: bytes) -> Optional[tuple[bytes, int, int]]:
    """Convertit un CF_DIB (BITMAPINFOHEADER + pixels, sans file header) en PNG."""
    try:
        header_size = struct.unpack_from("<I", dib, 0)[0]
        bpp = struct.unpack_from("<H", dib, 14)[0]
        clr_used = struct.unpack_from("<I", dib, 32)[0]
        if bpp <= 8:
            palette = clr_used if clr_used else (1 << bpp)
        else:
            palette = clr_used
        offset = 14 + header_size + palette * 4
        filesize = 14 + len(dib)
        fileheader = b"BM" + struct.pack("<IHHI", filesize, 0, 0, offset)
        img = Image.open(io.BytesIO(fileheader + dib))
        img = img.convert("RGBA")
        out = io.BytesIO()
        img.save(out, "PNG")
        return out.getvalue(), img.width, img.height
    except Exception:
        return None


class ClipboardWatcher:
    """Surveille le presse-papiers via GetClipboardSequenceNumber."""

    def __init__(self) -> None:
        self._last = self._seq()

    @staticmethod
    def _seq() -> int:
        if _user32 is None:
            return 0
        try:
            return int(_user32.GetClipboardSequenceNumber())
        except Exception:
            return 0

    def poll(self):
        if not _WIN_OK:
            return None
        seq = self._seq()
        if seq == self._last:
            return None
        self._last = seq

        try:
            win32clipboard.OpenClipboard()
        except Exception:
            return None
        try:
            formats = _enum_formats()
            if _looks_secret(formats):
                return None

            CF_DIB = win32clipboard.CF_DIB
            CF_UNICODETEXT = win32clipboard.CF_UNICODETEXT

            if CF_DIB in formats:
                try:
                    dib = win32clipboard.GetClipboardData(CF_DIB)
                    conv = _dib_to_png(bytes(dib)) if dib else None
                    if conv:
                        png, w, h = conv
                        return CapturedImage(png, w, h, _front_app())
                except Exception:
                    pass

            if CF_UNICODETEXT in formats:
                try:
                    text = win32clipboard.GetClipboardData(CF_UNICODETEXT)
                    if text:
                        return CapturedText(str(text), _front_app())
                except Exception:
                    pass
            return None
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass


def write_text(text: str) -> None:
    if not _WIN_OK:
        return
    try:
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_UNICODETEXT, text)
    except Exception:
        pass
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass


def write_image(blob: bytes) -> None:
    if not _WIN_OK:
        return
    try:
        img = Image.open(io.BytesIO(blob)).convert("RGB")
        out = io.BytesIO()
        img.save(out, "BMP")
        dib = out.getvalue()[14:]  # retire le BITMAPFILEHEADER (14 octets)
        win32clipboard.OpenClipboard()
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
    except Exception:
        pass
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass


def png_dimensions(blob: bytes) -> tuple[int, int]:
    if not _WIN_OK:
        return (0, 0)
    try:
        with Image.open(io.BytesIO(blob)) as img:
            return int(img.width), int(img.height)
    except Exception:
        return (0, 0)


# --- Collage automatique -----------------------------------------------------
_VK_CONTROL = 0x11
_VK_V = 0x56
_KEYEVENTF_KEYUP = 0x0002


class AutoPaste:
    def __init__(self) -> None:
        self._hwnd: Optional[int] = None
        self._our_hwnd: Optional[int] = None

    def remember_front_app(self) -> None:
        if _user32 is None:
            return
        try:
            self._hwnd = _user32.GetForegroundWindow()
        except Exception:
            self._hwnd = None

    def restore_and_paste(self) -> bool:
        if _user32 is None or not self._hwnd:
            return False
        try:
            _user32.SetForegroundWindow(self._hwnd)
            time.sleep(0.08)
            # Ctrl down, V down, V up, Ctrl up
            _user32.keybd_event(_VK_CONTROL, 0, 0, 0)
            _user32.keybd_event(_VK_V, 0, 0, 0)
            _user32.keybd_event(_VK_V, 0, _KEYEVENTF_KEYUP, 0)
            _user32.keybd_event(_VK_CONTROL, 0, _KEYEVENTF_KEYUP, 0)
            return True
        except Exception:
            return False
        finally:
            self._hwnd = None


def recognize_text(blob: bytes, languages: Optional[list[str]] = None) -> Optional[str]:
    """OCR Windows — jalon ultérieur.

    Repli optionnel sur Tesseract si `pytesseract` + Tesseract sont installés ;
    sinon renvoie None (l'app fonctionne sans OCR). L'implémentation native
    Windows.Media.Ocr (winsdk) sera ajoutée à l'étape OCR du portage.
    """
    if not blob:
        return None
    try:
        import pytesseract  # type: ignore[import]
        from PIL import Image as _Image  # type: ignore[import]
        img = _Image.open(io.BytesIO(blob))
        txt = pytesseract.image_to_string(img)
        return txt.strip() or None
    except Exception:
        return None
