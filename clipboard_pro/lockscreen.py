"""Module retiré.

L'ancien "lockscreen" (écran de saisie d'une clé d'accès en dur au premier
lancement) a été supprimé pour la distribution publique : il bloquait les
amis qui n'avaient pas le mot de passe et ne constituait pas une vraie
sécurité. Ce stub reste pour ne pas casser un éventuel import résiduel et
pour garantir qu'aucun mot de passe en clair n'est embarqué dans le binaire.

Si une vraie option de verrouillage est souhaitée un jour, l'implémenter ici
proprement (désactivée par défaut, mot de passe choisi par l'utilisateur et
stocké sous forme de hash, jamais en clair).
"""
from __future__ import annotations


def show_lockscreen_blocking() -> bool:
    """No-op : aucun verrouillage. Retourne toujours True (accès autorisé)."""
    return True
