"""Guide d'utilisation — explication détaillée de chaque fonctionnalité.

Complémentaire de la cheatsheet (qui se concentre sur les raccourcis).
Ouvrable via le menu tray « Guide d'utilisation… ».

Chaque section explique une feature en quelques lignes pédagogiques —
pensé pour un utilisateur qui découvre l'app et veut savoir « à quoi ça
sert » sans devoir tout tester.
"""
from __future__ import annotations

from typing import Optional

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .theme import PALETTE, QSS, current_qss


# Structure du guide : liste de (emoji, titre, description en RichText HTML).
# La description peut contenir <b>, <code>, <br> et liens internes vers
# les raccourcis (texte uniquement).

SECTIONS: list[tuple[str, str, str]] = [
    (
        "📋",
        "Capture automatique",
        "Dès que vous copiez quelque chose avec <b>⌘C</b> (texte ou image), "
        "Klip l'attrape et l'ajoute en haut de l'historique. "
        "Aucune action de votre part — l'app surveille en permanence le "
        "presse-papiers système (toutes les 150 ms, zéro CPU).<br><br>"
        "Les apps comme 1Password ou Bitwarden marquent les mots de "
        "passe comme « confidentiels » via NSPasteboard — Klip "
        "les <b>ignore automatiquement</b> et ne les stocke jamais.",
    ),
    (
        "🖼",
        "Captures d'écran",
        "Quand vous faites <b>⌘⇧3</b> (écran entier) ou <b>⌘⇧4</b> (zone) "
        "et que vous attendez que la vignette macOS disparaisse, le PNG "
        "écrit sur le Bureau est <b>ajouté automatiquement</b> à l'historique "
        "et au presse-papiers.<br><br>"
        "<b>Astuce :</b> ajoutez <b>Ctrl</b> au raccourci (<code>Ctrl+⌘⇧4</code>) "
        "pour envoyer la capture directement au presse-papiers sans passer "
        "par un fichier — instantané, parfait quand vous voulez la coller "
        "tout de suite ailleurs.",
    ),
    (
        "🔍",
        "Recherche floue (fuzzy)",
        "Tapez n'importe quel mot dans la barre de recherche en haut — la "
        "liste se filtre en direct. Les frappes proches (<code>clpbrd</code> "
        "trouve <code>clipboard</code>), les fautes de frappe, et l'ordre "
        "des mots sont tolérés.<br><br>"
        "Les éléments récents et fréquemment réutilisés sont remontés en "
        "premier. La recherche cherche aussi dans le texte OCR-isé des "
        "images.",
    ),
    (
        "🔎",
        "OCR sur les images",
        "Chaque image capturée est analysée en arrière-plan par le framework "
        "<b>Vision</b> de macOS — entièrement local, sans réseau, sans coût. "
        "Le texte extrait devient cherchable depuis la barre de recherche, "
        "et copiable d'un clic depuis l'aperçu (« Copier le texte (OCR) »).<br><br>"
        "Vous pouvez choisir les langues reconnues dans "
        "<b>Préférences → OCR</b> — moins de langues = OCR plus rapide "
        "et plus précis.",
    ),
    (
        "⭐",
        "Favoris",
        "Sélectionnez un item et appuyez sur <b>⌘P</b> (ou le bouton "
        "« ☆ Épingler ») pour le marquer comme favori. Les favoris sont "
        "<b>toujours préservés</b> — même si la rétention automatique "
        "supprime des éléments anciens, vos favoris restent.<br><br>"
        "Cliquez sur le filtre <b>★ Favoris</b> en haut pour les retrouver.",
    ),
    (
        "✂️",
        "Snippets ;nom",
        "Transformez un texte en raccourci nommé : sélectionnez-le, appuyez "
        "sur <b>⌘S</b>, choisissez un nom (ex. <code>mail</code>). "
        "Ensuite, dans <b>n'importe quelle app</b>, tapez <code>;mail</code> "
        "suivi d'un espace ou d'une ponctuation — Klip remplace "
        "automatiquement par le contenu complet.<br><br>"
        "⚠️ <b>Désactivé par défaut</b> car ça nécessite d'écouter le "
        "clavier global. Activez-le dans <b>Préférences → Snippets</b> "
        "quand vous êtes prêt(e).",
    ),
    (
        "🪄",
        "Macro — transformations de texte",
        "Sous l'aperçu d'un item texte, le bouton <b>Macro ▾</b> ouvre un "
        "menu avec des transformations rapides : "
        "<b>MAJUSCULES</b>, <b>minuscules</b>, <b>Title Case</b>, "
        "<b>slugify (kebab-case)</b>, <b>base64</b> (encode/decode), "
        "<b>URL</b> (encode/decode), suppression des espaces de bordure. "
        "Le résultat est copié et collé automatiquement dans l'app "
        "précédente.",
    ),
    (
        "🎯",
        "Actions contextuelles",
        "Selon le type détecté, l'aperçu propose des actions intelligentes :<br>"
        " • <b>URL</b> → Ouvrir dans le navigateur, ou copier sans paramètres "
        "de tracking (utm_*, fbclid, gclid…)<br>"
        " • <b>JSON</b> → Formater joliment, ou minifier<br>"
        " • <b>Couleur hex</b> → Convertir en rgb()/hsl()<br>"
        " • <b>Email</b> → Composer un mail<br>"
        " • <b>Chemin de fichier</b> → Révéler dans le Finder<br>"
        " • <b>HTML</b> → Coller en texte brut (sans tags)",
    ),
    (
        "🔒",
        "Détection de secrets",
        "Klip reconnaît les clés API et tokens les plus courants "
        "(OpenAI, Anthropic, GitHub, AWS, Stripe, Slack, Google, Notion, "
        "HuggingFace, Twilio, SendGrid…) ainsi que les clés privées SSH/PGP.<br><br>"
        "Quand un secret est détecté dans ce que vous venez de copier, "
        "il est <b>jamais stocké</b> en base et une notification vous le "
        "signale. Deuxième ligne de défense en plus du flag "
        "« confidentiel » du système.",
    ),
    (
        "🗑",
        "Rétention automatique",
        "Une fois par heure, Klip nettoie automatiquement les "
        "éléments plus anciens que la durée que vous avez choisie. Par "
        "défaut : <b>90 jours pour les textes</b>, <b>30 jours pour les "
        "images</b>.<br><br>"
        "Réglez ça dans <b>Préférences → Confidentialité</b> — sliders "
        "à 7 / 30 / 60 / 90 / 180 / 365 jours, ou ∞ (jamais nettoyer). "
        "Les <b>favoris</b> et les <b>snippets</b> sont toujours préservés "
        "quel que soit leur âge.",
    ),
    (
        "⚙️",
        "Préférences (⌘,)",
        "Six onglets pour tout régler :<br>"
        " • <b>Général</b> — thème (sombre/clair/auto), couleur d'accent, "
        "démarrage automatique, raccourci global<br>"
        " • <b>Capture</b> — tailles maximum texte/image, activation des "
        "captures d'écran<br>"
        " • <b>Snippets</b> — opt-in de l'expansion <code>;nom</code><br>"
        " • <b>OCR</b> — on/off, langues reconnues<br>"
        " • <b>Confidentialité</b> — durées de rétention<br>"
        " • <b>Avancé</b> — historique des changements de paramètres",
    ),
    (
        "🏆",
        "Réussites",
        "Quelques badges déblocables au fil de votre usage : "
        "<b>🎉 Premier pas</b>, <b>💯 Centurion</b> (100 items), "
        "<b>🚀 Power user</b> (1000 items), <b>✂️ Snippeteur</b>, "
        "<b>⭐ Sélectif</b>, <b>🖼 Photographe</b>, <b>🌐 Multi-app</b>, "
        "<b>🔥 Fan</b>.<br><br>"
        "Visibles dans la fenêtre <b>À propos de Klip</b>.",
    ),
]


class GuideDialog(QDialog):
    """Fenêtre Guide d'utilisation — sections empilées dans un scroll."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Guide d'utilisation — Klip")
        self.setMinimumSize(600, 700)
        self.setModal(False)
        # Re-éval à l'ouverture (cf. cheatsheet.py) — sans ça, le mode clair
        # n'était pas honoré sur les dialogs ouverts après changement.
        self.setStyleSheet(current_qss() + _guide_qss())
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 14)
        root.setSpacing(12)

        # En-tête
        title = QLabel("Guide d'utilisation")
        title.setProperty("class", "h1")
        root.addWidget(title)

        subtitle = QLabel(
            "Tout ce que Klip sait faire, en une page. "
            "Pour les raccourcis seuls, ouvrez plutôt « Raccourcis… » (⌘?)."
        )
        subtitle.setWordWrap(True)
        subtitle.setProperty("class", "meta")
        root.addWidget(subtitle)

        # Zone scrollable avec les sections
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        scroll_widget = QWidget()
        scroll_lay = QVBoxLayout(scroll_widget)
        scroll_lay.setContentsMargins(0, 8, 0, 0)
        scroll_lay.setSpacing(12)

        for emoji, name, desc_html in SECTIONS:
            scroll_lay.addWidget(self._build_section(emoji, name, desc_html))

        scroll_lay.addStretch(1)
        scroll.setWidget(scroll_widget)
        root.addWidget(scroll, 1)

        # Pied : Fermer
        footer = QHBoxLayout()
        footer.addStretch(1)
        close_btn = QPushButton("Fermer")
        close_btn.setObjectName("primary")
        close_btn.setDefault(True)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

    def _build_section(self, emoji: str, name: str, desc_html: str) -> QWidget:
        """Une section = cadre avec emoji + titre + description RichText."""
        frame = QFrame()
        frame.setObjectName("guideSection")
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(6)

        # Ligne titre (emoji + nom)
        header = QHBoxLayout()
        header.setSpacing(10)
        emoji_lbl = QLabel(emoji)
        emoji_lbl.setStyleSheet(
            "font-size: 24px; background: transparent; border: 0;"
        )
        name_lbl = QLabel(name)
        name_lbl.setProperty("class", "h2")
        # Important : on garde un peu de style local pour annuler
        # le background/border hérités du QFrame parent.
        name_lbl.setStyleSheet("background: transparent; border: 0;")
        header.addWidget(emoji_lbl)
        header.addWidget(name_lbl, 1)
        lay.addLayout(header)

        # Description (RichText)
        desc_lbl = QLabel(desc_html)
        desc_lbl.setWordWrap(True)
        desc_lbl.setTextFormat(Qt.TextFormat.RichText)
        desc_lbl.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: 13px; "
            f"line-height: 1.5; background: transparent; border: 0;"
        )
        lay.addWidget(desc_lbl)

        return frame


def _guide_qss() -> str:
    """Encapsulé pour ré-évaluation dynamique (cf. cheatsheet.py)."""
    return f"""
QDialog {{
    background: {PALETTE['bg']};
    color: {PALETTE['text']};
}}
QFrame#guideSection {{
    background: {PALETTE['bg_panel']};
    border: 1px solid {PALETTE['border']};
    border-radius: 8px;
}}
/* Zone scrollable — sans ces règles, Qt met un fond blanc par défaut
   sur le viewport et sur le widget contenu, ce qui crée les bandes
   claires entre les sections sombres. */
QScrollArea, QScrollArea > QWidget, QScrollArea > QWidget > QWidget {{
    background: {PALETTE['bg']};
    border: 0;
}}
QScrollArea {{
    background: transparent;
}}
"""


def open_guide(parent: Optional[QWidget] = None) -> GuideDialog:
    """Crée/affiche le guide et renvoie l'instance.

    Le caller doit garder la référence Python pour éviter le GC immédiat.
    """
    win = GuideDialog(parent=parent)
    win.show()
    win.raise_()
    win.activateWindow()
    return win
