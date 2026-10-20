"""Ed25519 — implémentation pure Python (domaine public, d'après la référence
de D. J. Bernstein et al.), portée Python 3 et optimisée avec `pow()` natif.

Conforme RFC 8032 (interopérabilité vérifiée avec la lib `cryptography`).
Aucune dépendance externe → bundling py2app sans risque.

Utilisée pour :
  • l'app (vérification de licence uniquement — `checkvalid`),
  • l'outil de génération de licences côté éditeur (`publickey`, `signature`).
"""
from __future__ import annotations

import hashlib

b = 256
q = 2 ** 255 - 19
l = 2 ** 252 + 27742317777372353535851937790883648493


def _H(m: bytes) -> bytes:
    return hashlib.sha512(m).digest()


def _inv(x: int) -> int:
    return pow(x, q - 2, q)


d = -121665 * _inv(121666) % q
_I = pow(2, (q - 1) // 4, q)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(d * y * y + 1)
    x = pow(xx, (q + 3) // 8, q)
    if (x * x - xx) % q != 0:
        x = (x * _I) % q
    if x % 2 != 0:
        x = q - x
    return x


_By = 4 * _inv(5) % q
_Bx = _xrecover(_By)
B = [_Bx % q, _By % q]


def _edwards(P, Q):
    x1, y1 = P
    x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + d * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - d * x1 * x2 * y1 * y2)
    return [x3 % q, y3 % q]


def _scalarmult(P, e: int):
    # Double-and-add itératif (évite toute limite de récursion en bundle).
    Q = [0, 1]
    bits = bin(e)[2:] if e > 0 else "0"
    for bit_char in bits:
        Q = _edwards(Q, Q)
        if bit_char == "1":
            Q = _edwards(Q, P)
    return Q


def _encodeint(y: int) -> bytes:
    return y.to_bytes(b // 8, "little")


def _encodepoint(P) -> bytes:
    x, y = P
    bits = [(y >> i) & 1 for i in range(b - 1)] + [x & 1]
    return bytes(sum(bits[i * 8 + j] << j for j in range(8)) for i in range(b // 8))


def _bit(h: bytes, i: int) -> int:
    return (h[i // 8] >> (i % 8)) & 1


def publickey(sk: bytes) -> bytes:
    h = _H(sk)
    a = 2 ** (b - 2) + sum(2 ** i * _bit(h, i) for i in range(3, b - 2))
    A = _scalarmult(B, a)
    return _encodepoint(A)


def _Hint(m: bytes) -> int:
    h = _H(m)
    return sum(2 ** i * _bit(h, i) for i in range(2 * b))


def signature(m: bytes, sk: bytes, pk: bytes) -> bytes:
    h = _H(sk)
    a = 2 ** (b - 2) + sum(2 ** i * _bit(h, i) for i in range(3, b - 2))
    r = _Hint(bytes(h[i] for i in range(b // 8, b // 4)) + m)
    R = _scalarmult(B, r)
    S = (r + _Hint(_encodepoint(R) + pk + m) * a) % l
    return _encodepoint(R) + _encodeint(S)


def _isoncurve(P) -> bool:
    x, y = P
    return (-x * x + y * y - 1 - d * x * x * y * y) % q == 0


def _decodeint(s: bytes) -> int:
    return int.from_bytes(s, "little")


def _decodepoint(s: bytes):
    y = int.from_bytes(s, "little") & ((1 << (b - 1)) - 1)
    x = _xrecover(y)
    if x & 1 != _bit(s, b - 1):
        x = q - x
    P = [x, y]
    if not _isoncurve(P):
        raise ValueError("point hors courbe")
    return P


def checkvalid(s: bytes, m: bytes, pk: bytes) -> bool:
    """True si la signature `s` (64 octets) de `m` est valide pour `pk` (32 o)."""
    try:
        if len(s) != b // 4 or len(pk) != b // 8:
            return False
        R = _decodepoint(s[0:b // 8])
        A = _decodepoint(pk)
        S = _decodeint(s[b // 8:b // 4])
        h = _Hint(_encodepoint(R) + pk + m)
        return _scalarmult(B, S) == _edwards(R, _scalarmult(A, h))
    except Exception:
        return False
