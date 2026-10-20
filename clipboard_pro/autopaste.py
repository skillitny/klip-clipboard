"""Auto-paste : réactive l'app frontale précédente et simule ⌘V.

Stratégie :
  1. Au moment où l'utilisateur invoque la fenêtre (hotkey ou tray icon), on
     mémorise l'app frontale via NSWorkspace.frontmostApplication().
  2. Quand il choisit un item et appuie Entrée, on :
       a. masque notre fenêtre,
       b. réactive l'app mémorisée par PID (NSRunningApplication.activateWithOptions_),
       c. simule un ⌘V global avec CGEventCreateKeyboardEvent.
"""
from __future__ import annotations

import time
from typing import Optional

try:
    from AppKit import NSWorkspace, NSRunningApplication  # type: ignore[import]
    from Quartz import (  # type: ignore[import]
        CGEventCreateKeyboardEvent,
        CGEventPost,
        CGEventSetFlags,
        kCGEventFlagMaskCommand,
        kCGHIDEventTap,
    )
    NATIVE_AVAILABLE = True
except Exception:  # pragma: no cover
    NATIVE_AVAILABLE = False


KEY_V = 9  # kVK_ANSI_V


class AutoPaste:
    def __init__(self) -> None:
        self._target_pid: Optional[int] = None
        self._our_pid: Optional[int] = None
        if NATIVE_AVAILABLE:
            try:
                self._our_pid = int(NSRunningApplication.currentApplication().processIdentifier())
            except Exception:
                self._our_pid = None

    def remember_front_app(self) -> None:
        """À appeler juste avant d'afficher la fenêtre."""
        if not NATIVE_AVAILABLE:
            return
        try:
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if not app:
                return
            pid = int(app.processIdentifier())
            # On ignore notre propre process (cas du clic dans le tray)
            if pid == self._our_pid:
                return
            self._target_pid = pid
        except Exception:
            pass

    def restore_and_paste(self) -> bool:
        """Réactive l'app mémorisée et simule ⌘V. Renvoie True si tout a marché."""
        if not NATIVE_AVAILABLE or not self._target_pid:
            return False
        try:
            app = NSRunningApplication.runningApplicationWithProcessIdentifier_(self._target_pid)
            if app is None:
                return False
            # NSApplicationActivateIgnoringOtherApps = 1 << 1 = 2
            app.activateWithOptions_(2)
            # Petit délai pour laisser l'app reprendre le focus avant le paste.
            time.sleep(0.08)
            # Down
            ev = CGEventCreateKeyboardEvent(None, KEY_V, True)
            CGEventSetFlags(ev, kCGEventFlagMaskCommand)
            CGEventPost(kCGHIDEventTap, ev)
            # Up
            ev = CGEventCreateKeyboardEvent(None, KEY_V, False)
            CGEventSetFlags(ev, kCGEventFlagMaskCommand)
            CGEventPost(kCGHIDEventTap, ev)
            return True
        except Exception:
            return False
        finally:
            self._target_pid = None
