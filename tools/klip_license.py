#!/usr/bin/env python3
"""Outil ÉDITEUR pour générer des licences Klip. NE PAS distribuer.

À garder pour toi (Yoni). Utilise la clé privée maître pour signer des
licences que l'app vérifiera hors-ligne avec sa clé publique.

PRÉREQUIS : la clé privée. Elle est lue, dans l'ordre :
  1. argument  --key <hex>
  2. variable d'environnement  KLIP_PRIVATE_HEX
  3. fichier  klip_master_key.secret  (ligne PRIVATE_KEY_HEX=...)

────────────────────────────────────────────────────────────────────────
EXEMPLES
  # Licence nominative (marche sur n'importe quel Mac, marquée au nom) :
  python3 tools/klip_license.py issue --name "Alice Dupont"

  # Licence verrouillée à un Mac précis (anti-partage fort) :
  #   l'ami te donne son "Identifiant de ce Mac" affiché à l'activation
  python3 tools/klip_license.py issue --name "Bob" --machine 3f9a1c77b0e2d4a8

  # (Ré)génère une nouvelle paire de clés (à faire UNE fois ; nécessite de
  #  re-coller la clé publique dans clipboard_pro/licensing.py + rebuild) :
  python3 tools/klip_license.py keygen
────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import sys
import time
from pathlib import Path

# Importer le module Ed25519 partagé avec l'app.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from clipboard_pro import _ed25519 as ed  # noqa: E402


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _load_private_key(arg_key: str | None) -> bytes:
    hex_key = arg_key or os.environ.get("KLIP_PRIVATE_HEX", "")
    if not hex_key:
        secret_file = ROOT / "klip_master_key.secret"
        if secret_file.exists():
            for line in secret_file.read_text().splitlines():
                if line.strip().startswith("PRIVATE_KEY_HEX="):
                    hex_key = line.split("=", 1)[1].strip()
                    break
    if not hex_key:
        sys.exit(
            "✗ Clé privée introuvable. Fournis --key <hex>, ou KLIP_PRIVATE_HEX, "
            "ou un fichier klip_master_key.secret."
        )
    try:
        sk = bytes.fromhex(hex_key)
    except ValueError:
        sys.exit("✗ Clé privée invalide (hex attendu).")
    if len(sk) != 32:
        sys.exit("✗ Clé privée invalide (32 octets attendus).")
    return sk


def cmd_keygen(_args: argparse.Namespace) -> None:
    sk = os.urandom(32)
    pk = ed.publickey(sk)
    print("Nouvelle paire générée — garde la privée SECRÈTE.\n")
    print("PRIVATE_KEY_HEX=" + sk.hex())
    print("PUBLIC_KEY_B64=" + base64.urlsafe_b64encode(pk).decode())
    print(
        "\n→ Recopie PUBLIC_KEY_B64 dans clipboard_pro/licensing.py "
        "(constante PUBLIC_KEY_B64), puis rebuild l'app."
    )


def cmd_issue(args: argparse.Namespace) -> None:
    sk = _load_private_key(args.key)
    pk = ed.publickey(sk)
    payload = {
        "n": args.name,
        "m": (args.machine or "").strip(),
        "id": secrets.token_hex(4),
        "t": int(time.time()),
    }
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    sig = ed.signature(payload_bytes, sk, pk)
    key_str = "KLIP1." + _b64(payload_bytes) + "." + _b64(sig)

    kind = "verrouillée machine" if payload["m"] else "nominative"
    print(f"Licence {kind} pour : {args.name}")
    if payload["m"]:
        print(f"Machine cible : {payload['m']}")
    print(f"ID licence    : {payload['id']}")
    print("\nClé à transmettre à l'utilisateur (copie tout, une seule ligne) :\n")
    print(key_str)


def main() -> None:
    p = argparse.ArgumentParser(description="Générateur de licences Klip (éditeur).")
    sub = p.add_subparsers(dest="cmd", required=True)

    pk = sub.add_parser("keygen", help="Générer une nouvelle paire de clés.")
    pk.set_defaults(func=cmd_keygen)

    pi = sub.add_parser("issue", help="Émettre une licence.")
    pi.add_argument("--name", required=True, help="Nom du titulaire (affiché dans l'app).")
    pi.add_argument("--machine", default="", help="Identifiant machine (licence verrouillée).")
    pi.add_argument("--key", default="", help="Clé privée hex (sinon env/fichier).")
    pi.set_defaults(func=cmd_issue)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
