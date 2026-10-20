"""Masquage des captures d'écran (v2.5).

Deux usages :

  • Manuel : l'éditeur (`redact_editor.py`) laisse l'utilisateur masquer
    des lignes ou des zones avant d'envoyer une capture.
  • Automatique : option « Toujours masquer les secrets dans les captures »
    (Préférences › Confidentialité). Quand elle est active, toute image qui
    SORT de Klip (copier, glisser, mini-fenêtre) a ses secrets recouverts
    d'une barre pleine. L'original reste intact dans l'historique.

Le masque est « brûlé » dans les pixels du PNG exporté : rien de caché
dans des calques, rien de récupérable en ouvrant le fichier.

Pourquoi la barre pleine pour l'automatique : un flou ou une pixellisation
se défont parfois (des outils reconstruisent le texte flouté). Le flou et
le pixel restent proposés dans l'éditeur pour l'esthétique (un nom, un
visage), pas pour une clé.
"""
from __future__ import annotations

import hashlib
import re
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from .secrets import TOKEN_PATTERNS, shannon_entropy

STYLES = ("bar", "blur", "pixel")
STYLE_LABELS = {"bar": "Barre", "blur": "Flou", "pixel": "Pixel"}
BAR_COLOR = "#111114"


# ----------------------------------------------------------------------------
# Détection des portions sensibles dans une ligne de texte
# ----------------------------------------------------------------------------

_CARD_RE = re.compile(r"(?<![\d])(?:\d[ \-]?){12,18}\d(?![\d])")
_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]){11,30}\b")
# « password: xxx », « api_key = xxx », « token "xxx" »… → on masque la valeur.
_KEYVALUE_RE = re.compile(
    r"(?i)\b(?:pass(?:word|wd)?|mot de passe|secret|token|api[_\- ]?key|"
    r"access[_\- ]?key|client[_\- ]?secret|auth)\b[\"']?\s*[:=]\s*[\"']?"
    r"(?P<val>[^\s\"']{8,})"
)
# « = » seulement en fin (padding base64), sinon « NOM=valeur » serait
# avalé en entier et la barre couvrirait aussi le nom de la variable.
_LONG_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-+/.]{32,}={0,2}")

# Vision rend parfois des lettres cyrilliques/grecques identiques à l'œil
# (« АPI », « Тq7 ») au lieu des latines : les regex ne matchent plus. On
# remplace caractère pour caractère (même longueur → mêmes index).
# Vision lit aussi « — » ou « – » pour « - », « × » pour « x », etc.
_CONFUSABLES = str.maketrans(
    "АВЕКМНОРСТХУаеорсухіјѕԁԛԝΑΒΕΖΗΙΚΜΝΟΡΤΥΧονі" "—–‐‑‒−×＿｜ǀ",
    "ABEKMHOPCTXYaeopcyxijsdqwABEZHIKMNOPTYXovi" "------x_||",
)


def normalize_ocr(text: str) -> str:
    """Texte OCR → texte comparable aux regex, MÊME LONGUEUR (index gardés).

    1. Table des sosies connus (cyrillique, grec, tirets, ×…).
    2. Tout autre caractère non ASCII collé à un caractère ASCII
       alphanumérique devient « X » : Vision invente parfois des signes
       (Ø, З…) au milieu d'une clé, et un seul suffit à casser la regex.
       Effet de bord sans danger : « réunion » devient « rXunion » pour la
       détection seulement, le texte affiché ne change pas.
    """
    t = list(text.translate(_CONFUSABLES))
    n = len(t)
    for i, c in enumerate(t):
        if ord(c) < 128 or c.isspace():
            continue
        left = i > 0 and t[i - 1].isascii() and t[i - 1].isalnum()
        right = i + 1 < n and t[i + 1].isascii() and t[i + 1].isalnum()
        if left or right:
            t[i] = "X"
    return "".join(t)


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = ord(ch) - 48
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _iban_ok(raw: str) -> bool:
    s = raw.replace(" ", "")
    if not (15 <= len(s) <= 34):
        return False
    s = s[4:] + s[:4]
    num = "".join(str(int(c, 36)) for c in s)
    return int(num) % 97 == 1


_WORD_RUN_RE = re.compile(r"[a-z]{4,}")


def _looks_random(tok: str) -> bool:
    """Long token de type clé (base64 / base62), PAS du code ni un chemin.

    Faux positifs vus en vrai : `_user32.GetWindowThreadProcessId`,
    `win32clipboard.EnumClipboardFormats`, `dist/Klip.app/Contents/...`.
    Un identifiant de code contient des mots (suites de minuscules) et des
    points ; une clé aléatoire contient des chiffres et très peu de « mots ».
    """
    if tok.lower().startswith(("http", "www.")) or "." in tok:
        return False
    words = len(_WORD_RUN_RE.findall(tok))
    if words > 2:
        return False
    digits = sum(c.isdigit() for c in tok)
    has_lower = any(c.islower() for c in tok)
    has_upper = any(c.isupper() for c in tok)
    if not (has_lower and has_upper):
        return False
    # Peu de chiffres : accepté seulement si quasi aucun « mot » dedans.
    if digits < 2 and words > 0:
        return False
    return shannon_entropy(tok) >= 4.0


def find_secret_spans(text: str) -> list[tuple[int, int, str]]:
    """Portions sensibles d'une ligne : [(début, fin, type)], fusionnées."""
    if not text:
        return []
    text = normalize_ocr(text)
    spans: list[tuple[int, int, str]] = []
    for name, pat in TOKEN_PATTERNS:
        for m in pat.finditer(text):
            spans.append((m.start(), m.end(), name))
    for m in _CARD_RE.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn_ok(digits):
            spans.append((m.start(), m.end(), "carte_bancaire"))
    for m in _IBAN_RE.finditer(text):
        try:
            if _iban_ok(m.group()):
                spans.append((m.start(), m.end(), "iban"))
        except ValueError:
            pass
    for m in _KEYVALUE_RE.finditer(text):
        spans.append((m.start("val"), m.end("val"), "valeur_secrete"))
    for m in _LONG_TOKEN_RE.finditer(text):
        if _looks_random(m.group()):
            spans.append((m.start(), m.end(), "token_long"))

    # Filet de sécurité : une portion détectée s'étend jusqu'à la fin de sa
    # suite sans espace (et recule jusqu'au « = », « : » ou guillemet qui la
    # précède). Si l'OCR a mal lu UN caractère au milieu d'une clé, la regex
    # s'arrête là et la fin de la clé resterait visible. Mieux vaut masquer
    # quelques caractères de trop.
    stops = set(" \t\"'`=:,;()[]{}<>")
    grown = []
    for st, en, k in spans:
        while st > 0 and text[st - 1] not in stops:
            st -= 1
        while en < len(text) and text[en] not in stops:
            en += 1
        grown.append((st, en, k))
    spans = grown

    spans.sort()
    merged: list[tuple[int, int, str]] = []
    for s, e, k in spans:
        if merged and s <= merged[-1][1]:
            ps, pe, pk = merged[-1]
            merged[-1] = (ps, max(pe, e), pk)
        else:
            merged.append((s, e, k))
    return merged


# ----------------------------------------------------------------------------
# Rendu : brûler les masques dans l'image
# ----------------------------------------------------------------------------

@dataclass
class Mask:
    x: float
    y: float
    w: float
    h: float
    style: str = "bar"


def pad_rect(x: float, y: float, w: float, h: float,
             img_w: int, img_h: int) -> tuple[float, float, float, float]:
    """Élargit un peu le rectangle OCR (Vision colle au glyphe) et le borne."""
    p = max(2.0, h * 0.18)
    nx, ny = max(0.0, x - p), max(0.0, y - p)
    nw = min(img_w - nx, w + 2 * p)
    nh = min(img_h - ny, h + 2 * p)
    return nx, ny, nw, nh


def render(image, masks: list[Mask]):
    """Renvoie une COPIE de la QImage avec les masques appliqués."""
    from PyQt6.QtCore import QRect, Qt
    from PyQt6.QtGui import QColor, QImage, QPainter

    out = image.convertToFormat(QImage.Format.Format_ARGB32)
    if not masks:
        return out
    painter = QPainter(out)
    try:
        for m in masks:
            r = QRect(int(m.x), int(m.y), max(1, int(round(m.w))), max(1, int(round(m.h))))
            r = r.intersected(out.rect())
            if r.isEmpty():
                continue
            if m.style == "bar":
                painter.fillRect(r, QColor(BAR_COLOR))
                continue
            crop = out.copy(r)
            if m.style == "pixel":
                block = max(6, min(r.width(), r.height()) // 4)
                small = crop.scaled(
                    max(1, r.width() // block), max(1, r.height() // block),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
                big = small.scaled(
                    r.width(), r.height(),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.FastTransformation,
                )
            else:  # blur : réduction forte puis agrandissement lissé, 2 passes
                big = crop
                for _ in range(2):
                    small = big.scaled(
                        max(1, r.width() // 14), max(1, r.height() // 14),
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    big = small.scaled(
                        r.width(), r.height(),
                        Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
            painter.drawImage(r.topLeft(), big)
    finally:
        painter.end()
    return out


def image_from_png(blob: bytes):
    from PyQt6.QtGui import QImage
    img = QImage()
    img.loadFromData(blob, "PNG")
    return img


def image_to_png(image) -> bytes:
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    buf.close()
    return bytes(ba)


# ----------------------------------------------------------------------------
# Masquage automatique des secrets
# ----------------------------------------------------------------------------

def secret_masks(blob: bytes, languages: Optional[list[str]] = None) -> list[Mask]:
    """OCR avec positions → une barre par secret détecté."""
    from .ocr import recognize_lines

    img = image_from_png(blob)
    if img.isNull():
        raise RuntimeError("image illisible")
    masks: list[Mask] = []
    for line in recognize_lines(blob, languages, span_finder=find_secret_spans):
        for span in line.spans:
            x, y, w, h = pad_rect(*span.rect, img.width(), img.height())
            masks.append(Mask(x, y, w, h, "bar"))
    return masks


_CACHE: "OrderedDict[str, Optional[bytes]]" = OrderedDict()
_CACHE_MAX = 16


def auto_mask_png(blob: bytes, languages: Optional[list[str]] = None) -> Optional[bytes]:
    """PNG avec les secrets masqués, ou None s'il n'y a aucun secret.

    Résultat mis en cache (empreinte du PNG) : recopier la même capture ne
    relance pas l'OCR.
    """
    if not blob:
        return None
    key = hashlib.sha256(blob).hexdigest()
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    masks = secret_masks(blob, languages)
    result = image_to_png(render(image_from_png(blob), masks)) if masks else None
    _CACHE[key] = result
    if len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return result


def export_png(blob: bytes, settings) -> Optional[bytes]:
    """Ce qui sort de Klip pour une image : masquée si l'option est active.

    Option active + échec du masquage → None (« quoi qu'il arrive ») :
    l'appelant n'envoie RIEN et prévient l'utilisateur, plutôt que de
    laisser partir l'original avec la clé visible.
    """
    if settings is None or not bool(settings.get("capture.mask_secrets_in_images", False)):
        return blob
    try:
        masked = auto_mask_png(blob, settings.get("ocr.languages", None))
    except Exception:
        return None
    return masked if masked is not None else blob
