"""Éditeur de masquage d'une capture (v2.5).

S'ouvre depuis le bouton « ✎ Éditer » (ou ⌘E) quand l'item est une image.

  • Clic sur une ligne de texte  → la ligne est masquée (re-clic = démasquée)
  • Glisser                       → masque une zone libre (visage, logo…)
  • Style : Barre · Flou · Pixel  → s'applique aux nouveaux masques
  • « Masquer les secrets »       → barre sur chaque clé / token / carte / IBAN
  • Copier / Enregistrer          → PNG avec les masques brûlés dans les pixels

Si l'option « Toujours masquer les secrets dans les captures » est active,
les secrets sont masqués dès l'ouverture et VERROUILLÉS (non retirables) :
c'est la promesse « quoi qu'il arrive ».

L'image d'origine dans l'historique n'est jamais modifiée.
"""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QCursor, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import redact
from .redact import Mask
from .theme import PALETTE, current_qss


class _Canvas(QWidget):
    """Affiche l'image masquée, à l'échelle, et gère clics / glisser."""

    def __init__(self, editor: "RedactEditor") -> None:
        super().__init__(editor)
        self.ed = editor
        self.setMouseTracking(True)
        self.setMinimumSize(420, 260)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._press: Optional[QPointF] = None
        self._drag: Optional[QPointF] = None
        self._hover_line: int = -1

    # --- géométrie image <-> écran ------------------------------------------

    def _layout(self) -> tuple[float, float, float]:
        iw, ih = self.ed.image.width(), self.ed.image.height()
        if iw <= 0 or ih <= 0:
            return 1.0, 0.0, 0.0
        s = min(self.width() / iw, self.height() / ih, 1.0)
        ox = (self.width() - iw * s) / 2
        oy = (self.height() - ih * s) / 2
        return s, ox, oy

    def _to_img(self, p: QPointF) -> QPointF:
        s, ox, oy = self._layout()
        return QPointF((p.x() - ox) / s, (p.y() - oy) / s)

    def _to_screen(self, r: QRectF) -> QRectF:
        s, ox, oy = self._layout()
        return QRectF(ox + r.x() * s, oy + r.y() * s, r.width() * s, r.height() * s)

    # --- rendu ---------------------------------------------------------------

    def paintEvent(self, _ev) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        s, ox, oy = self._layout()
        pix: QPixmap = self.ed.preview_pixmap
        target = QRectF(ox, oy, pix.width() * s, pix.height() * s)
        p.drawPixmap(target, pix, QRectF(pix.rect()))

        accent = QColor(PALETTE["accent"])
        if 0 <= self._hover_line < len(self.ed.lines) and self._drag is None:
            r = self._to_screen(self.ed.line_rect(self._hover_line))
            fill = QColor(accent)
            fill.setAlpha(40)
            p.fillRect(r, fill)
            p.setPen(QPen(accent, 1.5))
            p.drawRect(r)

        if self._press is not None and self._drag is not None:
            r = QRectF(self._press, self._drag).normalized()
            fill = QColor(accent)
            fill.setAlpha(50)
            p.fillRect(r, fill)
            p.setPen(QPen(accent, 1.5, Qt.PenStyle.DashLine))
            p.drawRect(r)
        p.end()

    # --- souris --------------------------------------------------------------

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self._press = ev.position()
            self._drag = None

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        pos = ev.position()
        if self._press is not None:
            if (pos - self._press).manhattanLength() > 5:
                self._drag = pos
                self.update()
            return
        line = self.ed.line_at(self._to_img(pos))
        if line != self._hover_line:
            self._hover_line = line
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if line >= 0 else Qt.CursorShape.CrossCursor
            )
            self.update()

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        if ev.button() != Qt.MouseButton.LeftButton or self._press is None:
            return
        start, drag = self._press, self._drag
        self._press = self._drag = None
        if drag is not None:
            a, b = self._to_img(start), self._to_img(drag)
            self.ed.add_zone(QRectF(a, b).normalized())
        else:
            self.ed.click_at(self._to_img(ev.position()))
        self.update()

    def leaveEvent(self, _ev) -> None:  # noqa: N802
        self._hover_line = -1
        self.update()


class RedactEditor(QDialog):
    def __init__(
        self,
        blob: bytes,
        settings=None,
        *,
        on_copy: Optional[Callable[[bytes], None]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Masquer avant d'envoyer")
        self.setModal(True)
        # objectName « root » → reçoit le fond du thème (QWidget#root dans
        # le QSS), sinon fond système clair + texte du thème sombre = illisible.
        self.setObjectName("root")
        self.setStyleSheet(current_qss())
        self.settings = settings
        self.on_copy = on_copy
        self.image = redact.image_from_png(blob)
        self.blob = blob
        self.masks: list[Mask] = []
        self.locked: list[Mask] = []   # secrets verrouillés par l'option
        self.lines: list = []          # OcrLine
        self._undo: list[list[Mask]] = []
        self.style = "bar"
        self.always_mask = bool(
            settings is not None and settings.get("capture.mask_secrets_in_images", False)
        )
        self.preview_pixmap = QPixmap.fromImage(self.image)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 18, 20, 16)
        outer.setSpacing(12)

        title = QLabel("Masquer avant d'envoyer")
        title.setProperty("class", "h2")
        outer.addWidget(title)
        hint = QLabel(
            "Clique sur une ligne pour la masquer, re-clique pour la démasquer. "
            "Glisse pour masquer une zone libre."
        )
        hint.setProperty("class", "meta")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        bar = QHBoxLayout()
        bar.setSpacing(6)
        self._style_btns: dict[str, QPushButton] = {}
        for key in redact.STYLES:
            b = QPushButton(redact.STYLE_LABELS[key])
            b.setCheckable(True)
            b.setProperty("chip", "true")
            b.clicked.connect(lambda _c=False, k=key: self._set_style(k))
            bar.addWidget(b)
            self._style_btns[key] = b
        self._style_btns["bar"].setToolTip("Recommandé pour les clés et mots de passe")
        self._style_btns["blur"].setToolTip("Esthétique seulement : un flou peut parfois se défaire")
        self._style_btns["pixel"].setToolTip("Esthétique seulement : une pixellisation peut parfois se défaire")
        bar.addSpacing(12)
        self.btn_secrets = QPushButton("Masquer les secrets")
        self.btn_secrets.setToolTip("Barre sur chaque clé API, token, carte bancaire, IBAN détecté")
        self.btn_secrets.clicked.connect(self.mask_secrets)
        bar.addWidget(self.btn_secrets)
        bar.addStretch(1)
        self.btn_undo = QPushButton("Annuler")
        self.btn_undo.setToolTip("⌘Z")
        self.btn_undo.clicked.connect(self.undo)
        bar.addWidget(self.btn_undo)
        self.btn_clear = QPushButton("Tout effacer")
        self.btn_clear.clicked.connect(self.clear)
        bar.addWidget(self.btn_clear)
        outer.addLayout(bar)

        self.canvas = _Canvas(self)
        outer.addWidget(self.canvas, 1)

        foot = QHBoxLayout()
        self.status = QLabel("Analyse du texte…")
        self.status.setProperty("class", "meta")
        foot.addWidget(self.status, 1)
        btn_close = QPushButton("Fermer")
        btn_close.clicked.connect(self.reject)
        foot.addWidget(btn_close)
        btn_save = QPushButton("Enregistrer…")
        btn_save.clicked.connect(self.save_as)
        foot.addWidget(btn_save)
        btn_copy = QPushButton("Copier")
        btn_copy.setObjectName("primary")
        btn_copy.setDefault(True)
        btn_copy.clicked.connect(self.copy)
        foot.addWidget(btn_copy)
        outer.addLayout(foot)

        QShortcut(QKeySequence.StandardKey.Undo, self, activated=self.undo)

        self._set_style("bar")
        self._size_to_screen()
        QTimer.singleShot(30, self._analyse)

    # --- init ----------------------------------------------------------------

    def _size_to_screen(self) -> None:
        screen = self.screen() or (self.parent().screen() if self.parent() else None)
        avail = screen.availableGeometry() if screen else None
        max_w = int(avail.width() * 0.8) if avail else 1100
        max_h = int(avail.height() * 0.8) if avail else 800
        iw, ih = max(1, self.image.width()), max(1, self.image.height())
        s = min((max_w - 40) / iw, (max_h - 190) / ih, 1.0)
        self.resize(max(640, int(iw * s) + 40), max(440, int(ih * s) + 190))

    def _analyse(self) -> None:
        from .ocr import recognize_lines

        langs = self.settings.get("ocr.languages", None) if self.settings else None
        self.setCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            self.lines = recognize_lines(self.blob, langs, span_finder=redact.find_secret_spans)
        except Exception:
            self.lines = []
            self._ocr_failed = True
        else:
            self._ocr_failed = False
        finally:
            self.unsetCursor()
        if self.always_mask:
            self.locked = self._secret_masks()
        self._refresh()

    # --- modèle --------------------------------------------------------------

    def _secret_masks(self) -> list[Mask]:
        out = []
        for ln in self.lines:
            for sp in ln.spans:
                x, y, w, h = redact.pad_rect(*sp.rect, self.image.width(), self.image.height())
                out.append(Mask(x, y, w, h, "bar"))
        return out

    def line_rect(self, i: int) -> QRectF:
        x, y, w, h = redact.pad_rect(*self.lines[i].rect, self.image.width(), self.image.height())
        return QRectF(x, y, w, h)

    def line_at(self, p: QPointF) -> int:
        for i in range(len(self.lines)):
            if self.line_rect(i).contains(p):
                return i
        return -1

    def _push_undo(self) -> None:
        self._undo.append(list(self.masks))
        if len(self._undo) > 50:
            self._undo.pop(0)

    def _set_style(self, key: str) -> None:
        self.style = key
        for k, b in self._style_btns.items():
            b.setChecked(k == key)

    def add_zone(self, r: QRectF) -> None:
        r = r.intersected(QRectF(0, 0, self.image.width(), self.image.height()))
        if r.width() < 3 or r.height() < 3:
            return
        self._push_undo()
        self.masks.append(Mask(r.x(), r.y(), r.width(), r.height(), self.style))
        self._refresh()

    def click_at(self, p: QPointF) -> None:
        # 1) clic sur un masque existant → on le retire (le plus récent d'abord)
        for i in range(len(self.masks) - 1, -1, -1):
            m = self.masks[i]
            if QRectF(m.x, m.y, m.w, m.h).contains(p):
                self._push_undo()
                del self.masks[i]
                self._refresh()
                return
        for m in self.locked:
            if QRectF(m.x, m.y, m.w, m.h).contains(p):
                self.status.setText(
                    "Ce secret reste masqué : option « Toujours masquer les secrets » "
                    "active (Préférences › Confidentialité)."
                )
                return
        # 2) clic sur une ligne → masque la ligne
        i = self.line_at(p)
        if i >= 0:
            r = self.line_rect(i)
            self._push_undo()
            self.masks.append(Mask(r.x(), r.y(), r.width(), r.height(), self.style))
            self._refresh()

    def mask_secrets(self) -> None:
        found = self._secret_masks()
        if not found:
            self.status.setText("Aucun secret détecté dans cette capture.")
            return
        self._push_undo()
        self.masks.extend(found)
        self._refresh(f"{len(found)} secret(s) masqué(s).")

    def undo(self) -> None:
        if self._undo:
            self.masks = self._undo.pop()
            self._refresh()

    def clear(self) -> None:
        if self.masks:
            self._push_undo()
            self.masks = []
            self._refresh()

    def all_masks(self) -> list[Mask]:
        return self.locked + self.masks

    def _refresh(self, msg: Optional[str] = None) -> None:
        self.preview_pixmap = QPixmap.fromImage(redact.render(self.image, self.all_masks()))
        self.canvas.update()
        self.btn_undo.setEnabled(bool(self._undo))
        self.btn_clear.setEnabled(bool(self.masks))
        if msg:
            self.status.setText(msg)
            return
        n = len(self.all_masks())
        parts = [f"{n} zone(s) masquée(s)" if n else "Aucune zone masquée"]
        if self.locked:
            parts.append(f"dont {len(self.locked)} secret(s) verrouillé(s)")
        if getattr(self, "_ocr_failed", False):
            parts.append("texte non analysé : glisse pour masquer à la main")
        elif not self.lines:
            parts.append("aucun texte détecté")
        self.status.setText(" · ".join(parts))

    # --- sortie --------------------------------------------------------------

    def result_png(self) -> bytes:
        if self.always_mask and getattr(self, "_ocr_failed", False):
            raise RuntimeError("analyse impossible")
        return redact.image_to_png(redact.render(self.image, self.all_masks()))

    def copy(self) -> None:
        try:
            png = self.result_png()
        except RuntimeError:
            self.status.setText(
                "Analyse du texte impossible : rien n'a été copié "
                "(option « Toujours masquer les secrets » active)."
            )
            return
        if self.on_copy:
            self.on_copy(png)
        self.accept()

    def save_as(self) -> None:
        try:
            png = self.result_png()
        except RuntimeError:
            self.status.setText("Analyse du texte impossible : rien n'a été enregistré.")
            return
        import os
        default = os.path.join(os.path.expanduser("~/Desktop"), "capture-masquee.png")
        path, _ = QFileDialog.getSaveFileName(self, "Enregistrer la capture masquée", default, "Image PNG (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        with open(path, "wb") as f:
            f.write(png)
        self.status.setText(f"Enregistrée : {os.path.basename(path)}")
