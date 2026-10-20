"""Écran d'activation par clé de licence (affiché tant qu'aucune licence
valide n'est enregistrée). Volontairement minimal : coller la clé → Activer.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import licensing


class ActivationDialog(QDialog):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Activer Klip")
        self.setModal(True)
        self.setMinimumWidth(460)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        title = QLabel("Bienvenue dans Klip")
        f = QFont()
        f.setPointSize(18)
        f.setBold(True)
        title.setFont(f)
        root.addWidget(title)

        sub = QLabel(
            "Cette copie nécessite une clé de licence personnelle.\n"
            "Colle ci-dessous la clé qui t'a été remise, puis clique Activer."
        )
        sub.setWordWrap(True)
        root.addWidget(sub)

        key_label = QLabel("Clé de licence (commence par « KLIP1. ») :")
        key_label.setStyleSheet("font-weight: 600;")
        root.addWidget(key_label)

        self.key_edit = QLineEdit()
        self.key_edit.setPlaceholderText("KLIP1.eyJ…  ← colle ta clé ici")
        self.key_edit.returnPressed.connect(self._activate)
        root.addWidget(self.key_edit)

        # Confort : si une clé KLIP1 est déjà dans le presse-papiers
        # (ex. l'ami vient de la copier depuis WhatsApp), on la pré-remplit
        # → il n'a plus qu'à cliquer « Activer ».
        try:
            clip = QGuiApplication.clipboard().text().strip()
            if clip.startswith("KLIP1.") and clip.count(".") == 2:
                self.key_edit.setText(clip)
        except Exception:
            pass

        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #e5534b;")
        self.error.hide()
        root.addWidget(self.error)

        # Identifiant machine (pour demander une licence verrouillée).
        # ⚠️ Source de confusion : ce N'EST PAS la clé d'activation.
        warn = QLabel(
            "⚠️ Ceci n'est pas la clé. Ne le saisis pas dans le champ ci-dessus."
        )
        warn.setWordWrap(True)
        warn.setStyleSheet("color: gray; font-size: 11px;")
        root.addWidget(warn)

        mid_row = QHBoxLayout()
        mid_label = QLabel("Identifiant de ce Mac :")
        mid_label.setStyleSheet("color: gray;")
        self.mid_value = QLineEdit(licensing.machine_id())
        self.mid_value.setReadOnly(True)
        self.mid_value.setMaximumWidth(170)
        self.mid_value.setStyleSheet("color: gray;")
        copy_btn = QPushButton("Copier")
        copy_btn.clicked.connect(self._copy_machine_id)
        mid_row.addWidget(mid_label)
        mid_row.addWidget(self.mid_value)
        mid_row.addWidget(copy_btn)
        mid_row.addStretch(1)
        root.addLayout(mid_row)

        hint = QLabel(
            "Astuce : pour une licence verrouillée à ton Mac, envoie cet "
            "identifiant à la personne qui t'a partagé l'app."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: gray; font-size: 11px;")
        root.addWidget(hint)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        quit_btn = QPushButton("Quitter")
        quit_btn.clicked.connect(self.reject)
        self.activate_btn = QPushButton("Activer")
        self.activate_btn.setDefault(True)
        self.activate_btn.clicked.connect(self._activate)
        btn_row.addWidget(quit_btn)
        btn_row.addWidget(self.activate_btn)
        root.addLayout(btn_row)

    def _copy_machine_id(self) -> None:
        QGuiApplication.clipboard().setText(self.mid_value.text())

    def _activate(self) -> None:
        key = self.key_edit.text().strip()
        ok, _info, reason = licensing.verify_key(key)
        if ok:
            licensing.save_license(key)
            self.accept()
        else:
            self.error.setText(reason or "Clé invalide.")
            self.error.show()


def require_license_blocking(parent: QWidget | None = None) -> bool:
    """Si une licence valide existe déjà → True sans rien afficher.
    Sinon affiche le dialog. Retourne True si activée, False si abandon.
    """
    ok, _ = licensing.current_license()
    if ok:
        return True
    dlg = ActivationDialog(parent)
    dlg.move(
        dlg.screen().geometry().center() - dlg.rect().center()
        if dlg.screen() else dlg.pos()
    )
    return dlg.exec() == QDialog.DialogCode.Accepted
