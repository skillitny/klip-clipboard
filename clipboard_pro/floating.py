"""Mini-fenêtre flottante (Phase 6, session 5).

Petite fenêtre `frameless`, `always-on-top` et `translucent` qui montre les
N derniers items capturés (5 par défaut). L'utilisateur peut :

  • La déplacer en glissant n'importe où sur le fond (la position est
    persistée dans ``settings.floating.x/y``)
  • Cliquer sur un item → copie automatique + collage dans l'app précédente
  • La fermer (croix ✕) ou la cacher → toggle aussi disponible depuis le
    menu tray et l'onglet Général des Préférences

Conçue pour les workflows répétitifs (copier-coller en rafale entre plusieurs
sources). Très inspirée des « clipboard manager » macOS modernes mais en
version légère et personnalisable.

Activation : opt-in via ``settings.floating.enabled``. Désactivée par défaut
parce qu'une fenêtre toujours visible ne convient pas à tout le monde.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from PyQt6.QtCore import QPoint, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QCursor, QGuiApplication, QMouseEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import osbackend as capture
from .db import Database, Item
from .theme import PALETTE


def _short_preview(item: Item, max_chars: int = 60) -> str:
    """Génère un texte court à afficher dans la mini-card."""
    if item.kind == "image":
        dims = f"{item.image_w}×{item.image_h}" if item.image_w else "image"
        return f"🖼  {dims}"
    if item.is_snippet and item.snippet_name:
        return f"✂️  ;{item.snippet_name}"
    if not item.text:
        return "[vide]"
    one = " ".join(item.text.split())
    return one[:max_chars] + ("…" if len(one) > max_chars else "")


class FloatingWindow(QWidget):
    """Mini-fenêtre flottante avec les N derniers items.

    Émet ``visibility_changed(bool)`` quand on la montre/cache, pour que
    `main.py` puisse synchroniser le setting et le menu tray.
    """

    visibility_changed = pyqtSignal(bool)

    DEFAULT_WIDTH = 260
    HEADER_HEIGHT = 32

    def __init__(
        self,
        db: Database,
        settings: Any,
        copy_callback: Callable[[Item], None],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.db = db
        self.settings = settings
        self.copy_callback = copy_callback
        # Pour le drag : on stocke la position de la souris au mousePress
        # par rapport au coin de la fenêtre.
        self._drag_offset: Optional[QPoint] = None

        # Window flags : frameless + always-on-top + Tool (n'apparait pas
        # dans le dock, n'enregistre pas dans le menu Window de l'app).
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        # Fond transparent pour pouvoir dessiner un rect arrondi en QSS
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(self.DEFAULT_WIDTH)
        self.setMaximumWidth(self.DEFAULT_WIDTH + 80)

        self._build_ui()
        self._restore_position()

    # -- Construction --------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Conteneur arrondi (le QWidget transparent ne dessine rien, donc
        # tout passe par un QFrame intérieur).
        self._container = QFrame()
        self._container.setObjectName("floatingRoot")
        self._container.setStyleSheet(
            f"""
            QFrame#floatingRoot {{
                background: {PALETTE['bg_panel']};
                border: 1px solid {PALETTE['border']};
                border-radius: 12px;
            }}
            """
        )
        container_lay = QVBoxLayout(self._container)
        container_lay.setContentsMargins(8, 8, 8, 8)
        container_lay.setSpacing(4)

        # Header — drag handle + bouton fermer
        header = QHBoxLayout()
        header.setContentsMargins(4, 0, 4, 4)
        header.setSpacing(4)

        title = QLabel("✂  Klip")
        title.setStyleSheet(
            f"color: {PALETTE['accent']}; font-weight: 700; "
            f"font-size: 12px; background: transparent;"
        )
        header.addWidget(title)
        header.addStretch(1)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                color: {PALETTE['text_faint']};
                border: 0;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                color: {PALETTE['text']};
                background: {PALETTE['bg_hover']};
                border-radius: 4px;
            }}
            """
        )
        close_btn.clicked.connect(self.hide_window)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        header.addWidget(close_btn)
        container_lay.addLayout(header)

        # Container pour les items (peuplé via refresh)
        self._items_box = QVBoxLayout()
        self._items_box.setContentsMargins(0, 0, 0, 0)
        self._items_box.setSpacing(3)
        container_lay.addLayout(self._items_box)

        # Footer hint
        hint = QLabel("Clic = copier · glisser pour déplacer")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(
            f"color: {PALETTE['text_faint']}; font-size: 9px; "
            f"background: transparent; padding: 2px 0;"
        )
        container_lay.addWidget(hint)

        root.addWidget(self._container)

    # -- API publique --------------------------------------------------------

    def refresh(self) -> None:
        """Recharge la liste depuis la DB. À appeler après chaque capture."""
        # Vide
        while self._items_box.count():
            child = self._items_box.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        count = int(self.settings.get("floating.item_count", 5) or 5)
        try:
            items = self.db.list_items(limit=count)
        except Exception:
            items = []

        if not items:
            empty = QLabel("Aucun élément encore.\nCopiez quelque chose pour commencer.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            empty.setStyleSheet(
                f"color: {PALETTE['text_faint']}; font-size: 11px; "
                f"background: transparent; padding: 12px;"
            )
            self._items_box.addWidget(empty)
            return

        for it in items[:count]:
            self._items_box.addWidget(self._build_item_card(it))

    def show_window(self) -> None:
        self.show()
        self.raise_()
        self.visibility_changed.emit(True)

    def hide_window(self) -> None:
        self.hide()
        self.visibility_changed.emit(False)

    def toggle(self) -> None:
        if self.isVisible():
            self.hide_window()
        else:
            self.show_window()

    # -- Construction d'une mini-card item -----------------------------------

    def _build_item_card(self, item: Item) -> QWidget:
        card = QPushButton()
        card.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        card.setFlat(True)
        card.setStyleSheet(
            f"""
            QPushButton {{
                text-align: left;
                background: {PALETTE['bg_elev']};
                color: {PALETTE['text']};
                border: 1px solid {PALETTE['border']};
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: {PALETTE['accent']};
                border-color: {PALETTE['accent']};
                color: white;
            }}
            """
        )
        # Préfixe « ⏎ » discret pour suggérer qu'un clic colle dans l'app
        # précédente — pas obligatoire mais ça donne du sens visuel.
        card.setText(_short_preview(item))
        card.clicked.connect(lambda _checked=False, it=item: self._on_card_clicked(it))
        return card

    def _on_card_clicked(self, item: Item) -> None:
        """Clic sur une mini-card : on délègue à `copy_callback` (qui gère
        le clipboard write + autopaste vers l'app précédente)."""
        try:
            self.copy_callback(item)
        except Exception:
            pass

    # -- Drag pour déplacer la fenêtre ---------------------------------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            # On ne drag QUE si on clique sur le fond (pas sur un bouton).
            child = self.childAt(event.position().toPoint())
            if child is None or isinstance(child, (QFrame, QLabel)):
                self._drag_offset = (
                    event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            self._save_position()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    # -- Persistance de la position ------------------------------------------

    def _save_position(self) -> None:
        p = self.pos()
        try:
            self.settings.set(
                "floating.x", int(p.x()),
                note="Position mini-fenêtre (drag)", source="floating_ui",
            )
            self.settings.set(
                "floating.y", int(p.y()),
                note=None, source="floating_ui",
            )
        except Exception:
            pass

    def _restore_position(self) -> None:
        x = int(self.settings.get("floating.x", -1) or -1)
        y = int(self.settings.get("floating.y", -1) or -1)
        if x < 0 or y < 0:
            # Première fois : on positionne en haut-droite de l'écran
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                geo = screen.availableGeometry()
                x = geo.right() - self.DEFAULT_WIDTH - 24
                y = geo.top() + 60
            else:
                x, y = 80, 80
        self.move(x, y)
