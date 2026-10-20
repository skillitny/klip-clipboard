"""Cheatsheet ⌘? — popup listant tous les raccourcis de l'app.

Ouvrable via :
  • Tray menu → « Raccourcis… »
  • ⌘? depuis la MainWindow (l'historique)

Affiche un tableau organisé en sections : global / historique / actions
sur item / préférences. Lecture seule, juste pédagogique.
"""
from __future__ import annotations

from typing import Optional

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


# Structure des raccourcis : liste de (section, [(combo, description), ...])
# Les combos utilisent les caractères macOS standard (⌘ ⌥ ⇧ ⌃ ⇥ ↵ ⌫ ⎋).
# La description doit être courte (≤ 60 chars) pour rester lisible.

SHORTCUTS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Global (depuis n'importe où)",
        [
            ("⌥⌘V",  "Ouvrir l'historique du presse-papiers"),
            ("⌘⇧3", "Capture d'écran (écran entier) — ajout auto à l'historique"),
            ("⌘⇧4", "Capture d'écran (zone) — ajout auto à l'historique"),
            ("Ctrl+⌘⇧3 / 4", "Capture directe vers presse-papiers (instantané)"),
            ("⌘⇧5", "Outil Capture d'écran macOS (configure le dossier)"),
        ],
    ),
    (
        "Dans la fenêtre d'historique",
        [
            ("↑ / ↓",  "Naviguer dans la liste"),
            ("↵",      "Copier l'item sélectionné et coller dans l'app précédente"),
            ("⌘1 – ⌘9", "Copier directement l'un des 9 premiers items"),
            ("⌘P",     "Épingler / désépingler en favori"),
            ("⌘S",     "Transformer en snippet ;nom"),
            ("⌫",      "Supprimer l'item (sauf favoris et snippets)"),
            ("⎋",      "Fermer la fenêtre"),
            ("⌘L",     "Focus sur la barre de recherche"),
        ],
    ),
    (
        "Filtres et catégories",
        [
            ("Tout / Texte / Image / Favoris / Snippets",
             "Filtres rapides en haut de la fenêtre"),
            ("Aujourd'hui / Cette semaine",
             "Filtres temporels"),
            ("Toutes apps ▾", "Filtrer par application source"),
        ],
    ),
    (
        "Préférences",
        [
            ("⌘,", "Ouvrir la fenêtre Préférences (6 onglets)"),
            ("⌘?", "Ouvrir cette aide"),
        ],
    ),
    (
        "Snippets (si activés dans Préférences → Snippets)",
        [
            (";nom + espace", "Remplace ;nom par le contenu du snippet"),
            (";nom + . , ; : ! ? )",
             "Pareil — n'importe quelle ponctuation déclenche"),
        ],
    ),
]


class CheatsheetDialog(QDialog):
    """Popup d'aide listant tous les raccourcis disponibles."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Raccourcis — Klip")
        self.setMinimumSize(560, 540)
        self.setModal(False)
        # current_qss() + _cheatsheet_qss() : tous deux re-évalués à
        # l'ouverture pour refléter le thème (clair/sombre) et l'accent
        # courants, sans dépendre de la version sombre figée à l'import.
        self.setStyleSheet(current_qss() + _cheatsheet_qss())
        self._build_ui()

    def _build_ui(self) -> None:
        # Conteneur racine + scroll area : la cheatsheet contient
        # beaucoup de sections, sans scroll les badges débordent.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Scroll area pour gérer les écrans plus petits — sans elle,
        # certaines sections en bas étaient tronquées.
        from PyQt6.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setObjectName("cheatScroll")

        body = QWidget()
        body.setObjectName("cheatBody")
        root = QVBoxLayout(body)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(18)

        # En-tête : titre h1 + sous-titre meta — même grammaire typo
        # que Préférences pour la cohérence visuelle.
        title = QLabel("Raccourcis clavier")
        title.setProperty("class", "h1")
        root.addWidget(title)

        subtitle = QLabel(
            "Tous les raccourcis de Klip — gardez cette fenêtre "
            "ouverte le temps de les mémoriser."
        )
        subtitle.setWordWrap(True)
        subtitle.setProperty("class", "meta")
        root.addWidget(subtitle)

        # Sections
        for section_title, items in SHORTCUTS:
            root.addWidget(self._build_section(section_title, items))

        root.addStretch(1)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        # Pied : bouton Fermer dans une bande dédiée pour éviter
        # qu'il scrolle avec le contenu.
        footer_wrap = QWidget()
        footer_wrap.setObjectName("cheatFooter")
        footer = QHBoxLayout(footer_wrap)
        footer.setContentsMargins(20, 12, 20, 14)
        footer.addStretch(1)
        close_btn = QPushButton("Fermer")
        close_btn.setObjectName("primary")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        outer.addWidget(footer_wrap)

    def _build_section(
        self, title: str, items: list[tuple[str, str]]
    ) -> QWidget:
        """Une section = titre + tableau (combo | description).

        Refactor session 5 : on utilise un QGridLayout dans un QFrame
        plutôt que QWidget imbriqués. L'ancien code mettait
        ``QWidget { border-bottom: … }`` sur chaque row, ce qui se
        propageait aux QLabel enfants (badges + descriptions) et leur
        ajoutait des traits parasites — rendu illisible. Avec QGridLayout
        chaque cellule est indépendante.
        """
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        # Titre de section (caps = uppercase + accent + letter-spacing)
        title_lbl = QLabel(title)
        title_lbl.setProperty("class", "caps")
        title_lbl.setStyleSheet("padding-top: 4px;")  # juste l'espacement
        lay.addWidget(title_lbl)

        # Tableau combo / description — QGridLayout 2 colonnes :
        #   col 0 : badge combo (largeur fixe minimum 140 px pour aligner
        #           proprement les descriptions, comme un vrai tableau).
        #   col 1 : description, étirée.
        rows_frame = QFrame()
        rows_frame.setObjectName("shortcutsBox")
        grid = QGridLayout(rows_frame)
        grid.setContentsMargins(14, 12, 14, 12)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(12)

        for i, (combo, desc) in enumerate(items):
            combo_lbl = QLabel(combo)
            combo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            # On utilise un objectName pour styler via QSS (cohérent avec
            # le reste de l'app, et change avec le thème).
            combo_lbl.setObjectName("comboBadge")
            combo_lbl.setMinimumWidth(120)
            combo_lbl.setSizePolicy(
                QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
            )

            desc_lbl = QLabel(desc)
            desc_lbl.setWordWrap(True)
            desc_lbl.setProperty("class", "body")
            desc_lbl.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )

            grid.addWidget(combo_lbl, i, 0,
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            grid.addWidget(desc_lbl, i, 1)

        # La 2e colonne (description) prend tout l'espace restant.
        grid.setColumnStretch(0, 0)
        grid.setColumnStretch(1, 1)

        lay.addWidget(rows_frame)
        return w


# QSS dédié à la cheatsheet — encadre les blocs de raccourcis dans une boîte
# subtile, comme un mini-tableau. Encapsulé dans une fonction pour que la
# f-string soit ré-évaluée à chaque ouverture avec la palette courante
# (sinon en mode clair, le QSS resterait figé sur la palette sombre).
def _cheatsheet_qss() -> str:
    """QSS dédié à la cheatsheet — refondu en session 6.

    Donne le même langage visuel que Préférences : fond global, body
    intérieur sans bordure visible, sections en cards avec relief
    subtil, badges de raccourcis en pastilles arrondies (mono).
    """
    return f"""
QDialog {{
    background: {PALETTE['bg']};
    color: {PALETTE['text']};
}}
QWidget#cheatBody, QScrollArea#cheatScroll, QScrollArea#cheatScroll > QWidget,
QScrollArea#cheatScroll > QWidget > QWidget {{
    background: {PALETTE['bg']};
}}
QFrame#shortcutsBox {{
    background: {PALETTE['bg_panel']};
    border: 1px solid {PALETTE['border']};
    border-radius: 10px;
}}
QLabel#comboBadge {{
    color: {PALETTE['text']};
    background: {PALETTE['bg_elev']};
    border: 1px solid {PALETTE['border']};
    border-radius: 6px;
    padding: 6px 14px;
    font-family: 'SF Mono', Menlo, Monaco, monospace;
    font-weight: 600;
    font-size: 13px;
    letter-spacing: 0.3px;
}}
QWidget#cheatFooter {{
    background: {PALETTE['bg_panel']};
    border-top: 1px solid {PALETTE['border']};
}}
"""


def open_cheatsheet(parent: Optional[QWidget] = None) -> CheatsheetDialog:
    """Crée/affiche la cheatsheet et renvoie l'instance.

    Comme pour la fenêtre Préférences : le caller doit garder une référence
    Python à l'instance (ex. ``self._cheat_win = open_cheatsheet(…)``)
    pour éviter le garbage collector.
    """
    win = CheatsheetDialog(parent=parent)
    win.show()
    win.raise_()
    win.activateWindow()
    return win
