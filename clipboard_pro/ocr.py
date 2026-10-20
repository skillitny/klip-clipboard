"""OCR des images via le framework Vision (macOS 10.15+).

Usage typique :
    text = recognize_text(png_bytes, languages=["fr-FR", "en-US"])
On l'appelle dans un worker thread pour ne pas bloquer l'UI.
"""
from __future__ import annotations

from typing import Optional


def _try_vision_ocr(blob: bytes, languages: list[str]) -> Optional[str]:
    try:
        from Foundation import NSData  # type: ignore[import]
        from Quartz import CIImage  # type: ignore[import]
        from Vision import (  # type: ignore[import]
            VNImageRequestHandler,
            VNRecognizeTextRequest,
        )
    except Exception:
        return None

    try:
        import objc  # type: ignore[import]
        # IMPORTANT (fuite mémoire) : on encadre chaque OCR dans un autorelease
        # pool. Ce module tourne dans un thread non géré par Cocoa : sans pool
        # explicite, les objets ObjC autoreleased (NSData, CIImage, handler/
        # request Vision) ne sont jamais drainés et s'accumulent. (Le drain
        # déterministe vient surtout du thread éphémère côté OCRWorker, mais
        # ce pool réduit le pic mémoire par appel.)
        with objc.autorelease_pool():
            data = NSData.dataWithBytes_length_(blob, len(blob))
            if data is None:
                return None
            ci_image = CIImage.imageWithData_(data)
            if ci_image is None:
                return None
            handler = VNImageRequestHandler.alloc().initWithCIImage_options_(ci_image, None)
            request = VNRecognizeTextRequest.alloc().init()
            request.setRecognitionLevel_(0)  # 0 = accurate, 1 = fast
            request.setUsesLanguageCorrection_(True)
            if languages:
                request.setRecognitionLanguages_(languages)
            ok, err = handler.performRequests_error_([request], None)
            if not ok:
                return None
            results = request.results() or []
            lines = []
            for obs in results:
                cands = obs.topCandidates_(1) or []
                if cands:
                    lines.append(str(cands[0].string()))
            return "\n".join(lines).strip() or None
    except Exception:
        return None


def recognize_text(blob: bytes, languages: Optional[list[str]] = None) -> Optional[str]:
    """Renvoie le texte extrait, ou None si Vision n'est pas dispo / pas de texte."""
    if not blob:
        return None
    return _try_vision_ocr(blob, languages or ["fr-FR", "en-US"])


# ----------------------------------------------------------------------------
# OCR avec positions (masquage des captures, v2.5)
# ----------------------------------------------------------------------------
#
# `recognize_text` ne rend que le texte. Pour masquer une ligne ou un secret
# précis dans l'image, il faut aussi SAVOIR OÙ il est. Vision donne, pour
# chaque ligne, un rectangle normalisé (0..1, origine en BAS à gauche) et,
# pour n'importe quelle portion du texte, le rectangle de cette portion
# (`boundingBoxForRange:error:`). On convertit tout en pixels, origine en
# HAUT à gauche (convention Qt).
#
# Les rectangles des « spans » (secrets) sont calculés DANS le pool
# d'autorelease, tant que les objets Vision sont vivants : on passe donc la
# fonction de détection en paramètre au lieu de garder des objets ObjC.

from dataclasses import dataclass, field
from typing import Callable


Rect = tuple[float, float, float, float]  # x, y, w, h en pixels (haut-gauche)


@dataclass
class OcrSpan:
    start: int
    end: int
    kind: str
    rect: Rect


@dataclass
class OcrLine:
    text: str
    rect: Rect
    spans: list[OcrSpan] = field(default_factory=list)


SpanFinder = Callable[[str], list[tuple[int, int, str]]]


def _utf16_index(text: str, i: int) -> int:
    """Index Python (code points) → index NSString (unités UTF-16)."""
    return len(text[:i].encode("utf-16-le")) // 2


def _to_pixels(bb, width: int, height: int) -> Rect:
    x = float(bb.origin.x) * width
    w = float(bb.size.width) * width
    h = float(bb.size.height) * height
    y = (1.0 - float(bb.origin.y) - float(bb.size.height)) * height
    return (x, y, w, h)


def _span_rect(cand, text: str, start: int, end: int, fallback: Rect,
               width: int, height: int) -> Rect:
    """Rectangle d'une portion de ligne.

    Vision ne sait localiser qu'au MOT près (suite sans espace) : pour
    « TOKEN=ghp_xxx » il rend le mot entier. On demande donc le rectangle
    du mot, puis on découpe dedans au prorata des caractères, avec un
    caractère de marge de chaque côté (mieux vaut déborder que laisser
    dépasser un bout de clé). Repli : la ligne entière.
    """
    ws = start
    while ws > 0 and not text[ws - 1].isspace():
        ws -= 1
    we = end
    while we < len(text) and not text[we].isspace():
        we += 1
    try:
        loc = _utf16_index(text, ws)
        length = _utf16_index(text, we) - loc
        res = cand.boundingBoxForRange_error_((loc, length), None)
        box = res[0] if isinstance(res, tuple) else res
        if box is None:
            return fallback
        x, y, w, h = _to_pixels(box.boundingBox(), width, height)
    except Exception:
        return fallback
    n = max(1, we - ws)
    if n <= (end - start):
        return (x, y, w, h)
    cw = w / n
    a = max(0, start - ws - 1)
    b = min(n, end - ws + 1)
    return (x + a * cw, y, (b - a) * cw, h)


def recognize_lines(
    blob: bytes,
    languages: Optional[list[str]] = None,
    span_finder: Optional[SpanFinder] = None,
) -> list[OcrLine]:
    """Lignes OCR avec leur position en pixels.

    Si `span_finder(text) -> [(start, end, kind)]` est fourni, chaque ligne
    reçoit aussi le rectangle précis de chaque portion trouvée (ex. une clé
    API au milieu d'une ligne). Lève RuntimeError si l'OCR échoue :
    le masquage automatique doit pouvoir refuser d'exporter plutôt que
    croire, à tort, qu'il n'y a aucun secret.
    """
    if not blob:
        return []
    try:
        import objc  # type: ignore[import]
        from Foundation import NSData  # type: ignore[import]
        from Quartz import CIImage  # type: ignore[import]
        from Vision import (  # type: ignore[import]
            VNImageRequestHandler,
            VNRecognizeTextRequest,
        )
    except Exception as exc:
        raise RuntimeError("Vision indisponible") from exc

    out: list[OcrLine] = []
    try:
        with objc.autorelease_pool():
            data = NSData.dataWithBytes_length_(blob, len(blob))
            if data is None:
                raise RuntimeError("image illisible")
            ci_image = CIImage.imageWithData_(data)
            if ci_image is None:
                raise RuntimeError("image illisible")
            extent = ci_image.extent()
            width = int(extent.size.width)
            height = int(extent.size.height)
            if width <= 0 or height <= 0:
                raise RuntimeError("image vide")
            handler = VNImageRequestHandler.alloc().initWithCIImage_options_(ci_image, None)
            request = VNRecognizeTextRequest.alloc().init()
            request.setRecognitionLevel_(0)  # accurate
            # Pas de correction linguistique : elle « corrige » les tokens
            # (sk-ant-… → mots du dictionnaire) et casse la détection.
            request.setUsesLanguageCorrection_(False)
            request.setRecognitionLanguages_(languages or ["fr-FR", "en-US"])
            ok, _err = handler.performRequests_error_([request], None)
            if not ok:
                raise RuntimeError("échec OCR Vision")
            for obs in request.results() or []:
                cands = obs.topCandidates_(1) or []
                if not cands:
                    continue
                cand = cands[0]
                text = str(cand.string())
                line = OcrLine(text=text, rect=_to_pixels(obs.boundingBox(), width, height))
                if span_finder is not None:
                    for start, end, kind in span_finder(text):
                        line.spans.append(OcrSpan(
                            start, end, kind,
                            _span_rect(cand, text, start, end, line.rect, width, height),
                        ))
                out.append(line)
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError("échec OCR Vision") from exc
    return out
