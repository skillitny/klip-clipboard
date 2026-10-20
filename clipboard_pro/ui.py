"""Fenêtre principale Klip — style Spotlight."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable, Optional

from PyQt6.QtCore import (
    QEasingCurve,
    QEvent,
    QMimeData,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    QUrl,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QAction,
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QPainter,
    QPainterPath,
    QPalette,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLayoutItem,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from . import osbackend as capture
from .actions import Action, actions_for, transformations_for
from .app_icons import app_icon_cache
from .classify import TYPES, classify
from .db import Database, Item
from .fuzzy import fuzzy_filter, since_today, since_week
from . import redact
from .theme import PALETTE, QSS, active_is_dark, current_qss


def _human_time(ts: float) -> str:
    delta = time.time() - ts
    if delta < 60:
        return "à l'instant"
    if delta < 3600:
        return f"il y a {int(delta // 60)} min"
    if delta < 86400:
        return f"il y a {int(delta // 3600)} h"
    if delta < 7 * 86400:
        return f"il y a {int(delta // 86400)} j"
    return datetime.fromtimestamp(ts).strftime("%d %b %Y")


def _human_size(n: int) -> str:
    n = float(n)
    for unit in ("o", "Ko", "Mo"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.0f} Go"


# ----------------------------------------------------------------------------
# Meta tags (session 6) — pastilles colorées subtiles pour les métadonnées
# d'un item dans la zone Aperçu. Chaque "kind" a une couleur de fond très
# légère + un texte coloré assorti. Volontairement sobre — pas carnaval.
# ----------------------------------------------------------------------------

# (fond, texte, bordure) — palette distinctive par catégorie (v2.3) :
# chaque "kind" a sa propre famille de couleur pour identification rapide
# au premier coup d'œil. Saturation modérée pour rester pro et lisible.
# Mode CLAIR : pastels clairs + texte foncé.
_TAG_COLORS_LIGHT: dict[str, tuple[str, str, str]] = {
    "type":    ("#ede9fe", "#5b21b6", "#a78bfa"),   # violet — Type de contenu
    "time":    ("#d1fae5", "#065f46", "#6ee7b7"),   # vert — Date
    "app":     ("#cffafe", "#155e75", "#67e8f9"),   # cyan/teal — Source/App
    "use":     ("#ffedd5", "#9a3412", "#fdba74"),   # orange — Usage
    "size":    ("#fef3c7", "#78350f", "#fcd34d"),   # jaune/ambre — Taille
    "snippet": ("#fce7f3", "#831843", "#f9a8d4"),   # rose — Snippets
}
# Mode SOMBRE : fonds sombres désaturés + texte coloré clair (même identité
# de teinte, mais qui se fond dans le panneau sombre au lieu de "flasher").
_TAG_COLORS_DARK: dict[str, tuple[str, str, str]] = {
    "type":    ("#2e2640", "#c4b5fd", "#5b4b8a"),   # violet
    "time":    ("#1d3a2e", "#6ee7b7", "#2f6b52"),   # vert
    "app":     ("#16363d", "#67e8f9", "#2b6b78"),   # cyan/teal
    "use":     ("#3a2a1d", "#fdba74", "#7a4a28"),   # orange
    "size":    ("#3a331a", "#fcd34d", "#7a6a2a"),   # jaune/ambre
    "snippet": ("#3a1f2e", "#f9a8d4", "#7a3a55"),   # rose
}


def _tag_palette() -> dict[str, tuple[str, str, str]]:
    """Renvoie la table de couleurs de pastilles adaptée au thème actif."""
    return _TAG_COLORS_DARK if active_is_dark() else _TAG_COLORS_LIGHT


def _meta_tags_html(tags: list[tuple[str, str]]) -> str:
    """Rend une liste de (kind, text) en pastilles HTML style "pill".

    Style v2.3.2 : pastilles pill (border-radius fort) avec léger contour
    1px assorti — donne du relief sans dramatiser. Pas d'icône emoji,
    juste le label propre. Inspiration Linear / labels Notion.
    """
    parts: list[str] = []
    _tc = _tag_palette()
    for kind, text in tags:
        bg, fg, bd = _tc.get(kind, _tc["size"])
        safe = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        parts.append(
            f'<span style="background:{bg}; color:{fg}; '
            f'border:1px solid {bd}; '
            f'padding:2px 10px; border-radius:11px; '
            f'font-size:11px; font-weight:600;">{safe}</span>'
        )
    return "&nbsp; ".join(parts)


# ----------------------------------------------------------------------------
# Item delegate (rendu personnalisé)
# ----------------------------------------------------------------------------

class ThumbCache:
    """Cache LRU de miniatures pour la liste d'images (session 5).

    Sans ça, on ne pourrait pas afficher de vraie miniature dans le badge
    de chaque item image — `list_items()` ne ramène plus `image_blob` en
    RAM (depuis v3) et charger les blobs complets pendant le `paint()` du
    delegate bloquerait l'UI. On charge à la demande la première fois
    qu'un item est dessiné, puis on garde la thumbnail prête à l'emploi.

    Limité à ``MAX_SIZE`` entrées pour éviter de grossir indéfiniment ;
    quand on dépasse, on vire le plus ancien (FIFO suffisant pour ce
    use case).
    """

    MAX_SIZE = 200
    THUMB_SIZE = 32     # pixels logiques
    RETINA_FACTOR = 2   # on stocke en 64x64 pour rester net sur Retina

    def __init__(self, db: Database) -> None:
        self.db = db
        self._cache: dict[int, QPixmap] = {}

    def get(self, item_id: int) -> Optional[QPixmap]:
        cached = self._cache.get(item_id)
        if cached is not None:
            return cached
        try:
            blob = self.db.get_image_blob(item_id)
        except Exception:
            return None
        if not blob:
            return None
        pix = QPixmap()
        if not pix.loadFromData(blob, "PNG"):
            return None

        target = self.THUMB_SIZE * self.RETINA_FACTOR
        # KeepAspectRatioByExpanding : on remplit le carré sans bandes
        # noires (crop centre ensuite). Plus joli qu'un fit avec marges.
        scaled = pix.scaled(
            target,
            target,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        # Crop au centre pour avoir exactement target x target
        w, h = scaled.width(), scaled.height()
        crop_x = max(0, (w - target) // 2)
        crop_y = max(0, (h - target) // 2)
        thumb = scaled.copy(crop_x, crop_y, target, target)
        thumb.setDevicePixelRatio(float(self.RETINA_FACTOR))

        # Éviction FIFO si on dépasse
        if len(self._cache) >= self.MAX_SIZE:
            oldest = next(iter(self._cache))
            del self._cache[oldest]
        self._cache[item_id] = thumb
        return thumb

    def invalidate(self, item_id: int) -> None:
        self._cache.pop(item_id, None)

    def clear(self) -> None:
        self._cache.clear()


class FlowLayout(QLayout):
    """Layout qui dispose ses enfants horizontalement et passe à la ligne
    automatiquement quand la largeur ne suffit plus.

    Adapté de l'exemple officiel Qt « Flow Layout ». Utilisé pour la rangée
    de boutons d'actions sous l'aperçu — sans ça, les nouvelles
    transformations Phase 1 (MAJUSCULES, slugifier, base64…) dépassent
    l'écran et sont coupées.
    """

    def __init__(self, parent: Optional[QWidget] = None,
                 margin: int = 0, spacing: int = 6) -> None:
        super().__init__(parent)
        if parent is None:
            self.setContentsMargins(margin, margin, margin, margin)
        self.setSpacing(spacing)
        self._items: list[QLayoutItem] = []

    def __del__(self):  # pragma: no cover — sécurité
        while self.count():
            self.takeAt(0)

    def addItem(self, item: QLayoutItem) -> None:
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int) -> Optional[QLayoutItem]:
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int) -> Optional[QLayoutItem]:
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self) -> Qt.Orientation:
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect) -> None:
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        x, y = rect.x(), rect.y()
        line_height = 0
        spacing = self.spacing()
        for item in self._items:
            w = item.sizeHint().width()
            h = item.sizeHint().height()
            next_x = x + w + spacing
            if next_x - spacing > rect.right() and line_height > 0:
                x = rect.x()
                y = y + line_height + spacing
                next_x = x + w + spacing
                line_height = 0
            if not test_only:
                item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
            x = next_x
            line_height = max(line_height, h)
        return y + line_height - rect.y()


class ItemDelegate(QStyledItemDelegate):
    ROW_HEIGHT = 56
    EMPTY_STATE_HEIGHT = 200
    CHECKBOX_SIZE = 18  # taille de la case à cocher en mode bulk
    CHECKBOX_AREA = 36  # largeur réservée à gauche quand bulk mode actif

    def __init__(
        self,
        parent=None,
        thumb_cache: Optional[ThumbCache] = None,
        is_bulk_mode_fn: Optional[Callable[[], bool]] = None,
        is_checked_fn: Optional[Callable[[int], bool]] = None,
    ):
        super().__init__(parent)
        self.thumb_cache = thumb_cache
        # Callbacks vers la MainWindow pour ne pas créer de dépendance
        # circulaire dans les imports. None = comportement legacy.
        self._is_bulk_mode = is_bulk_mode_fn or (lambda: False)
        self._is_checked = is_checked_fn or (lambda _id: False)
        # Cache d'icônes des apps source (Chrome, Claude, VSCode, …)
        # pour rendre une vraie icône au lieu du badge ¶ générique.
        self._app_icons = app_icon_cache(icon_size=32)

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        # Les placeholders d'état vide (pas de data UserRole) prennent
        # toute la hauteur disponible, pour respirer visuellement.
        item = index.data(Qt.ItemDataRole.UserRole)
        if item is None:
            return QSize(option.rect.width(), self.EMPTY_STATE_HEIGHT)
        return QSize(option.rect.width(), self.ROW_HEIGHT)

    def _checkbox_rect_for(self, item_rect: QRect) -> QRect:
        """Calcule le rectangle de la checkbox (centré vertical à gauche)."""
        cx = item_rect.left() + 12
        cy = item_rect.top() + (item_rect.height() - self.CHECKBOX_SIZE) // 2
        return QRect(cx, cy, self.CHECKBOX_SIZE, self.CHECKBOX_SIZE)

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        item: Item = index.data(Qt.ItemDataRole.UserRole)
        if item is None:
            super().paint(painter, option, index)
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect.adjusted(2, 1, -2, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)

        bg = QColor(PALETTE["accent"]) if selected else (
            QColor(PALETTE["bg_hover"]) if hover else QColor(PALETTE["bg_panel"])
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 6, 6)

        # === Mode bulk : dessiner la checkbox à gauche + décaler le reste ===
        bulk_mode = self._is_bulk_mode()
        content_offset = 0
        if bulk_mode:
            cb_rect = self._checkbox_rect_for(rect)
            content_offset = self.CHECKBOX_AREA  # décale le badge + texte
            is_text = (item.kind == "text")
            checked = is_text and self._is_checked(item.id)
            # Rendu checkbox — 4 cas distincts pour rester visible
            # quel que soit l'état du curseur (selected) :
            #   1. checked  + selected : fond blanc, bord blanc, ✓ violet
            #   2. checked  + non-sel  : fond violet, bord violet, ✓ blanc
            #   3. non-chk  + selected : fond transparent, bord blanc épais
            #   4. non-chk  + non-sel  : fond bg_elev, bord violet
            #   5. image (non cochable) : grisée
            if not is_text:
                border_col = QColor(PALETTE["text_faint"])
                fill_col = QColor(PALETTE["bg_elev"])
                painter.setBrush(fill_col)
                painter.setPen(border_col)
                painter.drawRoundedRect(cb_rect, 4, 4)
            else:
                accent = QColor(PALETTE["accent"])
                if checked and selected:
                    fill_col = QColor("white")
                    border_col = QColor("white")
                    check_col = accent
                elif checked and not selected:
                    fill_col = accent
                    border_col = accent
                    check_col = QColor("white")
                elif not checked and selected:
                    fill_col = QColor(0, 0, 0, 0)  # transparent
                    border_col = QColor("white")
                    check_col = None
                else:
                    fill_col = QColor(PALETTE["bg_elev"])
                    border_col = accent
                    check_col = None
                painter.setBrush(fill_col)
                pen = painter.pen()
                pen.setColor(border_col)
                pen.setWidth(2)
                painter.setPen(pen)
                painter.drawRoundedRect(cb_rect, 4, 4)
                if checked and check_col is not None:
                    painter.setPen(check_col)
                    check_font = QFont(painter.font())
                    check_font.setPointSize(12)
                    check_font.setBold(True)
                    painter.setFont(check_font)
                    painter.drawText(cb_rect, Qt.AlignmentFlag.AlignCenter, "✓")

        # Badge type (couleur swatch pour les couleurs hex)
        type_info = TYPES.get(item.content_type, TYPES["plain"]) if item.kind == "text" else TYPES["image"]
        badge_color = QColor(type_info.color)
        if item.content_type == "color" and item.text:
            try:
                badge_color = QColor(item.text.strip())
                if not badge_color.isValid():
                    badge_color = QColor(type_info.color)
            except Exception:
                badge_color = QColor(type_info.color)
        badge_rect = QRect(rect.left() + 10 + content_offset, rect.top() + 12, 32, 32)

        # Pour les images on essaie d'afficher une vraie miniature au lieu
        # du badge générique bleu/jaune. Si la thumbnail n'est pas encore
        # disponible (premier render, blob manquant) on retombe sur le
        # badge classique pour ne pas laisser un trou.
        thumb_drawn = False
        if (
            item.kind == "image"
            and not item.is_snippet
            and self.thumb_cache is not None
        ):
            thumb = self.thumb_cache.get(item.id)
            if thumb is not None:
                # Clip arrondi pour respecter le radius du badge
                path = QPainterPath()
                path.addRoundedRect(
                    float(badge_rect.x()),
                    float(badge_rect.y()),
                    float(badge_rect.width()),
                    float(badge_rect.height()),
                    8.0,
                    8.0,
                )
                painter.save()
                painter.setClipPath(path)
                painter.drawPixmap(badge_rect, thumb)
                painter.restore()
                # Petit liseré pour bien détacher la miniature du fond,
                # surtout sur les screenshots blancs (Safari, doc, etc.)
                pen_color = QColor("white") if selected else QColor(PALETTE["border"])
                painter.setPen(pen_color)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawRoundedRect(badge_rect, 8, 8)
                thumb_drawn = True

        if not thumb_drawn:
            # v2.3 — Si on connaît l'app source et qu'on peut récupérer
            # son icône macOS native, on la dessine à la place du badge
            # coloré générique. Plus parlant visuellement (l'utilisateur
            # reconnaît instantanément Chrome, Claude, VSCode, etc.).
            app_pix: Optional[QPixmap] = None
            if not item.is_snippet and item.source_app:
                try:
                    app_pix = self._app_icons.get(item.source_app)
                except Exception:
                    app_pix = None

            if app_pix is not None and not app_pix.isNull():
                # Clip arrondi pour respecter le radius du badge
                path = QPainterPath()
                path.addRoundedRect(
                    float(badge_rect.x()),
                    float(badge_rect.y()),
                    float(badge_rect.width()),
                    float(badge_rect.height()),
                    8.0,
                    8.0,
                )
                painter.save()
                painter.setClipPath(path)
                painter.drawPixmap(badge_rect, app_pix)
                painter.restore()
            else:
                # Fallback : badge coloré classique avec icône ou ✎ pour snippet.
                if selected:
                    overlay = QColor("white")
                    overlay.setAlphaF(0.25)
                    painter.setBrush(overlay)
                else:
                    painter.setBrush(badge_color)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(badge_rect, 8, 8)
                painter.setPen(QColor("white"))
                font = QFont(painter.font())
                font.setBold(True)
                painter.setFont(font)
                if item.is_snippet:
                    painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, "✎")
                else:
                    painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, type_info.icon)

        # Numéro de raccourci (1-9) pour les premiers items
        row = index.row()
        if row < 9:
            n_rect = QRect(rect.left() + 10, rect.top() + 8, 20, 14)
            painter.setPen(QColor("white") if selected else QColor(PALETTE["text_faint"]))
            small = QFont(painter.font())
            small.setPointSize(8)
            small.setBold(False)
            painter.setFont(small)
            painter.drawText(n_rect, Qt.AlignmentFlag.AlignLeft, f"⌘{row + 1}")

        # Texte principal
        text_left = badge_rect.right() + 12
        text_right = rect.right() - 100
        title_font = QFont(painter.font())
        title_font.setBold(False)
        title_font.setPointSize(13)
        painter.setFont(title_font)
        painter.setPen(QColor("white") if selected else QColor(PALETTE["text"]))
        fm = QFontMetrics(title_font)
        elided = fm.elidedText(item.display_name, Qt.TextElideMode.ElideRight, text_right - text_left)
        painter.drawText(text_left, rect.top() + 22, elided)

        # Sous-titre
        sub_font = QFont(painter.font())
        sub_font.setPointSize(10)
        painter.setFont(sub_font)
        painter.setPen(QColor("white" if selected else PALETTE["text_faint"]))
        sub_parts = [type_info.label]
        if item.is_snippet:
            sub_parts.insert(0, "Snippet")
        if item.source_app:
            sub_parts.append(item.source_app)
        if item.use_count > 1:
            sub_parts.append(f"utilisé {item.use_count}×")
        if item.kind == "text" and item.size_bytes:
            sub_parts.append(_human_size(item.size_bytes))
        elif item.kind == "image" and item.image_w:
            sub_parts.append(f"{item.image_w}×{item.image_h}")
        sub = " · ".join(sub_parts)
        sub_fm = QFontMetrics(sub_font)
        sub = sub_fm.elidedText(sub, Qt.TextElideMode.ElideRight, text_right - text_left)
        painter.drawText(text_left, rect.top() + 40, sub)

        # Timestamp
        ts_text = _human_time(item.created_at)
        ts_rect = QRect(rect.right() - 96, rect.top() + 8, 86, 18)
        painter.setPen(QColor("white" if selected else PALETTE["text_faint"]))
        painter.drawText(ts_rect, int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter), ts_text)

        # Étoile favori
        if item.is_favorite:
            painter.setPen(QColor(PALETTE["favorite"]))
            star_font = QFont(painter.font())
            star_font.setPointSize(14)
            painter.setFont(star_font)
            star_rect = QRect(rect.right() - 28, rect.top() + 28, 20, 20)
            painter.drawText(star_rect, Qt.AlignmentFlag.AlignCenter, "★")

        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:
        """Intercepte les clics sur la checkbox en mode bulk.

        Si le mode bulk est actif et que le clic tombe dans la zone
        checkbox d'un item TEXTE, on toggle la sélection via le callback
        fourni par MainWindow et on consomme l'événement (pour ne pas
        déclencher la sélection normale qui ouvrirait l'aperçu).
        """
        if not self._is_bulk_mode():
            return super().editorEvent(event, model, option, index)
        if event.type() != QEvent.Type.MouseButtonPress:
            return super().editorEvent(event, model, option, index)
        item: Item = index.data(Qt.ItemDataRole.UserRole)
        if item is None or item.kind != "text":
            return super().editorEvent(event, model, option, index)
        rect = option.rect.adjusted(2, 1, -2, -1)
        cb_rect = self._checkbox_rect_for(rect)
        # On élargit légèrement la hitbox pour faciliter le clic.
        hit = cb_rect.adjusted(-6, -6, 6, 6)
        try:
            pos = event.position().toPoint()
        except AttributeError:
            pos = event.pos()
        if hit.contains(pos):
            parent = self.parent()
            # `parent()` du delegate = la QListWidget. Sa `parent()` est la
            # MainWindow ; on remonte pour appeler le callback.
            window = parent.window() if parent is not None else None
            cb = getattr(window, "_on_bulk_item_toggled", None)
            if callable(cb):
                cb(item.id)
            return True  # consommé : pas de sélection normale
        return super().editorEvent(event, model, option, index)


# ----------------------------------------------------------------------------
# QListWidget custom : supporte le drag d'items vers Finder/Mail/Slack/etc.
# ----------------------------------------------------------------------------


class HistoryListWidget(QListWidget):
    """QListWidget qui peuple le mime data lors d'un drag externe.

    Override de ``mimeData()`` pour construire un ``QMimeData`` riche :

      • Texte  → ``setText()`` (collable dans Mail / Slack / TextEdit / etc.)
                + écriture dans ``/tmp/klip_export_<id>.txt`` exposée comme
                URL (permet le drop dans Finder en tant que fichier).
      • Image  → blob écrit dans ``/tmp/klip_export_<id>.png`` exposé comme
                URL (Finder accepte) + ``setImageData(QImage)`` (Slack /
                certains éditeurs acceptent l'image inline).

    L'app receveuse choisit ce qui l'intéresse dans le mime data — Finder
    prend les URLs, Slack prend l'image inline ou le texte, etc.
    """

    def __init__(self, db: Database, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.db = db
        self.settings: Any = None  # renseigné par MainWindow (masquage export)
        # Activation du drag : on autorise uniquement le drag SORTANT
        # (pas le drop entrant — on ne réordonne pas la liste à la main).
        self.setDragEnabled(True)
        self.setAcceptDrops(False)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragOnly)
        # Le drag commence après un petit mouvement de souris — évite de
        # déclencher un drag accidentel quand on veut juste cliquer.
        self.setDefaultDropAction(Qt.DropAction.CopyAction)

    def mimeData(self, items) -> QMimeData:  # type: ignore[override]
        """Construit le QMimeData pour le drag externe."""
        import os
        import re
        import tempfile

        mime = QMimeData()
        if not items:
            return mime

        # On gère uniquement le premier item (SingleSelection sur cette liste).
        list_item = items[0]
        item: Optional[Item] = list_item.data(Qt.ItemDataRole.UserRole)
        if not item:
            return mime

        tmp_dir = tempfile.gettempdir()
        urls: list[QUrl] = []

        if item.kind == "image":
            blob = self.db.get_image_blob(item.id)
            if not blob:
                return mime
            # Option « Toujours masquer les secrets » (cf. redact.export_png).
            blob = redact.export_png(blob, self.settings)
            if blob is None:
                return mime  # masquage impossible → on ne laisse rien sortir
            # Nom de fichier descriptif (ex. klip_export_42.png)
            path = os.path.join(tmp_dir, f"klip_export_{item.id}.png")
            try:
                with open(path, "wb") as f:
                    f.write(blob)
                urls.append(QUrl.fromLocalFile(path))
            except Exception:
                pass
            # Image inline pour les apps qui l'acceptent (Slack, etc.)
            pix = QPixmap()
            if pix.loadFromData(blob, "PNG"):
                mime.setImageData(pix.toImage())

        elif item.kind == "text" and item.text:
            # Texte direct (collable n'importe où qui accepte du texte)
            mime.setText(item.text)
            # Et un .txt temporaire pour pouvoir drop dans Finder.
            # Nom dérivé du contenu pour rester lisible.
            head = " ".join(item.text.split())[:40]
            safe = re.sub(r"[^\w\-.]+", "_", head).strip("_") or f"item_{item.id}"
            path = os.path.join(tmp_dir, f"klip_export_{item.id}_{safe}.txt")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(item.text)
                urls.append(QUrl.fromLocalFile(path))
            except Exception:
                pass

        if urls:
            mime.setUrls(urls)

        return mime


# ----------------------------------------------------------------------------
# Fenêtre principale
# ----------------------------------------------------------------------------

class MainWindow(QMainWindow):
    item_copied = pyqtSignal(int)
    snippet_changed = pyqtSignal()

    def __init__(
        self,
        db: Database,
        autopaste_cb: Optional[Callable[[], None]] = None,
        theme: str = "dark",
        settings: Any = None,
        toolbar_callbacks: Optional[dict[str, Callable[[], None]]] = None,
    ) -> None:
        super().__init__()
        self.db = db
        self.autopaste_cb = autopaste_cb
        # On garde le thème choisi pour pouvoir le re-appliquer si besoin.
        self._theme = theme
        # `settings` est optionnel pour rétro-compat — utilisé pour les
        # smart folders (filtres sauvegardés, session 5).
        self.settings = settings
        # Callbacks pour les boutons du header (v2.3). Clés attendues :
        # "prefs", "shortcuts", "guide", "about", "floating". Valeurs =
        # callables sans argument. Si None ou clé manquante, on tombe sur
        # des handlers par défaut qui importent les modules eux-mêmes.
        self._toolbar_callbacks = toolbar_callbacks or {}
        self.setWindowTitle("Klip")
        # v2.3 — taille initiale + minimum réaliste pour que la sidebar
        # (220px), la liste (≥280px), l'aperçu (≥360px) et la toolbar
        # header (6 boutons) tiennent sans se chevaucher. En dessous de
        # 1080px de large, la toolbar header passe en icon-only via
        # resizeEvent ci-dessous.
        self.resize(1180, 700)
        self.setMinimumSize(1080, 600)

        self._filter_kind: Optional[str] = None
        self._filter_favs = False
        self._filter_snippets = False
        self._filter_secrets = False
        self._filter_since: Optional[float] = None
        self._filter_source: Optional[str] = None
        # Mode édition inline (session 5 v2). Quand True, le preview_text
        # est éditable, un bandeau s'affiche, et on intercepte ⌘↩ pour
        # valider + ⎋ pour annuler.
        self._edit_mode = False
        self._edit_orig_item_id: Optional[int] = None
        self._action_buttons: list[QPushButton] = []
        # Mode bulk (v2.3) : sélection multiple via checkboxes sur les items
        # texte. Activé par le bouton "Copier en masse" en bas de sidebar.
        # Les images ne sont pas cochables (cf. discussion produit).
        self._bulk_mode: bool = False
        self._bulk_checked_ids: set[int] = set()

        self._build_ui()
        self._wire_shortcuts()
        self.refresh()

    # --- construction -------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        root_lay = QVBoxLayout(root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)

        # ============================================================
        # 1) Header band en haut, full width (sous la titlebar) — v2.3
        # ============================================================
        # Refonte v2.3 : le bandeau passe d'accent violet à fond neutre
        # clair (cohérent avec le reste de l'app, mode light). À droite,
        # une toolbar de 6 boutons donne accès aux actions globales :
        # Préférences, Raccourcis, Guide, À propos, Mini-fenêtre flottante,
        # Vider. Avant : ces actions étaient uniquement disponibles via
        # le menu de l'icône menubar — pas évident à découvrir.
        header_band = QWidget()
        header_band.setObjectName("headerBand")
        header_band.setFixedHeight(68)
        band_lay = QHBoxLayout(header_band)
        band_lay.setContentsMargins(20, 10, 16, 10)
        band_lay.setSpacing(8)
        title_lbl = QLabel("Klip")
        title_lbl.setObjectName("headerTitle")
        subtitle_lbl = QLabel("Historique du presse-papiers")
        subtitle_lbl.setObjectName("headerSubtitle")
        self.header_count = QLabel("")
        self.header_count.setObjectName("headerCount")
        band_lay.addWidget(title_lbl)
        band_lay.addWidget(subtitle_lbl)
        # Gros stretch avant les boutons (pousse la toolbar vers la droite)
        # + des petits stretchs entre chaque bouton pour les espacer
        # naturellement de gauche à droite au lieu de les coller en grappe.
        band_lay.addStretch(3)

        # === Toolbar des actions globales (à droite du header) ===
        # Chaque "bouton" est en fait un QWidget custom : icône SVG-like en
        # gros au-dessus + label dessous. Séparateur QFrame vertical entre
        # chaque pour bien marquer l'ambiance "toolbar" (cf. image cible).
        # `_toolbar_text_labels` mémorise les QLabel labels pour pouvoir
        # les cacher en mode étroit (responsive cf. resizeEvent).
        self._toolbar_text_labels: list[QLabel] = []
        # Labels raccourcis (l'intégralité reste dans le tooltip).
        # "Guide d'utilisation" et "Mini-fenêtre flottante" tronquaient
        # systématiquement aux tailles standards de fenêtre.
        toolbar_specs: list[tuple[str, str, str, Callable[[], None]]] = [
            # (icon, label, tooltip, handler)
            ("⚙",  "Préférences", "Préférences (⌘,)",                self._toolbar_open_prefs),
            ("⌘",  "Raccourcis",  "Raccourcis (⌘?)",                 self._toolbar_open_shortcuts),
            ("📖", "Guide",       "Guide d'utilisation",             self._toolbar_open_guide),
            ("ⓘ",  "À propos",    "À propos de Klip",                self._toolbar_open_about),
            ("◳",  "Flottante",   "Mini-fenêtre flottante",          self._toolbar_toggle_floating),
            ("🗑", "Vider",       "Vider (favoris/snippets préservés)", self._toolbar_clear),
        ]
        # Onglet ÉDITEUR « Licences » — visible uniquement si la clé privée
        # est présente (donc jamais chez les amis). Coloré en rouge plus bas.
        try:
            from . import licadmin
            if licadmin.is_editor():
                toolbar_specs.append(
                    ("🔑", "Licences", "Gérer les licences (éditeur)",
                     self._toolbar_open_licenses)
                )
        except Exception:
            pass
        for i, (icon, label, tooltip, handler) in enumerate(toolbar_specs):
            if i > 0:
                # Séparateur vertical entre les boutons (sans stretch :
                # les stretches comprimaient les labels et provoquaient
                # leur troncature, ex. "Préférences" -> "référence")
                sep = QFrame()
                sep.setObjectName("toolbarSep")
                sep.setFrameShape(QFrame.Shape.VLine)
                sep.setFixedWidth(1)
                sep.setFixedHeight(36)
                band_lay.addWidget(sep)

            btn = QPushButton()
            btn.setObjectName("toolbarBtn")
            btn.setToolTip(tooltip)
            btn.setFlat(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(handler)
            # Min-width assez large pour que "Préférences" et "Raccourcis"
            # (les plus longs des labels) tiennent à font-size 10px sans
            # troncature. Hauteur fixe pour alignement.
            btn.setMinimumWidth(96)
            btn.setMinimumHeight(48)
            btn.setSizePolicy(
                QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
            )
            # Layout interne du bouton : icône (gros) + label (petit) verticalement
            # stretch en haut et en bas pour centrer verticalement, même
            # quand le label est caché (mode compact responsive).
            btn_lay = QVBoxLayout(btn)
            btn_lay.setContentsMargins(8, 4, 8, 4)
            btn_lay.setSpacing(2)
            btn_lay.addStretch(1)
            icon_lbl = QLabel(icon)
            icon_lbl.setObjectName("toolbarBtnIcon")
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            text_lbl = QLabel(label)
            text_lbl.setObjectName("toolbarBtnLabel")
            text_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            # L'onglet éditeur « Licences » ressort en rouge.
            if label == "Licences":
                for _lbl in (icon_lbl, text_lbl):
                    _lbl.setStyleSheet("color: #ef4444; font-weight: 700;")
            btn_lay.addWidget(icon_lbl)
            btn_lay.addWidget(text_lbl)
            btn_lay.addStretch(1)
            # On mémorise le label pour le toggle responsive
            self._toolbar_text_labels.append(text_lbl)
            band_lay.addWidget(btn)

        root_lay.addWidget(header_band)

        # ============================================================
        # 2) Corps : sidebar pleine hauteur à gauche + contenu à droite
        # ============================================================
        body_row = QHBoxLayout()
        body_row.setContentsMargins(0, 0, 0, 0)
        body_row.setSpacing(0)

        # --- Sidebar verticale (du bandeau au bas) ---
        sidebar = QFrame()
        sidebar.setObjectName("filterSidebar")
        sidebar.setFixedWidth(220)
        sb_lay = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(12, 14, 12, 14)
        sb_lay.setSpacing(4)

        # Recherche en haut de la sidebar (compact)
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Rechercher…  ⌘L")
        self.search.textChanged.connect(self.refresh)
        sb_lay.addWidget(self.search)
        sb_lay.addSpacing(10)

        # Création de tous les boutons (filtres) avant placement.
        # v2.3.5 — icônes en préfixe pour reconnaissance visuelle rapide
        # (style référence user image 2).
        self.btn_all = self._make_chip("Tout", checked=True)
        self.btn_text = self._make_chip("Texte")
        self.btn_image = self._make_chip("Image")
        self.btn_fav = self._make_chip("Favoris")
        self.btn_snip = self._make_chip("Snippets")
        self.btn_secret = self._make_chip("Secret")
        self.btn_today = self._make_chip("Aujourd'hui")
        self.btn_week = self._make_chip("Cette semaine")

        # v2.3 — compteurs dynamiques alignés à droite sur chaque filtre.
        # `_filter_count_labels` mémorise les QLabel des compteurs pour
        # pouvoir les rafraîchir depuis `refresh()` via `_refresh_filter_counts`.
        self._filter_count_labels: dict[str, QLabel] = {}
        for key, btn, icon, label_text in (
            ("all",   self.btn_all,   "▦", "Tout"),
            ("text",  self.btn_text,  "T", "Texte"),
            ("image", self.btn_image, "◰", "Image"),
            ("fav",   self.btn_fav,   "★", "Favoris"),
            ("snip",  self.btn_snip,  "✎", "Snippets"),
            ("secret", self.btn_secret, "🔒", "Secret"),
        ):
            self._filter_count_labels[key] = self._inject_count_into_chip(
                btn, label_text, icon=icon
            )

        # Section FILTRES — v2.3.5 wrappée dans un QFrame "bloc" stylé
        sb_lay.addWidget(self._sb_section_title("Filtres"))
        filters_block = QFrame()
        filters_block.setObjectName("sidebarBlock")
        fb_lay = QVBoxLayout(filters_block)
        fb_lay.setContentsMargins(6, 6, 6, 6)
        fb_lay.setSpacing(2)
        for btn in (self.btn_all, self.btn_text, self.btn_image,
                    self.btn_fav, self.btn_snip, self.btn_secret):
            btn.setProperty("chip", False)
            btn.setProperty("class", "sidebarItem")
            btn.setMinimumHeight(32)
            fb_lay.addWidget(btn)
        sb_lay.addWidget(filters_block)
        sb_lay.addSpacing(10)

        # Section TEMPS — même traitement bloc
        sb_lay.addWidget(self._sb_section_title("Temps"))
        time_block = QFrame()
        time_block.setObjectName("sidebarBlock")
        tb_lay = QVBoxLayout(time_block)
        tb_lay.setContentsMargins(6, 6, 6, 6)
        tb_lay.setSpacing(2)
        for btn in (self.btn_today, self.btn_week):
            btn.setProperty("chip", False)
            btn.setProperty("class", "sidebarItem")
            btn.setMinimumHeight(32)
            tb_lay.addWidget(btn)
        sb_lay.addWidget(time_block)
        sb_lay.addSpacing(10)

        # Section APPLICATION — bloc avec dropdown
        sb_lay.addWidget(self._sb_section_title("Application"))
        app_block = QFrame()
        app_block.setObjectName("sidebarBlock")
        ab_lay = QVBoxLayout(app_block)
        ab_lay.setContentsMargins(6, 6, 6, 6)
        ab_lay.setSpacing(2)
        self.source_combo = QComboBox()
        self.source_combo.addItem("Toutes apps", None)
        self.source_combo.currentIndexChanged.connect(self._on_source_change)
        ab_lay.addWidget(self.source_combo)
        sb_lay.addWidget(app_block)
        sb_lay.addSpacing(10)

        # Section MES FILTRES retirée (v2.3) — l'utilisateur a demandé une
        # sidebar épurée. Les méthodes smart_folders restent dans le code
        # mais ne sont plus exposées dans l'UI principale. On garde le
        # container caché (et le layout) pour ne rien casser ailleurs si
        # un appel à _rebuild_smart_folders_ui() survient encore.
        self._smart_folders_row = QVBoxLayout()
        self._smart_folders_row.setSpacing(4)
        self._smart_folders_container = QWidget()
        self._smart_folders_container.setLayout(self._smart_folders_row)
        self._smart_folders_container.hide()  # masqué : pas dans sb_lay
        self._rebuild_smart_folders_ui()

        sb_lay.addStretch(1)

        # === Zone "Mode bulk" en bas de sidebar (v2.3) ===
        # Bouton principal "Copier en masse" qui toggle l'affichage des
        # checkboxes sur les items texte. Quand au moins 1 item est coché,
        # une zone contextuelle apparaît juste au-dessus avec le compteur
        # et le bouton "Copier la sélection".
        self.bulk_context_widget = QWidget()
        self.bulk_context_widget.setObjectName("bulkContextWidget")
        bc_lay = QVBoxLayout(self.bulk_context_widget)
        bc_lay.setContentsMargins(10, 10, 10, 10)
        bc_lay.setSpacing(8)
        self.lbl_bulk_count = QLabel("0 élément sélectionné")
        self.lbl_bulk_count.setObjectName("bulkCountLabel")
        self.lbl_bulk_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_bulk_copy = QPushButton("Copier la sélection")
        self.btn_bulk_copy.clicked.connect(self._copy_bulk_selection)
        bc_lay.addWidget(self.lbl_bulk_count)
        bc_lay.addWidget(self.btn_bulk_copy)
        self.bulk_context_widget.hide()
        sb_lay.addWidget(self.bulk_context_widget)

        self.btn_bulk_mass = QPushButton("Copier en masse")
        self.btn_bulk_mass.setObjectName("primary")
        self.btn_bulk_mass.setMinimumHeight(36)
        self.btn_bulk_mass.clicked.connect(self._toggle_bulk_mode)
        sb_lay.addWidget(self.btn_bulk_mass)

        body_row.addWidget(sidebar, 0)

        # --- Contenu principal (à droite) ---
        content = QWidget()
        content.setObjectName("contentArea")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)

        # v2.3 — Ligne de stats supprimée (demande user : info redondante
        # avec les compteurs de la sidebar (Tout 1437, Texte 1416, etc.).
        # On garde les QLabel en mémoire (non ajoutés au layout) pour ne
        # pas casser le code de refresh() qui les met à jour.
        self.stats_label = QLabel("")
        self.stats_label.setObjectName("meta")
        self.stats_label.hide()
        self.header_count.hide()

        # Le body (list + preview) suit en dessous
        body = QHBoxLayout()
        body.setSpacing(10)
        # `HistoryListWidget` (subclass) au lieu de `QListWidget` natif —
        # ajoute le support drag externe vers Finder/Mail/Slack via un
        # `mimeData()` override qui expose URLs locales + texte + image.
        self.list = HistoryListWidget(self.db)
        self.list.settings = self.settings
        # Cache de miniatures partagé avec le delegate — chargé à la demande
        # depuis db.get_image_blob() pour ne pas exploser la RAM.
        self._thumb_cache = ThumbCache(self.db)
        self.list.setItemDelegate(
            ItemDelegate(
                self.list,
                thumb_cache=self._thumb_cache,
                is_bulk_mode_fn=lambda: self._bulk_mode,
                is_checked_fn=lambda iid: iid in self._bulk_checked_ids,
            )
        )
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setUniformItemSizes(True)
        self.list.setMouseTracking(True)
        self.list.currentItemChanged.connect(self._on_select)
        self.list.itemActivated.connect(lambda *_: self.copy_current())
        # Double-clic sur un item texte → mode édition inline (différent
        # de itemActivated qui se déclenche aussi sur Entrée).
        self.list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_context_menu)
        # Largeur minimum pour qu'on voie toujours au moins un titre tronqué
        # raisonnablement (et pas juste l'emoji ⌘1).
        self.list.setMinimumWidth(280)

        # Panneau aperçu
        self.preview_frame = QFrame()
        self.preview_frame.setObjectName("preview")
        pv = QVBoxLayout(self.preview_frame)
        pv.setContentsMargins(18, 14, 18, 14)
        pv.setSpacing(10)
        # Hiérarchie : caps "APERÇU" en accent / meta sur la ligne de
        # détails / espace / contenu en dessous.
        self.preview_title = QLabel("Aperçu")
        self.preview_title.setProperty("class", "caps")
        # v2.3.3 — Le preview_meta passe d'un QLabel HTML à un container
        # avec FlowLayout pour pouvoir styler chaque tag via QSS (qui
        # supporte vraiment border-radius, contrairement au rich text Qt
        # qui l'ignore sur <span> inline). Le QLabel `preview_meta` reste
        # créé pour rétro-compat (certains code paths le mettent à "").
        self.preview_meta = QLabel("")
        self.preview_meta.hide()  # plus utilisé visuellement
        self.preview_meta_container = QWidget()
        self.preview_meta_flow = FlowLayout(spacing=6)
        self.preview_meta_container.setLayout(self.preview_meta_flow)
        self.preview_image = QLabel()
        self.preview_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_image.setMinimumHeight(140)
        self.preview_image.setMaximumHeight(320)
        # Cadre subtil autour de l'image + fond doux pour mieux la séparer
        # du texte OCR qui peut suivre dessous. Sans ça l'image flottait
        # « brute » sans isoler clairement la zone visuelle.
        self.preview_image.setStyleSheet(
            f"QLabel {{"
            f"  background: {PALETTE['bg_elev']};"
            f"  border: 1px solid {PALETTE['border']};"
            f"  border-radius: 8px;"
            f"  padding: 8px;"
            f"}}"
        )
        self.preview_image.hide()
        self.color_swatch = QLabel()
        self.color_swatch.setMinimumHeight(64)
        self.color_swatch.hide()
        self.preview_text = QTextEdit()
        self.preview_text.setObjectName("previewBody")
        self.preview_text.setReadOnly(True)
        self.preview_text.setFont(QFont("SF Mono, Menlo, Monaco, monospace", 12))
        # Bandeau visible uniquement en mode édition inline.
        self.edit_banner = QLabel("✎  Mode édition  —  ⌘↩ valider · ⎋ annuler")
        self.edit_banner.setStyleSheet(
            f"color: white; background: {PALETTE['accent']}; "
            f"border-radius: 6px; padding: 4px 10px; "
            f"font-size: 11px; font-weight: 600;"
        )
        self.edit_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.edit_banner.hide()
        self.preview_ocr_label = QLabel("")
        self.preview_ocr_label.setObjectName("meta")
        self.preview_ocr_label.setWordWrap(True)
        self.preview_ocr_label.hide()
        pv.addWidget(self.preview_title)
        pv.addWidget(self.preview_meta)
        pv.addWidget(self.preview_meta_container)
        pv.addWidget(self.edit_banner)
        pv.addWidget(self.color_swatch)
        pv.addWidget(self.preview_image)
        pv.addWidget(self.preview_text, 1)
        pv.addWidget(self.preview_ocr_label)

        # Séparateur visuel Aperçu ↑ / Actions ↓ — sans ça les boutons
        # collaient au texte et on ne percevait pas que la zone change
        # de rôle (visualisation → manipulation).
        sep = QFrame()
        sep.setObjectName("previewSep")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1)
        pv.addSpacing(6)
        pv.addWidget(sep)
        pv.addSpacing(4)

        # Boutons standards. QHBoxLayout pour avoir Supprimer
        # ancre a droite via addStretch(). On reduit padding/font pour
        # que tout rentre confortablement dans le panneau.
        actions = QHBoxLayout()
        actions.setSpacing(4)
        self.btn_copy = QPushButton("Copier")
        self.btn_copy.setObjectName("primary")
        self.btn_copy.clicked.connect(self.copy_current)
        self.btn_pin = QPushButton("☆ Épingler")
        self.btn_pin.clicked.connect(self.toggle_favorite_current)
        self.btn_snippet = QPushButton("✎ Snippet…")
        self.btn_snippet.clicked.connect(self.make_snippet_current)
        # Bouton « ✎ Éditer » (session 5 v2) — entre en mode édition
        # inline sur l'item texte courant. Plus visible qu'un raccourci
        # ⌘E ou un double-clic, surtout pour les utilisateurs casual.
        # Désactivé pour les items non-texte.
        self.btn_edit = QPushButton("✎ Éditer")
        self.btn_edit.clicked.connect(self._enter_edit_mode)
        self.btn_edit.setEnabled(False)
        self.btn_edit.setToolTip(
            "Éditer le texte avant de le copier (⌘E ou double-clic)"
        )
        # Nouveau bouton « Macro ▾ » (session 5) — regroupe toutes les
        # transformations de texte (UPPER, lower, slug, base64, url, trim…)
        # dans un menu déroulant pour éviter d'inonder la zone d'aperçu avec
        # 8 boutons supplémentaires. Désactivé tant qu'aucun item texte
        # n'est sélectionné.
        self.btn_transform = QPushButton("Macro ▾")
        self.btn_transform.clicked.connect(self._show_transform_menu)
        self.btn_transform.setEnabled(False)
        self.btn_del = QPushButton("Supprimer")
        self.btn_del.setObjectName("danger")
        self.btn_del.clicked.connect(self.delete_current)
        # Style compact pour que les 5 boutons rentrent dans la largeur
        # du panneau apercu sans tronquage. font/padding reduits.
        compact_qss = (
            "QPushButton { padding: 5px 9px; font-size: 11px; }"
        )
        for _btn in (self.btn_copy, self.btn_pin, self.btn_edit,
                     self.btn_transform, self.btn_del):
            _btn.setStyleSheet(_btn.styleSheet() + compact_qss)
        actions.addWidget(self.btn_copy)
        actions.addWidget(self.btn_pin)
        actions.addWidget(self.btn_edit)
        actions.addWidget(self.btn_transform)
        actions.addStretch(1)
        actions.addWidget(self.btn_del)
        # Note (session 5 v2) : `self.btn_snippet` n'est plus ajouté à la
        # rangée — son action vit maintenant en première entrée du menu
        # déroulant « Macro ▾ ».
        pv.addLayout(actions)

        # Container pour les actions contextuelles dynamiques. On utilise
        # un FlowLayout (wrap automatique) au lieu d'un QHBoxLayout, sinon
        # les nouvelles transformations Phase 1 (MAJUSCULES, slugifier,
        # base64, URL…) dépassent à droite et sont tronquées.
        self.actions_row = FlowLayout(spacing=6)
        actions_wrap = QWidget()
        actions_wrap.setLayout(self.actions_row)
        pv.addWidget(actions_wrap)

        # Layout liste/preview AVEC handle draggable (v2.4).
        # L'utilisateur peut élargir la liste au détriment de l'aperçu et
        # inversement, via la poignée centrale. La position est mémorisée.
        self.list.setMinimumWidth(220)
        self.list.setMaximumWidth(16777215)  # plus de cap : le splitter gère
        self.preview_frame.setMinimumWidth(320)
        self.body_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.body_splitter.setObjectName("bodySplitter")
        self.body_splitter.setHandleWidth(8)
        self.body_splitter.setChildrenCollapsible(False)
        self.body_splitter.addWidget(self.list)
        self.body_splitter.addWidget(self.preview_frame)
        self.body_splitter.setStretchFactor(0, 0)
        self.body_splitter.setStretchFactor(1, 1)

        # Position initiale ou restaurée depuis les réglages.
        saved = self.settings.get("ui.split_sizes", None) if self.settings else None
        if (isinstance(saved, (list, tuple)) and len(saved) == 2
                and all(isinstance(x, int) and x > 0 for x in saved)):
            self.body_splitter.setSizes(list(saved))
        else:
            self.body_splitter.setSizes([320, 720])

        # Sauvegarde débouncée (500 ms après le dernier mouvement) pour ne
        # pas spammer le journal des réglages pendant le glissement.
        if self.settings is not None:
            self._split_save_timer = QTimer(self)
            self._split_save_timer.setSingleShot(True)
            self._split_save_timer.setInterval(500)
            self._split_save_timer.timeout.connect(
                lambda: self.settings.set(
                    "ui.split_sizes", self.body_splitter.sizes(), source="ui"
                )
            )
            self.body_splitter.splitterMoved.connect(
                lambda *_: self._split_save_timer.start()
            )

        body.addWidget(self.body_splitter, 1)
        layout.addLayout(body, 1)

        # On rattache le contenu au body_row à droite de la sidebar.
        body_row.addWidget(content, 1)
        root_lay.addLayout(body_row, 1)

        # Status bar
        self.status = QStatusBar()
        self.status.setSizeGripEnabled(False)
        self.setStatusBar(self.status)
        # Message d'accueil compact ; les raccourcis détaillés sont dans la
        # cheatsheet ⌘?. Avant : ligne trop longue qui se faisait tronquer.
        self.status.showMessage("⌘? pour les raccourcis  ·  ⌘, pour les préférences")

        # Applique le QSS correspondant au thème choisi (dark/light/auto).
        # Le thème est passé au constructeur depuis main.py via les settings.
        self.setStyleSheet(current_qss(self._theme))

    def _sb_section_title(self, label: str) -> QLabel:
        """Helper : titre de section dans la sidebar (caps + accent)."""
        lbl = QLabel(label.upper())
        lbl.setProperty("class", "caps")
        lbl.setStyleSheet("padding: 4px 6px 2px 6px;")
        return lbl

    def _inject_count_into_chip(
        self,
        btn: QPushButton,
        label_text: str,
        icon: Optional[str] = None,
    ) -> QLabel:
        """Transforme un QPushButton en chip à 3 colonnes : icône + label + count.

        v2.3.5 — icône optionnelle en début de ligne pour reconnaissance
        visuelle rapide (▦ Tout, T Texte, ◰ Image, ★ Favoris, ✎ Snippets).
        """
        btn.setText("")
        lay = QHBoxLayout(btn)
        lay.setContentsMargins(10, 0, 12, 0)
        lay.setSpacing(8)
        if icon:
            icon_lbl = QLabel(icon)
            icon_lbl.setObjectName("filterChipIcon")
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            icon_lbl.setFixedWidth(18)
            icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            lay.addWidget(icon_lbl)
        lbl = QLabel(label_text)
        lbl.setObjectName("filterChipLabel")
        lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        cnt = QLabel("")
        cnt.setObjectName("filterCount")
        cnt.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        cnt.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        lay.addWidget(lbl)
        lay.addStretch(1)
        lay.addWidget(cnt)
        return cnt

    # ------------------------------------------------------------------
    # Helpers — dialogs custom theme-aware (v2.3.7)
    # ------------------------------------------------------------------
    # QMessageBox standard utilise le style natif macOS et reste sombre
    # même quand on lui setStyleSheet(current_qss()). On construit un
    # QDialog complet qui hérite du QSS de la MainWindow et passe en
    # WindowModal pour bloquer pendant qu'il s'affiche.

    def _confirm_dialog(
        self, title: str, message: str, info: str = "",
        danger: bool = False,
    ) -> bool:
        """Affiche un dialog Oui/Non stylé via le QSS de l'app.
        Retourne True si l'utilisateur clique Oui.
        """
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setModal(True)
        dlg.setMinimumWidth(420)
        dlg.setStyleSheet(current_qss())

        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(24, 22, 24, 18)
        outer.setSpacing(12)

        # En-tête icône + titre
        head = QHBoxLayout()
        head.setSpacing(14)
        icon_lbl = QLabel("⚠" if danger else "?")
        icon_lbl.setStyleSheet(
            f"font-size: 26px; font-weight: 700; "
            f"color: {PALETTE['danger'] if danger else PALETTE['accent']}; "
            f"background: transparent; border: 0;"
        )
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setFixedWidth(36)
        head.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)
        msg_lbl = QLabel(message)
        msg_lbl.setStyleSheet(
            f"font-size: 14px; font-weight: 600; "
            f"color: {PALETTE['text']}; background: transparent; border: 0;"
        )
        msg_lbl.setWordWrap(True)
        text_col.addWidget(msg_lbl)
        if info:
            info_lbl = QLabel(info)
            info_lbl.setStyleSheet(
                f"font-size: 12px; "
                f"color: {PALETTE['text_dim']}; background: transparent; border: 0;"
            )
            info_lbl.setWordWrap(True)
            text_col.addWidget(info_lbl)
        head.addLayout(text_col, 1)
        outer.addLayout(head)

        # Boutons (No à gauche, Yes à droite)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_no = QPushButton("Annuler")
        btn_no.setMinimumWidth(90)
        btn_yes = QPushButton("Supprimer" if danger else "Confirmer")
        btn_yes.setObjectName("danger" if danger else "primary")
        btn_yes.setMinimumWidth(110)
        btn_no.clicked.connect(dlg.reject)
        btn_yes.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_no)
        btn_row.addWidget(btn_yes)
        outer.addLayout(btn_row)

        return dlg.exec() == QDialog.DialogCode.Accepted

    # ------------------------------------------------------------------
    # Responsive : toolbar header en icon-only quand fenêtre étroite
    # ------------------------------------------------------------------
    TOOLBAR_COMPACT_THRESHOLD = 950  # px — en dessous, on cache les labels

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """Bascule la toolbar en mode icon-only quand la fenêtre est étroite.

        Au-dessus du seuil, on réaffiche les labels sous chaque icône.
        En dessous, on les cache (les boutons ne montrent que l'emoji),
        ce qui évite la troncature pénible des longs noms (« Guide
        d'utilisation », « Mini-fenêtre flottante »…).
        """
        super().resizeEvent(event)
        labels = getattr(self, "_toolbar_text_labels", None)
        if not labels:
            return
        compact = self.width() < self.TOOLBAR_COMPACT_THRESHOLD
        for lbl in labels:
            lbl.setVisible(not compact)

    # ------------------------------------------------------------------
    # Handlers du toolbar header (v2.3)
    # ------------------------------------------------------------------
    # Chaque handler vérifie d'abord si l'appelant a fourni un callback
    # (cas standard : main.py passe ses _open_prefs / _open_cheatsheet…
    # déjà testés et qui gèrent le holder anti-duplicate). Si aucun
    # callback fourni, on tombe sur un import direct du module pour que
    # la MainWindow reste utilisable sans plomberie (test, mode dev).

    def _toolbar_open_prefs(self) -> None:
        cb = self._toolbar_callbacks.get("prefs")
        if cb:
            try:
                cb()
                return
            except Exception:
                pass
        # Fallback : import direct. Signature: open_preferences(settings, db, ...)
        try:
            from .prefs import open_preferences
            open_preferences(self.settings, self.db, parent=self)
        except Exception as e:
            QMessageBox.warning(self, "Préférences", f"Erreur : {e}")

    def _toolbar_open_shortcuts(self) -> None:
        cb = self._toolbar_callbacks.get("shortcuts")
        if cb:
            try:
                cb()
                return
            except Exception:
                pass
        try:
            from .cheatsheet import open_cheatsheet
            open_cheatsheet(parent=self)
        except Exception as e:
            QMessageBox.warning(self, "Raccourcis", f"Erreur : {e}")

    def _toolbar_open_guide(self) -> None:
        cb = self._toolbar_callbacks.get("guide")
        if cb:
            try:
                cb()
                return
            except Exception:
                pass
        try:
            from .guide import open_guide
            open_guide(parent=self)
        except Exception as e:
            QMessageBox.warning(self, "Guide", f"Erreur : {e}")

    def _toolbar_open_about(self) -> None:
        cb = self._toolbar_callbacks.get("about")
        if cb:
            try:
                cb()
                return
            except Exception:
                pass
        try:
            from .about import open_about
            open_about(self.db, parent=self)
        except Exception as e:
            QMessageBox.warning(self, "À propos", f"Erreur : {e}")

    def _toolbar_open_licenses(self) -> None:
        """Ouvre le gestionnaire de licences (mode éditeur uniquement)."""
        try:
            from .licadmin_ui import open_license_admin
            if not hasattr(self, "_licadmin_holder"):
                self._licadmin_holder = []
            if self._licadmin_holder and self._licadmin_holder[-1].isVisible():
                w = self._licadmin_holder[-1]
                w.raise_()
                w.activateWindow()
                return
            self._licadmin_holder.clear()
            self._licadmin_holder.append(open_license_admin(parent=self))
        except Exception as e:
            QMessageBox.warning(self, "Licences", f"Erreur : {e}")

    def _toolbar_toggle_floating(self) -> None:
        cb = self._toolbar_callbacks.get("floating")
        if cb:
            try:
                cb()
                return
            except Exception as e:
                QMessageBox.warning(self, "Mini-fenêtre", f"Erreur : {e}")
                return
        QMessageBox.information(
            self,
            "Mini-fenêtre flottante",
            "La mini-fenêtre se contrôle depuis les Préférences ou via le "
            "menu de l'icône menubar (✂ en haut).\n\nPour basculer rapidement : "
            "ouvre Préférences → Apparence."
        )

    def _toolbar_clear(self) -> None:
        """Vider l'historique en préservant favoris + snippets.
        Toujours avec confirmation (action destructive)."""
        if not self._confirm_dialog(
            title="Vider l'historique",
            message="Vider l'historique du presse-papiers ?",
            info="Les favoris (★) et snippets (✎) seront préservés.\n"
                 "Cette action est irréversible.",
            danger=True,
        ):
            return
        try:
            n = self.db.clear_non_favorites()
            self.refresh()
            try:
                self.status.showMessage(f"✓ {n} élément(s) supprimé(s)", 3000)
            except Exception:
                pass
        except Exception as e:
            QMessageBox.warning(self, "Vider", f"Erreur : {e}")

    # ------------------------------------------------------------------
    # Mode bulk (v2.3) : sélection multiple via checkboxes
    # ------------------------------------------------------------------

    def _toggle_bulk_mode(self) -> None:
        """Active / désactive le mode bulk.

        En mode bulk :
          - Les items texte affichent une checkbox à gauche.
          - Les items image ne sont pas cochables (checkbox grisée).
          - La zone contextuelle "X éléments sélectionnés" apparaît si
            au moins 1 item est coché.
          - Le bouton "Copier en masse" devient "Annuler".

        À la sortie : reset du set de cochés + UI normale.
        """
        self._bulk_mode = not self._bulk_mode
        if self._bulk_mode:
            self.btn_bulk_mass.setText("Annuler")
            self.lbl_bulk_count.setText("0 élément sélectionné")
            self.bulk_context_widget.hide()  # apparaîtra dès la 1ère case cochée
        else:
            self.btn_bulk_mass.setText("Copier en masse")
            self._bulk_checked_ids.clear()
            self.bulk_context_widget.hide()
        # Force le delegate à redessiner les items (avec/sans checkboxes)
        self.list.viewport().update()

    def _on_bulk_item_toggled(self, item_id: int) -> None:
        """Appelé par le ItemDelegate quand on clique sur une checkbox.

        Toggle l'ID dans le set, met à jour le label compteur, affiche
        ou cache la zone contextuelle selon qu'il y a au moins 1 sélection.
        """
        if item_id in self._bulk_checked_ids:
            self._bulk_checked_ids.discard(item_id)
        else:
            self._bulk_checked_ids.add(item_id)
        n = len(self._bulk_checked_ids)
        if n == 0:
            self.lbl_bulk_count.setText("0 élément sélectionné")
            self.bulk_context_widget.hide()
        else:
            label = "élément sélectionné" if n == 1 else "éléments sélectionnés"
            self.lbl_bulk_count.setText(f"{n} {label}")
            self.bulk_context_widget.show()
        self.list.viewport().update()

    def _copy_bulk_selection(self) -> None:
        """Concatène le texte des items cochés avec séparateur '---'
        et copie dans le presse-papiers. Affiche un toast de confirmation.
        """
        if not self._bulk_checked_ids:
            return
        texts: list[str] = []
        # Ordre déterministe par created_at desc pour stabilité visuelle.
        # On récupère chaque item via la liste actuellement chargée pour
        # éviter une nouvelle requête DB par item.
        all_items_by_id: dict[int, Item] = {}
        for i in range(self.list.count()):
            li = self.list.item(i)
            data = li.data(Qt.ItemDataRole.UserRole) if li else None
            if isinstance(data, Item):
                all_items_by_id[data.id] = data
        for iid in self._bulk_checked_ids:
            it = all_items_by_id.get(iid)
            if it and it.kind == "text" and it.text:
                texts.append(it.text)
        if not texts:
            return
        joined = "\n---\n".join(texts)
        QGuiApplication.clipboard().setText(joined)
        n = len(texts)
        try:
            self.status.showMessage(
                f"✓ {n} élément{'s' if n > 1 else ''} copié{'s' if n > 1 else ''} "
                f"(séparateur '---')", 3000
            )
        except Exception:
            pass
        # On sort du mode bulk après une copie réussie : flux naturel.
        self._toggle_bulk_mode()

    def _refresh_filter_counts(self) -> None:
        """Met à jour les compteurs (Tout 1420, Texte 38, Image 30, etc.)
        affichés à droite de chaque filtre dans la sidebar. Lit ``db.stats()``.
        """
        if not hasattr(self, "_filter_count_labels"):
            return
        try:
            stats = self.db.stats()
        except Exception:
            return
        mapping = {
            "all":   int(stats.get("total") or 0),
            "text":  int(stats.get("text_count") or 0),
            "image": int(stats.get("image_count") or 0),
            "fav":   int(stats.get("favs") or 0),
            "snip":  int(stats.get("snippets") or 0),
            "secret": int(stats.get("secrets") or 0),
        }
        for key, n in mapping.items():
            lbl = self._filter_count_labels.get(key)
            if lbl is not None:
                lbl.setText(str(n))

    def reapply_theme(self) -> None:
        """Hook appelé depuis Préférences quand l'utilisateur change le
        thème ou l'accent.

        Re-applique le QSS courant + restyle les widgets dont le
        stylesheet est inline (basé sur ``PALETTE['xxx']`` figé au moment
        de la création du widget). Sans ça, après changement d'accent
        on aurait le QSS global mis à jour mais les éléments stylés
        inline (preview_image, edit_banner, swatch, …) gardaient leur
        ancienne couleur jusqu'au prochain redémarrage.
        """
        try:
            self.setStyleSheet(current_qss())
        except Exception:
            pass
        # 1) preview_image (fond + bordure)
        try:
            self.preview_image.setStyleSheet(
                f"QLabel {{"
                f"  background: {PALETTE['bg_elev']};"
                f"  border: 1px solid {PALETTE['border']};"
                f"  border-radius: 8px;"
                f"  padding: 8px;"
                f"}}"
            )
        except Exception:
            pass
        # 2) edit_banner (couleur de bande accent)
        try:
            self.edit_banner.setStyleSheet(
                f"color: white; background: {PALETTE['accent']}; "
                f"border-radius: 6px; padding: 4px 10px; "
                f"font-size: 11px; font-weight: 600;"
            )
        except Exception:
            pass
        # 3) Force le repaint du delegate de la liste (qui peint avec
        # PALETTE['accent'] sur la sélection).
        try:
            self.list.viewport().update()
        except Exception:
            pass
        # 4) Re-render le preview pour rafraîchir les tags meta (couleurs
        # adaptées au thème) — preview_meta utilise du HTML avec couleurs
        # figées au moment du _render_preview précédent.
        try:
            cur = self.list.currentItem()
            if cur is not None:
                self._render_preview(cur.data(Qt.ItemDataRole.UserRole))
        except Exception:
            pass
        # 5) Rebuild des smart folders (le bouton "+ Filtre" et les
        # chips sauvegardés ont leur styling inline généré par
        # _rebuild_smart_folders_ui — on relance la construction pour
        # qu'ils prennent la palette courante).
        try:
            self._rebuild_smart_folders_ui()
        except Exception:
            pass

    def _make_chip(self, text: str, checked: bool = False) -> QPushButton:
        """Crée un bouton "chip" — le styling vit dans theme.py (QSS global)
        sous le sélecteur ``QPushButton[chip="true"]`` pour qu'il se
        ré-évalue automatiquement quand on change de thème. L'ancienne
        version posait un ``setStyleSheet`` inline avec une f-string
        évaluée à la création → en mode sombre les chips gardaient le
        fond crème du mode clair.
        """
        btn = QPushButton(text)
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.clicked.connect(self._on_chip)
        btn.setProperty("chip", True)
        return btn

    # --- filters ------------------------------------------------------------

    def _on_chip(self) -> None:
        sender = self.sender()
        # Type / favoris / snippets sont mutuellement exclusifs
        if sender in (self.btn_all, self.btn_text, self.btn_image, self.btn_fav, self.btn_snip, self.btn_secret):
            for b in (self.btn_all, self.btn_text, self.btn_image, self.btn_fav, self.btn_snip, self.btn_secret):
                b.setChecked(b is sender)
            self._filter_kind = None
            self._filter_favs = False
            self._filter_snippets = False
            self._filter_secrets = False
            if sender is self.btn_text:
                self._filter_kind = "text"
            elif sender is self.btn_image:
                self._filter_kind = "image"
            elif sender is self.btn_fav:
                self._filter_favs = True
            elif sender is self.btn_snip:
                self._filter_snippets = True
            elif sender is self.btn_secret:
                self._filter_secrets = True
        # Date — exclusif entre eux
        if sender in (self.btn_today, self.btn_week):
            other = self.btn_week if sender is self.btn_today else self.btn_today
            if sender.isChecked():
                other.setChecked(False)
            self._filter_since = (
                since_today() if self.btn_today.isChecked()
                else since_week() if self.btn_week.isChecked()
                else None
            )
        self.refresh()

    def _on_source_change(self, idx: int) -> None:
        self._filter_source = self.source_combo.itemData(idx)
        self.refresh()

    def _refresh_source_combo(self) -> None:
        current = self.source_combo.currentData()
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItem("Toutes apps", None)
        for app, count in self.db.top_source_apps(8):
            self.source_combo.addItem(f"{app}  ({count})", app)
        # restore selection
        if current:
            i = self.source_combo.findData(current)
            if i >= 0:
                self.source_combo.setCurrentIndex(i)
        self.source_combo.blockSignals(False)

    # --- smart folders (filtres sauvegardés) -------------------------------

    def _rebuild_smart_folders_ui(self) -> None:
        """Reconstruit la rangée de chips smart folders depuis settings."""
        # Vide la rangée actuelle
        while self._smart_folders_row.count():
            child = self._smart_folders_row.takeAt(0)
            if child and child.widget():
                child.widget().deleteLater()

        # Label fixe à gauche
        label = QLabel("Mes filtres :")
        label.setStyleSheet(
            f"color: {PALETTE['text_dim']}; font-size: 11px; "
            f"padding: 4px 4px 4px 0;"
        )
        self._smart_folders_row.addWidget(label)

        # Chips depuis settings
        folders = []
        if self.settings is not None:
            raw = self.settings.get("smart_folders", []) or []
            if isinstance(raw, list):
                folders = [f for f in raw if isinstance(f, dict)]

        if not folders:
            empty = QLabel("aucun — cliquez « + » pour bookmarker l'état actuel")
            empty.setStyleSheet(
                f"color: {PALETTE['text_faint']}; font-size: 11px; "
                f"font-style: italic; padding: 4px 0;"
            )
            self._smart_folders_row.addWidget(empty)
        else:
            for folder in folders:
                self._smart_folders_row.addWidget(self._make_smart_chip(folder))

        self._smart_folders_row.addStretch(1)

        # Bouton « + Filtre » à droite (toujours présent)
        add_btn = QPushButton("+ Filtre")
        add_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background: {PALETTE['bg_elev']}; "
            f"  color: {PALETTE['accent']}; "
            f"  border: 1px dashed {PALETTE['accent']}; "
            f"  border-radius: 12px; "
            f"  padding: 3px 12px; "
            f"  font-size: 11px; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background: {PALETTE['accent']}; "
            f"  color: white; "
            f"  border-style: solid;"
            f"}}"
        )
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setToolTip(
            "Sauvegarde l'état actuel des filtres et de la recherche\n"
            "sous un nom — pour le rappliquer d'un clic plus tard."
        )
        add_btn.clicked.connect(self._save_current_as_smart_folder)
        self._smart_folders_row.addWidget(add_btn)

    def _make_smart_chip(self, folder: dict) -> QPushButton:
        """Crée un chip pour un smart folder donné."""
        name = str(folder.get("name", "?"))
        chip = QPushButton(name)
        chip.setStyleSheet(
            f"QPushButton {{"
            f"  background: {PALETTE['bg_panel']}; "
            f"  color: {PALETTE['text']}; "
            f"  border: 1px solid {PALETTE['border']}; "
            f"  border-radius: 12px; "
            f"  padding: 3px 12px; "
            f"  font-size: 11px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  border-color: {PALETTE['accent']}; "
            f"  color: {PALETTE['accent']};"
            f"}}"
        )
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        chip.setToolTip(f"Cliquer pour appliquer • Clic droit pour supprimer")
        chip.clicked.connect(lambda _checked=False, f=folder: self._apply_smart_folder(f))
        chip.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        chip.customContextMenuRequested.connect(
            lambda _pos, n=name: self._smart_folder_context_menu(n)
        )
        return chip

    def _save_current_as_smart_folder(self) -> None:
        """Bookmark l'état courant des filtres + recherche sous un nom."""
        if self.settings is None:
            QMessageBox.warning(
                self,
                "Indisponible",
                "Les smart folders nécessitent l'accès aux préférences.",
            )
            return

        name, ok = QInputDialog.getText(
            self,
            "Nouveau filtre",
            "Donnez un nom à ce filtre :",
            text="",
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            return

        folder = {
            "name": name,
            "kind": self._filter_kind,
            "favorites_only": self._filter_favs,
            "snippets_only": self._filter_snippets,
            "secrets_only": self._filter_secrets,
            "since_ts": self._filter_since,
            "source_app": self._filter_source,
            "query": self.search.text(),
        }
        folders = list(self.settings.get("smart_folders", []) or [])
        # Si un filtre avec le même nom existe → on remplace (pas de doublons)
        folders = [f for f in folders if isinstance(f, dict) and f.get("name") != name]
        folders.append(folder)
        self.settings.set(
            "smart_folders",
            folders,
            note=f"Filtre « {name} » sauvegardé.",
            source="ui",
        )
        self._rebuild_smart_folders_ui()

    def _apply_smart_folder(self, folder: dict) -> None:
        """Applique tous les filtres + recherche d'un smart folder."""
        self._filter_kind = folder.get("kind")
        self._filter_favs = bool(folder.get("favorites_only", False))
        self._filter_snippets = bool(folder.get("snippets_only", False))
        self._filter_secrets = bool(folder.get("secrets_only", False))
        self._filter_since = folder.get("since_ts")
        self._filter_source = folder.get("source_app")

        # Resynchronise la barre de recherche
        query = str(folder.get("query", "") or "")
        self.search.blockSignals(True)
        self.search.setText(query)
        self.search.blockSignals(False)

        # Resynchronise l'état visuel des chips standards
        self._sync_chip_visual_state()
        self.refresh()

    def _sync_chip_visual_state(self) -> None:
        """Aligne l'état coché des chips standards sur les filtres internes."""
        # Type / favoris / snippets — exclusifs
        self.btn_all.setChecked(
            self._filter_kind is None
            and not self._filter_favs
            and not self._filter_snippets
            and not self._filter_secrets
        )
        self.btn_text.setChecked(self._filter_kind == "text")
        self.btn_image.setChecked(self._filter_kind == "image")
        self.btn_fav.setChecked(self._filter_favs)
        self.btn_snip.setChecked(self._filter_snippets)
        self.btn_secret.setChecked(self._filter_secrets)

        # Date — aujourd'hui/semaine/aucun
        from .fuzzy import since_today, since_week
        is_today = (
            self._filter_since is not None
            and abs(self._filter_since - since_today()) < 1
        )
        is_week = (
            self._filter_since is not None
            and abs(self._filter_since - since_week()) < 1
        )
        self.btn_today.setChecked(is_today)
        self.btn_week.setChecked(is_week)

        # Source app combo
        if self._filter_source is not None:
            i = self.source_combo.findData(self._filter_source)
            if i >= 0:
                self.source_combo.blockSignals(True)
                self.source_combo.setCurrentIndex(i)
                self.source_combo.blockSignals(False)

    def _smart_folder_context_menu(self, name: str) -> None:
        """Clic droit sur un chip smart folder → menu contextuel."""
        menu = QMenu(self)
        del_action = menu.addAction(f"Supprimer « {name} »")
        chosen = menu.exec(QCursor.pos())
        if chosen == del_action:
            self._remove_smart_folder(name)

    def _remove_smart_folder(self, name: str) -> None:
        if self.settings is None:
            return
        folders = list(self.settings.get("smart_folders", []) or [])
        folders = [f for f in folders if isinstance(f, dict) and f.get("name") != name]
        self.settings.set(
            "smart_folders",
            folders,
            note=f"Filtre « {name} » supprimé.",
            source="ui",
        )
        self._rebuild_smart_folders_ui()

    # --- shortcuts ----------------------------------------------------------

    def _wire_shortcuts(self) -> None:
        QShortcut(QKeySequence("Esc"), self, self._on_escape)
        # ⌘E pour entrer en édition, ⌘↩ pour valider l'édition
        QShortcut(QKeySequence("Meta+E"), self, self._enter_edit_mode)
        QShortcut(QKeySequence("Ctrl+E"), self, self._enter_edit_mode)
        QShortcut(QKeySequence("Meta+Return"), self, self._validate_edit_mode)
        QShortcut(QKeySequence("Ctrl+Return"), self, self._validate_edit_mode)
        QShortcut(QKeySequence("Meta+L"), self, self.search.setFocus)
        QShortcut(QKeySequence("Ctrl+L"), self, self.search.setFocus)
        QShortcut(QKeySequence("Meta+P"), self, self.toggle_favorite_current)
        QShortcut(QKeySequence("Ctrl+P"), self, self.toggle_favorite_current)
        QShortcut(QKeySequence("Meta+S"), self, self.make_snippet_current)
        QShortcut(QKeySequence("Backspace"), self, self.delete_current_if_search_empty)
        QShortcut(QKeySequence("Delete"), self, self.delete_current)
        QShortcut(QKeySequence("Return"), self, self.copy_current)
        QShortcut(QKeySequence("Enter"), self, self.copy_current)
        QShortcut(QKeySequence("Down"), self, lambda: self._move(1))
        QShortcut(QKeySequence("Up"), self, lambda: self._move(-1))
        # Espace → Quick Look natif macOS sur item image (ou texte long).
        # Comme dans Finder/Photos/Mail.
        QShortcut(QKeySequence("Space"), self, self.quick_look_current)
        # Cmd+1..9 → copie directe
        for i in range(1, 10):
            sc = QShortcut(QKeySequence(f"Meta+{i}"), self)
            sc.activated.connect(lambda n=i: self._copy_index(n - 1))
            sc2 = QShortcut(QKeySequence(f"Ctrl+{i}"), self)
            sc2.activated.connect(lambda n=i: self._copy_index(n - 1))

    # --- listing ------------------------------------------------------------

    def refresh(self) -> None:
        self._refresh_source_combo()
        self._refresh_filter_counts()
        rows = self.db.list_items(
            kind=self._filter_kind,
            favorites_only=self._filter_favs,
            snippets_only=self._filter_snippets,
            secrets_only=self._filter_secrets,
            since_ts=self._filter_since,
            source_app=self._filter_source,
            limit=2000,
        )
        q = self.search.text().strip()
        if q:
            rows = fuzzy_filter(rows, q)

        stats = self.db.stats()
        total = int(stats.get("total") or 0)
        favs = int(stats.get("favs") or 0)
        snips = int(stats.get("snippets") or 0)

        self.list.blockSignals(True)
        self.list.clear()
        for it in rows:
            row = QListWidgetItem()
            row.setData(Qt.ItemDataRole.UserRole, it)
            # Tooltip riche au survol — utile surtout pour les textes
            # longs coupés dans la liste. macOS gère le délai et le
            # rendu natif via la bulle d'info système.
            row.setToolTip(self._make_item_tooltip(it))
            self.list.addItem(row)

        # État vide explicatif (Phase 1) — au lieu d'une liste blanche déroutante
        if not rows:
            placeholder = QListWidgetItem(self._empty_state_message(q, total))
            placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
            placeholder.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list.addItem(placeholder)

        self.list.blockSignals(False)
        if rows:
            self.list.setCurrentRow(0)
        else:
            self._render_preview(None)

        # Petit fade-in subtil sur la liste après refresh (sauf 1er render)
        self._animate_list_fadein()

        # Le footer affiche les éléments « réels » uniquement, pas le placeholder.
        shown = len(rows)
        self.stats_label.setText(
            f"{shown} affiché(s) · {total} total · {favs} favoris · {snips} snippets"
        )
        # Le header en haut à droite affiche un compteur synthétique propre.
        # Ne s'actualise qu'au refresh, ce qui est suffisant.
        if hasattr(self, "header_count"):
            label_item = "élément" if total <= 1 else "éléments"
            self.header_count.setText(f"{total} {label_item}")

    @staticmethod
    def _empty_state_message(query: str, total_in_db: int) -> str:
        """Message d'état vide adapté au contexte (premier lancement / filtre / recherche)."""
        if total_in_db == 0:
            return (
                "✂\n\n"
                "Bienvenue dans Klip\n\n"
                "Copiez du texte ou une image dans n'importe quelle app (⌘C)\n"
                "et il apparaîtra ici automatiquement.\n\n"
                "Appuyez sur ⌘? pour voir tous les raccourcis."
            )
        if query:
            return (
                f"🔍\n\nAucun résultat pour « {query} »\n\n"
                "Essayez un autre mot-clé, ou effacez la recherche\n"
                "pour voir tous les éléments."
            )
        return (
            "🔍\n\nAucun élément avec ces filtres\n\n"
            "Essayez de changer la catégorie ou la période en haut\n"
            "de la fenêtre."
        )

    @staticmethod
    def _make_item_tooltip(item: Item) -> str:
        """Texte de survol riche pour un item (HTML).

        Affiche un en-tête meta (type, date, source, taille) + un extrait
        plus long que le rendu dans la liste — utile pour les textes
        coupés à 160 chars dans le delegate.
        """
        # En-tête meta : type · date · source · taille
        meta_parts = []
        type_label = (
            TYPES.get(item.content_type, TYPES["plain"]).label
            if item.kind == "text"
            else "Image"
        )
        meta_parts.append(type_label)
        meta_parts.append(_human_time(item.created_at))
        if item.source_app:
            meta_parts.append(item.source_app)
        if item.size_bytes:
            meta_parts.append(_human_size(item.size_bytes))
        meta = "  ·  ".join(meta_parts)

        if item.is_snippet and item.snippet_name:
            header = f"<b>;{item.snippet_name}</b>  &nbsp;&nbsp;<span style='color:#888'>{meta}</span>"
        else:
            header = f"<span style='color:#888'>{meta}</span>"

        # Corps : texte long ou aperçu image
        if item.kind == "image":
            dims = f"{item.image_w}×{item.image_h}" if item.image_w else "image"
            body = f"<i>{dims}</i>"
            if item.ocr_text:
                ocr = item.ocr_text.strip()[:500]
                body += f"<br><br><b>OCR :</b> {ocr}"
        else:
            text = (item.text or "").strip()
            # On tronque à ~700 chars pour rester dans une bulle lisible
            if len(text) > 700:
                text = text[:700] + " […]"
            # Échappe les balises HTML basiques pour ne pas casser le tooltip
            text = (
                text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace("\n", "<br>")
            )
            body = text

        return f"{header}<br><br>{body}"

    def _animate_list_fadein(self) -> None:
        """Petit fade-in du QListWidget après un refresh.

        Très subtil (200 ms, ease-out) — donne une sensation de fluidité
        sans être bloquant. Évite l'animation au tout premier render pour
        ne pas retarder l'apparition de la fenêtre.
        """
        if not hasattr(self, "_first_refresh_done"):
            self._first_refresh_done = True
            return
        effect = self.list.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(self.list)
            self.list.setGraphicsEffect(effect)
        # Stop l'animation précédente si elle tourne encore
        prev = getattr(self, "_list_fade_anim", None)
        if prev is not None:
            try:
                prev.stop()
            except Exception:
                pass
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(200)
        anim.setStartValue(0.6)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start()
        self._list_fade_anim = anim

    def _move(self, delta: int) -> None:
        if not self.list.count():
            return
        cur = max(0, self.list.currentRow())
        self.list.setCurrentRow((cur + delta) % self.list.count())

    def _on_select(self, current, _previous=None) -> None:
        # Si on était en mode édition et qu'on change d'item, on annule
        # silencieusement (sans restore — _render_preview va re-peindre).
        if self._edit_mode:
            self._cancel_edit_mode(restore_text=False)
        item = current.data(Qt.ItemDataRole.UserRole) if current else None
        self._render_preview(item)

    def _clear_action_buttons(self) -> None:
        for b in self._action_buttons:
            self.actions_row.removeWidget(b)
            b.deleteLater()
        self._action_buttons.clear()

    def _clear_preview_tags(self) -> None:
        """Vide le FlowLayout des tags d'aperçu (entre 2 sélections d'item)."""
        flow = getattr(self, "preview_meta_flow", None)
        if flow is None:
            return
        while flow.count() > 0:
            it = flow.takeAt(0)
            if it is None:
                continue
            w = it.widget()
            if w is not None:
                w.deleteLater()

    def _set_preview_tags(self, tags: list[tuple[str, str]]) -> None:
        """Crée un QLabel par tag, stylé via QSS pour rendre de vraies
        pills (border + border-radius supportés par QSS, contrairement
        au rich text HTML de Qt qui ignore ces propriétés sur <span>).
        """
        self._clear_preview_tags()
        flow = getattr(self, "preview_meta_flow", None)
        if flow is None:
            return
        _tc = _tag_palette()
        for kind, text in tags:
            bg, fg, bd = _tc.get(kind, _tc["size"])
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"QLabel {{"
                f"  background: {bg};"
                f"  color: {fg};"
                f"  border: 1px solid {bd};"
                f"  border-radius: 11px;"
                f"  padding: 2px 12px;"
                f"  font-size: 11px;"
                f"  font-weight: 600;"
                f"}}"
            )
            flow.addWidget(lbl)

    def _render_preview(self, item: Optional[Item]) -> None:
        self._clear_action_buttons()
        if not item:
            self.preview_text.clear()
            self.preview_image.hide()
            self.color_swatch.hide()
            self.preview_meta.setText("")
            self._clear_preview_tags()
            self.preview_ocr_label.hide()
            self.btn_pin.setText("☆ Épingler")
            self.btn_snippet.setText("✎ Snippet…")
            self.btn_snippet.setEnabled(False)
            self.btn_transform.setEnabled(False)
            self.btn_edit.setEnabled(False)
            return

        # Métadonnées sous forme de tags colorés (session 6) — au lieu de
        # "Code · il y a 18 h · Klip · 366 o", on rend chaque méta dans
        # une pastille colorée subtile. Les couleurs restent douces pour
        # ne pas faire "carnaval" (cf. demande user).
        type_info = TYPES.get(item.content_type, TYPES["plain"]) if item.kind == "text" else TYPES["image"]

        tags: list[tuple[str, str]] = []  # (kind, text)
        if item.is_snippet and item.snippet_name:
            tags.append(("snippet", item.snippet_name))
        # v2.3.1 — plus d'icône emoji devant le label (¶ avant "Texte")
        # pour un rendu plus propre style Linear/Notion.
        tags.append(("type", type_info.label))
        tags.append(("time", _human_time(item.created_at)))
        if item.source_app:
            tags.append(("app", item.source_app))
        if item.use_count:
            tags.append(("use", f"utilisé {item.use_count}×"))
        if item.kind == "text" and item.size_bytes:
            tags.append(("size", _human_size(item.size_bytes)))
        elif item.kind == "image" and item.image_w:
            tags.append(("size", f"{item.image_w}×{item.image_h}"))

        # v2.3.3 — rendu des tags via QLabel widgets + QSS au lieu du
        # HTML rich text qui ignore border-radius sur <span>.
        self._set_preview_tags(tags)

        # Couleur ?
        if item.content_type == "color" and item.text:
            color = QColor(item.text.strip())
            if color.isValid():
                self.color_swatch.setStyleSheet(
                    f"background: {color.name()}; border: 1px solid {PALETTE['border']}; border-radius: 8px;"
                )
                self.color_swatch.show()
            else:
                self.color_swatch.hide()
        else:
            self.color_swatch.hide()

        if item.kind == "image":
            # Charge le blob à la demande — list_items() ne le ramène plus en
            # RAM pour éviter de bouffer 1 Go quand la DB a 200 captures 4K.
            blob = self.db.get_image_blob(item.id)
            if blob:
                pix = QPixmap()
                pix.loadFromData(blob, "PNG")
                # Calcul de la zone d'affichage : on tient compte du padding
                # du QLabel (8px de chaque côté défini dans le QSS du
                # preview_image) pour éviter que l'image dépasse du cadre.
                target_w = max(120, (self.preview_image.width() or 360) - 16)
                target_h = 260  # cohérent avec maxHeight - padding
                self.preview_image.setPixmap(
                    pix.scaled(
                        target_w,
                        target_h,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self.preview_image.show()
                self.preview_text.hide()
                if item.ocr_text:
                    self.preview_ocr_label.setText(f"📝 OCR : {item.ocr_text}")
                    self.preview_ocr_label.show()
                elif item.ocr_text is None:
                    # ocr_text NULL = OCR pas encore passé (worker en file).
                    # On informe l'utilisateur au lieu de ne rien afficher.
                    self.preview_ocr_label.setText("📝 Analyse du texte en cours…")
                    self.preview_ocr_label.show()
                else:
                    # ocr_text == "" = OCR fait, aucun texte trouvé.
                    self.preview_ocr_label.hide()
            else:
                # Blob manquant (suite à purge ou corruption) — fallback texte.
                self.preview_image.hide()
                self.preview_text.show()
                self.preview_text.setPlainText("[Image introuvable ou supprimée]")
                self.preview_ocr_label.hide()
        else:
            self.preview_image.hide()
            self.preview_text.show()
            self.preview_text.setPlainText(item.text or "")
            self.preview_ocr_label.hide()

        self.btn_pin.setText("★ Épinglé" if item.is_favorite else "☆ Épingler")
        if item.is_snippet:
            self.btn_snippet.setText(f"✎ ;{item.snippet_name} ✕")
        else:
            self.btn_snippet.setText("✎ Snippet…")
        self.btn_snippet.setEnabled(item.kind == "text")
        # Activer « Macro ▾ » et « ✎ Éditer » uniquement pour du texte non vide.
        is_text_editable = item.kind == "text" and bool(item.text)
        self.btn_transform.setEnabled(is_text_editable)
        self.btn_edit.setEnabled(is_text_editable or item.kind == "image")
        self.btn_edit.setToolTip(
            "Masquer des lignes ou des zones avant d'envoyer (⌘E)"
            if item.kind == "image"
            else "Éditer le texte avant de le copier (⌘E ou double-clic)"
        )

        # Actions contextuelles
        for action in actions_for(item, copy_callback=self._copy_text):
            btn = QPushButton(action.label)
            if action.primary:
                btn.setObjectName("primary")
            btn.clicked.connect(self._wrap_action(action))
            self.actions_row.addWidget(btn)
            self._action_buttons.append(btn)

        # Bouton OCR manuel : pour une image dont le texte n'a pas (encore)
        # été extrait. `actions_for` n'expose « Copier le texte (OCR) » que
        # si ocr_text est déjà rempli ; ici on couvre le cas où l'extraction
        # automatique en arrière-plan n'a rien donné, a échoué, ou n'est pas
        # encore passée — l'utilisateur peut forcer l'extraction à la demande.
        if item.kind == "image" and not item.ocr_text:
            ocr_btn = QPushButton("Extraire le texte (OCR)")
            ocr_btn.setObjectName("primary")
            ocr_btn.clicked.connect(
                lambda _checked=False, it=item: self._extract_ocr(it)
            )
            self.actions_row.addWidget(ocr_btn)
            self._action_buttons.append(ocr_btn)

    def _extract_ocr(self, item: Item) -> None:
        """Lance l'OCR Vision sur l'image à la demande, met à jour la DB et
        l'UI, puis copie le texte trouvé dans le presse-papiers.

        Synchrone (l'image fait quelques centaines de Ko, Vision répond en
        <1 s) ; on donne un retour clair dans la barre de statut quel que
        soit le résultat — y compris « aucun texte détecté »."""
        blob = self.db.get_image_blob(item.id)
        if not blob:
            self.status.showMessage("Image introuvable (probablement purgée).", 3000)
            return
        self.status.showMessage("Extraction du texte en cours…", 1500)
        QApplication.processEvents()
        languages = ["fr-FR", "en-US"]
        if self.settings is not None:
            raw = self.settings.get("ocr.languages", languages)
            if isinstance(raw, list) and raw and all(isinstance(x, str) for x in raw):
                languages = raw
        try:
            from .osbackend import recognize_text
            txt = recognize_text(blob, languages=languages) or ""
        except Exception as e:
            self.status.showMessage(f"OCR indisponible : {e}", 4000)
            return
        self.db.set_ocr(item.id, txt)
        item.ocr_text = txt
        self.refresh_ocr(item.id)
        if txt.strip():
            capture.write_text(txt)
            self.status.showMessage(
                "Texte extrait et copié dans le presse-papiers.", 3000
            )
        else:
            self.status.showMessage("Aucun texte détecté dans cette image.", 3000)

    def refresh_ocr(self, item_id: int) -> None:
        """Met à jour en place l'item OCR-isé sans rebuild ni saut de
        sélection. Appelé soit par le worker OCR de fond (signal `done`),
        soit après une extraction manuelle.

        On recharge l'item frais depuis la DB, on remplace les données
        portées par la ligne correspondante, et si c'est l'item affiché on
        re-peint l'aperçu pour faire apparaître le bouton / le texte OCR."""
        fresh = self.db.get(item_id)
        if fresh is None:
            return
        for i in range(self.list.count()):
            li = self.list.item(i)
            data = li.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, Item) and data.id == item_id:
                li.setData(Qt.ItemDataRole.UserRole, fresh)
                li.setToolTip(self._make_item_tooltip(fresh))
                if self.list.currentItem() is li:
                    self._render_preview(fresh)
                break

    def _wrap_action(self, action: Action) -> Callable[[], None]:
        def _():
            try:
                action.handler()
            except Exception as e:
                self.status.showMessage(f"Erreur action : {e}", 3000)
        return _

    def _copy_text(self, text: str) -> None:
        capture.write_text(text)
        self.status.showMessage("Texte transformé copié dans le presse-papiers", 2500)
        QTimer.singleShot(120, self.hide)
        if self.autopaste_cb:
            QTimer.singleShot(180, self.autopaste_cb)

    def _current_item(self) -> Optional[Item]:
        cur = self.list.currentItem()
        return cur.data(Qt.ItemDataRole.UserRole) if cur else None

    # --- actions ------------------------------------------------------------

    def _copy_index(self, idx: int) -> None:
        if 0 <= idx < self.list.count():
            self.list.setCurrentRow(idx)
            self.copy_current()

    def copy_current(self) -> None:
        # En mode édition, le bouton « Copier » sert à valider l'édition
        # (avec le texte potentiellement modifié, pas l'original).
        if self._edit_mode:
            self._validate_edit_mode()
            return
        item = self._current_item()
        if not item:
            return
        if item.kind == "image":
            # Charge le blob à la demande (cf. _render_preview).
            blob = self.db.get_image_blob(item.id)
            if not blob:
                self.status.showMessage("Image introuvable (probablement purgée).", 3000)
                return
            # Option « Toujours masquer les secrets » : c'est la version
            # masquée qui sort. None = masquage impossible → on n'envoie rien.
            out = redact.export_png(blob, self.settings)
            if out is None:
                self.status.showMessage(
                    "Masquage des secrets impossible : rien n'a été copié.", 4000
                )
                return
            capture.write_image(out)
        elif item.text is not None:
            capture.write_text(item.text)
        self.db.touch(item.id)
        self.item_copied.emit(item.id)
        size_str = _human_size(item.size_bytes) if item.size_bytes else ""
        self.status.showMessage(f"Copié dans le presse-papiers · {size_str}", 2500)
        QTimer.singleShot(120, self.hide)
        if self.autopaste_cb:
            QTimer.singleShot(180, self.autopaste_cb)

    def toggle_favorite_current(self) -> None:
        item = self._current_item()
        if not item:
            return
        self.db.toggle_favorite(item.id)
        self.refresh()

    def quick_look_current(self) -> None:
        """Ouvre Quick Look natif macOS sur l'item courant (Espace).

        Pour les images : on écrit le blob dans un PNG temporaire et on
        lance ``qlmanage -p`` qui ouvre le popup natif macOS plein écran
        (le même que dans Finder/Photos/Mail). Pour les textes longs, on
        fait pareil avec un ``.txt`` — bonus utile pour relire un email
        ou un bout de code en grand.

        On garde une référence au process pour le tuer si on relance
        Quick Look sur un autre item, sinon plusieurs popups s'empilent.
        """
        import os
        import subprocess
        import tempfile

        item = self._current_item()
        if not item:
            return

        # Tuer le précédent Quick Look s'il existe (évite empilement)
        proc = getattr(self, "_ql_proc", None)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=0.5)
            except Exception:
                pass

        tmp_dir = tempfile.gettempdir()
        path: Optional[str] = None

        if item.kind == "image":
            blob = self.db.get_image_blob(item.id)
            if not blob:
                return
            path = os.path.join(tmp_dir, f"klip_preview_{item.id}.png")
            try:
                with open(path, "wb") as f:
                    f.write(blob)
            except Exception:
                return
        elif item.kind == "text" and item.text:
            # Bonus : Quick Look sur du texte (utile pour relire un long
            # email/extrait de code en plein écran). On limite aux textes
            # > 200 chars pour ne pas spammer pour des one-liners.
            if len(item.text) < 200:
                return
            path = os.path.join(tmp_dir, f"klip_preview_{item.id}.txt")
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(item.text)
            except Exception:
                return

        if not path:
            return

        # Lance qlmanage -p (Quick Look macOS) en background.
        # stdout/stderr redirigés vers DEVNULL — qlmanage est verbeux.
        try:
            self._ql_proc = subprocess.Popen(
                ["qlmanage", "-p", path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            # qlmanage doit toujours être dispo sur macOS ; au cas où…
            pass

    # --- Édition inline d'item (session 5 v2) -------------------------------

    def _on_item_double_clicked(self, list_item) -> None:
        """Double-clic sur un item de la liste → mode édition (si texte)."""
        item = list_item.data(Qt.ItemDataRole.UserRole) if list_item else None
        if not item or item.kind != "text":
            return
        self._enter_edit_mode()

    def _open_redact_editor(self, item: Item) -> None:
        """Éditeur de masquage (v2.5) : masquer des lignes / zones d'une
        capture avant de l'envoyer. L'original dans l'historique ne bouge pas."""
        from .redact_editor import RedactEditor

        blob = self.db.get_image_blob(item.id)
        if not blob:
            self.status.showMessage("Image introuvable (probablement purgée).", 3000)
            return

        def _on_copy(png: bytes) -> None:
            capture.write_image(png)
            self.db.touch(item.id)
            self.status.showMessage("Capture masquée copiée dans le presse-papiers", 2500)
            QTimer.singleShot(120, self.hide)
            if self.autopaste_cb:
                QTimer.singleShot(180, self.autopaste_cb)

        dlg = RedactEditor(blob, self.settings, on_copy=_on_copy, parent=self)
        dlg.exec()

    def _enter_edit_mode(self) -> None:
        """Bascule le panneau d'aperçu en édition inline."""
        item = self._current_item()
        if item and item.kind == "image":
            self._open_redact_editor(item)
            return
        if not item or item.kind != "text" or not item.text:
            return
        if self._edit_mode:
            return  # déjà en édition

        self._edit_mode = True
        self._edit_orig_item_id = item.id
        # Le QTextEdit devient éditable
        self.preview_text.setReadOnly(False)
        self.preview_text.setFocus(Qt.FocusReason.ShortcutFocusReason)
        # Curseur à la fin pour reprise rapide
        cursor = self.preview_text.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self.preview_text.setTextCursor(cursor)
        # Cadre violet autour pour signaler le mode
        self.preview_text.setStyleSheet(
            f"QTextEdit {{ background: {PALETTE['bg_panel']}; "
            f"border: 2px solid {PALETTE['accent']}; "
            f"border-radius: 6px; padding: 6px; }}"
        )
        # Bandeau d'instructions
        self.edit_banner.show()
        # Le bouton Copier devient le bouton « Valider »
        self.btn_copy.setText("Valider (⌘↩)")
        # Cache le bouton « Éditer » pendant l'édition (redondant)
        self.btn_edit.hide()

    def _validate_edit_mode(self) -> None:
        """Valide l'édition : met à jour l'item EN PLACE (conserve favori,
        snippet, position dans les filtres actifs) puis le re-sélectionne.

        Auparavant on créait un nouvel item — déroutant : sous un filtre
        comme « Favoris », le nouvel item (non-favori) était masqué et
        l'édition semblait « ne pas se sauvegarder ».
        """
        if not self._edit_mode:
            return
        new_text = self.preview_text.toPlainText()
        if not new_text.strip():
            # Texte vide → on annule plutôt que de vider l'item
            self._cancel_edit_mode()
            return

        orig_id = self._edit_orig_item_id
        target_id = None
        try:
            if orig_id is not None:
                target_id = self.db.update_text(orig_id, new_text)
            if not target_id:
                # Pas d'original connu → on retombe sur la création d'un item.
                target_id = self.db.add_text(new_text, source_app="Klip (édition)")
        except Exception:
            target_id = None

        # Sort du mode édition et rafraîchit la liste
        self._cancel_edit_mode(restore_text=False)
        self.refresh()

        if target_id:
            # Re-sélectionne l'item mis à jour s'il est visible sous le
            # filtre courant.
            found = False
            for i in range(self.list.count()):
                it = self.list.item(i)
                data = it.data(Qt.ItemDataRole.UserRole) if it else None
                if data and getattr(data, "id", None) == target_id:
                    self.list.setCurrentRow(i)
                    found = True
                    break
            if hasattr(self, "status") and self.status is not None:
                self.status.showMessage("Modification enregistrée.", 2500)
            # Si l'item édité n'est plus visible (filtre restrictif), on
            # garde quand même l'aperçu à jour avec le nouveau texte.
            if not found:
                self.preview_text.setPlainText(new_text)
        else:
            if hasattr(self, "status") and self.status is not None:
                self.status.showMessage(
                    "Échec de l'enregistrement de la modification.", 3000
                )

    def _cancel_edit_mode(self, restore_text: bool = True) -> None:
        """Sort du mode édition. Si restore_text, recharge le texte original."""
        if not self._edit_mode:
            return
        self._edit_mode = False
        orig_id = self._edit_orig_item_id
        self._edit_orig_item_id = None
        self.preview_text.setReadOnly(True)
        self.preview_text.setStyleSheet("")  # retour au style du QSS global
        self.edit_banner.hide()
        self.btn_copy.setText("Copier")
        # Re-montre le bouton « Éditer »
        self.btn_edit.show()
        if restore_text and orig_id is not None:
            # Recharge le contenu original depuis la DB pour l'affichage
            try:
                item = self.db.get(orig_id)
                if item and item.text is not None:
                    self.preview_text.setPlainText(item.text)
            except Exception:
                pass

    def _on_escape(self) -> None:
        """Esc : si en édition → annule, sinon cache la fenêtre."""
        if self._edit_mode:
            self._cancel_edit_mode()
        else:
            self.hide()

    def _show_transform_menu(self) -> None:
        """Affiche le menu déroulant sous le bouton « Macro ▾ ».

        Contient :
          • L'action snippet (créer / retirer selon l'état actuel)
          • Un séparateur
          • Toutes les transformations de texte applicables (UPPER, lower,
            slug, base64, URL, trim…), peuplées dynamiquement par
            ``transformations_for(item)``.
        """
        item = self._current_item()
        if not item or item.kind != "text" or not item.text:
            return

        def _do_copy(text: str) -> None:
            capture.write_text(text)
            self.close()
            if self.autopaste_cb is not None:
                QTimer.singleShot(50, self.autopaste_cb)

        menu = QMenu(self)

        # Snippet — en premier (action plus structurante que les transformations).
        # Le label dépend de l'état : créer ou retirer.
        if item.is_snippet and item.snippet_name:
            snip_label = f"✎  Retirer du snippet ;{item.snippet_name}"
        else:
            snip_label = "✎  Créer un snippet ;nom…"
        snip_act = menu.addAction(snip_label)
        snip_act.triggered.connect(self.make_snippet_current)

        # Séparateur entre Snippet (création) et Transformations (texte).
        actions_list = transformations_for(item, copy_callback=_do_copy)
        if actions_list:
            menu.addSeparator()
            for act in actions_list:
                menu_act = menu.addAction(act.label)
                menu_act.triggered.connect(act.handler)

        btn = self.btn_transform
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def make_snippet_current(self) -> None:
        item = self._current_item()
        if not item or item.kind != "text":
            return
        if item.is_snippet:
            self.db.unset_snippet(item.id)
            self.snippet_changed.emit()
            self.refresh()
            return
        name, ok = QInputDialog.getText(
            self, "Nouveau snippet",
            "Nom (sans le ;) — lettres, chiffres, _ ou - :",
            text=item.snippet_name or "",
        )
        if not ok or not name.strip():
            return
        if self.db.make_snippet(item.id, name.strip()):
            self.snippet_changed.emit()
            self.refresh()
        else:
            QMessageBox.warning(self, "Snippet", "Nom invalide ou déjà pris.")

    def delete_current(self) -> None:
        item = self._current_item()
        if not item:
            return
        if item.is_favorite or item.is_snippet:
            # v2.3.7 — dialog custom theme-aware (QMessageBox restait
            # sombre/illisible même avec setStyleSheet en light mode)
            if not self._confirm_dialog(
                title="Supprimer ?",
                message="Cet élément est épinglé ou est un snippet.",
                info="Le supprimer quand même ?",
                danger=True,
            ):
                return
            self.db.force_delete(item.id)
            if item.is_snippet:
                self.snippet_changed.emit()
        else:
            self.db.delete(item.id)
        self.refresh()

    def delete_current_if_search_empty(self) -> None:
        if self.search.hasFocus():
            return
        self.delete_current()

    # --- contextual menu ----------------------------------------------------

    def _show_context_menu(self, pos: QPoint) -> None:
        item = self._current_item()
        if not item:
            return
        menu = QMenu(self)
        a_copy = QAction("Copier (↩)", self)
        a_copy.triggered.connect(self.copy_current)
        a_pin = QAction("Désépingler" if item.is_favorite else "Épingler (⌘P)", self)
        a_pin.triggered.connect(self.toggle_favorite_current)
        a_snip = QAction(
            "Retirer du snippet" if item.is_snippet else "Créer un snippet… (⌘S)",
            self,
        )
        a_snip.triggered.connect(self.make_snippet_current)
        a_del = QAction("Supprimer (⌫)", self)
        a_del.triggered.connect(self.delete_current)
        menu.addAction(a_copy)
        menu.addAction(a_pin)
        menu.addAction(a_snip)
        menu.addSeparator()
        menu.addAction(a_del)
        menu.exec(self.list.mapToGlobal(pos))

    # --- show/hide ----------------------------------------------------------

    def show_centered(self) -> None:
        from PyQt6.QtGui import QCursor
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - self.width() // 2, geo.center().y() - self.height() // 2)
        self.search.clear()
        self.search.setFocus()
        self.show()
        self.raise_()
        self.activateWindow()
