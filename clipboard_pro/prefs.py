"""Fenêtre Préférences de Klip — UI du §15 (cycle de vie des données).

Onglets : Général / Capture / Snippets / OCR / Confidentialité / Avancé.
Pour l'instant, seuls Confidentialité et Avancé sont câblés ; les autres
sont des placeholders qui seront remplis dans les prochaines phases.

Onglet Confidentialité — cœur de §15 :

  • Sliders discrets 7 / 30 / 60 / 90 / 180 / 365 / ∞ (jours) avec emojis
    pour la rétention texte et images, label dynamique au-dessus.
  • Bandeau « Actif depuis le JJ/MM/AAAA. Auparavant : N jours » sous
    chaque slider, alimenté par ``db.last_setting_change(key)``.
  • Bouton « Appliquer maintenant… » : aperçu via ``preview_trim_by_age()``
    puis confirmation avant ``trim_by_age()``.

Onglet Avancé : liste scrollable de ``db.list_settings_log(limit=100)``.

Le slider n'émet ``valueChanged`` qu'au release, pas pendant le drag,
pour éviter de polluer ``settings_log`` avec une ligne par cran traversé.

Conçu pour le thread Qt principal uniquement.
"""
from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .theme import PALETTE, QSS, current_qss

# Chemin canonique du LaunchAgent — utilisé pour le toggle « démarrage auto ».
LAUNCH_AGENT_LABEL = "com.user.clipboardpro"
LAUNCH_AGENT_PATH = (
    Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_LABEL}.plist"
)


# ---------------------------------------------------------------------------
# QSS additionnel — étend le thème global pour les widgets propres aux Prefs
# (QTabWidget, QGroupBox, QSlider, QMessageBox). On force aussi le fond
# sombre du QDialog pour que la fenêtre Préférences ait le même look que
# l'app principale, indépendamment du mode système (light/dark) de macOS.
# ---------------------------------------------------------------------------

def _prefs_qss_extras() -> str:
    """Encapsulé pour ré-évaluation à chaque construction.

    Indispensable pour le mode clair : avec une constante f-string évaluée
    à l'import, la palette était figée sur PALETTE_DARK pour toujours.
    """
    return f"""
QDialog {{
    background: {PALETTE['bg']};
    color: {PALETTE['text']};
}}
/* === Sidebar style macOS Sequoia ===
   Liste à gauche de la fenêtre Préférences. Fond légèrement plus
   foncé que le content (= profondeur), séparateur droit, items
   arrondis. Sur sélection : fond accent avec une fine barre violette
   plus foncée à gauche pour le rappel visuel. Hover plus marqué pour
   donner du retour tactile. */
QListWidget#prefsSidebar {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {PALETTE['bg']},
        stop:1 {PALETTE['bg_panel']}
    );
    border: 0;
    border-right: 1px solid {PALETTE['border']};
    padding: 14px 8px;
    outline: 0;
}}
QListWidget#prefsSidebar::item {{
    color: {PALETTE['text_dim']};
    padding: 8px 12px;
    border-radius: 8px;
    border-left: 3px solid transparent;
    font-size: 13px;
    font-weight: 500;
    margin: 1px 4px;
}}
QListWidget#prefsSidebar::item:hover {{
    background: {PALETTE['bg_hover']};
    color: {PALETTE['text']};
    border-left: 3px solid {PALETTE['border']};
}}
QListWidget#prefsSidebar::item:selected {{
    background: {PALETTE['accent']};
    color: white;
    border-left: 3px solid {PALETTE['accent_dim']};
    font-weight: 600;
}}
QTabWidget::pane {{
    background: {PALETTE['bg_panel']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    top: -1px;
}}
QTabBar::tab {{
    background: {PALETTE['bg_elev']};
    color: {PALETTE['text_dim']};
    padding: 8px 18px;
    margin-right: 2px;
    border: 1px solid {PALETTE['border']};
    border-bottom: 0;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
QTabBar::tab:selected {{
    background: {PALETTE['bg_panel']};
    color: {PALETTE['text']};
    font-weight: 600;
}}
QTabBar::tab:hover:!selected {{
    background: {PALETTE['bg_hover']};
    color: {PALETTE['text']};
}}
QGroupBox {{
    background: {PALETTE['bg_panel']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
    margin-top: 14px;
    padding: 16px 12px 12px 12px;
    color: {PALETTE['text']};
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    margin-left: 8px;
    color: {PALETTE['text_dim']};
    background: transparent;
}}
QSlider::groove:horizontal {{
    background: {PALETTE['bg_elev']};
    height: 6px;
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: {PALETTE['accent']};
    border-radius: 3px;
}}
QSlider::add-page:horizontal {{
    background: {PALETTE['bg_elev']};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {PALETTE['accent']};
    border: 2px solid {PALETTE['bg']};
    width: 18px;
    height: 18px;
    margin: -7px 0;
    border-radius: 11px;
}}
QSlider::handle:horizontal:hover {{
    background: {PALETTE['accent_dim']};
}}
QMessageBox {{
    background: {PALETTE['bg']};
    color: {PALETTE['text']};
}}
QMessageBox QLabel {{
    color: {PALETTE['text']};
}}
QCheckBox {{
    color: {PALETTE['text']};
    spacing: 8px;
    padding: 4px 0;
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border: 1.5px solid {PALETTE['border']};
    background: {PALETTE['bg_elev']};
    border-radius: 5px;
}}
QCheckBox::indicator:hover {{
    border-color: {PALETTE['accent']};
}}
QCheckBox::indicator:checked {{
    background: {PALETTE['accent']};
    border-color: {PALETTE['accent']};
    /* Pas d'image de coche dispo en Qt sans ressource — on triche
       avec un fond plein et la couleur de border qui change. */
}}
QSpinBox {{
    background: {PALETTE['bg_elev']};
    color: {PALETTE['text']};
    border: 1px solid {PALETTE['border']};
    border-radius: 6px;
    padding: 4px 8px;
    min-width: 70px;
    selection-background-color: {PALETTE['accent']};
}}
QSpinBox:focus {{
    border: 1px solid {PALETTE['accent']};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background: {PALETTE['bg_panel']};
    border: 0;
    width: 16px;
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
    background: {PALETTE['bg_hover']};
}}
QSpinBox::up-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid {PALETTE['text_dim']};
}}
QSpinBox::down-arrow {{
    image: none;
    width: 0;
    height: 0;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {PALETTE['text_dim']};
}}
"""


# ---------------------------------------------------------------------------
# Crans du slider de rétention.
# ---------------------------------------------------------------------------
# Convention pour la valeur en jours :
#   N > 0   → garder pendant N jours
#   -1      → « Toujours » (jamais nettoyer)
#
# Les emojis sont volontairement « ludiques » (le user a demandé le plus
# tactile/visuel) : sablier → calendrier → automne → bougie → infini.

RETENTION_STEPS: list[tuple[int, str, str]] = [
    # (jours, label humain, emoji)
    (7,   "7 jours", "⏳"),
    (30,  "30 jours", "📅"),
    (60,  "60 jours", "🗓️"),
    (90,  "90 jours", "📆"),
    (180, "6 mois",  "🍂"),
    (365, "1 an",    "🎂"),
    (-1,  "Toujours", "♾️"),
]


def _coerce_days(raw: Any) -> Optional[int]:
    """Convertit une valeur potentiellement stringifiée en int (jours).

    Les valeurs dans ``settings_log`` sont passées par ``_stringify`` côté
    settings.py — donc ``old_value`` est typiquement la chaîne ``"90"``, pas
    l'entier 90. Renvoie None si la conversion échoue.
    """
    if raw is None:
        return None
    if isinstance(raw, bool):  # avant int car bool ⊂ int
        return None
    if isinstance(raw, int):
        return raw
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _days_to_index(days: int) -> int:
    """Retourne l'index du cran correspondant, ou le cran le plus proche."""
    for i, (value, _, _) in enumerate(RETENTION_STEPS):
        if value == days:
            return i
    if days < 0:
        return len(RETENTION_STEPS) - 1  # ∞
    # Valeur exotique → cran fini le plus proche
    return min(
        range(len(RETENTION_STEPS) - 1),
        key=lambda i: abs(RETENTION_STEPS[i][0] - days),
    )


def _index_to_days(idx: int) -> int:
    return RETENTION_STEPS[idx][0]


def _fmt_date(ts: Any) -> str:
    """Timestamp unix (float ou str) → ``'JJ/MM/AAAA'``."""
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%d/%m/%Y")
    except (TypeError, ValueError, OSError):
        return "?"


def _fmt_days(raw: Any) -> str:
    """Renvoie le label humain pour une valeur de rétention (None-safe)."""
    d = _coerce_days(raw)
    if d is None:
        return str(raw) if raw is not None else "—"
    for value, label, _ in RETENTION_STEPS:
        if value == d:
            return label
    if d < 0:
        return "Toujours"
    return f"{d} jours"


# ---------------------------------------------------------------------------
# Widget : slider de rétention.
# ---------------------------------------------------------------------------


class RetentionSlider(QWidget):
    """Slider 7 crans + label dynamique + bandeau « actif depuis le … ».

    Émet ``valueChanged(int)`` uniquement quand l'utilisateur relâche le
    slider (pas pendant le drag) — évite 6 entrées dans ``settings_log``
    quand on traverse tout le rail.
    """

    valueChanged = pyqtSignal(int)

    def __init__(
        self,
        title: str,
        current_days: int,
        last_change: Optional[dict] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._build_ui()
        self.set_value(current_days)
        self.refresh_change_banner(last_change)

    # -- Construction --------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        # Spacing plus généreux pour éviter que les ticks emojis chevauchent
        # le bandeau « Actif depuis… » qui est en italic juste en dessous.
        root.setSpacing(10)

        # En-tête : titre à gauche, valeur courante (emoji + label) à droite
        header = QHBoxLayout()
        header.setSpacing(8)
        title_lbl = QLabel(self._title)
        title_lbl.setStyleSheet(
            f"color: {PALETTE['text']}; font-weight: 600;"
        )
        self._value_lbl = QLabel("—")
        self._value_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._value_lbl.setStyleSheet(
            f"color: {PALETTE['accent']}; font-weight: 700; font-size: 14px;"
        )
        header.addWidget(title_lbl)
        header.addStretch(1)
        header.addWidget(self._value_lbl)
        root.addLayout(header)

        # Le slider : 7 positions discrètes
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(len(RETENTION_STEPS) - 1)
        self._slider.setSingleStep(1)
        self._slider.setPageStep(1)
        self._slider.setTickInterval(1)
        self._slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._slider.valueChanged.connect(self._on_slider_moved)
        self._slider.sliderReleased.connect(self._on_slider_released)
        root.addWidget(self._slider)

        # Ticks emojis sous le rail (tooltip = label complet)
        ticks_row = QHBoxLayout()
        ticks_row.setContentsMargins(2, 0, 2, 0)
        ticks_row.setSpacing(0)
        for _, label, emoji in RETENTION_STEPS:
            t = QLabel(emoji)
            t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            t.setStyleSheet(f"font-size: 14px; color: {PALETTE['text_dim']};")
            t.setToolTip(label)
            ticks_row.addWidget(t, 1)
        root.addLayout(ticks_row)

        # Bandeau « Actif depuis le … »
        # Marge top en plus pour bien séparer des ticks emojis du dessus.
        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        self._banner.setStyleSheet(
            f"color: {PALETTE['text_dim']}; font-size: 11px; "
            f"font-style: italic; padding: 6px 0 0 0;"
        )
        self._banner.setMinimumHeight(20)
        root.addWidget(self._banner)

    # -- API publique --------------------------------------------------------

    def set_value(self, days: int) -> None:
        idx = _days_to_index(int(days))
        self._slider.blockSignals(True)
        self._slider.setValue(idx)
        self._slider.blockSignals(False)
        self._refresh_value_label(idx)

    def value_days(self) -> int:
        return _index_to_days(self._slider.value())

    def refresh_change_banner(self, last_change: Optional[dict]) -> None:
        """Met à jour le texte « Actif depuis le … Auparavant : … »."""
        if not last_change:
            self._banner.setText(
                "Réglage initial — aucun changement encore enregistré."
            )
            return
        ts = last_change.get("changed_at")
        old_v = last_change.get("old_value")
        new_v = last_change.get("new_value")
        date_str = _fmt_date(ts) if ts else "?"
        old_human = _fmt_days(old_v)
        new_human = _fmt_days(new_v)
        # Cas du premier lancement v3 où old == new (note "Valeur initiale
        # par défaut") : on affiche un message dédié, plus parlant.
        if (
            _coerce_days(old_v) is not None
            and _coerce_days(new_v) is not None
            and _coerce_days(old_v) == _coerce_days(new_v)
        ):
            self._banner.setText(
                f"Actif depuis le {date_str} (valeur par défaut : {new_human})."
            )
        else:
            self._banner.setText(
                f"Actif depuis le {date_str}. Auparavant : {old_human}."
            )

    # -- Slots internes ------------------------------------------------------

    def _on_slider_moved(self, idx: int) -> None:
        self._refresh_value_label(idx)

    def _on_slider_released(self) -> None:
        # On émet seulement à la fin du drag — évite le spam de settings_log
        self.valueChanged.emit(self.value_days())

    def _refresh_value_label(self, idx: int) -> None:
        _, label, emoji = RETENTION_STEPS[idx]
        self._value_lbl.setText(f"{emoji}  {label}")


# ---------------------------------------------------------------------------
# Fenêtre Préférences principale.
# ---------------------------------------------------------------------------


class PreferencesWindow(QDialog):
    """Fenêtre Préférences (QTabWidget classique).

    Arguments :
      - settings : instance de :class:`clipboard_pro.settings.Settings`.
      - db       : instance de :class:`clipboard_pro.db.Database`.
    """

    def __init__(
        self,
        settings: Any,
        db: Any,
        expander: Any = None,
        screenshot_watcher: Any = None,
        ocr_worker: Any = None,
        hotkey_manager: Any = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.db = db
        # L'expander est passé par main.py pour permettre le toggle à chaud
        # (start/stop sans relancer l'app). Peut être None si on instancie
        # depuis un contexte qui n'en dispose pas.
        self.expander = expander
        # Idem pour le screenshot watcher (toggle à chaud de la surveillance
        # du dossier de captures macOS).
        self.screenshot_watcher = screenshot_watcher
        # L'OCR worker — utilisé pour kicker le worker quand l'utilisateur
        # ré-active l'OCR ou change les langues (pour ré-OCR-iser
        # immédiatement les images en attente sans poireauter 15 s).
        self.ocr_worker = ocr_worker
        # Le HotkeyManager — utilisé par l'éditeur de raccourci global pour
        # changer le combo à chaud via set_combo().
        self.hotkey_manager = hotkey_manager

        self.setWindowTitle("Préférences — Klip")
        self.setMinimumSize(720, 720)
        self.setModal(False)

        # Applique le thème sombre global + nos surcharges. Sans ça, la
        # fenêtre prend le thème système macOS (souvent clair) et nos
        # couleurs « text_dim » deviennent illisibles sur fond clair.
        self.setStyleSheet(current_qss() + _prefs_qss_extras())

        self._build_ui()
        self._refresh_log()

    # -- Construction --------------------------------------------------------

    def _build_ui(self) -> None:
        """Layout style macOS Sequoia (Réglages Système nouvelle version) :
        sidebar à gauche avec icônes par catégorie + content stack à droite.
        Beaucoup plus moderne que des onglets en haut.
        """
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # === Body : sidebar | content ===
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # --- Sidebar ---
        sections = [
            ("🎨",  "Général"),
            ("📸",  "Capture"),
            ("✂️",  "Snippets"),
            ("🔍",  "OCR"),
            ("🔒",  "Confidentialité"),
            ("⚙️",  "Avancé"),
        ]
        self.sidebar = QListWidget()
        self.sidebar.setObjectName("prefsSidebar")
        self.sidebar.setFixedWidth(196)
        self.sidebar.setSpacing(2)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar.setFrameShape(QFrame.Shape.NoFrame)
        for emoji, name in sections:
            item = QListWidgetItem(f"  {emoji}    {name}")
            item.setSizeHint(QSize(0, 36))
            self.sidebar.addItem(item)
        body.addWidget(self.sidebar)

        # --- Content stack ---
        self.stack = QStackedWidget()
        self.stack.addWidget(self._wrap_scroll(self._build_general_tab()))
        self.stack.addWidget(self._wrap_scroll(self._build_capture_tab()))
        self.stack.addWidget(self._wrap_scroll(self._build_snippets_tab()))
        self.stack.addWidget(self._wrap_scroll(self._build_ocr_tab()))
        self.stack.addWidget(self._wrap_scroll(self._build_privacy_tab()))
        self.stack.addWidget(self._wrap_scroll(self._build_advanced_tab()))
        body.addWidget(self.stack, 1)

        # Lien sidebar <-> stack
        self.sidebar.currentRowChanged.connect(self.stack.setCurrentIndex)
        # Ouverture par défaut sur Confidentialité (index 4)
        self.sidebar.setCurrentRow(4)
        self.stack.setCurrentIndex(4)

        root.addLayout(body, 1)

        # --- Footer (séparateur + bouton Fermer) ---
        footer_sep = QFrame()
        footer_sep.setFrameShape(QFrame.Shape.HLine)
        footer_sep.setStyleSheet(
            f"background: {PALETTE['border']}; max-height: 1px; border: 0;"
        )
        root.addWidget(footer_sep)

        footer = QHBoxLayout()
        footer.setContentsMargins(14, 10, 14, 12)
        footer.addStretch(1)
        close_btn = QPushButton("Fermer")
        close_btn.setObjectName("primary")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

    def _wrap_scroll(self, content: QWidget) -> QScrollArea:
        """Wrap un onglet dans un QScrollArea pour éviter les débordements.

        Le contenu garde sa largeur (pas d'élargissement intempestif),
        scroll vertical activé si besoin, fond transparent pour respecter
        le thème de la fenêtre.
        """
        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: 0; }"
            "QScrollArea > QWidget > QWidget { background: transparent; }"
        )
        return scroll

    def _placeholder_tab(self, msg: str) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch(1)
        lbl = QLabel(msg)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            f"color: {PALETTE['text_faint']}; font-style: italic;"
        )
        lay.addWidget(lbl)
        lay.addStretch(1)
        return w

    # -- Onglet OCR ----------------------------------------------------------

    # Langues supportées par Vision (macOS). Liste curée — Vision en accepte
    # plus, mais celles-ci couvrent ~95 % des usages et sont garanties
    # disponibles depuis macOS 12+.
    OCR_LANGUAGES: list[tuple[str, str, str]] = [
        # (code ISO, drapeau emoji, label affiché)
        ("fr-FR", "🇫🇷", "Français"),
        ("en-US", "🇺🇸", "English"),
        ("es-ES", "🇪🇸", "Español"),
        ("de-DE", "🇩🇪", "Deutsch"),
        ("it-IT", "🇮🇹", "Italiano"),
        ("pt-BR", "🇧🇷", "Português (BR)"),
        ("zh-Hans", "🇨🇳", "中文 (简)"),
        ("zh-Hant", "🇹🇼", "中文 (繁)"),
        ("ja-JP", "🇯🇵", "日本語"),
        ("ko-KR", "🇰🇷", "한국어"),
        ("ru-RU", "🇷🇺", "Русский"),
        ("uk-UA", "🇺🇦", "Українська"),
    ]

    def _build_ocr_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(14)

        title = QLabel("OCR")
        title.setProperty("class", "h1")
        lay.addWidget(title)

        intro = QLabel(
            "Reconnaissance de texte dans les images via le framework "
            "<b>Vision</b> de macOS — entièrement local, gratuit, sans réseau."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setProperty("class", "body")
        intro.setStyleSheet(f"color: {PALETTE['text']};")
        lay.addWidget(intro)

        # --- Bloc Activation -------------------------------------------------
        lay.addSpacing(20)

        # ═══ Section ACTIVATION ═══
        section_enable = QLabel("Activation")
        section_enable.setProperty("class", "caps")
        lay.addWidget(section_enable)
        lay.addSpacing(10)

        enable_group = QFrame()
        enable_group.setObjectName("card")
        en_lay = QVBoxLayout(enable_group)
        en_lay.setContentsMargins(18, 16, 18, 16)
        en_lay.setSpacing(12)

        self.ocr_checkbox = QCheckBox(
            "Reconnaître automatiquement le texte des images capturées"
        )
        self.ocr_checkbox.setChecked(
            bool(self.settings.get("ocr.enabled", True))
        )
        self.ocr_checkbox.toggled.connect(self._on_ocr_toggled)
        en_lay.addWidget(self.ocr_checkbox)

        en_hint = QLabel(
            "Quand activé, chaque nouvelle image est analysée en arrière-plan "
            "(~100–500 ms par capture). Le texte extrait devient cherchable "
            "depuis la barre de recherche."
        )
        en_hint.setWordWrap(True)
        en_hint.setStyleSheet(
            f"color: {PALETTE['text_dim']}; font-size: 11px;"
        )
        en_lay.addWidget(en_hint)

        lay.addWidget(enable_group)

        # --- Bloc Langues ----------------------------------------------------
        lay.addSpacing(28)

        # ═══ Section LANGUES RECONNUES ═══
        section_lang = QLabel("Langues reconnues")
        section_lang.setProperty("class", "caps")
        lay.addWidget(section_lang)
        lay.addSpacing(10)

        lang_group = QFrame()
        lang_group.setObjectName("card")
        lg_lay = QVBoxLayout(lang_group)
        lg_lay.setContentsMargins(18, 16, 18, 16)
        lg_lay.setSpacing(8)

        lg_hint = QLabel(
            "Cochez les langues à reconnaître. Plus la liste est courte, "
            "plus l'OCR est précis et rapide. L'ordre de priorité est "
            "celui affiché ci-dessous."
        )
        lg_hint.setWordWrap(True)
        lg_hint.setStyleSheet(
            f"color: {PALETTE['text_dim']}; font-size: 11px;"
        )
        lg_lay.addWidget(lg_hint)

        # Grille de checkboxes — 2 colonnes pour économiser la verticale
        current_langs = self.settings.get(
            "ocr.languages", ["fr-FR", "en-US"]
        )
        if not isinstance(current_langs, list):
            current_langs = ["fr-FR", "en-US"]
        self.ocr_lang_checkboxes: dict[str, QCheckBox] = {}

        grid = QHBoxLayout()
        col_left = QVBoxLayout()
        col_right = QVBoxLayout()
        for i, (code, flag, label) in enumerate(self.OCR_LANGUAGES):
            cb = QCheckBox(f"{flag}  {label}")
            cb.setChecked(code in current_langs)
            cb.toggled.connect(self._on_ocr_languages_changed)
            self.ocr_lang_checkboxes[code] = cb
            (col_left if i % 2 == 0 else col_right).addWidget(cb)
        col_left.addStretch(1)
        col_right.addStretch(1)
        grid.addLayout(col_left, 1)
        grid.addLayout(col_right, 1)
        lg_lay.addLayout(grid)

        lay.addWidget(lang_group)

        # --- Bloc Stats ------------------------------------------------------
        lay.addSpacing(28)

        # ═══ Section STATISTIQUES ═══
        section_stats = QLabel("Statistiques")
        section_stats.setProperty("class", "caps")
        lay.addWidget(section_stats)
        lay.addSpacing(10)

        stats_group = QFrame()
        stats_group.setObjectName("card")
        sg_lay = QVBoxLayout(stats_group)
        sg_lay.setContentsMargins(18, 16, 18, 16)
        sg_lay.setSpacing(6)

        self.ocr_stats_lbl = QLabel("Chargement…")
        self.ocr_stats_lbl.setWordWrap(True)
        self.ocr_stats_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.ocr_stats_lbl.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: 12px;"
        )
        sg_lay.addWidget(self.ocr_stats_lbl)

        refresh_row = QHBoxLayout()
        refresh_row.addStretch(1)
        ocr_refresh_btn = QPushButton("Rafraîchir")
        ocr_refresh_btn.clicked.connect(self._refresh_ocr_stats)
        refresh_row.addWidget(ocr_refresh_btn)
        sg_lay.addLayout(refresh_row)

        lay.addWidget(stats_group)
        lay.addStretch(1)

        # Premier remplissage
        self._refresh_ocr_stats()
        return w

    def _refresh_ocr_stats(self) -> None:
        if not hasattr(self, "ocr_stats_lbl"):
            return
        try:
            stats = self.db.ocr_stats() or {}
        except Exception:
            stats = {}
        total = int(stats.get("total_images", 0))
        done = int(stats.get("with_ocr", 0))
        pending = int(stats.get("pending_ocr", 0))
        if total == 0:
            self.ocr_stats_lbl.setText(
                "Aucune image dans l'historique pour l'instant."
            )
            return

        pct = (done / total * 100) if total else 0
        text_dim = PALETTE["text_dim"]

        # On compose les phrases hors f-string pour éviter le piège des
        # apostrophes/double-quotes imbriquées dans le HTML inline.
        pending_phrase = f"{pending} image(s) en attente d'analyse"
        if pending:
            pending_phrase += " — le worker les traitera dès qu'il sera réveillé"
        pending_phrase += "."

        html = (
            f"<b>{done}</b> image(s) avec texte reconnu sur "
            f"<b>{total}</b> ({pct:.0f} %).<br>"
            f'<span style="color:{text_dim};font-size:11px;">{pending_phrase}</span>'
        )
        self.ocr_stats_lbl.setText(html)

    def _on_ocr_toggled(self, checked: bool) -> None:
        self.settings.set(
            "ocr.enabled",
            bool(checked),
            note=(
                "OCR auto activé via Préférences."
                if checked
                else "OCR auto désactivé via Préférences."
            ),
            source="prefs_ui",
        )
        # Si on réactive, on kick le worker pour qu'il traite immédiatement
        # le backlog d'images sans OCR.
        if checked and self.ocr_worker is not None:
            try:
                self.ocr_worker.kick()
            except Exception:
                pass
        self._refresh_ocr_stats()
        self._refresh_log()

    def _on_ocr_languages_changed(self, _checked: bool) -> None:
        selected = [
            code for code, cb in self.ocr_lang_checkboxes.items() if cb.isChecked()
        ]
        # Garde-fou : on impose au moins une langue.
        if not selected:
            QMessageBox.information(
                self,
                "Au moins une langue requise",
                "L'OCR a besoin d'au moins une langue. Le français a été "
                "réactivé par défaut.",
            )
            fr_cb = self.ocr_lang_checkboxes.get("fr-FR")
            if fr_cb is not None:
                fr_cb.blockSignals(True)
                fr_cb.setChecked(True)
                fr_cb.blockSignals(False)
            selected = ["fr-FR"]

        self.settings.set(
            "ocr.languages",
            selected,
            note=f"Modifié depuis Préférences : {', '.join(selected)}.",
            source="prefs_ui",
        )
        self._refresh_log()

    # -- Onglet Confidentialité ----------------------------------------------

    def _build_privacy_tab(self) -> QWidget:
        """Onglet Confidentialité — refonte hiérarchie (session 5 v2).

        Structure :
            H1 « Confidentialité »
            body intro (le pourquoi en 1 phrase)

            CAPS « RÉTENTION AUTOMATIQUE »
            body description courte
            ┌─ card Texte ──────────┐
            ├─ card Images ─────────┤
            row : hint meta · Bouton « Appliquer maintenant »

            CAPS « DÉTECTION DES SECRETS »
            ┌─ card avec checkbox + note longue ─┐
        """
        w = QWidget()
        lay = QVBoxLayout(w)
        # Espacements plus généreux : 20px de marge, 16px entre éléments
        # majeurs (24px entre sections via spacers explicites).
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(8)

        # ── En-tête de l'onglet ──────────────────────────────────────
        title = QLabel("Confidentialité")
        title.setProperty("class", "h1")
        lay.addWidget(title)

        intro = QLabel(
            "Décidez combien de temps Klip mémorise vos copies et comment "
            "il traite les secrets détectés."
        )
        intro.setWordWrap(True)
        intro.setProperty("class", "body")
        lay.addWidget(intro)

        lay.addSpacing(20)  # respire avant la 1ʳᵉ section

        # ═══════════════ Section 1 : RÉTENTION ═══════════════
        section1 = QLabel("Rétention automatique")
        section1.setProperty("class", "caps")
        lay.addWidget(section1)

        section1_desc = QLabel(
            "Klip nettoie une fois par heure les éléments plus anciens "
            "que la durée choisie. Vos favoris et snippets sont toujours "
            "préservés, peu importe leur âge."
        )
        section1_desc.setWordWrap(True)
        section1_desc.setProperty("class", "meta")
        lay.addWidget(section1_desc)

        lay.addSpacing(10)

        # Card Texte
        text_card = QFrame()
        text_card.setObjectName("card")
        text_lay = QVBoxLayout(text_card)
        text_lay.setContentsMargins(18, 16, 18, 16)
        self.text_slider = RetentionSlider(
            "Garder les textes pendant",
            int(self.settings.get("retention.text_days", 90) or 90),
            self._safe_last_change("retention.text_days"),
        )
        self.text_slider.valueChanged.connect(self._on_text_days_changed)
        text_lay.addWidget(self.text_slider)
        lay.addWidget(text_card)

        lay.addSpacing(8)

        # Card Images
        img_card = QFrame()
        img_card.setObjectName("card")
        img_lay = QVBoxLayout(img_card)
        img_lay.setContentsMargins(18, 16, 18, 16)
        self.image_slider = RetentionSlider(
            "Garder les images pendant",
            int(self.settings.get("retention.image_days", 30) or 30),
            self._safe_last_change("retention.image_days"),
        )
        self.image_slider.valueChanged.connect(self._on_image_days_changed)
        img_lay.addWidget(self.image_slider)
        lay.addWidget(img_card)

        lay.addSpacing(12)

        # Ligne d'action « Appliquer maintenant »
        action_row = QHBoxLayout()
        hint = QLabel("Nettoyage automatique chaque heure.")
        hint.setProperty("class", "faint")
        action_row.addWidget(hint)
        action_row.addStretch(1)
        apply_btn = QPushButton("Appliquer maintenant…")
        apply_btn.clicked.connect(self._on_apply_now)
        action_row.addWidget(apply_btn)
        lay.addLayout(action_row)

        lay.addSpacing(28)  # gros espace entre sections majeures

        # ═══════════════ Section 2 : SECRETS ═══════════════
        section2 = QLabel("Détection des secrets")
        section2.setProperty("class", "caps")
        lay.addWidget(section2)

        section2_desc = QLabel(
            "Votre clipboard système n'est <b>jamais</b> affecté — ⌘V colle "
            "toujours normalement. Cette option contrôle uniquement si Klip "
            "<b>mémorise</b> les secrets dans son historique cherchable.<br>"
            "Décochée, les secrets détectés (clés API, tokens…) sont "
            "enregistrés dans la catégorie dédiée <b>🔒 Secret</b>."
        )
        section2_desc.setWordWrap(True)
        section2_desc.setTextFormat(Qt.TextFormat.RichText)
        section2_desc.setProperty("class", "meta")
        lay.addWidget(section2_desc)

        lay.addSpacing(10)

        # Card secrets — accent gauche violet pour signaler une option de sécu
        secrets_card = QFrame()
        secrets_card.setObjectName("card")
        secrets_card.setProperty("accent", "true")
        sg_lay = QVBoxLayout(secrets_card)
        sg_lay.setContentsMargins(18, 16, 18, 16)
        sg_lay.setSpacing(10)

        self.secrets_checkbox = QCheckBox(
            "Ne pas enregistrer les secrets détectés"
        )
        self.secrets_checkbox.setChecked(
            bool(self.settings.get("capture.detect_secrets", True))
        )
        self.secrets_checkbox.toggled.connect(self._on_secrets_toggled)
        sg_lay.addWidget(self.secrets_checkbox)

        patterns_label = QLabel(
            "<b>Patterns reconnus</b> : OpenAI · Anthropic · GitHub · "
            "AWS · Stripe · Slack · Google API · Notion · HuggingFace · "
            "Twilio · SendGrid · Linear · NPM · JWT · clés SSH/PGP… "
            "plus une heuristique d'entropie pour les mots de passe."
        )
        patterns_label.setWordWrap(True)
        patterns_label.setTextFormat(Qt.TextFormat.RichText)
        patterns_label.setProperty("class", "faint")
        sg_lay.addWidget(patterns_label)

        # v2.5 — même carte : le pendant « captures d'écran » de l'option
        # ci-dessus. Mêmes motifs (secrets.py) + cartes bancaires et IBAN.
        self.mask_images_checkbox = QCheckBox(
            "Toujours masquer les secrets dans les captures d'écran"
        )
        self.mask_images_checkbox.setChecked(
            bool(self.settings.get("capture.mask_secrets_in_images", False))
        )
        self.mask_images_checkbox.toggled.connect(self._on_mask_images_toggled)
        sg_lay.addWidget(self.mask_images_checkbox)

        mask_label = QLabel(
            "Quand tu copies ou glisses une capture depuis Klip, les clés, "
            "tokens, cartes bancaires et IBAN visibles sont recouverts d'une "
            "barre. L'original reste dans l'historique. Pour masquer d'autres "
            "éléments à la main : ouvre la capture et clique « ✎ Éditer »."
        )
        mask_label.setWordWrap(True)
        mask_label.setProperty("class", "faint")
        sg_lay.addWidget(mask_label)

        lay.addWidget(secrets_card)
        lay.addStretch(1)
        return w

    def _on_mask_images_toggled(self, checked: bool) -> None:
        self.settings.set(
            "capture.mask_secrets_in_images",
            bool(checked),
            note=(
                "Masquage automatique des secrets dans les captures activé."
                if checked
                else "Masquage automatique des secrets dans les captures désactivé."
            ),
            source="prefs_ui",
        )
        self._refresh_log()

    def _on_secrets_toggled(self, checked: bool) -> None:
        self.settings.set(
            "capture.detect_secrets",
            bool(checked),
            note=(
                "Détection de secrets activée."
                if checked
                else "Détection de secrets DÉSACTIVÉE — tout sera enregistré."
            ),
            source="prefs_ui",
        )
        self._refresh_log()

    # -- Onglet Général ------------------------------------------------------

    def _build_general_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        # Marges identiques à Confidentialité (cohérence visuelle)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(8)

        title = QLabel("Général")
        title.setProperty("class", "h1")
        lay.addWidget(title)

        intro = QLabel("Réglages d'apparence, de démarrage automatique et de raccourci global.")
        intro.setWordWrap(True)
        intro.setProperty("class", "body")
        lay.addWidget(intro)

        lay.addSpacing(20)

        # ═══════════════ Section APPARENCE ═══════════════
        section_appearance = QLabel("Apparence")
        section_appearance.setProperty("class", "caps")
        lay.addWidget(section_appearance)
        lay.addSpacing(10)

        theme_group = QFrame()
        theme_group.setObjectName("card")
        th_lay = QVBoxLayout(theme_group)
        th_lay.setContentsMargins(18, 16, 18, 16)
        th_lay.setSpacing(12)

        theme_row = QHBoxLayout()
        theme_lbl = QLabel("Thème :")
        theme_lbl.setStyleSheet(f"color: {PALETTE['text']};")
        self.theme_combo = QComboBox()
        # Les 3 modes sont maintenant disponibles (Phase 2, session 5).
        self.theme_combo.addItem("Automatique (suit macOS)", "auto")
        self.theme_combo.addItem("Sombre", "dark")
        self.theme_combo.addItem("Clair", "light")

        cur_theme = str(self.settings.get("ui.theme", "dark"))
        idx = self.theme_combo.findData(cur_theme)
        if idx < 0:
            idx = self.theme_combo.findData("dark")
        self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        theme_row.addWidget(theme_lbl)
        theme_row.addStretch(1)
        theme_row.addWidget(self.theme_combo)
        th_lay.addLayout(theme_row)

        # --- Couleur d'accent personnalisable (Phase 6) ---
        accent_row = QHBoxLayout()
        accent_lbl = QLabel("Couleur d'accent :")
        accent_lbl.setStyleSheet(f"color: {PALETTE['text']};")
        self.accent_combo = QComboBox()
        self.accent_combo.setIconSize(QSize(14, 14))
        # Import local pour pouvoir lister les couleurs prédéfinies.
        from .theme import ACCENT_PALETTES
        for code, label, hex_accent, _hex_dim in ACCENT_PALETTES:
            # Vraie pastille colorée via QIcon (pixmap dessiné à la volée).
            # L'ancien rendu utilisait le caractère ``●`` dans le texte mais
            # il prenait la couleur du foreground (gris/blanc) → la pastille
            # ne se voyait jamais vraiment en couleur.
            self.accent_combo.addItem(
                self._make_color_icon(hex_accent), label, code
            )
        cur_accent = str(self.settings.get("ui.accent", "violet"))
        # Tolère les anciens settings sous forme hex (#7c5cff) en mappant.
        idx = self.accent_combo.findData(cur_accent)
        if idx < 0:
            # Essayer de matcher par hex
            for i, (code, _l, hex_a, _hd) in enumerate(ACCENT_PALETTES):
                if cur_accent.lower() == hex_a.lower():
                    idx = i
                    break
        if idx < 0:
            idx = 0  # défaut : Violet
        self.accent_combo.setCurrentIndex(idx)
        self.accent_combo.currentIndexChanged.connect(self._on_accent_changed)
        accent_row.addWidget(accent_lbl)
        accent_row.addStretch(1)
        accent_row.addWidget(self.accent_combo)
        th_lay.addLayout(accent_row)

        theme_note = QLabel(
            "Les changements sont <b>appliqués immédiatement</b> sur la plupart "
            "des éléments. Quelques widgets gardent leur style jusqu'au "
            "prochain redémarrage de l'app pour un rendu parfait."
        )
        theme_note.setWordWrap(True)
        theme_note.setTextFormat(Qt.TextFormat.RichText)
        theme_note.setStyleSheet(
            f"color: {PALETTE['text_dim']}; font-size: 11px;"
        )
        th_lay.addWidget(theme_note)

        lay.addWidget(theme_group)
        lay.addSpacing(28)

        # ═══════════════ Section DÉMARRAGE ═══════════════
        section_startup = QLabel("Démarrage")
        section_startup.setProperty("class", "caps")
        lay.addWidget(section_startup)
        lay.addSpacing(10)

        startup_group = QFrame()
        startup_group.setObjectName("card")
        st_lay = QVBoxLayout(startup_group)
        st_lay.setContentsMargins(18, 16, 18, 16)
        st_lay.setSpacing(12)

        self.startup_checkbox = QCheckBox(
            "Lancer Klip automatiquement à la connexion"
        )
        # On lit l'état RÉEL depuis launchctl, pas un setting. Sinon
        # divergence possible entre le fichier de prefs et l'état système.
        self.startup_checkbox.setChecked(self._is_launch_agent_loaded())
        # Si le LaunchAgent n'est pas installé du tout, on désactive la
        # checkbox et on propose à la place un bouton d'installation.
        self.startup_checkbox.setEnabled(LAUNCH_AGENT_PATH.exists())
        self.startup_checkbox.toggled.connect(self._on_startup_toggled)
        st_lay.addWidget(self.startup_checkbox)

        # Zone d'information / action selon la présence du LaunchAgent
        self.startup_info_widget = QWidget()
        info_lay = QVBoxLayout(self.startup_info_widget)
        info_lay.setContentsMargins(0, 0, 0, 0)
        info_lay.setSpacing(8)

        if LAUNCH_AGENT_PATH.exists():
            startup_info = QLabel(
                f"Géré via le LaunchAgent <code>{LAUNCH_AGENT_LABEL}</code>. "
                f"Le toggle ci-dessus appelle <code>launchctl load/unload -w</code>."
            )
            startup_info.setWordWrap(True)
            startup_info.setTextFormat(Qt.TextFormat.RichText)
            startup_info.setStyleSheet(
                f"color: {PALETTE['text_faint']}; font-size: 11px;"
            )
            info_lay.addWidget(startup_info)
        else:
            # Bandeau d'avertissement + bouton d'installation directe.
            warn = QLabel(
                "<b>⚠ Aucun LaunchAgent n'est installé sur ce profil macOS.</b><br>"
                "Cliquez sur le bouton ci-dessous pour créer le fichier "
                f"<code>{LAUNCH_AGENT_PATH.name}</code> dans "
                "<code>~/Library/LaunchAgents/</code> et l'activer."
            )
            warn.setWordWrap(True)
            warn.setTextFormat(Qt.TextFormat.RichText)
            warn.setStyleSheet(
                f"color: {PALETTE['text']}; font-size: 12px; "
                f"background: {PALETTE['bg_elev']}; "
                f"border: 1px solid {PALETTE['border']}; "
                f"border-left: 3px solid #fbbf24; "
                f"border-radius: 6px; padding: 12px;"
            )
            info_lay.addWidget(warn)

            install_row = QHBoxLayout()
            install_row.addStretch(1)
            install_btn = QPushButton("Installer le démarrage automatique…")
            install_btn.setObjectName("primary")
            install_btn.clicked.connect(self._install_launch_agent)
            install_row.addWidget(install_btn)
            info_lay.addLayout(install_row)

        st_lay.addWidget(self.startup_info_widget)

        lay.addWidget(startup_group)

        # --- Bloc Raccourci global -------------------------------------------
        lay.addSpacing(28)

        # ═══════════════ Section RACCOURCI GLOBAL ═══════════════
        section_hotkey = QLabel("Raccourci global")
        section_hotkey.setProperty("class", "caps")
        lay.addWidget(section_hotkey)
        lay.addSpacing(10)

        hotkey_group = QFrame()
        hotkey_group.setObjectName("card")
        hk_lay = QVBoxLayout(hotkey_group)
        hk_lay.setContentsMargins(18, 16, 18, 16)
        hk_lay.setSpacing(12)

        current_combo = str(self.settings.get("hotkey.combo", "<alt>+<cmd>+v"))
        human = self._humanize_combo(current_combo)

        # Form layout pour aligner proprement les labels et les contrôles
        # (label fixe à gauche, contrôle qui prend le reste).
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        # Ligne 1 : combo actuel (badge monospace)
        self.hotkey_value = QLabel(human)
        self.hotkey_value.setStyleSheet(
            f"color: {PALETTE['text']}; "
            f"background: {PALETTE['bg_elev']}; "
            f"border: 1px solid {PALETTE['border']}; "
            f"border-radius: 4px; padding: 4px 12px; "
            f"font-family: 'SF Mono', Menlo, monospace; "
            f"font-weight: 700; letter-spacing: 1px;"
        )
        self.hotkey_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.hotkey_value.setMaximumWidth(120)
        # Wrap dans un container avec stretch pour aligner à gauche
        cur_wrap = QWidget()
        cur_wrap_l = QHBoxLayout(cur_wrap)
        cur_wrap_l.setContentsMargins(0, 0, 0, 0)
        cur_wrap_l.addWidget(self.hotkey_value)
        cur_wrap_l.addStretch(1)
        form.addRow("Combo actuel :", cur_wrap)

        # Ligne 2 : éditeur + bouton Appliquer SUR LA MÊME LIGNE
        edit_wrap = QWidget()
        edit_wrap_l = QHBoxLayout(edit_wrap)
        edit_wrap_l.setContentsMargins(0, 0, 0, 0)
        edit_wrap_l.setSpacing(6)

        self.hotkey_edit = QKeySequenceEdit()
        qt_seq = self._pynput_to_qt(current_combo)
        if qt_seq:
            self.hotkey_edit.setKeySequence(QKeySequence(qt_seq))
        try:
            self.hotkey_edit.setMaximumSequenceLength(1)
        except AttributeError:
            pass
        edit_wrap_l.addWidget(self.hotkey_edit, 1)

        self.hotkey_apply_btn = QPushButton("Appliquer")
        self.hotkey_apply_btn.setObjectName("primary")
        self.hotkey_apply_btn.clicked.connect(self._on_hotkey_apply)
        edit_wrap_l.addWidget(self.hotkey_apply_btn)

        form.addRow("Nouveau combo :", edit_wrap)
        hk_lay.addLayout(form)

        # Ligne 3 : bouton « Réinitialiser » aligné avec les fields
        reset_row = QHBoxLayout()
        reset_row.addStretch(1)
        reset_btn = QPushButton("Réinitialiser (⌥⌘V)")
        reset_btn.clicked.connect(self._on_hotkey_reset)
        reset_row.addWidget(reset_btn)
        hk_lay.addLayout(reset_row)

        hotkey_note = QLabel(
            "Cliquez dans le champ puis tapez votre combo (ex. ⌥⌘V, "
            "⌃⇧Espace, ⌥⌘C…). Appliqué à chaud — sans relancer l'app."
        )
        hotkey_note.setWordWrap(True)
        hotkey_note.setProperty("class", "faint")
        hk_lay.addWidget(hotkey_note)

        lay.addWidget(hotkey_group)

        lay.addStretch(1)
        return w

    # -- Helpers Général -----------------------------------------------------

    @staticmethod
    def _make_color_icon(hex_color: str, size: int = 14) -> QIcon:
        """Dessine une pastille circulaire de la couleur donnée → QIcon.

        Utilisé pour le combo « Couleur d'accent » : avant on plaçait un
        caractère ``●`` dans le texte, mais il prenait la couleur du
        foreground (gris/blanc selon le thème) — la pastille n'était donc
        jamais en couleur. Avec un QIcon dessiné on a une vraie pastille.
        """
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            p.setBrush(QColor(hex_color))
            p.setPen(Qt.PenStyle.NoPen)
            # Petit inset d'1 px pour que les bords du cercle ne soient pas
            # mangés par l'anti-aliasing du bord du pixmap.
            p.drawEllipse(1, 1, size - 2, size - 2)
        finally:
            p.end()
        return QIcon(pix)

    @staticmethod
    def _humanize_combo(pynput_combo: str) -> str:
        """Format pynput (ex. ``<alt>+<cmd>+v``) → texte humain (⌥⌘V)."""
        s = pynput_combo
        # Modifiers
        s = s.replace("<alt>", "⌥").replace("<cmd>", "⌘")
        s = s.replace("<ctrl>", "⌃").replace("<shift>", "⇧")
        # Touches spéciales
        s = s.replace("<space>", "Espace").replace("<enter>", "↵")
        s = s.replace("<tab>", "⇥").replace("<esc>", "⎋")
        # Séparateurs et casse
        s = s.replace("+", "")
        # Met en majuscule les lettres restantes (le 'v' final → 'V')
        return s.upper() if len(s) <= 6 else s

    @staticmethod
    def _qt_to_pynput(qt_str: str) -> Optional[str]:
        """Convertit un combo Qt (ex. 'Alt+Ctrl+V') vers le format pynput.

        Subtilité macOS : Qt swap par défaut Ctrl ↔ Meta sur Mac, donc
        quand l'utilisateur tape ⌘V, Qt rapporte "Ctrl+V" (et ⌃V réel
        donnerait "Meta+V"). On compose donc :
          Qt "Ctrl" → ⌘ → pynput "<cmd>"
          Qt "Meta" → ⌃ → pynput "<ctrl>"
          Qt "Alt"  → ⌥ → pynput "<alt>"
          Qt "Shift" → ⇧ → pynput "<shift>"
        Renvoie None si la chaîne est vide ou ne contient pas de touche
        non-modificateur (combo invalide pour pynput).
        """
        if not qt_str:
            return None
        # On garde uniquement le premier combo si plusieurs séparés par ", "
        first = qt_str.split(", ")[0].strip()
        if not first:
            return None
        parts = first.split("+")
        out_parts: list[str] = []
        has_regular_key = False
        for p in parts:
            p = p.strip()
            if not p:
                continue
            p_lower = p.lower()
            if p_lower == "ctrl":
                out_parts.append("<cmd>")
            elif p_lower == "meta":
                out_parts.append("<ctrl>")
            elif p_lower == "alt":
                out_parts.append("<alt>")
            elif p_lower == "shift":
                out_parts.append("<shift>")
            elif len(p) == 1:
                out_parts.append(p.lower())
                has_regular_key = True
            else:
                # Touche spéciale : F1, Space, Return, Tab, Esc, …
                # pynput accepte <f1>, <space>, <enter>, <tab>, <esc>
                mapping = {
                    "space": "<space>",
                    "return": "<enter>",
                    "enter": "<enter>",
                    "tab": "<tab>",
                    "esc": "<esc>",
                    "escape": "<esc>",
                    "backspace": "<backspace>",
                    "delete": "<delete>",
                }
                key = mapping.get(p_lower, f"<{p_lower}>")
                out_parts.append(key)
                has_regular_key = True
        if not has_regular_key:
            return None
        return "+".join(out_parts)

    @staticmethod
    def _pynput_to_qt(pynput_str: str) -> Optional[str]:
        """Conversion inverse pour pré-remplir le QKeySequenceEdit."""
        if not pynput_str:
            return None
        s = pynput_str
        s = s.replace("<cmd>", "Ctrl")
        s = s.replace("<ctrl>", "Meta")
        s = s.replace("<alt>", "Alt")
        s = s.replace("<shift>", "Shift")
        s = s.replace("<space>", "Space")
        s = s.replace("<enter>", "Return")
        s = s.replace("<tab>", "Tab")
        s = s.replace("<esc>", "Esc")
        # Lettres uniques en majuscule
        parts = s.split("+")
        return "+".join(p.upper() if len(p) == 1 else p for p in parts)

    @staticmethod
    def _is_launch_agent_loaded() -> bool:
        """True si ``launchctl list`` connaît notre Label."""
        try:
            result = subprocess.run(
                ["launchctl", "list", LAUNCH_AGENT_LABEL],
                capture_output=True,
                timeout=2,
            )
            return result.returncode == 0
        except Exception:
            return False

    # -- Slots Général -------------------------------------------------------

    def _apply_theme_and_accent(self) -> None:
        """Applique à chaud le QSS combiné theme + accent + force le repaint.

        Pourquoi le force-repaint : la mutation de ``PALETTE`` met à jour
        les *valeurs* dans le dict mais les widgets déjà peints (ex. la
        liste de l'historique avec son delegate custom qui dessine en
        ``PALETTE["accent"]``) ne se redessinent pas spontanément quand
        le dict change. Sans le ``update()`` forcé partout, l'item
        sélectionné garde la couleur violette de l'ancien accent jusqu'à
        ce que l'utilisateur clique ailleurs.
        """
        theme = str(self.settings.get("ui.theme", "dark") or "dark")
        accent = str(self.settings.get("ui.accent", "violet") or "violet")
        try:
            from PyQt6.QtWidgets import QApplication, QListView, QAbstractItemView
            from .theme import apply_theme
            qss = apply_theme(theme, accent)
            app = QApplication.instance()
            if app is None:
                return
            app.setStyleSheet(qss)

            # Force un repaint complet sur toutes les fenêtres ouvertes.
            for w in app.topLevelWidgets():
                try:
                    # Re-poke le style pour que QSS soit ré-évalué partout
                    w.style().unpolish(w)
                    w.style().polish(w)
                    w.update()
                    # Les QListView/QListWidget ont un viewport interne qui
                    # ne se redessine que via viewport().update() — sans ça
                    # le delegate continue de dessiner avec l'ancien accent.
                    for lv in w.findChildren(QAbstractItemView):
                        lv.viewport().update()
                    # Les autres widgets avec stylesheet inline ne se
                    # rafraîchissent pas tout seuls non plus — on demande
                    # un repolish général à tout l'arbre.
                    from PyQt6.QtWidgets import QWidget
                    for child in w.findChildren(QWidget):
                        child.style().unpolish(child)
                        child.style().polish(child)
                except Exception:
                    pass

            # Notifie aussi la MainWindow si elle expose un hook
            # ``reapply_theme()`` (cf. ui.py). Ça lui permet de
            # rebuilder ses widgets stylés inline (preview_image,
            # edit_banner) avec les nouvelles couleurs.
            for w in app.topLevelWidgets():
                hook = getattr(w, "reapply_theme", None)
                if callable(hook):
                    try:
                        hook()
                    except Exception:
                        pass
        except Exception:
            # Pas critique — au pire, c'est le prochain démarrage qui applique.
            pass

    def _on_theme_changed(self, _idx: int) -> None:
        theme = str(self.theme_combo.currentData() or "dark")
        self.settings.set(
            "ui.theme",
            theme,
            note=f"Modifié depuis Préférences : {theme}.",
            source="prefs_ui",
        )
        self._apply_theme_and_accent()
        self._refresh_log()

    def _on_accent_changed(self, _idx: int) -> None:
        accent = str(self.accent_combo.currentData() or "violet")
        self.settings.set(
            "ui.accent",
            accent,
            note=f"Couleur d'accent modifiée : {accent}.",
            source="prefs_ui",
        )
        self._apply_theme_and_accent()
        self._refresh_log()

    def _generate_launch_agent_plist(self) -> str:
        """Génère le contenu XML d'un LaunchAgent pour cette installation.

        On utilise le `sys.executable` courant (souvent le Python du venv qui
        fait tourner l'app) et le dossier qui contient le module
        `clipboard_pro` pour reconstituer un plist fonctionnel — la même
        forme que `install.sh` produit.
        """
        import sys
        import clipboard_pro as _cp
        app_dir = Path(_cp.__file__).resolve().parent.parent
        home = Path.home()

        # Deux modes :
        #   • App empaquetée (py2app pose sys.frozen) → on lance DIRECTEMENT
        #     le binaire du bundle .app (ex. /Applications/Klip.app/Contents/
        #     MacOS/Klip). C'est crucial : `open -a` rendrait la main aussitôt
        #     et KeepAlive bouclerait ; le binaire MacOS reste au premier plan
        #     donc launchd le surveille correctement. Lancer `python -m
        #     clipboard_pro.main` depuis un venv de dev démarrerait une AUTRE
        #     instance fragile au lieu de l'app installée.
        #   • Dev (lancé via venv) → fallback `python -m clipboard_pro.main`.
        program_args: list[str] = []
        env_pythonpath: Optional[str] = None
        if getattr(sys, "frozen", False):
            exe = Path(sys.executable).resolve()
            bundle = next(
                (p for p in (exe, *exe.parents) if p.suffix == ".app"), None
            )
            if bundle is not None:
                binary = bundle / "Contents" / "MacOS" / bundle.stem
                program_args = [str(binary)]
        if not program_args:
            program_args = [sys.executable or "/usr/bin/python3",
                            "-m", "clipboard_pro.main"]
            env_pythonpath = str(app_dir)

        args_xml = "\n".join(f"    <string>{a}</string>" for a in program_args)
        env_xml = (
            "  <key>EnvironmentVariables</key>\n"
            "  <dict>\n"
            f"    <key>PYTHONPATH</key>      <string>{env_pythonpath}</string>\n"
            "  </dict>\n"
        ) if env_pythonpath else ""

        # Pas de f-string sur tout le bloc (lisibilité + zéro risque d'apostrophe).
        # KeepAlive = {SuccessfulExit: false} : relance UNIQUEMENT après un
        # crash (sortie non nulle). Un « Quitter » volontaire (exit 0) ne
        # relance pas — l'utilisateur garde le contrôle. RunAtLoad relance à
        # chaque ouverture de session (le vrai correctif du « se ferme quand
        # je ferme ma session »).
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n'
            '<dict>\n'
            f'  <key>Label</key>             <string>{LAUNCH_AGENT_LABEL}</string>\n'
            '  <key>ProgramArguments</key>\n'
            '  <array>\n'
            f'{args_xml}\n'
            '  </array>\n'
            f'  <key>WorkingDirectory</key>  <string>{app_dir}</string>\n'
            '  <key>RunAtLoad</key>         <true/>\n'
            '  <key>KeepAlive</key>\n'
            '  <dict>\n'
            '    <key>SuccessfulExit</key>  <false/>\n'
            '  </dict>\n'
            '  <key>ProcessType</key>       <string>Interactive</string>\n'
            f'  <key>StandardOutPath</key>   <string>{home}/.clipboard_pro/stdout.log</string>\n'
            f'  <key>StandardErrorPath</key> <string>{home}/.clipboard_pro/stderr.log</string>\n'
            f'{env_xml}'
            '</dict>\n'
            '</plist>\n'
        )

    def _install_launch_agent(self) -> None:
        """Crée le plist + le charge via launchctl. Refresh l'UI ensuite."""
        # Confirmation préalable car ça touche au système de démarrage.
        plist_content = self._generate_launch_agent_plist()
        confirm = QMessageBox.question(
            self,
            "Installer le démarrage automatique ?",
            f"Cela va :\n\n"
            f"  • Créer {LAUNCH_AGENT_PATH}\n"
            f"  • Activer le démarrage de Klip à chaque connexion\n"
            f"  • Démarrer une nouvelle instance maintenant\n\n"
            f"Continuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        # 1) Créer le dossier + écrire le plist
        try:
            LAUNCH_AGENT_PATH.parent.mkdir(parents=True, exist_ok=True)
            LAUNCH_AGENT_PATH.write_text(plist_content, encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(
                self,
                "Échec de l'écriture",
                f"Impossible d'écrire {LAUNCH_AGENT_PATH} :\n{e}",
            )
            return

        # 2) Charger via launchctl
        try:
            result = subprocess.run(
                ["launchctl", "load", "-w", str(LAUNCH_AGENT_PATH)],
                capture_output=True,
                timeout=5,
            )
        except Exception as e:
            QMessageBox.warning(
                self,
                "Plist créé mais non chargé",
                f"Le fichier a été créé, mais launchctl a échoué :\n{e}\n\n"
                f"Vous pouvez le charger manuellement avec :\n"
                f"launchctl load -w {LAUNCH_AGENT_PATH}",
            )
            return

        if result.returncode != 0:
            err = (result.stderr.decode(errors="replace")
                   + result.stdout.decode(errors="replace")).strip()
            if "service already loaded" not in err.lower():
                QMessageBox.warning(
                    self,
                    "Plist créé mais launchctl a renvoyé une erreur",
                    f"Le fichier est en place, mais :\n{err or '(silencieux)'}\n\n"
                    f"Si l'app n'apparaît pas comme démarrée, redémarrez "
                    f"votre Mac ou lancez :\n"
                    f"launchctl load -w {LAUNCH_AGENT_PATH}",
                )
                return

        # 3) Trace dans settings_log + message de succès
        self.settings.set(
            "startup.enabled",
            True,
            note="LaunchAgent installé depuis Préférences.",
            source="prefs_ui",
        )

        QMessageBox.information(
            self,
            "C'est fait !",
            "Le démarrage automatique est activé. "
            "Klip se lancera à chaque connexion.\n\n"
            "Note : une seconde instance de l'app vient probablement "
            "de démarrer en parallèle. C'est normal — quittez l'instance "
            "actuelle (si elle est sans LaunchAgent) pour ne garder que celle "
            "lancée par macOS.",
        )

        # 4) Mettre à jour la checkbox visuellement, sans déclencher de toggle
        self.startup_checkbox.blockSignals(True)
        self.startup_checkbox.setChecked(True)
        self.startup_checkbox.setEnabled(True)
        self.startup_checkbox.blockSignals(False)
        self._refresh_log()

    def _apply_new_hotkey(self, new_combo: str) -> bool:
        """Applique un nouveau combo via le HotkeyManager + sauvegarde le setting.

        Renvoie True si OK, False sinon (l'erreur a déjà été affichée).
        """
        if self.hotkey_manager is None:
            QMessageBox.warning(
                self,
                "HotkeyManager indisponible",
                "Impossible de changer le raccourci à chaud — le manager "
                "n'a pas été passé à cette fenêtre. La valeur sera quand "
                "même sauvegardée et appliquée au prochain démarrage."
            )
            self.settings.set(
                "hotkey.combo",
                new_combo,
                note=f"Modifié via Préférences : {new_combo}.",
                source="prefs_ui",
            )
            self._refresh_log()
            return True

        old_combo = str(self.settings.get("hotkey.combo", "<alt>+<cmd>+v"))
        # set_combo gère le rollback en interne si install() échoue.
        ok = bool(self.hotkey_manager.set_combo(new_combo))
        if not ok:
            err = getattr(self.hotkey_manager, "error", None) or "raison inconnue"
            QMessageBox.warning(
                self,
                "Combo non appliqué",
                f"Impossible d'installer le combo « {self._humanize_combo(new_combo)} » :\n\n"
                f"{err}\n\n"
                f"L'ancien combo a été restauré.",
            )
            return False

        # Succès : on persiste + on rafraîchit l'affichage humain
        self.settings.set(
            "hotkey.combo",
            new_combo,
            note=f"Combo {old_combo} → {new_combo} appliqué à chaud.",
            source="prefs_ui",
        )
        self.hotkey_value.setText(self._humanize_combo(new_combo))
        self._refresh_log()
        return True

    def _on_hotkey_apply(self) -> None:
        seq = self.hotkey_edit.keySequence()
        qt_str = seq.toString(QKeySequence.SequenceFormat.PortableText)
        if not qt_str:
            QMessageBox.information(
                self,
                "Combo vide",
                "Cliquez d'abord dans le champ « Nouveau combo » et tapez "
                "votre raccourci, puis cliquez sur Appliquer.",
            )
            return

        pynput_combo = self._qt_to_pynput(qt_str)
        if not pynput_combo:
            QMessageBox.warning(
                self,
                "Combo invalide",
                f"« {qt_str} » n'est pas un raccourci valide. "
                "Il doit comporter au moins un modificateur (⌥, ⌘, ⌃, ⇧) "
                "et une touche normale.",
            )
            return

        self._apply_new_hotkey(pynput_combo)

    def _on_hotkey_reset(self) -> None:
        default_combo = "<alt>+<cmd>+v"
        if self._apply_new_hotkey(default_combo):
            # Resynchronise aussi l'éditeur pour refléter la réinitialisation
            self.hotkey_edit.setKeySequence(
                QKeySequence(self._pynput_to_qt(default_combo) or "")
            )

    def _on_startup_toggled(self, checked: bool) -> None:
        if not LAUNCH_AGENT_PATH.exists():
            QMessageBox.warning(
                self,
                "LaunchAgent introuvable",
                "Aucun LaunchAgent n'est installé.\n\n"
                "Lancez le script `install.sh` depuis le dossier de l'app "
                "pour activer le démarrage automatique.",
            )
            self.startup_checkbox.blockSignals(True)
            self.startup_checkbox.setChecked(False)
            self.startup_checkbox.blockSignals(False)
            return

        # `-w` persiste l'état (enabled/disabled) entre redémarrages.
        cmd = "load" if checked else "unload"
        try:
            result = subprocess.run(
                ["launchctl", cmd, "-w", str(LAUNCH_AGENT_PATH)],
                capture_output=True,
                timeout=5,
            )
        except Exception as e:
            QMessageBox.warning(
                self,
                "Erreur",
                f"Impossible d'exécuter launchctl :\n{e}",
            )
            self.startup_checkbox.blockSignals(True)
            self.startup_checkbox.setChecked(not checked)
            self.startup_checkbox.blockSignals(False)
            return

        # `launchctl load` sur un agent déjà chargé renvoie une erreur
        # (et inversement pour unload). On reflète ça dans l'UI sans planter,
        # mais on tolère le cas où c'est juste "déjà dans cet état".
        if result.returncode != 0:
            err = (result.stderr.decode(errors="replace")
                   + result.stdout.decode(errors="replace"))
            already_loaded = "service already loaded" in err.lower()
            not_loaded = (
                "could not find specified service" in err.lower()
                or "no such file or directory" in err.lower()
            )
            if not (already_loaded or not_loaded):
                QMessageBox.warning(
                    self,
                    "Erreur launchctl",
                    f"launchctl {cmd} a échoué :\n{err.strip() or '(silencieux)'}",
                )
                self.startup_checkbox.blockSignals(True)
                self.startup_checkbox.setChecked(not checked)
                self.startup_checkbox.blockSignals(False)
                return

        # Trace dans settings_log (clé pseudo, source prefs_ui) pour l'historique.
        self.settings.set(
            "startup.enabled",
            bool(checked),
            note=(
                "Démarrage auto activé via Préférences."
                if checked
                else "Démarrage auto désactivé via Préférences."
            ),
            source="prefs_ui",
        )
        self._refresh_log()

    # -- Onglet Capture ------------------------------------------------------

    def _build_capture_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(14)

        title = QLabel("Capture")
        title.setProperty("class", "h1")
        lay.addWidget(title)

        intro = QLabel(
            "Réglages de la capture automatique du presse-papiers et "
            "des captures d'écran."
        )
        intro.setWordWrap(True)
        intro.setProperty("class", "body")
        lay.addWidget(intro)

        lay.addSpacing(20)

        # ═══ Section TAILLES MAXIMUM ═══
        section_size = QLabel("Tailles maximum")
        section_size.setProperty("class", "caps")
        lay.addWidget(section_size)
        lay.addSpacing(10)

        size_group = QFrame()
        size_group.setObjectName("card")
        sg_lay = QVBoxLayout(size_group)
        sg_lay.setContentsMargins(18, 16, 18, 16)
        sg_lay.setSpacing(12)

        sg_desc = QLabel(
            "Les éléments plus volumineux que ces limites sont ignorés "
            "silencieusement (avec une notification dans la barre de menu). "
            "Cela évite de capturer accidentellement un fichier .log de plusieurs Mo."
        )
        sg_desc.setWordWrap(True)
        sg_desc.setStyleSheet(
            f"color: {PALETTE['text_dim']}; font-size: 11px;"
        )
        sg_lay.addWidget(sg_desc)

        # Texte
        text_row = QHBoxLayout()
        text_lbl = QLabel("Texte maximum :")
        text_lbl.setStyleSheet(f"color: {PALETTE['text']};")
        self.text_max_spin = QSpinBox()
        self.text_max_spin.setRange(1, 100)
        self.text_max_spin.setSuffix("  Mo")
        cur_text_mb = max(1, int(
            self.settings.get("capture.max_text_bytes", 5 * 1024 * 1024) // (1024 * 1024)
        ))
        self.text_max_spin.setValue(cur_text_mb)
        self.text_max_spin.editingFinished.connect(self._on_text_max_changed)
        text_row.addWidget(text_lbl)
        text_row.addStretch(1)
        text_row.addWidget(self.text_max_spin)
        sg_lay.addLayout(text_row)

        # Image
        img_row = QHBoxLayout()
        img_lbl = QLabel("Image maximum :")
        img_lbl.setStyleSheet(f"color: {PALETTE['text']};")
        self.image_max_spin = QSpinBox()
        self.image_max_spin.setRange(5, 500)
        self.image_max_spin.setSingleStep(5)
        self.image_max_spin.setSuffix("  Mo")
        cur_image_mb = max(5, int(
            self.settings.get("capture.max_image_bytes", 50 * 1024 * 1024) // (1024 * 1024)
        ))
        self.image_max_spin.setValue(cur_image_mb)
        self.image_max_spin.editingFinished.connect(self._on_image_max_changed)
        img_row.addWidget(img_lbl)
        img_row.addStretch(1)
        img_row.addWidget(self.image_max_spin)
        sg_lay.addLayout(img_row)

        lay.addWidget(size_group)

        # --- Bloc Captures d'écran --------------------------------------------
        lay.addSpacing(28)

        # ═══ Section CAPTURES D'ÉCRAN ═══
        section_screen = QLabel("Captures d'écran  (⌘⇧3 / ⌘⇧4 / ⌘⇧5)")
        section_screen.setProperty("class", "caps")
        lay.addWidget(section_screen)
        lay.addSpacing(10)

        screen_group = QFrame()
        screen_group.setObjectName("card")
        sc_lay = QVBoxLayout(screen_group)
        sc_lay.setContentsMargins(18, 16, 18, 16)
        sc_lay.setSpacing(12)

        self.screen_checkbox = QCheckBox(
            "Ajouter automatiquement les captures d'écran à l'historique"
        )
        self.screen_checkbox.setChecked(
            bool(self.settings.get("screenshot_watcher.enabled", True))
        )
        self.screen_checkbox.toggled.connect(self._on_screenshot_toggled)
        sc_lay.addWidget(self.screen_checkbox)

        # Affichage du dossier surveillé (read-only)
        folder_path = "—"
        if self.screenshot_watcher is not None:
            try:
                folder_path = str(self.screenshot_watcher.folder)
            except Exception:
                folder_path = "—"

        folder_row = QHBoxLayout()
        folder_lbl = QLabel("Dossier surveillé :")
        folder_lbl.setStyleSheet(f"color: {PALETTE['text_dim']};")
        self.folder_value = QLabel(folder_path)
        self.folder_value.setStyleSheet(
            f"color: {PALETTE['text']}; "
            f"background: {PALETTE['bg_elev']}; "
            f"border: 1px solid {PALETTE['border']}; "
            f"border-radius: 4px; padding: 4px 8px; "
            f"font-family: 'SF Mono', Menlo, monospace; font-size: 11px;"
        )
        self.folder_value.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        folder_row.addWidget(folder_lbl)
        folder_row.addWidget(self.folder_value, 1)
        sc_lay.addLayout(folder_row)

        folder_hint = QLabel(
            "Le dossier est piloté par macOS. Pour le changer : ouvrez "
            "l'outil Capture d'écran (<b>⌘⇧5</b>) → Options → "
            "« Enregistrer dans ». Le watcher prendra le nouveau dossier "
            "au prochain démarrage de l'app."
        )
        folder_hint.setWordWrap(True)
        folder_hint.setTextFormat(Qt.TextFormat.RichText)
        folder_hint.setStyleSheet(
            f"color: {PALETTE['text_faint']}; font-size: 11px;"
        )
        sc_lay.addWidget(folder_hint)

        # Astuce contre le piège macOS de la vignette flottante :
        # si l'utilisateur drag la vignette dans une autre app avant qu'elle
        # disparaisse, macOS n'écrit JAMAIS le fichier sur disque — donc
        # notre watcher ne peut rien voir. La parade : utiliser Ctrl+...
        # qui envoie la capture directement au presse-papiers, où notre
        # ClipboardWatcher (poll NSPasteboard à 150 ms) la chope instantanément.
        capture_combo = str(self.settings.get("capture.hotkey", "<alt>+<cmd>+<shift>+s") or "")
        capture_human = self._humanize_combo(capture_combo) if capture_combo else "(désactivé)"
        tip = QLabel(
            "<b>💡 Capture instantanée :</b><br>"
            f"Notre raccourci dédié <b>{capture_human}</b> lance une "
            "capture interactive qui va <b>directement dans le presse-papiers</b>, "
            "sans fichier sur le Bureau ni vignette macOS. Klip la récupère en "
            "moins de 200 ms. Modifiable via <code>capture.hotkey</code> "
            "dans <code>~/.clipboard_pro/settings.json</code>.<br><br>"
            "<b>Alternative natif macOS</b> : ajoutez <b>Ctrl</b> à un "
            "raccourci système — <b>Ctrl+⌘⇧4</b> ou <b>Ctrl+⌘⇧3</b>. "
            "Même résultat, mais sans configuration à faire."
        )
        tip.setWordWrap(True)
        tip.setTextFormat(Qt.TextFormat.RichText)
        tip.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: 12px; "
            f"background: {PALETTE['bg_elev']}; "
            f"border: 1px solid {PALETTE['border']}; "
            f"border-left: 3px solid {PALETTE['accent']}; "
            f"border-radius: 6px; padding: 12px;"
        )
        sc_lay.addWidget(tip)

        lay.addWidget(screen_group)

        lay.addStretch(1)
        return w

    def _on_text_max_changed(self) -> None:
        mb = int(self.text_max_spin.value())
        new_bytes = mb * 1024 * 1024
        self.settings.set(
            "capture.max_text_bytes",
            new_bytes,
            note=f"Modifié depuis Préférences : {mb} Mo.",
            source="prefs_ui",
        )
        self._refresh_log()

    def _on_image_max_changed(self) -> None:
        mb = int(self.image_max_spin.value())
        new_bytes = mb * 1024 * 1024
        self.settings.set(
            "capture.max_image_bytes",
            new_bytes,
            note=f"Modifié depuis Préférences : {mb} Mo.",
            source="prefs_ui",
        )
        self._refresh_log()

    def _on_screenshot_toggled(self, checked: bool) -> None:
        """Toggle à chaud le watcher de captures d'écran."""
        if self.screenshot_watcher is not None:
            try:
                if checked:
                    self.screenshot_watcher.start()
                else:
                    self.screenshot_watcher.stop()
            except Exception as e:
                QMessageBox.warning(
                    self,
                    "Erreur",
                    f"Impossible de modifier la surveillance :\n{e}",
                )
                # Revert visuel
                self.screen_checkbox.blockSignals(True)
                self.screen_checkbox.setChecked(not checked)
                self.screen_checkbox.blockSignals(False)
                return

        self.settings.set(
            "screenshot_watcher.enabled",
            bool(checked),
            note=(
                "Activée depuis Préférences."
                if checked
                else "Désactivée depuis Préférences."
            ),
            source="prefs_ui",
        )
        self._refresh_log()

    # -- Onglet Snippets -----------------------------------------------------

    def _build_snippets_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(14)

        title = QLabel("Snippets")
        title.setProperty("class", "h1")
        lay.addWidget(title)

        intro = QLabel(
            "Les snippets permettent de remplacer automatiquement <code>;nom</code> "
            "par leur contenu, dès que vous tapez un espace ou une ponctuation après."
        )
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.TextFormat.RichText)
        intro.setProperty("class", "body")
        lay.addWidget(intro)

        # --- Bloc Activation ---------------------------------------------------
        lay.addSpacing(20)

        # ═══ Section EXPANSION AUTOMATIQUE ═══
        section_expander = QLabel("Expansion automatique  (opt-in)")
        section_expander.setProperty("class", "caps")
        lay.addWidget(section_expander)
        lay.addSpacing(10)

        expander_group = QFrame()
        expander_group.setObjectName("card")
        expander_group.setProperty("accent", "true")
        eg_lay = QVBoxLayout(expander_group)
        eg_lay.setContentsMargins(18, 16, 18, 16)
        eg_lay.setSpacing(12)

        self.expander_checkbox = QCheckBox(
            "Activer l'expansion automatique ;nom → contenu"
        )
        self.expander_checkbox.setChecked(
            bool(self.settings.get("expander.enabled", False))
        )
        self.expander_checkbox.toggled.connect(self._on_expander_toggled)
        eg_lay.addWidget(self.expander_checkbox)

        # Bandeau d'avertissement encadré — visible et lisible
        warning = QLabel(
            "<b>⚠️ À savoir avant d'activer :</b><br>"
            "Cette fonctionnalité écoute toutes vos frappes clavier "
            "<b>de manière globale, dans toutes les applications</b>, pour "
            "détecter les séquences <code>;nom</code>.<br><br>"
            "Aucune donnée n'est envoyée ni stockée — la détection est "
            "purement locale.<br><br>"
            "Nécessite la permission « <b>Surveillance des entrées</b> » dans "
            "<i>Réglages Système → Confidentialité et sécurité → "
            "Surveillance des entrées</i>."
        )
        warning.setWordWrap(True)
        warning.setTextFormat(Qt.TextFormat.RichText)
        warning.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: 12px; "
            f"background: {PALETTE['bg_elev']}; "
            f"border: 1px solid {PALETTE['border']}; "
            f"border-left: 3px solid #fbbf24; "
            f"border-radius: 6px; padding: 12px;"
        )
        eg_lay.addWidget(warning)

        # Délimiteurs (read-only info)
        delim_hint = QLabel(
            "Caractères qui déclenchent l'expansion : "
            "espace, tab, retour à la ligne, et ponctuation "
            "<code>. , ; : ! ? )</code>."
        )
        delim_hint.setWordWrap(True)
        delim_hint.setTextFormat(Qt.TextFormat.RichText)
        delim_hint.setStyleSheet(
            f"color: {PALETTE['text_faint']}; font-size: 11px;"
        )
        eg_lay.addWidget(delim_hint)

        lay.addWidget(expander_group)

        # --- Bloc Snippets existants ------------------------------------------
        lay.addSpacing(28)

        # ═══ Section SNIPPETS EXISTANTS ═══
        section_list = QLabel("Snippets existants")
        section_list.setProperty("class", "caps")
        lay.addWidget(section_list)
        lay.addSpacing(10)

        list_group = QFrame()
        list_group.setObjectName("card")
        lg_lay = QVBoxLayout(list_group)
        lg_lay.setContentsMargins(18, 16, 18, 16)
        lg_lay.setSpacing(8)

        self.snippets_list = QListWidget()
        self.snippets_list.setAlternatingRowColors(False)
        lg_lay.addWidget(self.snippets_list, 1)

        create_hint = QLabel(
            "Pour créer un snippet : ouvrez l'historique avec ⌥⌘V, "
            "sélectionnez un texte et appuyez sur ⌘S."
        )
        create_hint.setWordWrap(True)
        create_hint.setStyleSheet(
            f"color: {PALETTE['text_faint']}; font-size: 11px;"
        )
        lg_lay.addWidget(create_hint)

        lay.addWidget(list_group, 1)

        # Premier remplissage
        self._refresh_snippets_list()
        return w

    def _refresh_snippets_list(self) -> None:
        if not hasattr(self, "snippets_list"):
            return
        self.snippets_list.clear()
        try:
            snippets = self.db.list_snippets() or []
        except Exception:
            snippets = []
        if not snippets:
            item = QListWidgetItem("Aucun snippet pour l'instant.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.snippets_list.addItem(item)
            return
        for s in snippets:
            text = (s.text or "").replace("\n", " ↵ ")
            preview = text[:90] + ("…" if len(text) > 90 else "")
            line = f";{s.snippet_name}   →   {preview}"
            self.snippets_list.addItem(QListWidgetItem(line))

    def _confirm_expander_activation(self) -> bool:
        """Dialog explicite avant d'activer l'écoute clavier globale."""
        msg = (
            "L'expansion automatique nécessite d'écouter le clavier global "
            "dans toutes les applications.\n\n"
            "✓ Aucune donnée n'est envoyée ou stockée\n"
            "✓ La détection est purement locale\n"
            "✓ Vous pouvez désactiver à tout moment\n\n"
            "Activer l'expansion maintenant ?"
        )
        confirm = QMessageBox.question(
            self,
            "Activer l'expansion automatique ?",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return confirm == QMessageBox.StandardButton.Yes

    def _on_expander_toggled(self, checked: bool) -> None:
        """Toggle l'expander à chaud (sans relancer l'app)."""
        # Activation : confirmation explicite + start() de l'expander
        if checked:
            if not self._confirm_expander_activation():
                # Refus → on remet la checkbox à OFF sans déclencher de signal
                self.expander_checkbox.blockSignals(True)
                self.expander_checkbox.setChecked(False)
                self.expander_checkbox.blockSignals(False)
                return

            if self.expander is not None:
                ok = bool(self.expander.start())
                if not ok:
                    QMessageBox.warning(
                        self,
                        "Activation impossible",
                        "Impossible de démarrer l'expander. Vérifiez que la "
                        "permission « Surveillance des entrées » est accordée "
                        "à Klip dans Réglages Système → "
                        "Confidentialité et sécurité, puis réessayez.",
                    )
                    self.expander_checkbox.blockSignals(True)
                    self.expander_checkbox.setChecked(False)
                    self.expander_checkbox.blockSignals(False)
                    return
        else:
            # Désactivation : pas de confirmation, stop immédiat
            if self.expander is not None:
                try:
                    self.expander.stop()
                except Exception:
                    pass

        # Persistance du setting (log auto dans settings_log)
        self.settings.set(
            "expander.enabled",
            bool(checked),
            note=(
                "Activé depuis Préférences."
                if checked
                else "Désactivé depuis Préférences."
            ),
            source="prefs_ui",
        )
        self._refresh_log()

    # -- Onglet Avancé -------------------------------------------------------

    def _build_advanced_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(14, 18, 14, 14)
        lay.setSpacing(8)

        title = QLabel("Avancé")
        title.setProperty("class", "h1")
        lay.addWidget(title)

        subtitle = QLabel("Historique des changements de paramètres")
        subtitle.setProperty("class", "h2")
        lay.addWidget(subtitle)

        desc = QLabel(
            "Toutes les modifications de préférences sont enregistrées dans "
            "la base, avec la date, l'ancienne et la nouvelle valeur."
        )
        desc.setWordWrap(True)
        desc.setProperty("class", "meta")
        lay.addWidget(desc)

        self.log_list = QListWidget()
        self.log_list.setAlternatingRowColors(False)
        # Le QSS global gère déjà le look (background, border, etc.) ;
        # on ne surcharge plus ici pour rester cohérent.
        lay.addWidget(self.log_list, 1)

        refresh_row = QHBoxLayout()
        refresh_row.addStretch(1)
        refresh_btn = QPushButton("Rafraîchir")
        refresh_btn.clicked.connect(self._refresh_log)
        refresh_row.addWidget(refresh_btn)
        lay.addLayout(refresh_row)

        return w

    # -- Helpers backend -----------------------------------------------------

    def _safe_last_change(self, key: str) -> Optional[dict]:
        try:
            return self.db.last_setting_change(key)
        except Exception:
            return None

    def _safe_list_log(self, limit: int = 100) -> list[dict]:
        try:
            rows = self.db.list_settings_log(limit=limit)
            return list(rows) if rows else []
        except Exception:
            return []

    # -- Slots ---------------------------------------------------------------

    def _on_text_days_changed(self, days: int) -> None:
        self.settings.set(
            "retention.text_days",
            int(days),
            note="Modifié depuis la fenêtre Préférences (curseur texte).",
            source="prefs_ui",
        )
        self.text_slider.refresh_change_banner(
            self._safe_last_change("retention.text_days")
        )
        self._refresh_log()

    def _on_image_days_changed(self, days: int) -> None:
        self.settings.set(
            "retention.image_days",
            int(days),
            note="Modifié depuis la fenêtre Préférences (curseur images).",
            source="prefs_ui",
        )
        self.image_slider.refresh_change_banner(
            self._safe_last_change("retention.image_days")
        )
        self._refresh_log()

    def _on_apply_now(self) -> None:
        text_days = int(self.settings.get("retention.text_days", 90) or 90)
        image_days = int(self.settings.get("retention.image_days", 30) or 30)

        # `trim_by_age` ignore les valeurs négatives (∞) — on les passe en None
        # pour rester cohérent avec l'API. Pas d'effet net.
        kw_text = text_days if text_days >= 0 else None
        kw_image = image_days if image_days >= 0 else None

        try:
            preview = self.db.preview_trim_by_age(
                max_text_days=kw_text,
                max_image_days=kw_image,
            )
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Aperçu impossible :\n{e}")
            return

        n_text = int(preview.get("text", 0) or 0)
        n_image = int(preview.get("image", 0) or 0)
        total = n_text + n_image

        if total == 0:
            QMessageBox.information(
                self,
                "Rien à supprimer",
                "Aucun élément ne dépasse les durées de rétention actuelles.",
            )
            return

        text_human = _fmt_days(text_days)
        image_human = _fmt_days(image_days)
        msg = (
            f"Cela va supprimer définitivement :\n\n"
            f"   • {n_text} texte(s) plus vieux que {text_human}\n"
            f"   • {n_image} image(s) plus vieille(s) que {image_human}\n\n"
            f"Total : {total} élément(s). Continuer ?"
        )
        confirm = QMessageBox.question(
            self,
            "Confirmer la suppression",
            msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        try:
            deleted = self.db.trim_by_age(
                max_text_days=kw_text,
                max_image_days=kw_image,
            )
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Le nettoyage a échoué :\n{e}")
            return

        n_deleted = int(deleted.get("text", 0) or 0) + int(deleted.get("image", 0) or 0)
        QMessageBox.information(
            self,
            "Nettoyage terminé",
            f"{n_deleted} élément(s) supprimé(s).",
        )
        self._refresh_log()

    # -- Rendu de la liste settings_log --------------------------------------

    def _refresh_log(self) -> None:
        """Reconstruit l'historique des changements en VRAI tableau aligné.

        Refonte session 6 : on remplace les items texte (qui ne s'aligne
        jamais correctement en colonnes — espaces variables selon la
        font) par des widgets custom posés dans le QListWidget. Chaque
        ligne = QHBoxLayout(heure | clé | ancien → nouveau | note).
        Largeurs fixes pour les 3 premières colonnes → vraie grille.
        Les headers de section (— AUJOURD'HUI —) restent en pleine
        largeur, en accent.
        """
        if not hasattr(self, "log_list"):
            return
        self.log_list.clear()
        rows = self._safe_list_log(limit=100)
        if not rows:
            item = QListWidgetItem("Aucun changement enregistré pour l'instant.")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.log_list.addItem(item)
            return

        today_dt = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        today_ts = today_dt.timestamp()
        yesterday_ts = today_ts - 86400

        def _bucket(ts: float) -> str:
            if ts >= today_ts:
                return "Aujourd'hui"
            if ts >= yesterday_ts:
                return "Hier"
            if ts >= today_ts - 7 * 86400:
                return datetime.fromtimestamp(ts).strftime("%A %d %B").capitalize()
            return datetime.fromtimestamp(ts).strftime("%B %Y").capitalize()

        last_bucket = None
        for row in rows:
            try:
                ts_f = float(row.get("changed_at") or 0)
                key = row.get("key") or "?"
                old_v = row.get("old_value")
                new_v = row.get("new_value")
                note = row.get("note") or ""
                bucket = _bucket(ts_f)

                if bucket != last_bucket:
                    self._add_log_section_header(bucket)
                    last_bucket = bucket

                when = (
                    datetime.fromtimestamp(ts_f).strftime("%H:%M")
                    if ts_f else "—"
                )
                if key in ("retention.text_days", "retention.image_days"):
                    old_h = _fmt_days(old_v)
                    new_h = _fmt_days(new_v)
                else:
                    old_h = str(old_v) if old_v is not None else "—"
                    new_h = str(new_v) if new_v is not None else "—"

                self._add_log_row(when, key, old_h, new_h, note)
            except (TypeError, ValueError):
                continue

    def _add_log_section_header(self, label: str) -> None:
        """Ajoute un header de section style "— AUJOURD'HUI —"."""
        item = QListWidgetItem()
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(8, 14, 8, 6)
        h.setSpacing(0)
        lbl = QLabel(f"— {label.upper()} —")
        lbl.setStyleSheet(
            f"color: {PALETTE['accent']}; font-size: 10px; "
            f"font-weight: 700; letter-spacing: 1.5px; "
            f"background: transparent; border: 0;"
        )
        h.addWidget(lbl)
        h.addStretch(1)
        item.setSizeHint(w.sizeHint())
        self.log_list.addItem(item)
        self.log_list.setItemWidget(item, w)

    def _add_log_row(
        self, when: str, key: str, old_v: str, new_v: str, note: str
    ) -> None:
        """Ajoute une ligne de tableau (heure | clé | ancien→nouveau | note)."""
        item = QListWidgetItem()
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(12, 4, 12, 4)
        h.setSpacing(14)

        # Colonne 1 : heure (mono, largeur fixe)
        when_lbl = QLabel(when)
        when_lbl.setFixedWidth(46)
        when_lbl.setStyleSheet(
            f"color: {PALETTE['text_faint']}; font-size: 12px; "
            f"font-family: 'SF Mono', Menlo, monospace; "
            f"background: transparent; border: 0;"
        )
        h.addWidget(when_lbl)

        # Colonne 2 : clé (mono, largeur fixe alignée)
        key_lbl = QLabel(key)
        key_lbl.setFixedWidth(190)
        key_lbl.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: 12px; "
            f"font-family: 'SF Mono', Menlo, monospace; font-weight: 600; "
            f"background: transparent; border: 0;"
        )
        key_lbl.setToolTip(key)
        h.addWidget(key_lbl)

        # Colonne 3 : ancien → nouveau (3 sous-éléments)
        change_wrap = QHBoxLayout()
        change_wrap.setSpacing(6)
        change_wrap.setContentsMargins(0, 0, 0, 0)
        old_lbl = QLabel(old_v)
        old_lbl.setStyleSheet(
            f"color: {PALETTE['text_dim']}; font-size: 12px; "
            f"background: transparent; border: 0;"
        )
        arrow_lbl = QLabel("→")
        arrow_lbl.setStyleSheet(
            f"color: {PALETTE['accent']}; font-size: 13px; font-weight: 700; "
            f"background: transparent; border: 0;"
        )
        new_lbl = QLabel(new_v)
        new_lbl.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: 12px; font-weight: 600; "
            f"background: transparent; border: 0;"
        )
        change_wrap.addWidget(old_lbl)
        change_wrap.addWidget(arrow_lbl)
        change_wrap.addWidget(new_lbl)
        change_wrap_widget = QWidget()
        change_wrap_widget.setLayout(change_wrap)
        change_wrap_widget.setMinimumWidth(170)
        h.addWidget(change_wrap_widget)

        # Colonne 4 : note (texte faible, flex)
        if note:
            note_lbl = QLabel(f"— {note}")
            note_lbl.setStyleSheet(
                f"color: {PALETTE['text_faint']}; font-size: 11px; "
                f"background: transparent; border: 0;"
            )
            note_lbl.setWordWrap(False)
            h.addWidget(note_lbl, 1)
        else:
            h.addStretch(1)

        item.setSizeHint(w.sizeHint())
        self.log_list.addItem(item)
        self.log_list.setItemWidget(item, w)


# ---------------------------------------------------------------------------
# Helper d'ouverture — exporté pour main.py.
# ---------------------------------------------------------------------------


def open_preferences(
    settings: Any,
    db: Any,
    expander: Any = None,
    screenshot_watcher: Any = None,
    ocr_worker: Any = None,
    hotkey_manager: Any = None,
    parent: Optional[QWidget] = None,
) -> PreferencesWindow:
    """Crée/affiche la fenêtre Préférences et renvoie l'instance.

    Note : pas de singleton ici. Le caller (main.py) doit garder une
    référence à l'instance (par ex. ``self._prefs_win = open_preferences(…)``)
    pour éviter que la fenêtre disparaisse à cause du garbage collector
    Python.

    `expander`, `screenshot_watcher`, `ocr_worker` et `hotkey_manager`
    (optionnels) sont passés pour permettre le toggle / la modification
    à chaud depuis les onglets correspondants sans relancer l'app.
    """
    win = PreferencesWindow(
        settings,
        db,
        expander=expander,
        screenshot_watcher=screenshot_watcher,
        ocr_worker=ocr_worker,
        hotkey_manager=hotkey_manager,
        parent=parent,
    )
    win.show()
    win.raise_()
    win.activateWindow()
    return win
