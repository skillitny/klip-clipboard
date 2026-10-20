"""Détection automatique du type d'un contenu copié."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

URL_RE = re.compile(r"^https?://[^\s]+$", re.I)
EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.-]+$")
HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
PHONE_RE = re.compile(r"^[+]?[\d\s().-]{7,}$")
NUMBER_RE = re.compile(r"^-?\d+(?:[.,]\d+)?$")
PATH_RE = re.compile(r"^(?:/|~|[A-Za-z]:\\)[\w./\\ -]+$")
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


@dataclass(frozen=True)
class TypeInfo:
    code: str       # identifiant stable
    label: str      # libellé court
    icon: str       # emoji utilisé comme badge dans l'UI
    color: str      # couleur du badge (hex)


TYPES: dict[str, TypeInfo] = {
    "url":     TypeInfo("url",     "URL",      "🔗", "#3b82f6"),
    "email":   TypeInfo("email",   "Email",    "✉️", "#8b5cf6"),
    "json":    TypeInfo("json",    "JSON",     "{}", "#14b8a6"),
    "code":    TypeInfo("code",    "Code",     "</>","#f59e0b"),
    "color":   TypeInfo("color",   "Couleur",  "🎨", "#ec4899"),
    "number":  TypeInfo("number",  "Nombre",   "#",  "#64748b"),
    "phone":   TypeInfo("phone",   "Tel.",     "📞", "#22c55e"),
    "path":    TypeInfo("path",    "Chemin",   "📁", "#f97316"),
    "uuid":    TypeInfo("uuid",    "UUID",     "id", "#a855f7"),
    "image":   TypeInfo("image",   "Image",    "🖼", "#0ea5e9"),
    "plain":   TypeInfo("plain",   "Texte",    "¶",  "#94a3b8"),
}


def classify(text: str) -> TypeInfo:
    """Renvoie le type le plus pertinent pour un texte."""
    if text is None:
        return TYPES["plain"]
    s = text.strip()
    if not s:
        return TYPES["plain"]

    if "\n" not in s:
        if URL_RE.match(s):
            return TYPES["url"]
        if EMAIL_RE.match(s):
            return TYPES["email"]
        if HEX_COLOR_RE.match(s):
            return TYPES["color"]
        if UUID_RE.match(s):
            return TYPES["uuid"]
        if NUMBER_RE.match(s):
            return TYPES["number"]
        if len(s) < 30 and PHONE_RE.match(s) and sum(c.isdigit() for c in s) >= 7:
            return TYPES["phone"]
        if PATH_RE.match(s):
            return TYPES["path"]

    # JSON
    if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
        try:
            json.loads(s)
            return TYPES["json"]
        except ValueError:
            pass

    # Heuristique code : présence simultanée de plusieurs marqueurs
    code_markers = 0
    for marker in (";", "{", "}", "()", "=>", "def ", "function ", "import ",
                   "class ", "const ", "let ", "var ", "#include", "<?", "</"):
        if marker in s:
            code_markers += 1
    if code_markers >= 2 or (s.count("\n") >= 2 and code_markers >= 1):
        return TYPES["code"]

    return TYPES["plain"]
