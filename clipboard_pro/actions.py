"""Actions contextuelles par type de contenu.

Chaque type peut exposer plusieurs actions ; la liste est calculée
dynamiquement dans l'UI à partir de l'élément sélectionné.
"""
from __future__ import annotations

import base64
import binascii
import json
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from typing import Callable, Optional
from urllib.parse import (
    parse_qsl,
    quote,
    unquote,
    urlencode,
    urlparse,
    urlunparse,
)

from .db import Item

# Paramètres d'URL connus pour le tracking — supprimés par "Strip tracking".
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_name", "utm_brand",
    "fbclid", "gclid", "gbraid", "wbraid", "msclkid", "yclid",
    "mc_cid", "mc_eid", "_hsenc", "_hsmi", "vero_id",
    "ref", "ref_src", "referrer", "spm",
    "icid", "igshid",
}


@dataclass
class Action:
    label: str
    handler: Callable[[], object]
    primary: bool = False


# --- helpers ----------------------------------------------------------------

def _open_url(url: str) -> None:
    subprocess.run(["open", url], check=False)


def _hex_to_rgb(h: str) -> Optional[tuple[int, int, int, Optional[float]]]:
    s = h.lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    if len(s) == 6:
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), None
    if len(s) == 8:
        a = int(s[6:8], 16) / 255
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), round(a, 2)
    return None


def _rgb_to_hsl(r: int, g: int, b: int) -> tuple[int, int, int]:
    r1, g1, b1 = r / 255, g / 255, b / 255
    cmax = max(r1, g1, b1)
    cmin = min(r1, g1, b1)
    delta = cmax - cmin
    l = (cmax + cmin) / 2
    if delta == 0:
        h = 0.0
        s = 0.0
    else:
        s = delta / (1 - abs(2 * l - 1)) if l not in (0, 1) else 0
        if cmax == r1:
            h = 60 * (((g1 - b1) / delta) % 6)
        elif cmax == g1:
            h = 60 * (((b1 - r1) / delta) + 2)
        else:
            h = 60 * (((r1 - g1) / delta) + 4)
    return round(h), round(s * 100), round(l * 100)


def _strip_tracking(url: str) -> str:
    p = urlparse(url)
    keep = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k not in TRACKING_PARAMS]
    return urlunparse(p._replace(query=urlencode(keep)))


def _strip_html(html: str) -> str:
    """Très basique — retire les tags HTML pour 'Coller en texte brut'."""
    return re.sub(r"<[^>]+>", "", html)


# --- Transformations de texte (Phase 1) -------------------------------------
#
# Ces helpers sont volontairement « purs » : ils prennent une chaîne et en
# renvoient une autre, sans toucher au presse-papiers. C'est `actions_for`
# qui décide quelles transformations exposer pour un item donné, et l'UI
# qui les applique via `copy_callback`.

# Regex pour détecter du texte qui ressemble à du base64. Volontairement
# stricte : on évite de proposer « Décoder base64 » sur n'importe quel
# texte (sinon spam dans la liste d'actions).
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")


def _to_upper(s: str) -> str:
    return s.upper()


def _to_lower(s: str) -> str:
    return s.lower()


def _to_title(s: str) -> str:
    """Title Case — première lettre de chaque mot en majuscule.

    On capitalise après un espace ou au début uniquement (pas après une
    apostrophe), pour respecter le français : « l'effet » → « L'effet »
    plutôt que « L'Effet ». Différent de ``str.title()`` qui galère sur
    les accents et les apostrophes.
    """
    return re.sub(
        r"(?:^|\s)\w",
        lambda m: m.group(0).upper(),
        s.lower(),
    )


def _to_slug(s: str) -> str:
    """ASCII-slug façon GitHub : sans accents, kebab-case, alphanumérique."""
    # NFKD pour décomposer les accents, puis on garde uniquement ASCII.
    normalized = unicodedata.normalize("NFKD", s)
    ascii_only = normalized.encode("ascii", errors="ignore").decode("ascii")
    # Tout ce qui n'est pas alphanumérique → tiret. Compression des tirets.
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return slug or s.strip().lower()  # fallback si tout a été dégagé


def _b64_encode(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def _looks_like_base64(s: str) -> bool:
    """True si le texte ressemble à du base64 décodable en UTF-8."""
    stripped = s.strip()
    if len(stripped) < 4 or len(stripped) % 4 != 0:
        return False
    if not _BASE64_RE.match(stripped):
        return False
    # Test final : ça décode-t-il en quelque chose ?
    try:
        decoded = base64.b64decode(stripped, validate=True)
        # On veut éviter les faux positifs sur du binaire — on n'expose que
        # si ça se décode en texte UTF-8 propre (sinon on garde le secret
        # pour soi).
        decoded.decode("utf-8")
        return True
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return False


def _b64_decode(s: str) -> Optional[str]:
    try:
        return base64.b64decode(s.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None


def _url_encode(s: str) -> str:
    """Échappe les caractères spéciaux pour usage dans une URL."""
    return quote(s, safe="")


def _looks_like_url_encoded(s: str) -> bool:
    """True si le texte contient au moins une séquence %XX."""
    return bool(re.search(r"%[0-9A-Fa-f]{2}", s))


def _url_decode(s: str) -> str:
    return unquote(s)


def _trim_whitespace(s: str) -> str:
    """Strip espaces / tabs / newlines en début et fin."""
    return s.strip()


def _has_outer_whitespace(s: str) -> bool:
    return s != s.strip() and bool(s.strip())


# --- public -----------------------------------------------------------------

def actions_for(item: Item, *, copy_callback: Callable[[str], None]) -> list[Action]:
    """Renvoie les actions **principales** disponibles pour cet item.

    Ce sont les actions contextuelles intelligentes qui dépendent du type
    de contenu détecté (ouvrir une URL, formater du JSON, etc.). Elles
    s'affichent en boutons rapides sous l'aperçu.

    Les **transformations** purement textuelles (UPPER, lower, base64…) ne
    sont PAS incluses ici depuis la session 5 — elles vivent dans
    :func:`transformations_for` et sont exposées via le menu déroulant
    « Transformer ▾ » dans l'UI. Ça évite d'avoir 10 boutons qui débordent
    sous chaque item texte.
    """
    out: list[Action] = []
    if item.kind != "text" or not item.text:
        # OCR pour image
        if item.kind == "image" and item.ocr_text:
            out.append(Action("Copier le texte (OCR)", lambda: copy_callback(item.ocr_text or ""), primary=True))
        return out

    text = item.text
    ct = item.content_type

    if ct == "url":
        out.append(Action("Ouvrir", lambda: _open_url(text), primary=True))
        clean = _strip_tracking(text)
        if clean != text:
            out.append(Action("Copier sans paramètres de tracking", lambda: copy_callback(clean)))
    elif ct == "json":
        try:
            obj = json.loads(text)
            pretty = json.dumps(obj, ensure_ascii=False, indent=2)
            mini = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
            if pretty != text:
                out.append(Action("Formater (joli)", lambda: copy_callback(pretty), primary=True))
            if mini != text:
                out.append(Action("Minifier", lambda: copy_callback(mini)))
        except ValueError:
            pass
    elif ct == "color":
        rgb = _hex_to_rgb(text)
        if rgb:
            r, g, b, a = rgb
            css_rgb = f"rgb({r}, {g}, {b})" if a is None else f"rgba({r}, {g}, {b}, {a})"
            h, s, l = _rgb_to_hsl(r, g, b)
            css_hsl = f"hsl({h}, {s}%, {l}%)" if a is None else f"hsla({h}, {s}%, {l}%, {a})"
            out.append(Action(f"Copier en {css_rgb}", lambda: copy_callback(css_rgb), primary=True))
            out.append(Action(f"Copier en {css_hsl}", lambda: copy_callback(css_hsl)))
    elif ct == "email":
        out.append(Action("Composer un mail", lambda: _open_url(f"mailto:{text}"), primary=True))
    elif ct == "phone":
        out.append(Action("Appeler (FaceTime)", lambda: _open_url(f"tel:{text}"), primary=True))
    elif ct == "path":
        out.append(Action("Révéler dans le Finder", lambda: subprocess.run(["open", "-R", text], check=False), primary=True))

    # Toujours : coller en texte brut (au cas où il y aurait du formatage)
    if "<" in text and ">" in text:
        clean = _strip_html(text)
        if clean.strip() and clean != text:
            out.append(Action("Coller en texte brut", lambda: copy_callback(clean)))

    return out


def transformations_for(item: Item, *, copy_callback: Callable[[str], None]) -> list[Action]:
    """Renvoie les transformations de texte disponibles pour cet item.

    Utilisé par l'UI pour peupler le menu déroulant « Transformer ▾ ».
    Renvoie liste vide pour les items non-texte ou texte vide.
    """
    out: list[Action] = []
    if item.kind != "text" or not item.text:
        return out

    text = item.text
    ct = item.content_type

    upper = _to_upper(text)
    if upper != text:
        out.append(Action("Tout en MAJUSCULES", lambda: copy_callback(upper)))
    lower = _to_lower(text)
    if lower != text:
        out.append(Action("tout en minuscules", lambda: copy_callback(lower)))
    title = _to_title(text)
    if title != text and title != upper and title != lower:
        out.append(Action("Title Case", lambda: copy_callback(title)))
    # Le slug ne fait sens que sur du texte court (titre, nom de variable…) ;
    # pas envie de slugifier un email de 4 paragraphes.
    if len(text) <= 200:
        slug = _to_slug(text)
        if slug and slug != text:
            out.append(Action("Slugifier (kebab-case)", lambda: copy_callback(slug)))

    # base64 : encode toujours dispo, décode seulement si ça ressemble
    b64 = _b64_encode(text)
    out.append(Action("Encoder en base64", lambda: copy_callback(b64)))
    if _looks_like_base64(text):
        decoded = _b64_decode(text)
        if decoded is not None and decoded != text:
            out.append(Action("Décoder le base64", lambda: copy_callback(decoded)))

    # URL encode : pas dispo si déjà une URL (l'utilisateur en veut rarement
    # l'encodage). URL decode : seulement si %XX détecté.
    if ct != "url":
        enc = _url_encode(text)
        if enc != text:
            out.append(Action("Encoder pour URL", lambda: copy_callback(enc)))
    if _looks_like_url_encoded(text):
        dec = _url_decode(text)
        if dec != text:
            out.append(Action("Décoder URL (%XX)", lambda: copy_callback(dec)))

    # Trim : seulement si y a des espaces inutiles autour.
    if _has_outer_whitespace(text):
        trimmed = _trim_whitespace(text)
        out.append(Action("Supprimer les espaces de bordure", lambda: copy_callback(trimmed)))

    return out
