"""Gestion des licences côté ÉDITEUR (toi). Activé uniquement si la clé privée
maître est présente sur la machine — donc invisible chez les amis.

Permet, depuis l'app :
- générer une clé de licence signée (même format que tools/klip_license.py),
- garder un registre local des clés émises (~/.clipboard_pro/licenses.json),
- préparer un dossier prêt à envoyer (DMG + notice + clé),
- préparer un email (via Mail.app, gratuit, depuis ton compte).

⚠️ La clé privée ne quitte jamais ta machine. Ce module n'est jamais
fonctionnel chez un ami (pas de clé privée → mode éditeur off).
"""
from __future__ import annotations

import base64
import json
import os
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from . import _ed25519 as ed

HOME = Path.home()
DATA_DIR = HOME / ".clipboard_pro"
REGISTRY_PATH = DATA_DIR / "licenses.json"

# Emplacements possibles de la clé privée maître (ordre de priorité).
_SECRET_LOCATIONS = [
    DATA_DIR / "klip_master_key.secret",
    HOME / "clipboard_history_app" / "klip_master_key.secret",
]

# Où chercher l'installateur (DMG macOS / EXE Windows) à joindre.
_INSTALLER_DIRS = [
    HOME / "clipboard_history_app",
    HOME / "Downloads",
    HOME / "Desktop",
]


# --- Clé privée / mode éditeur ----------------------------------------------
def load_private_key_hex() -> Optional[str]:
    env = os.environ.get("KLIP_PRIVATE_HEX", "").strip()
    if env:
        return env
    for p in _SECRET_LOCATIONS:
        try:
            if p.exists():
                for line in p.read_text().splitlines():
                    line = line.strip()
                    if line.startswith("PRIVATE_KEY_HEX="):
                        return line.split("=", 1)[1].strip()
        except OSError:
            continue
    return None


def is_editor() -> bool:
    """True si la clé privée est disponible → on est sur la machine éditeur."""
    hx = load_private_key_hex()
    if not hx:
        return False
    try:
        return len(bytes.fromhex(hx)) == 32
    except ValueError:
        return False


# --- Génération de clé -------------------------------------------------------
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def issue(name: str, email: str = "", machine_id: str = "") -> Optional[str]:
    """Génère et renvoie une clé de licence signée, ou None si pas éditeur."""
    hx = load_private_key_hex()
    if not hx:
        return None
    sk = bytes.fromhex(hx)
    pk = ed.publickey(sk)
    payload = {
        "n": name.strip(),
        "m": (machine_id or "").strip(),
        "id": secrets.token_hex(4),
        "t": int(time.time()),
    }
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig = ed.signature(payload_bytes, sk, pk)
    key_str = "KLIP1." + _b64(payload_bytes) + "." + _b64(sig)
    return key_str


# --- Registre local ----------------------------------------------------------
def list_entries() -> list[dict]:
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (OSError, ValueError):
        pass
    return []


def _save_entries(entries: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(REGISTRY_PATH, 0o600)
    except OSError:
        pass


def add_and_issue(name: str, email: str = "", machine_id: str = "",
                  platform: str = "mac") -> Optional[dict]:
    """Génère une clé, l'enregistre dans le registre, renvoie l'entrée créée.

    platform : "mac" ou "windows" — détermine l'installateur et la notice
    inclus dans le dossier d'envoi.
    """
    key = issue(name, email, machine_id)
    if not key:
        return None
    entry = {
        "name": name.strip(),
        "email": (email or "").strip(),
        "machine_id": (machine_id or "").strip(),
        "platform": "windows" if str(platform).lower().startswith("win") else "mac",
        "key": key,
        "created_at": time.time(),
    }
    entries = list_entries()
    entries.insert(0, entry)
    _save_entries(entries)
    return entry


# --- Sélection de l'installateur selon la plateforme ------------------------
def find_installer(platform: str = "mac") -> Optional[Path]:
    """Trouve l'installateur le plus récent : DMG (mac) ou EXE (windows)."""
    patterns = ("Klip-*.exe", "Klip*Setup*.exe") if str(platform).lower().startswith("win") \
        else ("Klip-*.dmg",)
    candidates: list[Path] = []
    for d in _INSTALLER_DIRS:
        for pat in patterns:
            try:
                candidates.extend(d.glob(pat))
            except OSError:
                continue
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def find_dmg() -> Optional[Path]:  # rétro-compat
    return find_installer("mac")


_NOTICE_MAC = """KLIP — Installation (Mac)

1) Ouvre Klip-*.dmg → glisse Klip dans Applications.
2) 1er lancement : CLIC DROIT sur Klip → Ouvrir → Ouvrir (une seule fois).
3) Klip demande une clé : colle la clé du fichier "Cle-de-licence.txt".

Si "Klip est endommagé" : ouvre Terminal et colle :
    xattr -dr com.apple.quarantine /Applications/Klip.app
puis relance Klip.

Raccourci : Option+Cmd+V.  Tout est local, rien n'est envoyé sur Internet.
"""

_NOTICE_WIN = """KLIP — Installation (Windows)

1) Lance l'installateur Klip (.exe).
2) Si "Windows a protégé votre PC" : clique "Informations complémentaires"
   puis "Exécuter quand même".
3) Klip demande une clé : colle la clé du fichier "Cle-de-licence.txt".

Raccourci : Ctrl+Alt+V.  Tout est local, rien n'est envoyé sur Internet.
"""


def _notice_for(platform: str) -> str:
    return _NOTICE_WIN if str(platform).lower().startswith("win") else _NOTICE_MAC


def _safe(name: str) -> str:
    s = re.sub(r"[^\w\- ]", "", name).strip().replace(" ", "-")
    return s or "ami"


def prepare_package(entry: dict, dest_base: Optional[Path] = None) -> dict:
    """Crée un dossier prêt à envoyer (installateur + notice + clé), selon la
    plateforme de l'entrée. Renvoie {ok, folder, installer_included, error}.
    """
    platform = entry.get("platform", "mac")
    base = dest_base or (HOME / "Desktop")
    folder = base / f"Klip-pour-{_safe(entry.get('name', 'ami'))}"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "Cle-de-licence.txt").write_text(
            f"Klip — clé de licence pour {entry.get('name','')}\n\n"
            f"{entry.get('key','')}\n\n"
            "Colle cette clé au premier lancement de Klip.\n",
            encoding="utf-8",
        )
        (folder / "LISEZ-MOI.txt").write_text(_notice_for(platform), encoding="utf-8")
        installer = find_installer(platform)
        included = False
        if installer and installer.exists():
            shutil.copy2(installer, folder / installer.name)
            included = True
        return {"ok": True, "folder": str(folder), "installer_included": included, "error": ""}
    except Exception as e:
        return {"ok": False, "folder": str(folder), "installer_included": False, "error": str(e)}


def _email_html(entry: dict, download_url: Optional[str] = None) -> str:
    """Template HTML d'email (branding orange Klip + HUMAIN). Une seule ligne
    (pas de retour à la ligne brut) pour s'insérer proprement dans AppleScript.
    Si `download_url` est fourni, un bouton de téléchargement est inclus
    (au lieu de référencer une pièce jointe).
    """
    name = (entry.get("name") or "").strip()
    key = (entry.get("key") or "").strip()
    win = str(entry.get("platform", "mac")).lower().startswith("win")
    shortcut = "Ctrl + Alt + V" if win else "⌥ ⌘ V"
    src = "l'installateur ci-dessous" if download_url else "le fichier en pièce jointe"
    if win:
        steps = (
            f"<li>Télécharge et lance {src} (.exe).</li>"
            "<li>Si « Windows a protégé votre PC » : clique « Informations "
            "complémentaires » puis « Exécuter quand même ».</li>"
            "<li>Colle ta clé ci-dessous au premier lancement.</li>"
        )
    else:
        steps = (
            f"<li>Ouvre {src} (.dmg), glisse <b>Klip</b> dans Applications.</li>"
            "<li>Premier lancement : <b>clic droit</b> sur Klip → <b>Ouvrir</b> "
            "→ Ouvrir (une seule fois).</li>"
            "<li>Colle ta clé ci-dessous au premier lancement.</li>"
        )
    button = ""
    if download_url:
        button = (
            f'<a href="{download_url}" style="display:inline-block;'
            'background:linear-gradient(135deg,#F59E0B,#D97706);color:#fff;'
            'text-decoration:none;font-weight:700;padding:13px 22px;'
            'border-radius:10px;margin:4px 0 20px">⬇  Télécharger Klip</a>'
        )
    return (
        '<div style="font-family:-apple-system,Segoe UI,Inter,sans-serif;'
        'max-width:560px;margin:0 auto;background:#0D0E12;border-radius:16px;'
        'overflow:hidden;border:1px solid rgba(255,255,255,.08)">'
        '<div style="background:linear-gradient(135deg,#F59E0B,#D97706);'
        'padding:28px 28px 22px">'
        '<div style="font-size:22px;font-weight:800;color:#1a1206">✂ Klip</div>'
        '<div style="font-size:14px;color:#3a2a06;margin-top:2px">'
        'Le presse-papiers qui n\'oublie rien.</div></div>'
        '<div style="padding:26px 28px;color:#EEF0F6">'
        f'<p style="font-size:16px;margin:0 0 14px">Salut {name} 👋</p>'
        '<p style="font-size:14px;color:#A5ABC0;line-height:1.6;margin:0 0 18px">'
        'Voici ton accès à <b style="color:#EEF0F6">Klip</b>. Trois étapes :</p>'
        f'<ol style="font-size:14px;color:#cfd3e0;line-height:1.7;'
        f'padding-left:18px;margin:0 0 16px">{steps}</ol>'
        f'{button}'
        '<div style="font-size:12px;color:#6A7088;margin:0 0 6px">'
        'TA CLÉ DE LICENCE</div>'
        '<div style="font-family:ui-monospace,Menlo,monospace;font-size:12px;'
        'color:#FBBF24;background:#1E2230;border:1px solid rgba(255,255,255,.08);'
        f'border-radius:10px;padding:12px 14px;word-break:break-all">{key}</div>'
        '<p style="font-size:13px;color:#A5ABC0;margin:18px 0 0">Ouvre Klip de '
        f'partout avec <b style="color:#EEF0F6">{shortcut}</b>. Tout reste sur '
        'ton ordi, rien n\'est envoyé sur Internet.</p>'
        '<p style="font-size:12px;color:#6A7088;margin:22px 0 0;'
        'border-top:1px solid rgba(255,255,255,.08);padding-top:14px">'
        'Un produit <b style="color:#A5ABC0">HUMAIN</b> · créé par Sarah</p>'
        '</div></div>'
    )


# --- Config email SMTP (Gmail / autre) --------------------------------------
MAIL_CONFIG_PATH = DATA_DIR / "klip_mail.json"


def load_mail_config() -> Optional[dict]:
    """Lit ~/.clipboard_pro/klip_mail.json si présent et complet."""
    try:
        cfg = json.loads(MAIL_CONFIG_PATH.read_text(encoding="utf-8"))
        if cfg.get("user") and cfg.get("password"):
            return cfg
    except (OSError, ValueError):
        pass
    return None


def mail_config_exists() -> bool:
    return load_mail_config() is not None


def _download_url_for(cfg: dict, platform: str) -> Optional[str]:
    if str(platform).lower().startswith("win"):
        return cfg.get("download_url_windows") or cfg.get("download_url")
    return cfg.get("download_url_mac") or cfg.get("download_url")


def send_email_smtp(entry: dict, cfg: dict) -> tuple[bool, str]:
    """Envoie l'email via SMTP (ex. Gmail) — 100% automatique, sans Mail.app.
    Inclut un bouton de téléchargement (lien) ; joint l'installateur seulement
    s'il est petit (< 20 Mo) et qu'aucun lien n'est configuré.
    """
    import smtplib
    import ssl
    from email.message import EmailMessage

    to = (entry.get("email") or "").strip()
    if not to:
        return False, "Aucune adresse email enregistrée pour cette licence."
    platform = entry.get("platform", "mac")
    dl = _download_url_for(cfg, platform)

    msg = EmailMessage()
    msg["Subject"] = "Ton accès à Klip 🧡"
    msg["From"] = f'{cfg.get("from_name", "HUMAIN")} <{cfg["user"]}>'
    msg["To"] = to
    key = entry.get("key", "")
    msg.set_content(
        f"Salut {entry.get('name','')},\n\nVoici ton accès à Klip.\n"
        f"Clé de licence : {key}\n"
        + (f"Télécharger : {dl}\n" if dl else "")
        + "\nUn produit HUMAIN."
    )
    msg.add_alternative(_email_html(entry, download_url=dl), subtype="html")

    if not dl:
        installer = find_installer(platform)
        if installer is None:
            return False, "Aucun lien de téléchargement configuré et installateur introuvable."
        if installer.stat().st_size > 20 * 1024 * 1024:
            return False, (
                f"L'installateur ({installer.stat().st_size // (1024*1024)} Mo) est trop "
                "lourd pour être joint par email. Configure un lien de téléchargement "
                "(download_url_mac / download_url_windows dans klip_mail.json)."
            )
        msg.add_attachment(installer.read_bytes(), maintype="application",
                           subtype="octet-stream", filename=installer.name)

    host = cfg.get("smtp_host", "smtp.gmail.com")
    port = int(cfg.get("smtp_port", 465))
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=30) as s:
            s.login(cfg["user"], cfg["password"])
            s.send_message(msg)
        return True, f"Email envoyé à {to} depuis {cfg['user']} ✅"
    except smtplib.SMTPAuthenticationError:
        return False, ("Authentification refusée. Vérifie l'adresse et le "
                       "« mot de passe d'application » dans klip_mail.json.")
    except Exception as e:
        return False, f"Échec de l'envoi : {e}"


def send_email(entry: dict, send: bool = True) -> tuple[bool, str]:
    """Envoie l'email. Priorité au SMTP (config klip_mail.json) ; sinon repli
    sur Mail.app (qui nécessite un compte configuré dans l'app Mail).
    """
    to = (entry.get("email") or "").strip()
    if not to:
        return False, "Aucune adresse email enregistrée pour cette licence."

    cfg = load_mail_config()
    if cfg:
        return send_email_smtp(entry, cfg)

    # --- Repli Mail.app (legacy) ---
    platform = entry.get("platform", "mac")
    installer = find_installer(platform)
    if installer is None:
        kind = "l'installateur Windows (.exe)" if str(platform).startswith("win") else "le DMG"
        return False, f"Impossible de trouver {kind} à joindre. Construis-le d'abord."

    subject = "Ton accès à Klip 🧡"
    html = _email_html(entry)

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    send_line = "send newMsg" if send else "activate"
    script = (
        'tell application "Mail"\n'
        f'set newMsg to make new outgoing message with properties {{subject:"{esc(subject)}", visible:true}}\n'
        'tell newMsg\n'
        f'set html content to "{esc(html)}"\n'
        f'make new to recipient at end of to recipients with properties {{address:"{esc(to)}"}}\n'
        f'make new attachment with properties {{file name:(POSIX file "{esc(str(installer))}")}} at after the last paragraph\n'
        'end tell\n'
        f'{send_line}\n'
        'end tell\n'
    )
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True,
                           text=True, timeout=60)
        if r.returncode != 0:
            return False, (r.stderr or "Erreur Mail.app").strip()
        verb = "envoyé" if send else "préparé"
        return True, f"Email {verb} à {to} ({installer.name} en pièce jointe via Mail Drop si nécessaire)."
    except Exception as e:
        return False, str(e)
