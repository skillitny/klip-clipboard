"""Petit panneau de statut des permissions macOS, avec ✓/✗ en direct et
boutons pour ouvrir le bon réglage. Affiché si une permission manque, et
accessible à tout moment depuis le menu de l'icône menubar.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import permissions


def _badge(state) -> str:
    if state is True:
        return "✅ Accordée"
    if state is False:
        return "❌ Manquante"
    return "❓ Inconnue"


class PermissionsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Permissions de Klip")
        self.setMinimumWidth(440)
        self._rows: list = []
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(14)

        title = QLabel("Permissions macOS")
        f = QFont()
        f.setPointSize(16)
        f.setBold(True)
        title.setFont(f)
        root.addWidget(title)

        intro = QLabel(
            "Ces autorisations activent le raccourci ⌥⌘V, le collage "
            "automatique et les snippets. Clique sur « Ouvrir » puis coche "
            "Klip dans la liste. Reviens ici et « Re-vérifier »."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        # Surveillance des entrées
        root.addLayout(self._perm_row(
            "Surveillance des entrées",
            "input_monitoring",
            permissions.open_input_monitoring_settings,
        ))
        # Accessibilité
        root.addLayout(self._perm_row(
            "Accessibilité",
            "accessibility",
            permissions.open_accessibility_settings,
        ))

        btn_row = QHBoxLayout()
        recheck = QPushButton("Re-vérifier")
        recheck.clicked.connect(self.refresh)
        close = QPushButton("Fermer")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        btn_row.addWidget(recheck)
        btn_row.addStretch(1)
        btn_row.addWidget(close)
        root.addLayout(btn_row)

    def _perm_row(self, label: str, key: str, opener) -> QHBoxLayout:
        row = QHBoxLayout()
        name = QLabel(label)
        name.setMinimumWidth(190)
        status = QLabel("…")
        open_btn = QPushButton("Ouvrir")
        open_btn.clicked.connect(lambda: opener())
        row.addWidget(name)
        row.addWidget(status, 1)
        row.addWidget(open_btn)
        self._rows.append((key, status))
        return row

    def refresh(self) -> None:
        s = permissions.status_summary()
        for key, status_label in self._rows:
            status_label.setText(_badge(s.get(key)))


def open_permissions(parent: QWidget | None = None) -> PermissionsDialog:
    win = PermissionsDialog(parent=parent)
    win.show()
    win.raise_()
    win.activateWindow()
    return win
