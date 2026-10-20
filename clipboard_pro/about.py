"""Page « À propos » — version visible, comptage des items, crédits.

Ouvrable depuis le tray menu (« À propos de Klip… »). Pas de
raccourci dédié, c'est une fenêtre qu'on ouvre rarement.
"""
from __future__ import annotations

from typing import Any, Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .theme import PALETTE, QSS, current_qss


# Version exposée publiquement. À bumper à chaque release significative.
# Cohérent avec ce qui apparaît dans HANDOFF.md et le README.
APP_VERSION = "2.5.1"
APP_BUILD = "v2.5.1 — Masquage des captures"


# Achievements (Phase 6). Chaque entrée : (emoji, titre, description,
# fonction `unlocked(stats)` qui renvoie True si débloqué).
# L'ordre détermine l'affichage dans la grille.

ACHIEVEMENTS: list[tuple[str, str, str, "callable"]] = [
    ("🎉", "Premier pas",      "Capturer 1 élément",
     lambda s: s.get("lifetime_total", 0) >= 1),
    ("✂️", "Snippeteur",       "Créer 1 snippet",
     lambda s: s.get("snippets_count", 0) >= 1),
    ("⭐", "Sélectif",         "Marquer 5 favoris",
     lambda s: s.get("favs_count", 0) >= 5),
    ("💯", "Centurion",        "Capturer 100 éléments",
     lambda s: s.get("lifetime_total", 0) >= 100),
    ("🖼", "Photographe",       "Capturer 10 images",
     lambda s: s.get("images_count", 0) >= 10),
    ("🌐", "Multi-app",        "Capturer depuis 5 apps",
     lambda s: s.get("distinct_source_apps", 0) >= 5),
    ("🔥", "Fan",              "Réutiliser un même item 10 fois",
     lambda s: s.get("most_used_count", 0) >= 10),
    ("🚀", "Power user",       "Capturer 1000 éléments",
     lambda s: s.get("lifetime_total", 0) >= 1000),
]


class AboutDialog(QDialog):
    """Fenêtre À propos avec version + stats DB + crédits."""

    def __init__(
        self,
        db: Any,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("À propos de Klip")
        self.setMinimumSize(480, 660)
        self.setModal(False)
        self.setStyleSheet(current_qss() + _about_qss())
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 18)
        root.setSpacing(12)

        # --- Logo / titre ---
        logo = QLabel("✂")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet(
            f"color: {PALETTE['accent']}; font-size: 56px; "
            f"padding: 8px 0 4px 0;"
        )
        root.addWidget(logo)

        title = QLabel("Klip")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: 24px; font-weight: 700;"
        )
        root.addWidget(title)

        version = QLabel(f"Version {APP_VERSION}")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        version.setStyleSheet(
            f"color: {PALETTE['text_dim']}; font-size: 13px;"
        )
        root.addWidget(version)

        build = QLabel(APP_BUILD)
        build.setAlignment(Qt.AlignmentFlag.AlignCenter)
        build.setStyleSheet(
            f"color: {PALETTE['text_faint']}; font-size: 11px; "
            f"font-family: 'SF Mono', Menlo, monospace; "
            f"padding-bottom: 8px;"
        )
        root.addWidget(build)

        # --- Description ---
        desc = QLabel(
            "Gestionnaire de presse-papiers macOS qui capture textes, "
            "images et captures d'écran automatiquement. Recherche fuzzy, "
            "OCR local, snippets, et plein de petites attentions."
        )
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: 12px; "
            f"padding: 8px 0;"
        )
        root.addWidget(desc)

        # --- Stats (cadre) ---
        stats_frame = QFrame()
        stats_frame.setObjectName("statsBox")
        stats_lay = QVBoxLayout(stats_frame)
        stats_lay.setContentsMargins(16, 14, 16, 14)
        stats_lay.setSpacing(6)

        stats_title = QLabel("Votre historique")
        stats_title.setStyleSheet(
            f"color: {PALETTE['accent']}; font-size: 11px; "
            f"font-weight: 700; text-transform: uppercase; "
            f"letter-spacing: 1px;"
        )
        stats_lay.addWidget(stats_title)

        self.stats_lbl = QLabel("Chargement…")
        self.stats_lbl.setWordWrap(True)
        self.stats_lbl.setTextFormat(Qt.TextFormat.RichText)
        self.stats_lbl.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: 13px; "
            f"line-height: 1.5;"
        )
        stats_lay.addWidget(self.stats_lbl)

        root.addWidget(stats_frame)

        # --- Achievements (Phase 6) ---
        ach_frame = QFrame()
        ach_frame.setObjectName("statsBox")
        ach_lay = QVBoxLayout(ach_frame)
        ach_lay.setContentsMargins(16, 14, 16, 14)
        ach_lay.setSpacing(10)

        ach_title = QLabel("Réussites")
        ach_title.setStyleSheet(
            f"color: {PALETTE['accent']}; font-size: 11px; "
            f"font-weight: 700; text-transform: uppercase; "
            f"letter-spacing: 1px;"
        )
        ach_lay.addWidget(ach_title)

        self.ach_summary = QLabel("")
        self.ach_summary.setStyleSheet(
            f"color: {PALETTE['text_dim']}; font-size: 11px;"
        )
        ach_lay.addWidget(self.ach_summary)

        self.ach_grid = QGridLayout()
        self.ach_grid.setHorizontalSpacing(8)
        self.ach_grid.setVerticalSpacing(8)
        ach_lay.addLayout(self.ach_grid)

        root.addWidget(ach_frame)

        # --- Crédits / liens ---
        credits = QLabel(
            "Construit avec <b>Python 3.14</b>, <b>PyQt6</b>, "
            "<b>SQLite</b>, et le framework <b>Vision</b> de macOS.<br>"
            f"<span style=\"color:{PALETTE['text_faint']}\">"
            "Developed by <b>Yoni Sitbon</b> — Projet personnel."
            "</span>"
        )
        credits.setWordWrap(True)
        credits.setAlignment(Qt.AlignmentFlag.AlignCenter)
        credits.setTextFormat(Qt.TextFormat.RichText)
        credits.setStyleSheet(
            f"color: {PALETTE['text_dim']}; font-size: 11px; "
            f"padding-top: 4px;"
        )
        root.addWidget(credits)

        root.addStretch(1)

        # --- Bouton fermer ---
        footer = QHBoxLayout()
        footer.addStretch(1)
        close_btn = QPushButton("Fermer")
        close_btn.setObjectName("primary")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

        # Premier remplissage des stats
        self._refresh_stats()

    def _refresh_stats(self) -> None:
        """Lit les stats DB et formatte le bloc « Votre historique »."""
        try:
            stats = self.db.stats() or {}
        except Exception:
            stats = {}

        total = int(stats.get("total", 0) or 0)
        texts = int(stats.get("text_count", 0) or 0)
        images = int(stats.get("image_count", 0) or 0)
        favs = int(stats.get("favs", 0) or 0)
        snippets = int(stats.get("snippets", 0) or 0)
        size_bytes = int(stats.get("bytes", 0) or 0)
        size_mb = size_bytes / (1024 * 1024)

        # On compose en HTML pour pouvoir mettre les chiffres en gras / accent
        accent = PALETTE["accent"]
        dim = PALETTE["text_dim"]
        html = (
            f"<span style=\"color:{accent};font-weight:700;\">{total:,}</span> "
            f"élément(s) au total<br>"
            f"<span style=\"color:{dim};\">"
            f"  • {texts:,} texte(s)<br>"
            f"  • {images:,} image(s)<br>"
            f"  • {favs:,} favori(s)<br>"
            f"  • {snippets:,} snippet(s)<br>"
            f"  • {size_mb:.1f} Mo en base"
            f"</span>"
        )
        # Format français : on remplace les virgules anglo par des espaces fines
        html = html.replace(",", " ")
        self.stats_lbl.setText(html)

        # Achievements (Phase 6)
        self._refresh_achievements()

    def _refresh_achievements(self) -> None:
        """Re-peuple la grille des achievements selon les stats actuelles."""
        # Clean + reset row sizes (sinon les anciennes rowMinimumHeight
        # persistent et causent un layout faussé au prochain refresh).
        while self.ach_grid.count():
            child = self.ach_grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        try:
            ach_stats = self.db.achievement_stats() or {}
        except Exception:
            ach_stats = {}

        # Spacing généreux entre les badges + colonnes équilibrées —
        # sinon ils se touchent et donnent l'impression de superposition.
        self.ach_grid.setHorizontalSpacing(12)
        self.ach_grid.setVerticalSpacing(12)
        self.ach_grid.setColumnStretch(0, 1)
        self.ach_grid.setColumnStretch(1, 1)

        unlocked_count = 0
        for i, (emoji, title, desc, predicate) in enumerate(ACHIEVEMENTS):
            try:
                unlocked = bool(predicate(ach_stats))
            except Exception:
                unlocked = False
            if unlocked:
                unlocked_count += 1
            badge = self._build_achievement_badge(emoji, title, desc, unlocked)
            # Disposition : 2 colonnes × 4 lignes
            row, col = divmod(i, 2)
            self.ach_grid.addWidget(badge, row, col)
            # FORCE la hauteur de la row — sans ça le QGridLayout
            # collapse parfois les rows et les badges se chevauchent
            # (bug constaté sur la capture user session 6).
            self.ach_grid.setRowMinimumHeight(row, 90)

        total = len(ACHIEVEMENTS)
        self.ach_summary.setText(
            f"{unlocked_count} sur {total} débloquée(s)."
        )

    def _build_achievement_badge(
        self,
        emoji: str,
        title: str,
        desc: str,
        unlocked: bool,
    ) -> QWidget:
        """Crée un widget badge pour un achievement.

        Refonte session 6 : l'ancien layout posait l'emoji à gauche et
        empilait titre+desc à droite dans un QVBoxLayout sans hauteur
        minimum. Quand la description était longue elle se faisait
        wrapper et se chevauchait visuellement avec le titre → texte
        illisible (cf. screenshot user).

        Nouveau layout :
          ┌──────────────────────────────────────┐
          │ 🏆   Premier pas                     │ ← header (emoji + titre)
          │      Premier élément copié           │ ← desc en dessous
          └──────────────────────────────────────┘
        Hauteur min fixée, padding généreux, word-wrap activé partout.
        """
        w = QFrame()
        # Hauteur fixée pour garantir que le contenu rentre toujours et
        # que la row du QGridLayout ne se rétracte pas.
        w.setMinimumHeight(82)
        w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        # Wrapping vertical principal : header (emoji+title) puis desc
        outer = QHBoxLayout(w)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(12)

        border_color = PALETTE["accent"] if unlocked else PALETTE["border"]
        text_color = PALETTE["text"] if unlocked else PALETTE["text_faint"]
        desc_color = PALETTE["text_dim"] if unlocked else PALETTE["text_faint"]
        w.setStyleSheet(
            f"QFrame {{ background: {PALETTE['bg_elev']}; "
            f"border: 1px solid {border_color}; "
            f"border-radius: 8px; }}"
        )

        # Emoji à gauche dans un encart fixe — ça évite que la largeur
        # varie selon l'emoji (certains font 2x la taille d'un caractère).
        emoji_lbl = QLabel(emoji)
        emoji_color = PALETTE["text"] if unlocked else PALETTE["text_faint"]
        emoji_lbl.setStyleSheet(
            f"font-size: 26px; background: transparent; border: 0; "
            f"color: {emoji_color};"
        )
        emoji_lbl.setFixedWidth(36)
        emoji_lbl.setAlignment(
            Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignTop
        )
        emoji_lbl.setContentsMargins(0, 2, 0, 0)
        outer.addWidget(emoji_lbl, 0, Qt.AlignmentFlag.AlignTop)

        # Bloc texte
        text_box = QVBoxLayout()
        text_box.setSpacing(3)
        text_box.setContentsMargins(0, 0, 0, 0)

        title_lbl = QLabel(title)
        title_lbl.setWordWrap(True)
        title_lbl.setStyleSheet(
            f"color: {text_color}; font-size: 13px; font-weight: 600; "
            f"background: transparent; border: 0;"
        )
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)

        desc_lbl = QLabel(desc)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(
            f"color: {desc_color}; font-size: 11px; "
            f"background: transparent; border: 0;"
        )
        desc_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft)
        # Hauteur min pour que la description ait toujours sa place,
        # même quand elle wrappe sur 2 lignes — sans ça, Qt collapsait
        # le label et le texte se faisait masquer.
        desc_lbl.setMinimumHeight(28)

        text_box.addWidget(title_lbl)
        text_box.addWidget(desc_lbl)
        text_box.addStretch(1)
        outer.addLayout(text_box, 1)

        return w


def _about_qss() -> str:
    """Encapsulé pour ré-évaluation dynamique (cf. cheatsheet.py)."""
    return f"""
QDialog {{
    background: {PALETTE['bg']};
    color: {PALETTE['text']};
}}
QFrame#statsBox {{
    background: {PALETTE['bg_panel']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
}}
"""


def open_about(db: Any, parent: Optional[QWidget] = None) -> AboutDialog:
    """Crée/affiche la fenêtre À propos et renvoie l'instance.

    Le caller doit garder une référence (cf. ``open_preferences``,
    ``open_cheatsheet``) pour éviter le garbage collector.
    """
    win = AboutDialog(db, parent=parent)
    win.show()
    win.raise_()
    win.activateWindow()
    return win
