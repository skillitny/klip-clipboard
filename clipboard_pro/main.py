"""Point d'entrée Klip v2."""
from __future__ import annotations

import signal
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import (
    QAction,
    QColor,
    QFont,
    QGuiApplication,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
)
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from . import secrets
from .about import open_about
from .osbackend import (
    AutoPaste,
    CapturedImage,
    CapturedText,
    ClipboardWatcher,
    png_dimensions,
    recognize_text,
    write_image,
    write_text,
)
from .cheatsheet import open_cheatsheet
from .floating import FloatingWindow
from .guide import open_guide
from .onboarding import open_onboarding
from .classify import classify
from .db import Database
from .expander import TextExpander
from .hotkey import HotkeyManager
from .log import get_logger, is_debug, setup_logging
from .prefs import open_preferences
from .screenshot_watcher import ScreenshotWatcher
from .settings import Settings
from .ui import MainWindow

log = get_logger(__name__)


def _make_tray_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#7c5cff"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(8, 8, 48, 48, 12, 12)
    p.setPen(QColor("white"))
    f = QFont()
    f.setBold(True)
    f.setPointSize(28)
    p.setFont(f)
    p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "✂")
    p.end()
    return QIcon(pix)


# ----------------------------------------------------------------------------
# Toaster — wrapper anti-spam pour QSystemTrayIcon.showMessage()
# ----------------------------------------------------------------------------

class Toaster:
    """Avale les toasts dupliqués émis à <``dedup_window_ms`` ms d'intervalle.

    Plusieurs sources peuvent déclencher le même message à quelques
    centaines de ms d'intervalle (ex. capture multiple, retention qui
    boucle, screenshot watcher qui réémet). Le tray macOS empile alors les
    notifications et l'utilisateur voit le même toast 3 fois — agaçant et
    pas pro.

    Politique de dédup :
      • Clé = (titre, message). Pas le timeout, pas l'icône → si seuls
        ceux-là diffèrent on considère que c'est le même toast.
      • Fenêtre par défaut : 2000 ms. Au-delà, on ré-affiche normalement.
      • On garde au plus 32 entrées dans le buffer (FIFO simple) — un
        process Klip long peut afficher des milliers de toasts, pas la
        peine de tout garder.
    """

    def __init__(self, tray: "QSystemTrayIcon", icon: QIcon, dedup_window_ms: int = 2000) -> None:
        self._tray = tray
        self._icon = icon
        self._window_ms = dedup_window_ms
        # clé -> dernier ts en ms (monotonic-like via QElapsedTimer pas dispo
        # facilement ici → on utilise time.monotonic_ns() qui est plus simple)
        import time as _time
        self._time = _time
        self._last_seen: dict[tuple[str, str], int] = {}
        self._suppressed_count = 0  # pour diagnostic

    def show(self, title: str, message: str, timeout_ms: int = 3000) -> bool:
        """Affiche le toast SAUF si on l'a déjà montré récemment.

        Renvoie True si le toast a été affiché, False s'il a été avalé.
        """
        key = (title, message)
        now_ms = self._time.monotonic_ns() // 1_000_000
        last = self._last_seen.get(key)
        if last is not None and (now_ms - last) < self._window_ms:
            self._suppressed_count += 1
            log.debug(
                "Toast dédupliqué (#%d) : %r — %r (Δ=%d ms)",
                self._suppressed_count, title, message, now_ms - last,
            )
            return False
        self._last_seen[key] = now_ms
        # Garde-fou mémoire : on tronque si > 32 entrées (ordre d'insertion).
        if len(self._last_seen) > 32:
            # On retire la moitié la plus ancienne.
            oldest = sorted(self._last_seen.items(), key=lambda kv: kv[1])[:16]
            for k, _ in oldest:
                self._last_seen.pop(k, None)
        self._tray.showMessage(title, message, self._icon, timeout_ms)
        return True


# ----------------------------------------------------------------------------
# Capture bridge
# ----------------------------------------------------------------------------

class CaptureBridge(QObject):
    captured = pyqtSignal(int, str)        # (item_id, kind)
    secret_blocked = pyqtSignal(str)       # nom du pattern
    too_large_skipped = pyqtSignal(str, int)  # (kind, size_bytes)

    # Valeurs de repli si jamais settings.get renvoie quelque chose d'absurde.
    _DEFAULT_MAX_TEXT_BYTES  = 5 * 1024 * 1024
    _DEFAULT_MAX_IMAGE_BYTES = 50 * 1024 * 1024

    def __init__(self, db: Database, settings: Optional[Settings] = None) -> None:
        super().__init__()
        self.db = db
        # `settings` est optionnel pour rétro-compat (ex. scripts qui
        # instancient CaptureBridge tout seul). En prod c'est toujours passé.
        self.settings = settings
        self.watcher = ClipboardWatcher()
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _max_text_bytes(self) -> int:
        if self.settings is None:
            return self._DEFAULT_MAX_TEXT_BYTES
        try:
            return int(self.settings.get(
                "capture.max_text_bytes", self._DEFAULT_MAX_TEXT_BYTES
            ))
        except (TypeError, ValueError):
            return self._DEFAULT_MAX_TEXT_BYTES

    def _max_image_bytes(self) -> int:
        if self.settings is None:
            return self._DEFAULT_MAX_IMAGE_BYTES
        try:
            return int(self.settings.get(
                "capture.max_image_bytes", self._DEFAULT_MAX_IMAGE_BYTES
            ))
        except (TypeError, ValueError):
            return self._DEFAULT_MAX_IMAGE_BYTES

    def _detect_secrets_enabled(self) -> bool:
        if self.settings is None:
            return True
        return bool(self.settings.get("capture.detect_secrets", True))

    def _tick(self) -> None:
        payload = self.watcher.poll()
        if payload is None:
            return
        # Évite de re-capturer ce qu'on a nous-même mis dans le presse-papiers
        # (sinon « Copier » depuis notre fenêtre crée un faux doublon avec
        # source_app="Klip" qui pollue le filtre par app).
        # On skip aussi l'ancien nom « Clipboard Pro » pour la rétro-compat
        # (anciens items capturés avant le rename — leur source_app pollue
        # toujours le filtre par app jusqu'à ce qu'on purge la DB).
        if payload.source_app in ("Klip", "Clipboard Pro"):
            return
        if isinstance(payload, CapturedText):
            # Limite de taille — éviter d'avaler un copier d'un fichier .log
            # de 50 Mo qui ferait gonfler la DB et la RAM.
            size = len(payload.text.encode("utf-8", errors="replace"))
            if size > self._max_text_bytes():
                self.too_large_skipped.emit("text", size)
                return
            # Détection de secrets — toggleable depuis Préférences →
            # Confidentialité. Note importante : le clipboard SYSTÈME n'est
            # jamais affecté ; on choisit juste de ne pas enregistrer le
            # secret dans notre historique.
            # Détection de secrets — désormais TOUJOURS évaluée, pour pouvoir
            # classer l'item. Le toggle « Ne pas enregistrer les secrets
            # détectés » (capture.detect_secrets) décide quoi en faire :
            #   • activé (défaut, protection)     → on bloque, rien n'est stocké.
            #   • désactivé (mode enregistrement)  → on STOCKE le secret en le
            #     marquant is_secret=True → il atterrit dans la catégorie
            #     dédiée « Secret » de l'historique (à côté de Favoris).
            secret_kind = secrets.detect(payload.text)
            if secret_kind and self._detect_secrets_enabled():
                self.secret_blocked.emit(secret_kind)
                return
            content_type = classify(payload.text).code
            new_id = self.db.add_text(
                payload.text,
                content_type=content_type,
                source_app=payload.source_app,
                is_secret=bool(secret_kind),
            )
            if new_id is not None:
                self.captured.emit(new_id, "text")
        elif isinstance(payload, CapturedImage):
            size = len(payload.png)
            if size > self._max_image_bytes():
                self.too_large_skipped.emit("image", size)
                return
            new_id = self.db.add_image(
                payload.png, payload.width, payload.height, payload.source_app
            )
            if new_id is not None:
                self.captured.emit(new_id, "image")


# ----------------------------------------------------------------------------
# OCR worker — non bloquant, utilise un thread Python normal
# ----------------------------------------------------------------------------

class OCRWorker(QObject):
    """Tourne en boucle dans un thread, OCR-ise les images sans `ocr_text`.

    Le worker respecte deux settings (lus à chaque cycle) :
      • ``ocr.enabled`` — si False, le worker dort et ne marque rien.
        Comme ça toggle à chaud depuis Préférences fonctionne sans
        relancer le thread (qui re-checke au prochain réveil).
      • ``ocr.languages`` — liste de codes ISO ("fr-FR", "en-US", …)
        passée à Vision pour booster la précision.
    """
    done = pyqtSignal(int)

    _DEFAULT_LANGUAGES = ["fr-FR", "en-US"]

    def __init__(self, db: Database, settings: Optional[Settings] = None) -> None:
        super().__init__()
        self.db = db
        self.settings = settings  # peut être None en standalone
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def kick(self) -> None:
        self._wake.set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _is_enabled(self) -> bool:
        if self.settings is None:
            return True
        return bool(self.settings.get("ocr.enabled", True))

    def _languages(self) -> list[str]:
        if self.settings is None:
            return list(self._DEFAULT_LANGUAGES)
        raw = self.settings.get("ocr.languages", self._DEFAULT_LANGUAGES)
        if isinstance(raw, list) and all(isinstance(x, str) for x in raw):
            return raw or list(self._DEFAULT_LANGUAGES)
        return list(self._DEFAULT_LANGUAGES)

    def _loop(self) -> None:
        while not self._stop.is_set():
            # OCR désactivé → on dort jusqu'au prochain kick.
            if not self._is_enabled():
                self._wake.wait(timeout=15.0)
                self._wake.clear()
                continue

            pending = self.db.list_pending_ocr(limit=8)
            if not pending:
                self._wake.wait(timeout=15.0)
                self._wake.clear()
                continue

            languages = self._languages()
            # IMPORTANT (fuite mémoire) : l'OCR Vision en mode « accurate »
            # alloue des buffers (décodage image + Espresso / Neural Engine)
            # qui ne sont libérés de façon FIABLE que lorsque le thread qui les
            # a créés se termine. Un autorelease pool par appel ne suffit pas :
            # une partie des allocations se fait sur des threads GCD internes à
            # Vision, hors de notre portée. Tant que ce worker vivait toute la
            # session, ces buffers s'accumulaient → la RAM grimpait à plus de
            # 20 Go en quelques centaines d'images.
            #
            # Solution : exécuter CHAQUE batch dans un thread ÉPHÉMÈRE. Quand il
            # se termine, macOS récupère toute sa mémoire. Le thread
            # orchestrateur (celui-ci) ne touche jamais à ObjC/Vision.
            # Validé : RAM bornée (~quelques centaines de Mo) au lieu d'une
            # croissance illimitée.
            worker = threading.Thread(
                target=self._process_batch,
                args=(pending, languages),
                daemon=True,
            )
            worker.start()
            worker.join()

    def _process_batch(self, pending, languages) -> None:
        """OCR-ise un batch. EXÉCUTÉ DANS UN THREAD ÉPHÉMÈRE (cf. _loop) pour
        garantir la libération mémoire des buffers Vision à la mort du thread."""
        for item in pending:
            if self._stop.is_set() or not self._is_enabled():
                break
            if not item.image_blob:
                self.db.set_ocr(item.id, "")  # vide → ne réessaie pas en boucle
                continue
            try:
                txt = recognize_text(item.image_blob, languages=languages) or ""
                self.db.set_ocr(item.id, txt)
                self.done.emit(item.id)
            except Exception:
                self.db.set_ocr(item.id, "")


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> int:
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # Phase 1 : logger structuré. Doit être tout en haut pour que les
    # éventuelles erreurs de chargement (DB locked, settings corrompus…)
    # apparaissent dans ~/Library/Logs/Klip/app.log.
    setup_logging(debug=is_debug())
    log.info("Klip démarre (argv=%r)", sys.argv[1:])

    app = QApplication(sys.argv)
    app.setApplicationName("Klip")
    app.setQuitOnLastWindowClosed(False)

    # Icône de l'app (Dock + fenêtres). Important quand on lance depuis les
    # sources (pas de bundle .app) : sinon macOS affiche l'icône générique de
    # Python. On pose l'icône orange par code.
    try:
        from pathlib import Path as _Path
        import clipboard_pro as _cp
        _icon_path = _Path(_cp.__file__).resolve().parent.parent / "icon.icns"
        if _icon_path.exists():
            from PyQt6.QtGui import QIcon
            app.setWindowIcon(QIcon(str(_icon_path)))
            try:  # Dock macOS pour un process non bundlé
                import AppKit
                _img = AppKit.NSImage.alloc().initWithContentsOfFile_(str(_icon_path))
                if _img is not None:
                    AppKit.NSApp.setApplicationIconImage_(_img)
            except Exception:
                pass
    except Exception:
        pass

    db = Database()
    settings = Settings(db=db)

    # Premier lancement : on tag les défauts dans le journal pour avoir une
    # ligne d'origine "à compter du JJ/MM/AAAA, les défauts sont X". Ça
    # facilite la lecture du `settings_log` plus tard.
    if not settings.get("_bootstrapped", False):
        settings.set("_bootstrapped", True, note="Premier lancement v3", source="migration")
        # Force une trace pour les valeurs de rétention par défaut, pour
        # que l'utilisateur sache d'où ça part même s'il ne change rien.
        settings.set(
            "retention.text_days",
            settings.get("retention.text_days"),
            note="Valeur initiale par défaut",
            source="migration",
        )
        settings.set(
            "retention.image_days",
            settings.get("retention.image_days"),
            note="Valeur initiale par défaut",
            source="migration",
        )

    autopaster = AutoPaste()

    # Résolution du thème (dark / light / auto qui suit macOS) + couleur
    # d'accent personnalisable au démarrage. CRUCIAL : on appelle
    # apply_theme() AVANT toute construction de widget, parce que ça mute
    # le dict ``PALETTE`` en place. Tous les modules qui ont fait
    # ``from .theme import PALETTE`` vont voir la nouvelle palette quand
    # ils accèderont à PALETTE['accent'] etc. dans leurs setStyleSheet
    # inline — sans cette mutation préalable, ils gardaient l'ancienne
    # palette sombre figée et l'accent personnalisé n'avait aucun effet.
    from .theme import apply_theme
    theme_choice = str(settings.get("ui.theme", "dark") or "dark")
    accent_choice = str(settings.get("ui.accent", "violet") or "violet")
    # Mode ÉDITEUR (clé privée présente) : accent ROUGE pour distinguer d'un
    # coup d'œil ton app de celle distribuée aux amis.
    try:
        from .licadmin import is_editor
        if is_editor():
            accent_choice = "rouge"
    except Exception:
        pass
    qss = apply_theme(theme_choice, accent_choice)
    app.setStyleSheet(qss)
    log.info("Thème actif : %s / accent %s", theme_choice, accent_choice)

    log.info("Init : construction MainWindow...")
    try:
        window = MainWindow(
        db,
        autopaste_cb=autopaster.restore_and_paste,
        theme=theme_choice,
        settings=settings,
        )
    except Exception:
        log.exception("Init : exception construction MainWindow")
        raise
    log.info("Init : MainWindow construite")

    bridge = CaptureBridge(db, settings=settings)

    # Tray icon
    icon = _make_tray_icon()
    tray = QSystemTrayIcon(icon, parent=app)
    tray.setToolTip("Klip — ⌥⌘V")

    # Wrapper anti-spam autour de showMessage() — défini juste après le
    # tray pour pouvoir l'utiliser partout au lieu de tray.showMessage().
    toaster = Toaster(tray, icon)
    menu = QMenu()
    a_open = QAction("Ouvrir l'historique", menu)
    a_open.triggered.connect(lambda: (autopaster.remember_front_app(), window.show_centered()))
    menu.addAction(a_open)

    # Préférences — fenêtre §15 (rétention configurable + journal des changements).
    # On garde une référence à la fenêtre ouverte dans une liste pour éviter
    # que le garbage collector Python la détruise dès que la callback finit.
    _prefs_holder: list = []

    def _open_prefs() -> None:
        # Si déjà ouverte, on la ramène devant plutôt que d'en ouvrir une autre.
        if _prefs_holder and _prefs_holder[-1].isVisible():
            win = _prefs_holder[-1]
            win.raise_()
            win.activateWindow()
            return
        _prefs_holder.clear()
        # On passe l'expander pour permettre le toggle à chaud (onglet Snippets)
        _prefs_holder.append(
            open_preferences(
                settings,
                db,
                expander=expander,
                screenshot_watcher=screenshot_watcher,
                ocr_worker=ocr_worker,
                hotkey_manager=hk,
                parent=None,
            )
        )

    a_prefs = QAction("Préférences…", menu)
    a_prefs.setShortcut(QKeySequence(QKeySequence.StandardKey.Preferences))
    a_prefs.triggered.connect(_open_prefs)
    menu.addSeparator()
    menu.addAction(a_prefs)

    # Cheatsheet ⌘? — popup d'aide listant tous les raccourcis.
    # Singleton léger comme pour les Préférences pour éviter d'en ouvrir 10.
    _cheat_holder: list = []

    def _open_cheat() -> None:
        if _cheat_holder and _cheat_holder[-1].isVisible():
            win = _cheat_holder[-1]
            win.raise_()
            win.activateWindow()
            return
        _cheat_holder.clear()
        _cheat_holder.append(open_cheatsheet(parent=None))

    a_cheat = QAction("Raccourcis…", menu)
    a_cheat.setShortcut(QKeySequence("Ctrl+?"))
    a_cheat.triggered.connect(_open_cheat)
    menu.addAction(a_cheat)

    # Guide d'utilisation — explication détaillée de chaque feature.
    _guide_holder: list = []

    def _open_guide() -> None:
        if _guide_holder and _guide_holder[-1].isVisible():
            win = _guide_holder[-1]
            win.raise_()
            win.activateWindow()
            return
        _guide_holder.clear()
        _guide_holder.append(open_guide(parent=None))

    a_guide = QAction("Guide d'utilisation…", menu)
    a_guide.triggered.connect(_open_guide)
    menu.addAction(a_guide)

    # Permissions — statut live + accès direct au bon réglage.
    _perms_holder: list = []

    def _open_perms() -> None:
        if _perms_holder and _perms_holder[-1].isVisible():
            win = _perms_holder[-1]
            win.raise_()
            win.activateWindow()
            return
        from .permissions_dialog import open_permissions
        _perms_holder.clear()
        _perms_holder.append(open_permissions(parent=None))

    a_perms = QAction("Permissions…", menu)
    a_perms.triggered.connect(_open_perms)
    menu.addAction(a_perms)

    # Note : l'action « Mini-fenêtre flottante » est ajoutée plus bas,
    # après la création de l'instance FloatingWindow (sinon UnboundLocalError
    # sur la variable `floating` qui n'est pas encore définie au moment de
    # la construction du menu).

    # À propos — version + stats DB.
    _about_holder: list = []

    def _open_about() -> None:
        if _about_holder and _about_holder[-1].isVisible():
            win = _about_holder[-1]
            win.raise_()
            win.activateWindow()
            return
        _about_holder.clear()
        _about_holder.append(open_about(db, parent=None))

    a_about = QAction("À propos de Klip…", menu)
    a_about.triggered.connect(_open_about)
    menu.addAction(a_about)

    a_clear = QAction("Vider (hors favoris/snippets)", menu)
    def _clear():
        n = db.clear_non_favorites()
        window.refresh()
        toaster.show("Klip", f"{n} élément(s) supprimé(s)", 2000)
    a_clear.triggered.connect(_clear)
    a_quit = QAction("Quitter", menu)
    a_quit.triggered.connect(app.quit)
    menu.addSeparator()
    menu.addAction(a_clear)
    menu.addSeparator()
    menu.addAction(a_quit)
    tray.setContextMenu(menu)

    # Raccourci ⌘, quand la MainWindow (historique) est ouverte.
    # QKeySequence.StandardKey.Preferences se mappe à ⌘+, sur macOS.
    prefs_sc = QShortcut(QKeySequence(QKeySequence.StandardKey.Preferences), window)
    prefs_sc.setContext(Qt.ShortcutContext.WindowShortcut)
    prefs_sc.activated.connect(_open_prefs)

    # ⌘? ouvre la cheatsheet depuis la MainWindow. Sur macOS, ⌘? se tape
    # avec Shift (⌘⇧/ sur QWERTY) — on accepte les deux pour la robustesse.
    cheat_sc = QShortcut(QKeySequence("Ctrl+?"), window)
    cheat_sc.setContext(Qt.ShortcutContext.WindowShortcut)
    cheat_sc.activated.connect(_open_cheat)
    cheat_sc2 = QShortcut(QKeySequence("Ctrl+Shift+/"), window)
    cheat_sc2.setContext(Qt.ShortcutContext.WindowShortcut)
    cheat_sc2.activated.connect(_open_cheat)
    tray.activated.connect(
        lambda reason: (
            autopaster.remember_front_app(),
            window.show_centered(),
        )
        if reason == QSystemTrayIcon.ActivationReason.Trigger
        else None
    )
    tray.show()

    def _show_from_hotkey():
        autopaster.remember_front_app()
        QTimer.singleShot(0, window.show_centered)

    # Hotkey global principal (⌥⌘V par défaut, éditable depuis Préférences)
    hk = HotkeyManager(_show_from_hotkey)
    if not hk.install() and hk.error:
        QTimer.singleShot(
            500,
            lambda: toaster.show(
                "Klip", hk.error or "Raccourci global indisponible", 5000
            ),
        )

    # Hotkey custom de capture instantanée (session 5 v2) — par défaut
    # ⌥⌘⇧S. Lance `screencapture -i -c` qui prend une capture
    # interactive et l'envoie DIRECTEMENT au presse-papiers (pas de
    # fichier sur disque, pas de vignette macOS bloquante). Notre
    # ClipboardWatcher détecte l'image en 150 ms et l'ajoute à
    # l'historique normalement.
    def _quick_capture() -> None:
        try:
            subprocess.Popen(
                ["screencapture", "-i", "-c"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            log.exception("Échec du lancement de `screencapture -i -c`")

    capture_combo = str(
        settings.get("capture.hotkey", "<alt>+<cmd>+<shift>+s")
        or "<alt>+<cmd>+<shift>+s"
    )
    hk_capture = HotkeyManager(_quick_capture, combo=capture_combo)
    if not hk_capture.install() and hk_capture.error:
        # Pas critique — peut être un conflit avec un autre app, ou la
        # permission Surveillance des entrées n'est pas donnée.
        QTimer.singleShot(
            1500,
            lambda: toaster.show(
                "Klip",
                "Raccourci de capture indisponible — voir Préférences → Capture",
                4000,
            ),
        )

    # OCR worker
    ocr_worker = OCRWorker(db, settings=settings)
    ocr_worker.start()

    # Mini-fenêtre flottante (Phase 6, session 5) — opt-in.
    def _floating_copy(item) -> None:
        """Callback appelé quand on clique sur une mini-card.
        On reproduit la logique de MainWindow.copy_current : write_text/image
        dans le pasteboard, touch l'item en DB, puis re-active l'app
        précédente + ⌘V via autopaste.
        """
        try:
            if item.kind == "image":
                blob = db.get_image_blob(item.id)
                if blob:
                    # Option « Toujours masquer les secrets » (v2.5).
                    from .redact import export_png
                    out = export_png(blob, settings)
                    if out is None:
                        return  # masquage impossible → rien ne sort
                    write_image(out)
            else:
                if item.text is not None:
                    write_text(item.text)
            db.touch(item.id)
            if window.isVisible():
                window.refresh()
            QTimer.singleShot(50, autopaster.restore_and_paste)
        except Exception:
            pass

    floating = FloatingWindow(db, settings, copy_callback=_floating_copy)
    if bool(settings.get("floating.enabled", False)):
        floating.show_window()
        QTimer.singleShot(0, floating.refresh)

    def _on_capture(_id: int, kind: str) -> None:
        if kind == "image":
            ocr_worker.kick()
        if window.isVisible():
            window.refresh()
        # Refresh la mini-fenêtre seulement si elle est visible — pas la
        # peine de charger la DB sinon.
        if floating.isVisible():
            floating.refresh()
    bridge.captured.connect(_on_capture)

    # Quand l'OCR de fond termine une image, on rafraîchit l'item dans la
    # fenêtre pour faire apparaître le texte + le bouton « Copier le texte
    # (OCR) » SANS attendre une resélection manuelle. Avant ce branchement,
    # le signal `done` n'était connecté à rien : le texte restait invisible
    # jusqu'à ce que l'utilisateur reclique l'item. `window.refresh_ocr` est
    # une méthode d'un QObject du thread principal → la connexion est
    # automatiquement mise en file (QueuedConnection) puisque `done` est
    # émis depuis le thread worker, donc exécution sûre côté UI.
    ocr_worker.done.connect(window.refresh_ocr)

    # Sync du setting quand l'utilisateur ferme la mini-window via la croix
    def _on_floating_visibility(visible: bool) -> None:
        try:
            settings.set(
                "floating.enabled",
                bool(visible),
                note=(
                    "Mini-fenêtre affichée."
                    if visible
                    else "Mini-fenêtre cachée."
                ),
                source="floating_ui",
            )
        except Exception:
            pass
    floating.visibility_changed.connect(_on_floating_visibility)

    # Action tray « Mini-fenêtre flottante » — déplacée ici (depuis le
    # bloc tray menu plus haut) parce qu'elle a besoin que `floating`
    # existe au moment où on connecte `visibility_changed`. Si on la met
    # avant la création de FloatingWindow, Python lève UnboundLocalError
    # (la variable `floating` est marquée comme locale à `main()` mais
    # pas encore assignée à l'évaluation de cette ligne).
    def _toggle_floating() -> None:
        if not floating.isVisible():
            floating.refresh()
        floating.toggle()

    a_floating = QAction("Mini-fenêtre flottante", menu)
    a_floating.setCheckable(True)
    a_floating.setChecked(bool(settings.get("floating.enabled", False)))
    a_floating.triggered.connect(_toggle_floating)
    floating.visibility_changed.connect(a_floating.setChecked)
    # On insère cette action juste avant le séparateur de la zone « Vider »
    # pour la voir bien placée dans le menu (entre « Guide… » et « Vider »).
    # `insertAction(before, action)` ; on cherche le premier separator.
    seps = [a for a in menu.actions() if a.isSeparator()]
    if seps:
        menu.insertAction(seps[0], a_floating)
    else:
        menu.addAction(a_floating)

    def _on_secret_blocked(kind: str) -> None:
        toaster.show(
            "Klip",
            f"Secret détecté ({kind}) — non enregistré.",
            2500,
        )
    bridge.secret_blocked.connect(_on_secret_blocked)

    def _on_too_large(kind: str, size_bytes: int) -> None:
        mb = size_bytes / (1024 * 1024)
        label = "Texte" if kind == "text" else "Image"
        toaster.show(
            "Klip",
            f"{label} trop volumineux ({mb:.1f} Mo) — non enregistré. "
            f"Augmentez la limite dans Préférences → Capture.",
            3000,
        )
    bridge.too_large_skipped.connect(_on_too_large)

    # Screenshot watcher : ⌘⇧3/4/5 enregistre un fichier ; on le pousse
    # automatiquement dans l'historique + le presse-papier pour éviter à
    # l'utilisateur d'avoir à utiliser le combo Ctrl+⌘⇧4.
    screenshot_watcher = ScreenshotWatcher()

    def _on_screenshot(path: str) -> None:
        try:
            blob = Path(path).read_bytes()
        except Exception:
            log.exception("Lecture du fichier screenshot %r impossible", path)
            return
        if not blob:
            log.warning("Screenshot %r est vide — on ignore", path)
            return
        w, h = png_dimensions(blob)
        new_id = db.add_image(blob, w, h, "Screenshot")
        if new_id is None:
            log.warning("db.add_image a renvoyé None (doublon ?) pour %r", path)
            return
        # Aussi dans le presse-papier système, pour un ⌘V immédiat sans passer
        # par la fenêtre de l'app.
        try:
            write_image(blob)
        except Exception:
            log.exception("write_image vers le presse-papier a échoué")
        ocr_worker.kick()
        if window.isVisible():
            window.refresh()
        toaster.show(
            "Klip",
            f"Capture ajoutée ({w}×{h}) — collez avec ⌘V",
            1500,
        )

    screenshot_watcher.new_screenshot.connect(_on_screenshot)
    screenshot_watcher.error_message.connect(
        lambda msg: toaster.show("Klip", msg, 6000)
    )
    screenshot_watcher.start()

    # Text expander : lookup → contenu du snippet.
    # ⚠️ L'expander écoute le clavier global → OPT-IN explicite via
    # settings.expander.enabled. Tant que désactivé, on ne démarre pas
    # le listener pynput (zéro surveillance des frappes).
    def _snippet_lookup(name: str) -> Optional[str]:
        item = db.find_snippet(name)
        if item and item.text:
            return item.text
        return None

    expander = TextExpander(_snippet_lookup)
    if settings.get("expander.enabled", False):
        expander.start()  # silencieux si pynput n'a pas de permission
    else:
        # Notification une seule fois pour informer que la feature existe
        # mais qu'elle nécessite un opt-in.
        if not settings.get("expander.notified_optin", False):
            QTimer.singleShot(
                3000,
                lambda: toaster.show(
                    "Klip",
                    "Snippets ;nom désactivés (l'expander lit le clavier global). "
                    "Activez-les dans Préférences → Snippets.",
                    6000,
                ),
            )
            settings.set("expander.notified_optin", True, source="migration")

    # --- Rétention + cap quotidien --------------------------------------
    # On purge :
    #   • par âge (settings.retention.text_days / image_days)
    #   • puis cap global (settings.retention.max_items)
    # Favoris et snippets sont préservés dans les deux cas.
    def _do_retention() -> None:
        try:
            text_days = settings.get("retention.text_days")
            image_days = settings.get("retention.image_days")
            max_items = settings.get("retention.max_items", 5000)
            # `None` / valeur négative = pas de purge par âge.
            n_age = db.trim_by_age(
                max_text_days=text_days if isinstance(text_days, int) and text_days >= 0 else None,
                max_image_days=image_days if isinstance(image_days, int) and image_days >= 0 else None,
            )
            n_cap = db.trim_to(int(max_items)) if isinstance(max_items, (int, float)) else 0
            total = (n_age.get("text", 0) + n_age.get("image", 0) + (n_cap or 0))
            if total > 0:
                log.info(
                    "Rétention : %d items purgés (texte=%d, image=%d, cap=%d)",
                    total,
                    n_age.get("text", 0),
                    n_age.get("image", 0),
                    n_cap or 0,
                )
                toaster.show(
                    "Klip",
                    f"Rétention : {total} ancien(s) item(s) supprimé(s).",
                    3000,
                )
        except Exception:
            log.exception("Passe de rétention échouée")

    # Premier passage 30s après le démarrage (laisse l'app respirer), puis 1×/h
    QTimer.singleShot(30 * 1000, _do_retention)
    trim_timer = QTimer()
    trim_timer.setInterval(60 * 60 * 1000)
    trim_timer.timeout.connect(_do_retention)
    trim_timer.start()

    # Sortie propre
    app.aboutToQuit.connect(ocr_worker.stop)
    app.aboutToQuit.connect(expander.stop)
    app.aboutToQuit.connect(hk.stop)
    app.aboutToQuit.connect(hk_capture.stop)
    app.aboutToQuit.connect(screenshot_watcher.stop)

    # Onboarding visuel — uniquement au tout premier lancement.
    # On garde une référence pour éviter le GC immédiat du QDialog.
    # NB : déclenché APRÈS l'activation de la licence (cf. _do_unlock_and_open),
    # pour éviter que l'onboarding et l'écran d'activation se chevauchent.
    _onboarding_holder: list = []

    def _maybe_show_onboarding() -> None:
        if bool(settings.get("onboarded", False)):
            return

        def _on_onboarding_done(skipped: bool) -> None:
            settings.set(
                "onboarded",
                True,
                note=("Onboarding passé" if skipped else "Onboarding terminé"),
                source="onboarding",
            )
            # Au premier lancement, on ouvre la fenetre d'historique
            # automatiquement pour que l'user comprenne que l'app vit
            # dans la barre de menu et voie son interface principale.
            QTimer.singleShot(200, window.show_centered)
            # Si une permission manque encore, on propose directement le
            # panneau de statut (plus simple que de chercher dans Réglages).
            def _check_perms():
                try:
                    from . import permissions
                    if not permissions.all_granted():
                        from .permissions_dialog import open_permissions
                        _onboarding_holder.append(open_permissions(parent=None))
                except Exception as e:
                    log.warning("Vérif permissions post-onboarding échouée : %r", e)
            QTimer.singleShot(700, _check_perms)

        win = open_onboarding(parent=None)
        win.finished_setup.connect(_on_onboarding_done)
        _onboarding_holder.append(win)

    # Helper : show la main window au premier plan macOS.
    def _open_window_now():
        log.info("Auto-open : show_centered() declenche")
        try:
            import AppKit  # pyobjc
            AppKit.NSApp.activateIgnoringOtherApps_(True)
        except Exception as e:
            log.warning("NSApp.activate echoue : %r", e)
        try:
            window.show_centered()
            QTimer.singleShot(150, window.raise_)
            QTimer.singleShot(200, window.activateWindow)
        except Exception as e:
            log.exception("Auto-open echoue : %r", e)

    # Auto-open de la fenetre principale au demarrage.
    # On declenche dans une callback differee (apres app.exec() lance)
    # pour eviter les states Qt bizarres causes par un modal trop tot.
    # NB : l'ancien "lockscreen" (gate mot de passe en dur) a ete retire
    # pour la distribution — aucune barriere a l'ouverture.
    def _do_unlock_and_open():
        # Klip est GRATUIT et sans activation : aucune clé requise pour l'utiliser
        # (accès libre après téléchargement). On ouvre directement.
        # Onboarding (1er lancement) sinon ouverture directe de la fenêtre.
        if not bool(settings.get("onboarded", False)):
            QTimer.singleShot(300, _maybe_show_onboarding)
        else:
            _open_window_now()

    QTimer.singleShot(300, _do_unlock_and_open)

    # Quand l'utilisateur double-clic sur Klip.app dans Applications
    # (alors qu'elle tourne deja en menubar), on reaffiche la fenetre.
    def _on_app_activate():
        log.info("ApplicationActivate intercepte")
        _open_window_now()
    # En PyQt6 : on intercepte via un event filter sur l'app
    from PyQt6.QtCore import QEvent
    class _ActivateFilter(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Type.ApplicationActivate:
                _on_app_activate()
            return False
    _filter = _ActivateFilter()
    app.installEventFilter(_filter)
    # Garde une ref pour pas que le GC bouffe le filter
    app._klip_activate_filter = _filter

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
