"""Détection de secrets — patterns connus + heuristique d'entropie.

Les contenus détectés ne sont pas écrits dans la base. C'est une 2ᵉ ligne
de défense, en plus de l'exclusion des pasteboard `ConcealedType`.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Optional

# Patterns de tokens largement reconnus.
# Sources : github.com/Yelp/detect-secrets, GitHub secret scanning patterns.
TOKEN_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("openai_key",       re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("openai_proj_key",  re.compile(r"\bsk-proj-[A-Za-z0-9_\-]{20,}\b")),
    ("anthropic_key",    re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("github_pat",       re.compile(r"\bghp_[A-Za-z0-9]{36,}\b")),
    ("github_oauth",     re.compile(r"\bgho_[A-Za-z0-9]{36,}\b")),
    ("github_user",      re.compile(r"\bghu_[A-Za-z0-9]{36,}\b")),
    ("github_server",    re.compile(r"\bghs_[A-Za-z0-9]{36,}\b")),
    ("github_refresh",   re.compile(r"\bghr_[A-Za-z0-9]{36,}\b")),
    ("aws_access_key",   re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_session_key",  re.compile(r"\bASIA[0-9A-Z]{16}\b")),
    ("slack_bot",        re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_api",       re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("stripe_live",      re.compile(r"\bsk_live_[0-9a-zA-Z]{24,}\b")),
    ("stripe_test",      re.compile(r"\bsk_test_[0-9a-zA-Z]{24,}\b")),
    ("jwt",              re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]*\b")),
    ("private_key",      re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----")),
    ("ssh_pubkey_priv",  re.compile(r"-----BEGIN OPENSSH PRIVATE KEY-----")),

    # --- Phase 1, session 5 : patterns supplémentaires ---------------------
    # GitHub fine-grained PAT (préfixe github_pat_, 82 chars depuis 2022).
    ("github_pat_fine",  re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    # GitLab personal access tokens (glpat-, 20 chars de base + variantes).
    ("gitlab_pat",       re.compile(r"\bglpat-[A-Za-z0-9_\-]{20,}\b")),
    # Notion internal integration token.
    ("notion_secret",    re.compile(r"\bsecret_[A-Za-z0-9]{43}\b")),
    # Notion v2 (depuis 2023) — préfixe ntn_.
    ("notion_token",     re.compile(r"\bntn_[A-Za-z0-9]{30,}\b")),
    # Hugging Face access tokens (hf_, 30+ chars).
    ("huggingface_token", re.compile(r"\bhf_[A-Za-z0-9]{30,}\b")),
    # Twilio Account SID + Auth Token (clé typique : SK suivi de 32 hex).
    ("twilio_account",   re.compile(r"\bAC[a-f0-9]{32}\b")),
    ("twilio_api_key",   re.compile(r"\bSK[a-f0-9]{32}\b")),
    # SendGrid API key (SG. + 22 chars + . + 43 chars).
    ("sendgrid_key",     re.compile(r"\bSG\.[A-Za-z0-9_\-]{22,}\.[A-Za-z0-9_\-]{43,}\b")),
    # Linear API key (lin_api_ + 40 chars).
    ("linear_key",       re.compile(r"\blin_api_[A-Za-z0-9]{40,}\b")),
    # NPM access token (npm_ + 36 chars).
    ("npm_token",        re.compile(r"\bnpm_[A-Za-z0-9]{36,}\b")),
    # Mailgun API key (key- + 32 hex).
    ("mailgun_key",      re.compile(r"\bkey-[a-f0-9]{32}\b")),
    # DigitalOcean PAT (dop_v1_ + 64 hex).
    ("digitalocean_pat", re.compile(r"\bdop_v1_[a-f0-9]{64}\b")),
    # Cloudflare API token (40 char base62, contexte difficile sans regex
    # plus permissif — on cible le préfixe documenté à partir de 2022).
    ("cloudflare_token", re.compile(r"\bCFPAT-[A-Za-z0-9_\-]{40,}\b")),
    # Discord bot token (3 segments base64 séparés par . — 24+.6+.27+).
    ("discord_bot",      re.compile(r"\b[MN][A-Za-z0-9]{23,}\.[A-Za-z0-9_\-]{6}\.[A-Za-z0-9_\-]{27,}\b")),
    # Telegram bot token (123:ABC-DEF, 35+ chars total).
    ("telegram_bot",     re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b")),
    # Bearer / Authorization Header complet (toléré strict pour éviter les FP).
    ("bearer_jwt",       re.compile(r"\bBearer\s+eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", re.IGNORECASE)),
]


def shannon_entropy(s: str) -> float:
    """Entropie de Shannon, en bits/caractère."""
    if not s:
        return 0.0
    counts = Counter(s)
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def looks_like_password(s: str) -> bool:
    """Heuristique : chaîne courte (10–60 chars), sans espace, mélange de classes,
    haute entropie."""
    s = s.strip()
    if " " in s or "\n" in s:
        return False
    if not (10 <= len(s) <= 60):
        return False
    has_lower = any(c.islower() for c in s)
    has_upper = any(c.isupper() for c in s)
    has_digit = any(c.isdigit() for c in s)
    has_punct = any(not c.isalnum() for c in s)
    classes = sum([has_lower, has_upper, has_digit, has_punct])
    if classes < 3:
        return False
    return shannon_entropy(s) >= 3.5


def detect(text: str) -> Optional[str]:
    """Renvoie le nom du pattern détecté ou None."""
    if not text:
        return None
    # Patterns explicites
    for name, pat in TOKEN_PATTERNS:
        if pat.search(text):
            return name
    # Heuristique mot de passe (ne prend qu'une ligne)
    s = text.strip()
    if "\n" not in s and looks_like_password(s):
        return "high_entropy_secret"
    return None
