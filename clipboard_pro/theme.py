"""Palette + feuille de style Qt — sombre et clair, accent personnalisable.

Le QSS est généré à partir d'une palette (dict). Au démarrage, on choisit
la palette selon ``settings.ui.theme`` :

  • ``"dark"``  → :data:`PALETTE_DARK`
  • ``"light"`` → :data:`PALETTE_LIGHT`
  • ``"auto"``  → suit ``defaults read -g AppleInterfaceStyle`` (macOS)

L'accent (violet par défaut) est personnalisable via ``settings.ui.accent``
— ``ACCENT_PALETTES`` liste les 8 couleurs prédéfinies (Phase 6).

Pour rétro-compat, ``PALETTE`` et ``QSS`` restent exportés et pointent vers
la version sombre (le défaut historique). Les nouveaux modules devraient
préférer ``current_palette(theme)`` / ``current_qss(theme)``.
"""
from __future__ import annotations

import subprocess
from typing import Dict, Optional


# ---------------------------------------------------------------------------
# Palettes
# ---------------------------------------------------------------------------

# Palette sombre — refonte session 6 (contraste poussé +60%).
# L'ancienne palette avait bg/bg_panel à 0.05 de luminance différence —
# l'œil ne distinguait quasiment pas les cards du canvas. La nouvelle
# pousse les différentiels :
#   bg (canvas)       très foncé (presque noir profond)
#   bg_panel (cards)  +20% luminance — vraie séparation visible
#   bg_elev (boutons) +35% luminance — clairement "élevé"
#   bg_hover          +50% luminance — feedback immédiat au hover
PALETTE_DARK: Dict[str, str] = {
    "bg":          "#13151a",   # canvas (presque noir profond)
    "bg_panel":    "#1e2230",   # cards / sidebars (+20% luminance)
    "bg_elev":     "#2a2f40",   # boutons / inputs (+35%)
    "bg_hover":    "#363d52",   # hover / focus (+50%)
    "border":      "#373d52",   # bordure subtile mais visible
    "text":        "#eef0f6",   # texte principal — presque blanc
    "text_dim":    "#a5abc0",   # meta info
    "text_faint":  "#6a7088",   # légendes
    "accent":      "#7c5cff",
    "accent_dim":  "#5b3fe0",
    "danger":      "#ef4444",
    "favorite":    "#fbbf24",
}

# Palette claire (Phase 2, session 5 → tuning session 6) — fond crème
# chaud plutôt que blanc cassé clinique. Inspiration : Reeder / Things /
# Bear (les apps macOS qui font le mode clair "chaud"). On reste subtil :
# pas de marron franc, juste une teinte beige discrète qui réchauffe sans
# devenir "carnaval".
PALETTE_LIGHT: Dict[str, str] = {
    "bg":          "#f3eee5",   # crème chaude — entre gris et beige léger
    "bg_panel":    "#fbf8f2",   # panneau légèrement plus clair (papier doux)
    "bg_elev":     "#ffffff",   # blanc pur pour inputs / éléments interactifs
    "bg_hover":    "#ebe5d8",   # crème plus foncée pour le hover
    "border":      "#d8d0c0",   # bordure beige neutre — visible mais douce
    "text":        "#1f1d18",   # noir chaud (légère teinte sépia)
    "text_dim":    "#6b665a",   # taupe moyen — meta info
    "text_faint":  "#9a9587",   # taupe clair — légendes
    "accent":      "#7c5cff",   # même violet — identité visuelle
    "accent_dim":  "#5b3fe0",
    "danger":      "#c53030",   # rouge plus chaud, mieux marié au beige
    "favorite":    "#c2701c",   # ambre profond pour les favoris
}


# ---------------------------------------------------------------------------
# Construction du QSS (paramétré par une palette)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Couleurs d'accent personnalisables (Phase 6)
# ---------------------------------------------------------------------------
# Chaque entrée : (code, label affiché, hex accent, hex accent_dim).
# Le label est en français pour cohérence avec l'UI. L'ordre détermine
# l'affichage dans le combo Préférences → Général → Apparence.

ACCENT_PALETTES: list[tuple[str, str, str, str]] = [
    ("violet", "Violet",  "#7c5cff", "#5b3fe0"),  # défaut historique
    ("indigo", "Indigo",  "#6366f1", "#4f46e5"),
    ("bleu",   "Bleu",    "#3b82f6", "#2563eb"),
    ("cyan",   "Cyan",    "#06b6d4", "#0891b2"),
    ("vert",   "Vert",    "#10b981", "#059669"),
    ("rose",   "Rose",    "#ec4899", "#db2777"),
    ("rouge",  "Rouge",   "#ef4444", "#dc2626"),
    ("orange", "Orange",  "#f59e0b", "#d97706"),
]


def _lookup_accent(accent: str) -> Optional[tuple[str, str]]:
    """Si ``accent`` est un hex (#RRGGBB) ou un code connu, renvoie (accent, accent_dim)."""
    if not accent:
        return None
    a = accent.strip().lower()
    # Match par code (violet, indigo, …)
    for code, _label, hex_accent, hex_dim in ACCENT_PALETTES:
        if a == code:
            return (hex_accent, hex_dim)
    # Match par hex direct
    if a.startswith("#"):
        for _code, _label, hex_accent, hex_dim in ACCENT_PALETTES:
            if a == hex_accent.lower():
                return (hex_accent, hex_dim)
        # Hex personnalisé inconnu : on garde accent_dim = même hex (pas idéal
        # mais évite de casser ; un futur fix calculera un vrai darken).
        return (accent, accent)
    return None


def _apply_accent(palette: Dict[str, str], accent: Optional[str]) -> Dict[str, str]:
    """Renvoie une COPIE de la palette avec l'accent éventuellement remplacé."""
    if not accent:
        return palette
    resolved = _lookup_accent(accent)
    if not resolved:
        return palette
    new_pal = dict(palette)
    new_pal["accent"], new_pal["accent_dim"] = resolved
    return new_pal


# ---------------------------------------------------------------------------
# Design system typographique (session 5 v2)
# ---------------------------------------------------------------------------
# Système à 6 niveaux pour avoir une hiérarchie visuelle cohérente partout
# dans l'app au lieu de tailles redéfinies inline à chaque widget.
#
# Usage côté widget Qt :
#
#   label = QLabel("Mon titre")
#   label.setProperty("class", "h1")   # ou "h2", "caps", "body", "meta", "faint"
#
# Le QSS global cible `QLabel[class="h1"] { ... }` etc.

FONT_TOKENS: Dict[str, Dict[str, str]] = {
    "h1": {
        # Titre principal de fenêtre
        "size": "22px",
        "weight": "700",
        "color_key": "text",
        "letter_spacing": "0",
    },
    "h2": {
        # Titre de section dans une fenêtre
        "size": "16px",
        "weight": "600",
        "color_key": "text",
        "letter_spacing": "0",
    },
    "caps": {
        # Mini-titre au-dessus d'un groupe (uppercase + accent)
        "size": "11px",
        "weight": "700",
        "color_key": "accent",
        "letter_spacing": "1px",
        "transform": "uppercase",
    },
    "body": {
        # Texte principal lisible
        "size": "13px",
        "weight": "400",
        "color_key": "text",
        "letter_spacing": "0",
    },
    "meta": {
        # Métadonnées discrètes (date, source app, taille…)
        "size": "11px",
        "weight": "400",
        "color_key": "text_dim",
        "letter_spacing": "0",
    },
    "faint": {
        # Hints désactivés ou très secondaires (en italique)
        "size": "11px",
        "weight": "400",
        "color_key": "text_faint",
        "letter_spacing": "0",
        "style": "italic",
    },
}


def make_qss(palette: Dict[str, str]) -> str:
    """Construit le QSS complet à partir d'une palette."""
    return f"""
* {{
    color: {palette['text']};
    font-family: -apple-system, "SF Pro Text", "Inter", "Segoe UI", sans-serif;
    font-size: 13px;
}}
QMainWindow, QWidget#root {{
    background: {palette['bg']};
}}
/* === Header band (v2.3) ===
   Bandeau supérieur en fond clair (cohérent avec le reste du light mode)
   contenant le titre Klip à gauche et une toolbar d'actions à droite. */
QWidget#headerBand {{
    background: {palette['bg_panel']};
    border-bottom: 1px solid {palette['border']};
}}
QLabel#headerTitle {{
    color: {palette['text']};
    font-size: 22px;
    font-weight: 700;
    background: transparent;
}}
QLabel#headerSubtitle {{
    color: {palette['text_dim']};
    font-size: 13px;
    font-weight: 400;
    background: transparent;
    padding-left: 4px;
    padding-top: 6px;
}}
QLabel#headerCount {{
    color: {palette['text_dim']};
    font-size: 12px;
    font-weight: 500;
    background: transparent;
}}
/* Boutons de la toolbar header (Préférences, Raccourcis, Guide, etc.).
   Le contenu (icône + label) vit dans des QLabel internes — le bouton
   lui-même n'a que le hover/press background. */
QPushButton#toolbarBtn {{
    background: transparent;
    border: 0;
    border-radius: 8px;
}}
QPushButton#toolbarBtn:hover {{
    background: {palette['bg_hover']};
}}
QPushButton#toolbarBtn:pressed {{
    background: {palette['bg_elev']};
}}
/* Icône et label internes des boutons toolbar — theme-aware via objectName */
QLabel#toolbarBtnIcon {{
    background: transparent;
    border: 0;
    color: {palette['text']};
    font-size: 17px;
    font-weight: 700;
}}
QLabel#toolbarBtnLabel {{
    background: transparent;
    border: 0;
    color: {palette['text_dim']};
    font-size: 10px;
    font-weight: 500;
}}
/* Séparateur vertical entre les boutons du toolbar header */
QFrame#toolbarSep {{
    background: {palette['border']};
    border: 0;
    max-width: 1px;
}}
/* Labels enfants des chips filtre sidebar. Qt QSS supporte mal les
   sélecteurs descendants (QPushButton QLabel), donc on cible les
   labels uniquement par objectName. La couleur de base depuis la
   palette (palette['text']) est lisible aussi bien sur le fond clair
   normal que sur le fond accent (violet/bleu) quand un filtre est
   sélectionné. */
QLabel#filterChipIcon {{
    background: transparent;
    border: 0;
    color: {palette['text']};
    font-size: 14px;
    font-weight: 700;
}}
QLabel#filterChipLabel {{
    background: transparent;
    border: 0;
    color: {palette['text']};
    font-size: 13px;
    font-weight: 500;
}}
QLabel#filterCount {{
    background: transparent;
    border: 0;
    color: {palette['text_faint']};
    font-size: 11px;
    font-weight: 500;
}}
/* "Bloc" visuel englobant une section de la sidebar (Filtres, Temps,
   Application) — léger fond + bordure pour structurer l'UI comme la
   référence Notion/Linear. */
QFrame#sidebarBlock {{
    background: {palette['bg_elev']};
    border: 1px solid {palette['border']};
    border-radius: 8px;
}}
/* Zone contextuelle bulk : "X éléments sélectionnés" + bouton */
QWidget#bulkContextWidget {{
    background: {palette['bg_elev']};
    border: 1px solid {palette['border']};
    border-radius: 8px;
}}
QLabel#bulkCountLabel {{
    background: transparent;
    border: 0;
    color: {palette['text_dim']};
    font-size: 11px;
    font-weight: 600;
}}
QWidget#contentArea {{
    background: {palette['bg']};
}}
/* === Sidebar filtres MainWindow (session 6, refonte pleine hauteur) ===
   Bande verticale à GAUCHE de toute l'app, du bandeau accent (en haut)
   au footer (en bas). Pas de border-radius — c'est une vraie sidebar
   plein-pot, séparée du contenu par une bordure droite uniquement. */
QFrame#filterSidebar {{
    background: {palette['bg_panel']};
    border: 0;
    border-right: 1px solid {palette['border']};
}}
QFrame#filterSidebar QLineEdit#search {{
    background: {palette['bg_elev']};
    border: 1px solid {palette['border']};
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 13px;
}}
QFrame#filterSidebar QComboBox {{
    background: {palette['bg_elev']};
    border: 1px solid {palette['border']};
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 26px;
}}
QPushButton[class="sidebarItem"] {{
    text-align: left;
    padding: 6px 12px;
    /* Léger inset (marge) pour que le fond survol/sélection reste bien à
       l'intérieur du bloc et ne déborde jamais sur ses bords arrondis. */
    margin: 1px 3px;
    border: 0;
    border-radius: 6px;
    background: transparent;
    color: {palette['text']};
    font-size: 13px;
    font-weight: 500;
}}
/* IMPORTANT : on répète margin + border-radius sur CHAQUE état. Sans ça,
   Qt peut peindre le fond :hover sur tout le rectangle (en ignorant la
   marge appliquée aux autres états) → le survol paraissait « déborder »
   par rapport à l'élément sélectionné. Géométrie identique partout. */
QPushButton[class="sidebarItem"]:hover {{
    background: {palette['bg_hover']};
    margin: 1px 3px;
    border-radius: 6px;
}}
QPushButton[class="sidebarItem"]:checked {{
    background: {palette['accent']};
    color: white;
    font-weight: 600;
    margin: 1px 3px;
    border-radius: 6px;
}}
/* Survol de l'élément déjà sélectionné : on garde l'accent (pas le gris). */
QPushButton[class="sidebarItem"]:checked:hover {{
    background: {palette['accent']};
    color: white;
    margin: 1px 3px;
    border-radius: 6px;
}}
/* Poignée du splitter liste/aperçu : fine ligne, surlignée au survol. */
QSplitter#bodySplitter::handle:horizontal {{
    background: transparent;
    border-left: 1px solid {palette['border']};
    margin: 10px 3px;
}}
QSplitter#bodySplitter::handle:horizontal:hover {{
    border-left: 2px solid {palette['accent']};
}}
/* === Chips de filtre (theme-aware) ===
   Migré depuis ``ui.py:_make_chip`` qui posait un setStyleSheet inline
   figé sur la palette du démarrage. Avec le sélecteur dans le QSS
   global, les chips se rerendent correctement au changement de thème. */
QPushButton[chip="true"] {{
    background: {palette['bg_panel']};
    border: 1px solid {palette['border']};
    border-radius: 14px;
    padding: 4px 12px;
    color: {palette['text_dim']};
    font-size: 12px;
}}
QPushButton[chip="true"]:hover {{
    background: {palette['bg_hover']};
    color: {palette['text']};
}}
QPushButton[chip="true"]:checked {{
    background: {palette['accent']};
    border-color: {palette['accent']};
    color: white;
    font-weight: 600;
}}
QLineEdit#search {{
    background: {palette['bg_panel']};
    border: 1px solid {palette['border']};
    border-radius: 10px;
    padding: 10px 14px;
    font-size: 15px;
    selection-background-color: {palette['accent']};
}}
QLineEdit#search:focus {{
    border: 1px solid {palette['accent']};
}}
QListWidget {{
    background: {palette['bg_panel']};
    border: 1px solid {palette['border']};
    border-radius: 10px;
    padding: 4px;
    outline: 0;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 6px;
    margin: 1px 2px;
    color: {palette['text']};
}}
QListWidget::item:hover {{
    background: {palette['bg_hover']};
}}
QListWidget::item:selected {{
    background: {palette['accent']};
    color: white;
}}
QFrame#preview {{
    background: {palette['bg_panel']};
    border: 1px solid {palette['border']};
    border-radius: 10px;
}}
QFrame#previewSep {{
    background: {palette['border']};
    border: 0;
    max-height: 1px;
}}
QTextEdit#previewBody {{
    background: transparent;
    border: 0;
    padding: 4px;
    color: {palette['text']};
    selection-background-color: {palette['accent']};
}}
QLabel {{
    color: {palette['text']};
}}
/* Tooltips : Qt rend les tooltips comme des QLabel → sans règle dédiée, la
   règle QLabel ci-dessus leur donnait un texte clair sur le fond clair par
   défaut = illisible en mode sombre. On force fond + texte cohérents. */
QToolTip {{
    background: {palette['bg_elev']};
    color: {palette['text']};
    border: 1px solid {palette['border']};
    padding: 6px 9px;
}}
QLabel#title {{
    color: {palette['text_dim']};
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
}}
QLabel#meta {{
    color: {palette['text_faint']};
    font-size: 11px;
}}
/* === Design system typographique (session 5 v2) ===
   Utilisable sur n'importe quel QLabel via setProperty("class", "h1" | "h2"
   | "caps" | "body" | "meta" | "faint"). Donne une hiérarchie cohérente
   sans avoir à redéfinir font-size/weight inline à chaque widget. */
QLabel[class="h1"] {{
    color: {palette['text']};
    font-size: 22px;
    font-weight: 700;
    padding: 4px 0;
}}
QLabel[class="h2"] {{
    color: {palette['text']};
    font-size: 16px;
    font-weight: 600;
    padding: 2px 0;
}}
QLabel[class="caps"] {{
    color: {palette['accent']};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
}}
QLabel[class="body"] {{
    color: {palette['text']};
    font-size: 13px;
    font-weight: 400;
}}
QLabel[class="meta"] {{
    color: {palette['text_dim']};
    font-size: 11px;
    font-weight: 400;
}}
QLabel[class="faint"] {{
    color: {palette['text_faint']};
    font-size: 11px;
    font-weight: 400;
    font-style: italic;
}}
/* === Cards (session 5 v2 — refonte hiérarchie + relief) ===
   Bloc de contenu avec radius et padding plus généreux que les
   QGroupBox natifs. Utiliser via setObjectName("card") sur un QFrame.
   Léger gradient top→bottom pour donner de la profondeur sans tomber
   dans le glassmorphism — l'effet est subtil. */
QFrame#card {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {palette['bg_elev']},
        stop:1 {palette['bg_panel']}
    );
    border: 1px solid {palette['border']};
    border-radius: 12px;
}}
QFrame#card[accent="true"] {{
    border-left: 3px solid {palette['accent']};
}}
QPushButton {{
    background: {palette['bg_elev']};
    border: 1px solid {palette['border']};
    border-radius: 8px;
    padding: 6px 12px;
}}
QPushButton:hover {{
    background: {palette['bg_hover']};
}}
QPushButton:pressed {{
    background: {palette['accent_dim']};
}}
QPushButton#primary {{
    background: {palette['accent']};
    border-color: {palette['accent']};
    color: white;
}}
QPushButton#primary:hover {{
    background: {palette['accent_dim']};
}}
QPushButton#danger {{
    color: white;
    background: {palette['danger']};
    border: 1px solid {palette['danger']};
    font-weight: 600;
}}
QPushButton#danger:hover {{
    background: {palette['danger']};
    border-color: {palette['danger']};
    opacity: 0.9;
}}
QPushButton#danger:pressed {{
    background: {palette['danger']};
    border-color: {palette['danger']};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 4px;
}}
QScrollBar::handle:vertical {{
    background: {palette['border']};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {palette['text_faint']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QStatusBar {{
    background: transparent;
    color: {palette['text_faint']};
}}
QMenu {{
    background: {palette['bg_elev']};
    border: 1px solid {palette['border']};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 14px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: {palette['accent']};
    color: white;
}}
QComboBox {{
    background: {palette['bg_elev']};
    color: {palette['text']};
    border: 1px solid {palette['border']};
    border-radius: 8px;
    padding: 6px 28px 6px 12px;
    selection-background-color: {palette['accent']};
}}
QComboBox:hover {{
    background: {palette['bg_hover']};
    border-color: {palette['accent']};
}}
QComboBox:focus {{
    border: 1px solid {palette['accent']};
}}
QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 22px;
    border: 0;
    background: transparent;
}}
QComboBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {palette['text_dim']};
    margin-right: 8px;
}}
QComboBox::down-arrow:hover {{
    border-top-color: {palette['text']};
}}
QComboBox QAbstractItemView {{
    background: {palette['bg_elev']};
    color: {palette['text']};
    border: 1px solid {palette['border']};
    border-radius: 8px;
    padding: 4px;
    outline: 0;
    selection-background-color: {palette['accent']};
    selection-color: white;
}}
/* Important : background EXPLICITE sur ::item au repos, sinon macOS
   laisse passer le fond système blanc à travers (bandes claires en haut
   du popup quand on ouvre une combobox). */
QComboBox QAbstractItemView::item {{
    background: {palette['bg_elev']};
    padding: 6px 12px;
    border-radius: 4px;
    color: {palette['text']};
    min-height: 22px;
    border: 0;
}}
QComboBox QAbstractItemView::item:hover {{
    background: {palette['bg_hover']};
}}
QComboBox QAbstractItemView::item:selected {{
    background: {palette['accent']};
    color: white;
}}
/* Le QListView interne du popup peut avoir son propre fond — on le force
   aussi pour pas avoir de mismatch. */
QComboBox QListView {{
    background: {palette['bg_elev']};
    border: 0;
}}
"""


# ---------------------------------------------------------------------------
# Résolution du thème (incluant le mode "auto" qui suit macOS)
# ---------------------------------------------------------------------------

def detect_system_theme() -> str:
    """Renvoie ``"dark"`` ou ``"light"`` selon le mode système macOS.

    Lit ``defaults read -g AppleInterfaceStyle`` : retourne ``"Dark"`` si
    l'utilisateur est en mode sombre, et échoue (rc != 0) en mode clair.
    Sur les autres OS ou si la commande échoue, on retombe sur ``"dark"``
    (notre défaut historique).
    """
    try:
        result = subprocess.run(
            ["defaults", "read", "-g", "AppleInterfaceStyle"],
            capture_output=True,
            timeout=2,
        )
        if result.returncode == 0:
            out = result.stdout.decode(errors="replace").strip().lower()
            return "dark" if "dark" in out else "light"
        # rc != 0 → la clé n'existe pas → mode clair
        return "light"
    except Exception:
        return "dark"


def resolve_theme(theme: str) -> str:
    """Mappe ``"auto"`` vers le thème système ; renvoie sinon ``theme`` tel quel.

    Garantit la sortie ∈ {``"dark"``, ``"light"``}. Toute valeur inconnue
    retombe sur ``"dark"``.
    """
    t = (theme or "dark").lower()
    if t == "auto":
        return detect_system_theme()
    if t in ("dark", "light"):
        return t
    return "dark"


def active_is_dark() -> bool:
    """True si le thème effectivement actif est sombre (résout ``auto``)."""
    return resolve_theme(_active_theme) == "dark"


def current_palette(theme: Optional[str] = None, accent: Optional[str] = None) -> Dict[str, str]:
    """Renvoie la palette correspondant au thème (après résolution "auto"),
    avec l'accent éventuellement remplacé.

    Si ``theme`` / ``accent`` sont None, on utilise l'état actif (défini par
    le dernier appel à ``apply_theme()``). C'est ce qui permet aux modules
    d'appeler ``current_qss()`` sans paramètres et de toujours obtenir la
    bonne palette en fonction du choix utilisateur courant.
    """
    t = theme if theme is not None else _active_theme
    a = accent if accent is not None else _active_accent
    resolved = resolve_theme(t)
    base = PALETTE_LIGHT if resolved == "light" else PALETTE_DARK
    return _apply_accent(base, a)


def current_qss(theme: Optional[str] = None, accent: Optional[str] = None) -> str:
    """Renvoie le QSS correspondant au thème + accent.

    Sans arguments → utilise l'état actif (cf. ``apply_theme()``).
    """
    return make_qss(current_palette(theme, accent))


# ---------------------------------------------------------------------------
# État actif + apply_theme() — mutation in-place de la palette globale.
# ---------------------------------------------------------------------------
# Le problème historique : les modules font ``from .theme import PALETTE, QSS``
# au top de leur fichier. Si on remplace ``PALETTE`` par un autre dict après
# import, les modules continuent de voir l'ancien (la référence locale est
# liée à l'ancien dict).
#
# Solution : on MUTE le dict ``PALETTE`` en place (``clear()`` + ``update()``).
# Python passant les dicts par référence, tous les modules verront
# automatiquement la nouvelle palette. ``QSS`` reste une string immutable —
# pour QSS, les modules doivent appeler ``current_qss()`` au moment où ils
# stylent leurs widgets.
#
# Ces variables module-level mémorisent le choix actif pour que
# ``current_qss()`` / ``current_palette()`` sans args fonctionnent.

_active_theme: str = "dark"
_active_accent: str = "violet"


def apply_theme(theme: str = "dark", accent: str = "violet") -> str:
    """Active la palette + accent et mute ``PALETTE`` en place.

    À appeler tout en haut de ``main.py`` avant toute construction de widget.
    Renvoie le QSS correspondant — ``main.py`` peut directement l'appliquer
    via ``app.setStyleSheet(...)``.

    Pour un changement à chaud depuis Préférences, on ré-appelle cette
    fonction : la mutation est propagée à tous les modules. Les widgets
    déjà construits gardent leur QSS inline figé jusqu'au prochain
    setStyleSheet — d'où la note utilisateur « redémarrage pour rendu
    parfait ».
    """
    global _active_theme, _active_accent
    _active_theme = theme or "dark"
    _active_accent = accent or "violet"

    new_palette = current_palette(theme, accent)
    # MUTATION : on garde le même objet dict, tous les ``from .theme import
    # PALETTE`` continuent de pointer dessus.
    PALETTE.clear()
    PALETTE.update(new_palette)
    return make_qss(new_palette)


# ---------------------------------------------------------------------------
# Rétro-compat : exports historiques.
# ---------------------------------------------------------------------------
# ``PALETTE`` démarre sur la version sombre ; sera muté au démarrage par
# ``apply_theme()`` selon le choix utilisateur. ``QSS`` reste sur la version
# sombre au moment de l'import — utiliser ``current_qss()`` pour avoir le
# QSS courant.
PALETTE: Dict[str, str] = dict(PALETTE_DARK)
QSS: str = make_qss(PALETTE_DARK)
