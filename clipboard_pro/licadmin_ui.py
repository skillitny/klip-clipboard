"""Fenêtre ÉDITEUR de gestion des licences (onglet « Licences »).

Liste les clés émises, permet d'en créer une (Mac ou Windows) et d'envoyer
l'app + la clé par email en un clic (via Mail.app, template HTML, l'installateur
en pièce jointe — Mail Drop gère les gros fichiers). Ouverte seulement en mode
éditeur (clé privée présente).
"""
from __future__ import annotations

import time
from typing import Optional

from PyQt6.QtGui import QFont, QGuiApplication
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from . import licadmin


def _fmt_date(ts: float) -> str:
    try:
        return time.strftime("%d/%m/%Y %H:%M", time.localtime(ts))
    except Exception:
        return ""


class _NewLicenseDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nouvelle licence")
        self.setModal(True)
        self.setMinimumWidth(440)
        self.result_entry: Optional[dict] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(12)

        title = QLabel("Créer une licence")
        f = QFont(); f.setPointSize(16); f.setBold(True)
        title.setFont(f)
        root.addWidget(title)

        root.addWidget(QLabel("Prénom / nom (obligatoire)"))
        self.name = QLineEdit(); self.name.setPlaceholderText("ex. Camille")
        root.addWidget(self.name)

        root.addWidget(QLabel("Plateforme de l'ami"))
        self.platform = QComboBox()
        self.platform.addItem("macOS (Apple Silicon)", "mac")
        self.platform.addItem("Windows 10/11", "windows")
        root.addWidget(self.platform)

        root.addWidget(QLabel("Email (pour l'envoi automatique)"))
        self.email = QLineEdit(); self.email.setPlaceholderText("camille@exemple.com")
        root.addWidget(self.email)

        root.addWidget(QLabel("Identifiant machine (optionnel — licence verrouillée)"))
        self.machine = QLineEdit(); self.machine.setPlaceholderText("vide = marche sur n'importe quel ordi")
        root.addWidget(self.machine)

        self.err = QLabel(""); self.err.setStyleSheet("color:#ef4444;"); self.err.hide()
        root.addWidget(self.err)

        hint = QLabel(
            "Avec un email : « Générer + envoyer » crée la clé ET envoie "
            "automatiquement l'app + la clé par mail. Sans email : génère "
            "seulement (à copier/partager à la main)."
        )
        hint.setWordWrap(True); hint.setStyleSheet("color:gray;font-size:11px;")
        root.addWidget(hint)

        row = QHBoxLayout(); row.addStretch(1)
        cancel = QPushButton("Annuler"); cancel.clicked.connect(self.reject)
        create = QPushButton("Générer + envoyer ✉")
        create.setDefault(True)
        create.setStyleSheet(
            "QPushButton{background:#ef4444;color:#fff;border:0;border-radius:8px;"
            "padding:8px 16px;font-weight:600;} QPushButton:hover{background:#dc2626;}"
        )
        create.clicked.connect(self._create)
        row.addWidget(cancel); row.addWidget(create)
        root.addLayout(row)

    def _create(self):
        name = self.name.text().strip()
        if not name:
            self.err.setText("Le prénom/nom est obligatoire.")
            self.err.show()
            return
        entry = licadmin.add_and_issue(
            name,
            email=self.email.text().strip(),
            machine_id=self.machine.text().strip(),
            platform=self.platform.currentData(),
        )
        if not entry:
            self.err.setText("Impossible de générer (clé privée introuvable).")
            self.err.show()
            return
        self.result_entry = entry
        # Envoi automatique de l'email si une adresse a été fournie.
        if entry.get("email"):
            ok, msg = licadmin.send_email(entry, send=True)
            if ok:
                QMessageBox.information(self, "Email envoyé", msg)
            else:
                QMessageBox.warning(
                    self, "Clé générée, email non envoyé",
                    msg + "\n\nLa clé est enregistrée ; tu peux la renvoyer "
                    "depuis la liste avec « Envoyer par email ».",
                )
        else:
            QMessageBox.information(
                self, "Clé générée",
                "Clé créée. Pas d'email fourni → utilise « Copier la clé » "
                "pour la partager.",
            )
        self.accept()


class LicenseAdminWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Klip — Licences (éditeur)")
        self.setMinimumSize(800, 460)
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("Licences émises")
        f = QFont(); f.setPointSize(17); f.setBold(True)
        title.setFont(f)
        header.addWidget(title)
        header.addStretch(1)
        new_btn = QPushButton("＋ Nouvelle licence")
        new_btn.setStyleSheet(
            "QPushButton{background:#ef4444;color:#fff;border:0;border-radius:8px;"
            "padding:8px 16px;font-weight:600;} QPushButton:hover{background:#dc2626;}"
        )
        new_btn.clicked.connect(self._new_license)
        header.addWidget(new_btn)
        root.addLayout(header)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Nom", "Plateforme", "Email", "Machine", "Date"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.copy_btn = QPushButton("Copier la clé")
        self.copy_btn.clicked.connect(self._copy_key)
        self.send_btn = QPushButton("📧 Envoyer par email")
        self.send_btn.setStyleSheet(
            "QPushButton{background:#ef4444;color:#fff;border:0;border-radius:8px;"
            "padding:8px 18px;font-weight:600;} QPushButton:hover{background:#dc2626;}"
        )
        self.send_btn.clicked.connect(self._send_email)
        actions.addWidget(self.copy_btn)
        actions.addStretch(1)
        actions.addWidget(self.send_btn)
        close = QPushButton("Fermer"); close.clicked.connect(self.accept)
        actions.addWidget(close)
        root.addLayout(actions)

        hint = QLabel(
            "« Envoyer par email » envoie automatiquement, depuis ton Mail, un "
            "joli message avec l'installateur en pièce jointe (les gros fichiers "
            "passent par Mail Drop) et la clé. L'ami n'a plus qu'à installer."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:gray;font-size:11px;")
        root.addWidget(hint)

    def _entries(self):
        return licadmin.list_entries()

    def refresh(self):
        entries = self._entries()
        self.table.setRowCount(len(entries))
        for r, e in enumerate(entries):
            plat = "Windows" if str(e.get("platform", "mac")).startswith("win") else "macOS"
            self.table.setItem(r, 0, QTableWidgetItem(e.get("name", "")))
            self.table.setItem(r, 1, QTableWidgetItem(plat))
            self.table.setItem(r, 2, QTableWidgetItem(e.get("email", "")))
            self.table.setItem(r, 3, QTableWidgetItem("🔒 oui" if e.get("machine_id") else "—"))
            self.table.setItem(r, 4, QTableWidgetItem(_fmt_date(e.get("created_at", 0))))
        if entries:
            self.table.selectRow(0)

    def _selected(self) -> Optional[dict]:
        row = self.table.currentRow()
        entries = self._entries()
        if 0 <= row < len(entries):
            return entries[row]
        return None

    def _new_license(self):
        dlg = _NewLicenseDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_entry:
            self.refresh()

    def _copy_key(self):
        e = self._selected()
        if not e:
            return
        QGuiApplication.clipboard().setText(e.get("key", ""))
        QMessageBox.information(self, "Licences", "Clé copiée dans le presse-papiers.")

    def _send_email(self):
        e = self._selected()
        if not e:
            return
        to = (e.get("email") or "").strip()
        if not to:
            QMessageBox.warning(self, "Email", "Cette licence n'a pas d'email. "
                                "Recrée-la avec un email, ou utilise « Copier la clé ».")
            return
        confirm = QMessageBox.question(
            self, "Envoyer", f"Envoyer Klip + la clé à {e.get('name','')} ({to}) ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        ok, msg = licadmin.send_email(e, send=True)
        if ok:
            QMessageBox.information(self, "Email envoyé", msg)
        else:
            QMessageBox.warning(self, "Email", msg)


def open_license_admin(parent=None) -> LicenseAdminWindow:
    win = LicenseAdminWindow(parent=parent)
    win.show()
    win.raise_()
    win.activateWindow()
    return win
