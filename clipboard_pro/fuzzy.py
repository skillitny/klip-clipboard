"""Recherche floue + scoring d'usage.

Le matching « fuzzy » accepte les sous-séquences (`btn` → `button`) et
booste les correspondances contiguës et préfixées.
"""
from __future__ import annotations

import math
import time
from typing import Iterable

from .db import Item


def _subsequence_score(query: str, target: str) -> float:
    """Renvoie un score [0, 1] selon la qualité du match sous-séquence,
    ou -1 si pas de match du tout."""
    if not query:
        return 0.0
    q = query.lower()
    t = target.lower()
    if q in t:
        # Bonus si le match est en début de chaîne
        idx = t.index(q)
        return 1.0 + (0.3 if idx == 0 else 0.0) - 0.001 * idx

    # Sous-séquence
    qi = 0
    last_pos = -1
    contiguous_bonus = 0.0
    for i, c in enumerate(t):
        if qi < len(q) and c == q[qi]:
            if last_pos == i - 1:
                contiguous_bonus += 0.05
            last_pos = i
            qi += 1
    if qi < len(q):
        return -1.0
    # Plus la chaîne est courte, meilleur le score
    return 0.5 + contiguous_bonus - 0.001 * len(t)


def score_item(item: Item, query: str, *, now: float | None = None) -> float:
    """Score combinant pertinence textuelle, fréquence d'usage et fraîcheur."""
    now = now if now is not None else time.time()

    relevance = _subsequence_score(query, item.searchable) if query else 0.0
    if query and relevance < 0:
        return -1.0

    # Fréquence : log compresse pour éviter qu'un truc copié 200 fois écrase tout.
    freq = math.log1p(max(0, item.use_count))
    # Fraîcheur : décroissance exponentielle sur 7 jours.
    age_days = max(0.0, (now - item.last_used_at) / 86400.0)
    recency = math.exp(-age_days / 7.0)
    fav = 0.6 if item.is_favorite else 0.0
    snippet = 1.0 if item.is_snippet else 0.0

    return relevance + 0.3 * freq + 0.5 * recency + fav + snippet


def fuzzy_filter(items: Iterable[Item], query: str) -> list[Item]:
    """Filtre + trie une collection d'items selon le score."""
    now = time.time()
    scored: list[tuple[float, Item]] = []
    for it in items:
        s = score_item(it, query, now=now)
        if s < 0:
            continue
        scored.append((s, it))
    # tri stable par score décroissant
    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in scored]


# --- helpers pour les filtres temporels -------------------------------------

def since_today() -> float:
    t = time.localtime()
    midnight = time.mktime(time.struct_time((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1)))
    return midnight


def since_week() -> float:
    return time.time() - 7 * 86400
