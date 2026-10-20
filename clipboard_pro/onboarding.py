"""Onboarding visuel premier lancement.

Affiche au tout premier demarrage de l'app (quand le setting ``onboarded``
est False). 6 ecrans navigables qui presentent les features cles + les
permissions macOS necessaires.

A la fin (ou si l'utilisateur clique "Passer"), ``onboarded`` passe a
True et le dialog ne reapparait plus aux lancements suivants.

Design : grosses cartes pedagogiques avec emoji + titre + description.
Navigation par dots en bas + boutons Precedent / Suivant. Tres inspire
des onboardings macOS modernes (Things, Linear, Raycast).
"""
from __future__ import annotations

import subprocess
from typing import Any, Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .theme import PALETTE, QSS, current_qss


# Les ecrans de l'onboarding.
# Chaque entree : (emoji_hero, titre, sous-titre, description html, [action]).
# `action` est optionnel : tuple (label_bouton, url_systempreferences).
# Le emoji est affiche en tres gros (96px) au centre, comme un logo.

SCREENS: list[tuple] = [
    (
        "✂",  # ciseaux
        "Bienvenue dans Klip",
        "Tout ce que vous copiez, a portee de doigt.",
        "Klip est un gestionnaire de presse-papiers moderne pour macOS. "
        "Il capture <b>automatiquement</b> tout ce que vous copiez "
        "- texte, images, captures d'ecran - et vous permet d'y revenir "
        "a tout moment.<br><br>"
        "<span style='font-size:11px;'>Concu pour les workflows repetitifs : "
        "redaction, code, design, support, ...</span>",
    ),
    (
        "\U0001F4CB",  # clipboard
        "Capture automatique",
        "Aucune action de votre part - Klip ecoute en permanence.",
        "Des que vous appuyez sur <b>Cmd+C</b> (texte ou image), Klip l'ajoute "
        "en haut de votre historique. Toutes les 150 ms, sans CPU.<br><br>"
        "Les <b>captures d'ecran</b> (Cmd+Shift+3 / Cmd+Shift+4) sont aussi "
        "detectees automatiquement et ajoutees.<br><br>"
        "<span style='font-size:11px;'>Astuce : ajoutez <b>Ctrl</b> au "
        "raccourci (Ctrl+Cmd+Shift+4) pour envoyer la capture directement au "
        "presse-papiers, sans attendre la vignette macOS.</span>",
    ),
    (
        "Opt+Cmd+V",
        "Le raccourci magique",
        "Appuyez sur Option+Cmd+V depuis n'importe ou - votre historique apparait.",
        "C'est le raccourci principal de Klip. Une fois la fenetre ouverte :"
        "<br><br>"
        "- <b>Fleches haut/bas</b> pour naviguer dans la liste<br>"
        "- <b>Entree</b> pour copier et coller dans l'app precedente<br>"
        "- <b>Cmd+1-9</b> pour copier les 9 premiers items directement<br>"
        "- <b>Espace</b> pour apercu Quick Look sur image<br>"
        "- <b>Glisser un item</b> vers Finder/Mail/Slack pour l'exporter",
    ),
    (
        "\U0001F510",  # padlock
        "Une derniere autorisation",
        "Klip a besoin d'une permission pour intercepter le raccourci global.",
        "Pour que <b>Option+Cmd+V</b> et l'expander de snippets fonctionnent, "
        "macOS demande de cocher Klip dans :<br><br>"
        "<b>Reglages Systeme &rarr; Confidentialite et securite "
        "&rarr; Surveillance des entrees</b><br><br>"
        "Cliquez sur le bouton ci-dessous, puis cochez la case <b>Klip</b> "
        "dans la liste. Vous devrez peut-etre relancer l'app une fois pour "
        "que la permission soit prise en compte.<br><br>"
        "<span style='font-size:11px;'>Sans cette permission, Klip reste "
        "accessible via l'icone ciseaux dans la barre des menus.</span>",
        ("Ouvrir les Reglages → Surveillance des entrees",
         "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"),
    ),
    (
        "✂️",  # ciseaux variant
        "Snippets ;nom et Macro",
        "Transformez vos textes en raccourcis nommes ou en transformations.",
        "<b>Snippets</b> : selectionnez un texte, appuyez sur <b>Cmd+S</b>, "
        "donnez-lui un nom. Ensuite, dans n'importe quelle app, tapez "
        "<code>;mail</code> + espace &rarr; expansion automatique.<br><br>"
        "<b>Macro</b> : sous l'apercu d'un item texte, ce bouton "
        "regroupe les transformations rapides : MAJUSCULES, minuscules, "
        "Title Case, slugifier, base64, URL encode, trim espaces.<br><br>"
        "<span style='font-size:11px;'>Snippets <b>opt-in</b> dans "
        "Preferences &rarr; Snippets - necessite la permission "
        "&laquo; Surveillance des entrees &raquo;.</span>",
    ),
    (
        "\U0001F3AF",  # bullseye
        "Vous etes pret(e) !",
        "Quelques touches finales pour aller plus loin.",
        "<b>Cmd+,</b> ouvre les Preferences (6 onglets).<br>"
        "<b>Cmd+?</b> affiche tous les raccourcis.<br>"
        "Le menu de l'icone ciseaux dans la barre du systeme propose en plus "
        "<b>Guide d'utilisation</b> (explications detaillees) et "
        "<b>Mini-fenetre flottante</b> (toujours visible, pratique pour "
        "les workflows repetitifs).<br><br>"
        "Bonne route avec Klip ! \U0001F680<br><br><span style='font-size:10px; color:#888;'>Developed by Yoni Sitbon</span>",
    ),
]


def _open_system_preferences(url: str) -> None:
    """Ouvre le panneau Reglages Systeme correspondant via `open` macOS."""
    try:
        subprocess.run(["open", url], check=False)
    except Exception:
        # Silencieux : si ca echoue, l'utilisateur fera a la main.
        pass


class OnboardingDialog(QDialog):
    """Dialog modal affiche au premier lancement.

    Emet ``finished_setup(skipped: bool)`` quand l'utilisateur termine ou
    passe - `main.py` connecte ce signal a ``settings.set("onboarded", True)``.
    """

    finished_setup = pyqtSignal(bool)  # True si Passer, False si termine normalement

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bienvenue dans Klip")
        self.setMinimumSize(620, 600)
        self.setModal(True)
        self.setStyleSheet(current_qss() + _onboarding_qss())
        self._current = 0
        self._build_ui()
        self._render(0)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # En-tete avec "Passer"
        header = QHBoxLayout()
        header.setContentsMargins(16, 12, 16, 0)
        header.addStretch(1)
        skip_btn = QPushButton("Passer")
        skip_btn.setFlat(True)
        skip_btn.setStyleSheet(
            f"QPushButton {{"
            f"  color: {PALETTE['text_faint']}; "
            f"  background: transparent; "
            f"  border: 0; "
            f"  font-size: 12px; "
            f"}}"
            f"QPushButton:hover {{ color: {PALETTE['text']}; }}"
        )
        skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        skip_btn.clicked.connect(self._on_skip)
        header.addWidget(skip_btn)
        root.addLayout(header)

        # Stack de pages (chacune sera un widget construit a la volee)
        self.stack = QStackedWidget()
        for i, screen in enumerate(SCREENS):
            emoji, title, subtitle, desc_html = screen[0], screen[1], screen[2], screen[3]
            action = screen[4] if len(screen) > 4 else None
            self.stack.addWidget(
                self._build_screen(emoji, title, subtitle, desc_html, action)
            )
        root.addWidget(self.stack, 1)

        # Dots de progression
        dots_row = QHBoxLayout()
        dots_row.setContentsMargins(0, 0, 0, 8)
        dots_row.addStretch(1)
        self._dots: list[QLabel] = []
        for i in range(len(SCREENS)):
            dot = QLabel("●")
            dot.setStyleSheet(
                f"color: {PALETTE['border']}; font-size: 14px; "
                f"background: transparent; padding: 0 3px;"
            )
            self._dots.append(dot)
            dots_row.addWidget(dot)
        dots_row.addStretch(1)
        root.addLayout(dots_row)

        # Pied : Precedent / Suivant (ou "Commencer" au dernier ecran)
        footer = QHBoxLayout()
        footer.setContentsMargins(20, 8, 20, 18)
        self._prev_btn = QPushButton("← Precedent")
        self._prev_btn.clicked.connect(self._on_prev)
        self._next_btn = QPushButton("Suivant →")
        self._next_btn.setObjectName("primary")
        self._next_btn.setDefault(True)
        self._next_btn.clicked.connect(self._on_next)
        footer.addWidget(self._prev_btn)
        footer.addStretch(1)
        footer.addWidget(self._next_btn)
        root.addLayout(footer)

    def _build_screen(
        self, emoji: str, title: str, subtitle: str, desc_html: str,
        action: Optional[tuple[str, str]] = None,
    ) -> QWidget:
        """Construit une page de l'onboarding.

        Si ``action`` est fourni (label, url), un bouton primaire est ajoute
        en bas de l'ecran qui ouvre l'URL via `open` macOS.
        """
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(40, 24, 40, 16)
        lay.setSpacing(16)

        lay.addStretch(1)

        # Emoji hero (tres gros, centre)
        emoji_lbl = QLabel(emoji)
        emoji_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Taille adaptative : si c'est un combo de touches (multi-char), plus petit
        font_size = 96 if len(emoji) <= 2 else 56
        emoji_lbl.setStyleSheet(
            f"color: {PALETTE['accent']}; "
            f"font-size: {font_size}px; "
            f"font-weight: 700; "
            f"background: transparent; "
            f"padding: 8px 0;"
        )
        lay.addWidget(emoji_lbl)

        # Titre H1
        title_lbl = QLabel(title)
        title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_lbl.setStyleSheet(
            f"color: {PALETTE['text']}; "
            f"font-size: 22px; font-weight: 700; "
            f"background: transparent; padding: 0;"
        )
        lay.addWidget(title_lbl)

        # Sous-titre (baseline)
        subtitle_lbl = QLabel(subtitle)
        subtitle_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle_lbl.setWordWrap(True)
        subtitle_lbl.setStyleSheet(
            f"color: {PALETTE['text_dim']}; "
            f"font-size: 13px; font-style: italic; "
            f"background: transparent;"
        )
        lay.addWidget(subtitle_lbl)

        # Description longue (RichText, dans un cadre)
        desc_frame = QFrame()
        desc_frame.setObjectName("onboardingDescBox")
        df_lay = QVBoxLayout(desc_frame)
        df_lay.setContentsMargins(20, 16, 20, 16)
        desc_lbl = QLabel(desc_html)
        desc_lbl.setWordWrap(True)
        desc_lbl.setTextFormat(Qt.TextFormat.RichText)
        desc_lbl.setStyleSheet(
            f"color: {PALETTE['text']}; "
            f"font-size: 13px; line-height: 1.55; "
            f"background: transparent; border: 0;"
        )
        df_lay.addWidget(desc_lbl)
        lay.addWidget(desc_frame)

        # Bouton d'action optionnel (ouvre Reglages Systeme)
        if action is not None:
            label, url = action
            action_row = QHBoxLayout()
            action_row.addStretch(1)
            action_btn = QPushButton(label)
            action_btn.setObjectName("primary")
            action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            action_btn.setStyleSheet(
                f"QPushButton#primary {{"
                f"  background: {PALETTE['accent']}; "
                f"  color: white; "
                f"  border: 0; "
                f"  border-radius: 8px; "
                f"  padding: 10px 18px; "
                f"  font-size: 13px; "
                f"  font-weight: 600; "
                f"}}"
                f"QPushButton#primary:hover {{ background: {PALETTE.get('accent_dim', PALETTE['accent'])}; }}"
            )
            action_btn.clicked.connect(lambda _checked=False, u=url: _open_system_preferences(u))
            action_row.addWidget(action_btn)
            action_row.addStretch(1)
            lay.addLayout(action_row)

        lay.addStretch(2)
        return w

    def _render(self, index: int) -> None:
        """Met a jour l'affichage selon l'index courant."""
        index = max(0, min(index, len(SCREENS) - 1))
        self._current = index
        self.stack.setCurrentIndex(index)

        # Mettre a jour les dots
        for i, dot in enumerate(self._dots):
            if i == index:
                dot.setStyleSheet(
                    f"color: {PALETTE['accent']}; font-size: 14px; "
                    f"background: transparent; padding: 0 3px;"
                )
            else:
                dot.setStyleSheet(
                    f"color: {PALETTE['border']}; font-size: 14px; "
                    f"background: transparent; padding: 0 3px;"
                )

        # Activer/desactiver Precedent
        self._prev_btn.setEnabled(index > 0)
        # Changer Suivant en "Commencer" au dernier ecran
        if index == len(SCREENS) - 1:
            self._next_btn.setText("Commencer ✨")
        else:
            self._next_btn.setText("Suivant →")

    # -- Slots --

    def _on_prev(self) -> None:
        self._render(self._current - 1)

    def _on_next(self) -> None:
        if self._current >= len(SCREENS) - 1:
            # Dernier ecran -> on termine normalement
            self.finished_setup.emit(False)
            self.accept()
        else:
            self._render(self._current + 1)

    def _on_skip(self) -> None:
        self.finished_setup.emit(True)
        self.accept()


def _onboarding_qss() -> str:
    """Encapsule pour re-evaluation dynamique (cf. cheatsheet.py)."""
    return f"""
QDialog {{
    background: {PALETTE['bg']};
    color: {PALETTE['text']};
}}
QFrame#onboardingDescBox {{
    background: {PALETTE['bg_panel']};
    border: 1px solid {PALETTE['border']};
    border-radius: 10px;
}}
"""


def open_onboarding(parent: Optional[QWidget] = None) -> OnboardingDialog:
    """Cree/affiche l'onboarding et renvoie l'instance.

    Le caller (main.py) doit :
      1. Connecter ``finished_setup`` a un slot qui met ``settings.onboarded = True``
      2. Garder une reference a l'instance pour eviter le GC immediat
    """
    win = OnboardingDialog(parent=parent)
    win.show()
    win.raise_()
    win.activateWindow()
    return win
