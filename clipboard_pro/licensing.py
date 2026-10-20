"""Licence hors-ligne pour Klip — vérification par signature Ed25519.

Principe : chaque utilisateur reçoit une clé de licence signée par la clé
privée maître (détenue par l'éditeur uniquement). L'app ne contient que la
clé PUBLIQUE et se contente de vérifier la signature → impossible de forger
une licence, même en lisant le code. Tout est local, aucun réseau.

Deux types de licence (au choix de l'éditeur, par clé) :
  • nominative          : champ "m" vide → utilisable sur n'importe quel Mac,
                          mais le nom du titulaire est affiché dans l'app
                          (dissuasion sociale contre le repartage).
  • verrouillée machine : champ "m" = empreinte du Mac cible → la licence ne
                          fonctionne que sur cette machine (anti-partage fort).

Format d'une clé :  KLIP1.<base64url(payload_json)>.<base64url(signature)>
payload_json = {"n": nom, "m": machine_id|"", "id": id_licence, "t": epoch}
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from . import _ed25519 as ed

# --- Clé publique maître (NON secrète). Générée une fois ; doit correspondre
#     à la clé privée gardée par l'éditeur (klip_master_key.secret). ----------
PUBLIC_KEY_B64 = "LCLv_LkLDU-rpJe7C2GnDpHLMXcJdPxbyiQokWY1M2o="

KEY_PREFIX = "KLIP1"
LICENSE_PATH = Path.home() / ".clipboard_pro" / "license.dat"


def _pubkey() -> bytes:
    return base64.urlsafe_b64decode(PUBLIC_KEY_B64)


# --- Empreinte machine -------------------------------------------------------
def machine_id() -> str:
    """Empreinte stable et anonyme du Mac (hash de l'IOPlatformUUID).

    Repli sur l'adresse MAC matérielle si ioreg est indisponible. La valeur
    est hashée → ne révèle pas l'UUID réel.
    """
    raw = ""
    try:
        out = subprocess.check_output(
            ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode("utf-8", "replace")
        m = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
        if m:
            raw = m.group(1)
    except Exception:
        raw = ""
    if not raw:
        try:
            import uuid
            raw = format(uuid.getnode(), "x")
        except Exception:
            raw = "unknown-machine"
    return hashlib.sha256(("klip:" + raw).encode()).hexdigest()[:16]


# --- Décodage / vérification d'une clé --------------------------------------
def _b64d(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def parse_key(key_str: str) -> Optional[dict]:
    """Vérifie la signature et renvoie le payload, ou None si invalide."""
    if not key_str:
        return None
    parts = key_str.strip().replace("\n", "").split(".")
    if len(parts) != 3 or parts[0] != KEY_PREFIX:
        return None
    try:
        payload = _b64d(parts[1])
        sig = _b64d(parts[2])
    except Exception:
        return None
    if not ed.checkvalid(sig, payload, _pubkey()):
        return None
    try:
        return json.loads(payload.decode("utf-8"))
    except Exception:
        return None


def verify_key(key_str: str) -> Tuple[bool, Optional[dict], str]:
    """(ok, info, raison). Vérifie signature ET liaison machine."""
    data = parse_key(key_str)
    if data is None:
        return False, None, "Clé invalide ou corrompue."
    bound = data.get("m") or ""
    if bound and bound != machine_id():
        return False, data, "Cette licence est liée à un autre Mac."
    return True, data, ""


# --- Stockage local de la licence -------------------------------------------
def save_license(key_str: str) -> None:
    LICENSE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LICENSE_PATH.write_text(key_str.strip(), encoding="utf-8")
    try:
        os.chmod(LICENSE_PATH, 0o600)
    except OSError:
        pass


def load_license() -> Optional[str]:
    try:
        return LICENSE_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def current_license() -> Tuple[bool, Optional[dict]]:
    """Charge la licence stockée et la vérifie. (ok, info)."""
    key = load_license()
    if not key:
        return False, None
    ok, info, _ = verify_key(key)
    return ok, info


def licensee_name() -> str:
    ok, info = current_license()
    if ok and info:
        return str(info.get("n", "")).strip()
    return ""
