"""Stockage SQLite pour l'historique du presse-papiers — v3.

Changements clés v3 par rapport à v2 :

  • Thread safety : un RLock protège toutes les opérations DB. Avant, OCRWorker
    (thread Python) et le thread Qt pouvaient écrire simultanément sur la
    même connexion ⇒ « database is locked » intermittent.
  • Fix RAM : `list_items()` ne charge plus les `image_blob` (ils peuvent
    peser 5–10 Mo chacun). Pour récupérer le blob d'une image précise,
    utiliser `get_image_blob(item_id)`.
  • Rétention : nouvelle méthode `trim_by_age()` qui supprime par âge,
    séparément texte/image, sans toucher aux favoris ni snippets.
  • Journal des réglages : nouvelle table `settings_log` qui trace chaque
    modification de paramètre (clé, ancienne/nouvelle valeur, note, date).

Migration auto : toutes les colonnes/tables manquantes sont créées en place
sans casser les bases existantes.
"""
from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import time
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

DB_PATH = Path.home() / ".clipboard_pro" / "history.db"
SCHEMA_VERSION = 3

BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    hash         TEXT NOT NULL UNIQUE,
    kind         TEXT NOT NULL,            -- 'text' | 'image'
    content_type TEXT NOT NULL DEFAULT 'plain',
    text         TEXT,
    image_blob   BLOB,
    image_w      INTEGER,
    image_h      INTEGER,
    size_bytes   INTEGER NOT NULL DEFAULT 0,
    is_favorite  INTEGER NOT NULL DEFAULT 0,
    source_app   TEXT,
    created_at   REAL NOT NULL,
    last_used_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_items_created  ON items(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_favorite ON items(is_favorite, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_items_kind     ON items(kind);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    changed_at REAL NOT NULL,
    key        TEXT NOT NULL,
    old_value  TEXT,
    new_value  TEXT,
    note       TEXT,
    source     TEXT NOT NULL DEFAULT 'ui'
);
CREATE INDEX IF NOT EXISTS idx_settings_log_changed ON settings_log(changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_settings_log_key     ON settings_log(key, changed_at DESC);
"""


# Migrations idempotentes (toutes utilisent IF NOT EXISTS).
def _ensure_column(conn: sqlite3.Connection, table: str, col: str, decl: str) -> None:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    if any(r[1] == col for r in rows):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


@dataclass
class Item:
    id: int
    kind: str
    content_type: str
    text: Optional[str]
    image_blob: Optional[bytes]
    image_w: Optional[int]
    image_h: Optional[int]
    size_bytes: int
    is_favorite: bool
    source_app: Optional[str]
    created_at: float
    last_used_at: float
    use_count: int = 0
    is_snippet: bool = False
    snippet_name: Optional[str] = None
    ocr_text: Optional[str] = None
    is_secret: bool = False

    @property
    def display_name(self) -> str:
        if self.is_snippet and self.snippet_name:
            return f";{self.snippet_name}"
        return self.preview

    @property
    def preview(self) -> str:
        if self.kind == "image":
            dims = f"{self.image_w}×{self.image_h}" if self.image_w else "image"
            if self.ocr_text:
                snippet = " ".join(self.ocr_text.split())[:80]
                return f"[{dims}] {snippet}…" if snippet else f"[Image {dims}]"
            return f"[Image {dims}]"
        if not self.text:
            return "[vide]"
        one = " ".join(self.text.split())
        return one[:160] + ("…" if len(one) > 160 else "")

    @property
    def searchable(self) -> str:
        parts = [self.text or "", self.ocr_text or "", self.snippet_name or "", self.source_app or ""]
        return "\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Hashing — normalisé pour éviter les faux doublons.
# ---------------------------------------------------------------------------

def _normalize_text_for_hash(text: str) -> str:
    """Normalise un texte pour éviter que 'hello', 'hello ', 'hello\\n' soient
    3 items distincts. On strip + on unifie les retours à la ligne. Le contenu
    original (non normalisé) reste stocké tel quel dans la colonne `text`.
    """
    if text is None:
        return ""
    s = text.replace("\r\n", "\n").replace("\r", "\n")
    return s.strip()


def _hash_text(text: str) -> str:
    return "t:" + hashlib.sha1(_normalize_text_for_hash(text).encode("utf-8", errors="replace")).hexdigest()


def _hash_blob(blob: bytes) -> str:
    """SHA-1 du blob PNG brut. Note : ce hash inclut les chunks metadata
    (tIME, tEXt) du PNG donc 2 captures identiques prises à des instants
    différents auront un hash différent. Un fix robuste (hash du raster
    décompressé via NSBitmapImageRep) est listé dans AUDIT.md §0.5.
    """
    return "i:" + hashlib.sha1(blob).hexdigest()


# Colonnes "ITEM sans image_blob" — pour les listings où on ne veut PAS
# charger les blobs en RAM. On expose `NULL` comme image_blob pour rester
# compatible avec _row_to_item.
_LIGHT_COLS = (
    "id, hash, kind, content_type, text, NULL as image_blob, "
    "image_w, image_h, size_bytes, is_favorite, source_app, "
    "created_at, last_used_at, use_count, is_snippet, snippet_name, ocr_text, "
    "is_secret"
)


class Database:
    """Connexion SQLite thread-safe (RLock interne) avec migrations idempotentes."""

    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Confidentialité : le dossier et la base ne doivent être lisibles
        # que par l'utilisateur courant. L'historique du presse-papiers peut
        # contenir des données sensibles ; on durcit les permissions à chaque
        # init (idempotent, et corrige aussi les bases créées avant ce fix).
        try:
            os.chmod(self.path.parent, 0o700)
            if self.path.exists():
                os.chmod(self.path, 0o600)
        except OSError:
            # Sur certains FS (montages réseau, etc.) chmod peut échouer ;
            # on ne bloque pas le démarrage pour autant.
            pass
        # Une seule connexion partagée entre threads, protégée par un RLock.
        # `check_same_thread=False` autorise l'usage cross-thread ; le lock
        # garantit qu'on ne fait pas deux INSERT en parallèle.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        # La base vient peut-être d'être créée par connect() : on re-verrouille
        # ses permissions (et celles des fichiers WAL/-shm créés ensuite).
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._lock = threading.RLock()
        with self._lock, self._conn:
            self._conn.executescript(BASE_SCHEMA)
            self._migrate()
            self._conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )

    def _migrate(self) -> None:
        c = self._conn
        _ensure_column(c, "items", "use_count",    "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(c, "items", "is_snippet",   "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(c, "items", "snippet_name", "TEXT")
        _ensure_column(c, "items", "ocr_text",     "TEXT")
        _ensure_column(c, "items", "is_secret",    "INTEGER NOT NULL DEFAULT 0")
        c.execute("CREATE INDEX IF NOT EXISTS idx_items_secret ON items(is_secret)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_items_snippet ON items(is_snippet, snippet_name)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_items_use ON items(use_count DESC, last_used_at DESC)")

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """Lock-then-transaction. Toutes les écritures passent par ici."""
        with self._lock:
            with self._conn:
                yield self._conn

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        """Lock pour les lectures. WAL permet la concurrence côté SQLite mais
        Python sqlite3 lui-même n'est pas garanti thread-safe."""
        with self._lock:
            yield self._conn

    # --- writes -------------------------------------------------------------

    def add_text(
        self,
        text: str,
        content_type: str = "plain",
        source_app: Optional[str] = None,
        is_secret: bool = False,
    ) -> Optional[int]:
        normalized = _normalize_text_for_hash(text)
        if not normalized:
            return None
        # Garder le texte original (sans le \r\n→\n et sans le trim) tant
        # qu'on a déjà strippé en fin pour pas garder des \n inutiles.
        stored = text.rstrip("\n")
        h = _hash_text(text)
        now = time.time()
        with self._tx() as c:
            row = c.execute("SELECT id FROM items WHERE hash=?", (h,)).fetchone()
            if row:
                c.execute(
                    "UPDATE items SET last_used_at=?, source_app=COALESCE(?, source_app) WHERE id=?",
                    (now, source_app, row["id"]),
                )
                return row["id"]
            cur = c.execute(
                """INSERT INTO items
                   (hash, kind, content_type, text, size_bytes, source_app, created_at, last_used_at, is_secret)
                   VALUES (?, 'text', ?, ?, ?, ?, ?, ?, ?)""",
                (h, content_type, stored, len(stored.encode("utf-8")), source_app, now, now,
                 1 if is_secret else 0),
            )
            return cur.lastrowid

    def update_text(self, item_id: int, new_text: str) -> Optional[int]:
        """Met à jour le texte d'un item existant EN PLACE (édition).

        Recalcule le hash et la taille. Conserve les attributs de l'item
        (favori, snippet, source…). Renvoie l'id de l'item portant désormais
        le texte (en principe ``item_id``), ou None si le texte est vide.

        Cas limite : si le nouveau texte a le même hash qu'un AUTRE item
        existant (édition vers un contenu déjà présent), on évite la
        violation de contrainte UNIQUE en renvoyant cet autre item (touché)
        plutôt qu'en dupliquant.
        """
        normalized = _normalize_text_for_hash(new_text)
        if not normalized:
            return None
        stored = new_text.rstrip("\n")
        h = _hash_text(new_text)
        now = time.time()
        with self._tx() as c:
            other = c.execute(
                "SELECT id FROM items WHERE hash=? AND id<>?", (h, item_id)
            ).fetchone()
            if other:
                c.execute(
                    "UPDATE items SET last_used_at=? WHERE id=?", (now, other["id"])
                )
                return other["id"]
            c.execute(
                "UPDATE items SET text=?, hash=?, size_bytes=?, last_used_at=? WHERE id=?",
                (stored, h, len(stored.encode("utf-8")), now, item_id),
            )
            return item_id

    def add_image(
        self,
        blob: bytes,
        width: int,
        height: int,
        source_app: Optional[str] = None,
    ) -> Optional[int]:
        if not blob:
            return None
        h = _hash_blob(blob)
        now = time.time()
        with self._tx() as c:
            row = c.execute("SELECT id FROM items WHERE hash=?", (h,)).fetchone()
            if row:
                c.execute(
                    "UPDATE items SET last_used_at=? WHERE id=?",
                    (now, row["id"]),
                )
                return row["id"]
            cur = c.execute(
                """INSERT INTO items
                   (hash, kind, content_type, image_blob, image_w, image_h,
                    size_bytes, source_app, created_at, last_used_at)
                   VALUES (?, 'image', 'png', ?, ?, ?, ?, ?, ?, ?)""",
                (h, blob, width, height, len(blob), source_app, now, now),
            )
            return cur.lastrowid

    def set_ocr(self, item_id: int, text: str) -> None:
        with self._tx() as c:
            c.execute("UPDATE items SET ocr_text=? WHERE id=?", (text, item_id))

    def toggle_favorite(self, item_id: int) -> bool:
        with self._tx() as c:
            row = c.execute("SELECT is_favorite FROM items WHERE id=?", (item_id,)).fetchone()
            if not row:
                return False
            new_val = 0 if row["is_favorite"] else 1
            c.execute("UPDATE items SET is_favorite=? WHERE id=?", (new_val, item_id))
            return bool(new_val)

    def touch(self, item_id: int) -> None:
        with self._tx() as c:
            c.execute(
                "UPDATE items SET last_used_at=?, use_count=use_count+1 WHERE id=?",
                (time.time(), item_id),
            )

    def delete(self, item_id: int) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM items WHERE id=? AND is_favorite=0 AND is_snippet=0", (item_id,))

    def force_delete(self, item_id: int) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM items WHERE id=?", (item_id,))

    def clear_non_favorites(self) -> int:
        with self._tx() as c:
            cur = c.execute("DELETE FROM items WHERE is_favorite=0 AND is_snippet=0")
            return cur.rowcount

    def trim_to(self, max_items: int = 5000) -> int:
        """Garde les `max_items` plus récents + tous les favoris + tous les snippets."""
        with self._tx() as c:
            cur = c.execute(
                """DELETE FROM items
                   WHERE is_favorite=0 AND is_snippet=0
                     AND id NOT IN (
                        SELECT id FROM items
                        WHERE is_favorite=0 AND is_snippet=0
                        ORDER BY created_at DESC
                        LIMIT ?
                     )""",
                (max_items,),
            )
            return cur.rowcount

    def trim_by_age(
        self,
        *,
        max_text_days: Optional[int] = None,
        max_image_days: Optional[int] = None,
    ) -> dict:
        """Supprime les items texte/image plus vieux que la rétention spécifiée.

        `None` = pas de limite (rétention infinie).
        Favoris et snippets sont toujours préservés.

        Renvoie un dict {'text': n, 'image': n}.
        """
        now = time.time()
        result = {"text": 0, "image": 0}
        with self._tx() as c:
            if max_text_days is not None and max_text_days >= 0:
                cutoff = now - max_text_days * 86400
                cur = c.execute(
                    "DELETE FROM items WHERE is_favorite=0 AND is_snippet=0 "
                    "AND kind='text' AND created_at < ?",
                    (cutoff,),
                )
                result["text"] = cur.rowcount
            if max_image_days is not None and max_image_days >= 0:
                cutoff = now - max_image_days * 86400
                cur = c.execute(
                    "DELETE FROM items WHERE is_favorite=0 AND is_snippet=0 "
                    "AND kind='image' AND created_at < ?",
                    (cutoff,),
                )
                result["image"] = cur.rowcount
        return result

    def preview_trim_by_age(
        self,
        *,
        max_text_days: Optional[int] = None,
        max_image_days: Optional[int] = None,
    ) -> dict:
        """Compte ce que `trim_by_age` supprimerait, sans rien supprimer."""
        now = time.time()
        result = {"text": 0, "image": 0}
        with self._read() as c:
            if max_text_days is not None and max_text_days >= 0:
                cutoff = now - max_text_days * 86400
                row = c.execute(
                    "SELECT COUNT(*) AS n FROM items "
                    "WHERE is_favorite=0 AND is_snippet=0 AND kind='text' "
                    "AND created_at < ?",
                    (cutoff,),
                ).fetchone()
                result["text"] = int(row["n"]) if row else 0
            if max_image_days is not None and max_image_days >= 0:
                cutoff = now - max_image_days * 86400
                row = c.execute(
                    "SELECT COUNT(*) AS n FROM items "
                    "WHERE is_favorite=0 AND is_snippet=0 AND kind='image' "
                    "AND created_at < ?",
                    (cutoff,),
                ).fetchone()
                result["image"] = int(row["n"]) if row else 0
        return result

    # --- snippets -----------------------------------------------------------

    def make_snippet(self, item_id: int, name: str) -> bool:
        name = name.strip().lstrip(";").lower()
        if not name or not name.replace("_", "").replace("-", "").isalnum():
            return False
        with self._tx() as c:
            existing = c.execute(
                "SELECT id FROM items WHERE is_snippet=1 AND snippet_name=? AND id<>?",
                (name, item_id),
            ).fetchone()
            if existing:
                return False
            c.execute(
                "UPDATE items SET is_snippet=1, snippet_name=?, is_favorite=1 WHERE id=?",
                (name, item_id),
            )
            return True

    def unset_snippet(self, item_id: int) -> None:
        with self._tx() as c:
            c.execute("UPDATE items SET is_snippet=0, snippet_name=NULL WHERE id=?", (item_id,))

    def find_snippet(self, name: str) -> Optional[Item]:
        name = name.strip().lstrip(";").lower()
        with self._read() as c:
            row = c.execute(
                "SELECT * FROM items WHERE is_snippet=1 AND snippet_name=? LIMIT 1", (name,)
            ).fetchone()
        return self._row_to_item(row) if row else None

    def list_snippets(self) -> list[Item]:
        with self._read() as c:
            rows = c.execute(
                f"SELECT {_LIGHT_COLS} FROM items WHERE is_snippet=1 ORDER BY snippet_name ASC"
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    # --- reads --------------------------------------------------------------

    def list_items(
        self,
        query: str = "",
        kind: Optional[str] = None,
        favorites_only: bool = False,
        snippets_only: bool = False,
        secrets_only: bool = False,
        since_ts: Optional[float] = None,
        source_app: Optional[str] = None,
        limit: int = 1000,
    ) -> list[Item]:
        """Liste les items pour l'UI — SANS charger les `image_blob`.

        Pour récupérer le blob d'une image précise (par ex. pour l'aperçu),
        appeler `get_image_blob(item_id)`. Ce changement (vs v2) divise par
        ~50 la RAM consommée par un refresh sur une DB pleine d'images.
        """
        sql = f"SELECT {_LIGHT_COLS} FROM items WHERE 1=1"
        params: list = []
        if favorites_only:
            sql += " AND is_favorite=1"
        if snippets_only:
            sql += " AND is_snippet=1"
        if secrets_only:
            sql += " AND is_secret=1"
        if kind:
            sql += " AND kind=?"
            params.append(kind)
        if since_ts is not None:
            sql += " AND created_at>=?"
            params.append(since_ts)
        if source_app:
            sql += " AND source_app=?"
            params.append(source_app)
        if query:
            like = f"%{query}%"
            sql += " AND (text LIKE ? OR ocr_text LIKE ? OR snippet_name LIKE ? OR source_app LIKE ?)"
            params.extend([like, like, like, like])
        # v2.3.6 — Tri chronologique pur (les favoris ne remontent plus
        # en tête de liste). Ils restent accessibles via le filtre Favoris.
        # Les snippets restent prioritaires car ce sont des éléments
        # fonctionnellement différents (raccourcis nommés).
        sql += " ORDER BY is_snippet DESC, created_at DESC LIMIT ?"
        params.append(limit)
        with self._read() as c:
            rows = c.execute(sql, params).fetchall()
        return [self._row_to_item(r) for r in rows]

    def get(self, item_id: int) -> Optional[Item]:
        """Récupère un item COMPLET (avec image_blob s'il y en a un)."""
        with self._read() as c:
            row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        return self._row_to_item(row) if row else None

    def get_image_blob(self, item_id: int) -> Optional[bytes]:
        """Charge UNIQUEMENT le `image_blob` d'un item, à la demande.

        Utilisé par l'UI quand l'utilisateur sélectionne ou copie une image.
        Évite de charger les blobs de tous les items à chaque refresh.
        """
        with self._read() as c:
            row = c.execute("SELECT image_blob FROM items WHERE id=?", (item_id,)).fetchone()
        if not row:
            return None
        blob = row["image_blob"]
        return bytes(blob) if blob is not None else None

    def top_source_apps(self, n: int = 8) -> list[tuple[str, int]]:
        with self._read() as c:
            rows = c.execute(
                """SELECT source_app, COUNT(*) AS c FROM items
                   WHERE source_app IS NOT NULL AND source_app<>''
                   GROUP BY source_app ORDER BY c DESC LIMIT ?""",
                (n,),
            ).fetchall()
        return [(r["source_app"], r["c"]) for r in rows]

    def stats(self) -> dict:
        with self._read() as c:
            row = c.execute(
                """SELECT
                      COUNT(*) AS total,
                      SUM(CASE WHEN kind='text' THEN 1 ELSE 0 END) AS text_count,
                      SUM(CASE WHEN kind='image' THEN 1 ELSE 0 END) AS image_count,
                      SUM(CASE WHEN is_favorite=1 THEN 1 ELSE 0 END) AS favs,
                      SUM(CASE WHEN is_snippet=1 THEN 1 ELSE 0 END) AS snippets,
                      SUM(CASE WHEN is_secret=1 THEN 1 ELSE 0 END) AS secrets,
                      SUM(size_bytes) AS bytes
                   FROM items"""
            ).fetchone()
        return dict(row) if row else {}

    # --- Export / Import (session 5 v2) -------------------------------------

    def export_items(self, *, include_blobs: bool = True) -> list[dict]:
        """Sérialise tous les items pour export JSON.

        ``image_blob`` est encodé en base64 si ``include_blobs=True``,
        sinon le blob est absent (export plus léger, image perdue).
        Le ``hash`` est conservé pour permettre la dédup à l'import.
        """
        import base64
        rows: list[dict] = []
        with self._read() as c:
            cursor = c.execute(
                """SELECT id, hash, kind, content_type, text, image_blob,
                          image_w, image_h, size_bytes, is_favorite,
                          source_app, created_at, last_used_at, use_count,
                          is_snippet, snippet_name, ocr_text
                   FROM items
                   ORDER BY created_at ASC"""
            )
            for r in cursor.fetchall():
                d = dict(r)
                blob = d.pop("image_blob", None)
                if blob is not None and include_blobs:
                    d["image_blob_b64"] = base64.b64encode(bytes(blob)).decode("ascii")
                else:
                    d["image_blob_b64"] = None
                d["is_favorite"] = bool(d.get("is_favorite", 0))
                d["is_snippet"] = bool(d.get("is_snippet", 0))
                rows.append(d)
        return rows

    def import_items(self, items: list[dict]) -> dict:
        """Insère les items depuis un export. Skip ceux dont le hash existe déjà.

        Renvoie ``{added, skipped, errors}``.
        """
        import base64
        added = 0
        skipped = 0
        errors = 0
        with self._tx() as c:
            for d in items:
                try:
                    h = d.get("hash")
                    if not h:
                        errors += 1
                        continue
                    # Skip si déjà en DB (dédup par hash)
                    existing = c.execute(
                        "SELECT id FROM items WHERE hash=?", (h,)
                    ).fetchone()
                    if existing:
                        skipped += 1
                        continue

                    # Reconstitue le blob image
                    blob = None
                    b64 = d.get("image_blob_b64")
                    if b64:
                        try:
                            blob = base64.b64decode(b64)
                        except Exception:
                            blob = None

                    c.execute(
                        """INSERT INTO items
                           (hash, kind, content_type, text, image_blob,
                            image_w, image_h, size_bytes, is_favorite,
                            source_app, created_at, last_used_at,
                            use_count, is_snippet, snippet_name, ocr_text)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            h,
                            d.get("kind", "text"),
                            d.get("content_type", "plain"),
                            d.get("text"),
                            blob,
                            d.get("image_w"),
                            d.get("image_h"),
                            int(d.get("size_bytes", 0) or 0),
                            1 if d.get("is_favorite") else 0,
                            d.get("source_app"),
                            float(d.get("created_at", time.time())),
                            float(d.get("last_used_at",
                                        d.get("created_at", time.time()))),
                            int(d.get("use_count", 0) or 0),
                            1 if d.get("is_snippet") else 0,
                            d.get("snippet_name"),
                            d.get("ocr_text"),
                        ),
                    )
                    added += 1
                except Exception:
                    errors += 1
        return {"added": added, "skipped": skipped, "errors": errors}

    def achievement_stats(self) -> dict:
        """Statistiques pour le système d'achievements (Phase 6).

        Différent de ``stats()`` qui ne donne que les compteurs courants.
        Ici on agrège des chiffres pertinents pour débloquer des badges :
          • ``current_total`` : items actuellement en base
          • ``lifetime_total`` : approximation des items capturés depuis
            le début (= max(id) — même si certains ont été trimés)
          • ``snippets_count`` / ``favs_count`` : compteurs de raccourcis
          • ``distinct_source_apps`` : nombre d'apps différentes vues
          • ``most_used_count`` : use_count max d'un item
          • ``texts_count`` / ``images_count`` : compteurs par type
        """
        with self._read() as c:
            row = c.execute(
                """SELECT
                      COUNT(*)                                AS current_total,
                      COALESCE(MAX(id), 0)                    AS lifetime_total,
                      SUM(CASE WHEN is_snippet=1 THEN 1 ELSE 0 END) AS snippets_count,
                      SUM(CASE WHEN is_favorite=1 THEN 1 ELSE 0 END) AS favs_count,
                      SUM(CASE WHEN kind='text'  THEN 1 ELSE 0 END) AS texts_count,
                      SUM(CASE WHEN kind='image' THEN 1 ELSE 0 END) AS images_count,
                      COALESCE(MAX(use_count), 0)              AS most_used_count
                   FROM items"""
            ).fetchone()
            apps_row = c.execute(
                "SELECT COUNT(DISTINCT source_app) AS n FROM items "
                "WHERE source_app IS NOT NULL AND source_app <> ''"
            ).fetchone()

        return {
            "current_total":        int(row["current_total"] or 0) if row else 0,
            "lifetime_total":       int(row["lifetime_total"] or 0) if row else 0,
            "snippets_count":       int(row["snippets_count"] or 0) if row else 0,
            "favs_count":           int(row["favs_count"] or 0) if row else 0,
            "texts_count":          int(row["texts_count"] or 0) if row else 0,
            "images_count":         int(row["images_count"] or 0) if row else 0,
            "most_used_count":      int(row["most_used_count"] or 0) if row else 0,
            "distinct_source_apps": int(apps_row["n"] or 0) if apps_row else 0,
        }

    def ocr_stats(self) -> dict:
        """Stats du pipeline OCR — total images, avec OCR, en attente."""
        with self._read() as c:
            row = c.execute(
                """SELECT
                      SUM(CASE WHEN kind='image' THEN 1 ELSE 0 END) AS total_images,
                      SUM(CASE WHEN kind='image'
                               AND ocr_text IS NOT NULL
                               AND ocr_text <> '' THEN 1 ELSE 0 END) AS with_ocr,
                      SUM(CASE WHEN kind='image'
                               AND (ocr_text IS NULL OR ocr_text = '')
                               THEN 1 ELSE 0 END) AS pending_ocr
                   FROM items"""
            ).fetchone()
        if not row:
            return {"total_images": 0, "with_ocr": 0, "pending_ocr": 0}
        return {
            "total_images": int(row["total_images"] or 0),
            "with_ocr":     int(row["with_ocr"] or 0),
            "pending_ocr":  int(row["pending_ocr"] or 0),
        }

    def list_pending_ocr(self, limit: int = 20) -> list[Item]:
        """Items image sans OCR — utilisé par OCRWorker. Charge bien le blob
        car l'OCR en a besoin."""
        with self._read() as c:
            rows = c.execute(
                "SELECT * FROM items WHERE kind='image' AND (ocr_text IS NULL OR ocr_text='') "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [self._row_to_item(r) for r in rows]

    # --- settings log -------------------------------------------------------

    def log_setting_change(
        self,
        key: str,
        old_value: Optional[str],
        new_value: Optional[str],
        note: Optional[str] = None,
        source: str = "ui",
    ) -> int:
        """Enregistre un changement de paramètre dans `settings_log`.

        Renvoie l'ID de la ligne insérée. Appelé automatiquement par
        `settings.Settings.set(...)`.
        """
        with self._tx() as c:
            cur = c.execute(
                """INSERT INTO settings_log (changed_at, key, old_value, new_value, note, source)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (time.time(), key, old_value, new_value, note, source),
            )
            return cur.lastrowid or 0

    def list_settings_log(self, key: Optional[str] = None, limit: int = 100) -> list[dict]:
        """Renvoie les derniers changements de réglages, plus récents en premier."""
        with self._read() as c:
            if key:
                rows = c.execute(
                    "SELECT * FROM settings_log WHERE key=? ORDER BY changed_at DESC LIMIT ?",
                    (key, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM settings_log ORDER BY changed_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def last_setting_change(self, key: str) -> Optional[dict]:
        """Renvoie le dernier changement enregistré pour cette clé (ou None)."""
        with self._read() as c:
            row = c.execute(
                "SELECT * FROM settings_log WHERE key=? ORDER BY changed_at DESC LIMIT 1",
                (key,),
            ).fetchone()
        return dict(row) if row else None

    # --- helpers internes ---------------------------------------------------

    @staticmethod
    def _row_to_item(row: sqlite3.Row) -> Item:
        keys = row.keys()
        def g(k, default=None):
            return row[k] if k in keys else default
        blob = g("image_blob")
        return Item(
            id=row["id"],
            kind=row["kind"],
            content_type=row["content_type"],
            text=row["text"],
            image_blob=bytes(blob) if blob is not None else None,
            image_w=row["image_w"],
            image_h=row["image_h"],
            size_bytes=row["size_bytes"],
            is_favorite=bool(row["is_favorite"]),
            source_app=row["source_app"],
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            use_count=int(g("use_count", 0) or 0),
            is_snippet=bool(g("is_snippet", 0)),
            snippet_name=g("snippet_name"),
            ocr_text=g("ocr_text"),
            is_secret=bool(g("is_secret", 0)),
        )
