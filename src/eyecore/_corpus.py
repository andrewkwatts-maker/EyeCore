"""CorpusManager — on-demand corpus download, indexing, and FTS search.

Corpus text lives in separate per-corpus SQLite databases in the user cache dir,
keeping the main baked DB small. The main DB only stores `corpus_registry` metadata.

Source types:
  'gutenberg' — Project Gutenberg book ID (int as string)
  'url'       — direct download URL (zip/tar archive or plain text)
  'git'       — git clone URL
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import urllib.request
from pathlib import Path

from eyecore._compress import cache_dir

# Embedded in the main app DB — just registry metadata
CORPUS_REGISTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS corpus_registry (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source      TEXT NOT NULL,
    status      TEXT DEFAULT 'available',
    local_path  TEXT,
    topic_ids   TEXT,
    size_mb     REAL,
    description TEXT,
    added_at    TEXT DEFAULT (datetime('now'))
);
"""

# Per-corpus DB schema (one .db file per corpus in cache dir)
CORPUS_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS texts (
    id         TEXT PRIMARY KEY,
    corpus_id  TEXT NOT NULL,
    title      TEXT,
    author     TEXT,
    content    TEXT,
    source_url TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS texts_fts USING fts5(
    id       UNINDEXED,
    title,
    content,
    tokenize='unicode61 remove_diacritics 1'
);
"""


class CorpusManager:
    """Manages a registry of text corpuses that are downloaded and indexed on demand."""

    def __init__(
        self,
        app_name: str,
        main_db: sqlite3.Connection,
        default_registry: list[dict] | None = None,
    ) -> None:
        self._app_name = app_name
        self._main_db = main_db
        self._cache = cache_dir(app_name) / "corpuses"
        self._cache.mkdir(exist_ok=True)
        self._corpus_conns: dict[str, sqlite3.Connection] = {}

        for stmt in CORPUS_REGISTRY_SCHEMA.strip().split(";"):
            s = stmt.strip()
            if s:
                main_db.execute(s)
        main_db.commit()

        if default_registry:
            self._seed(default_registry)

    def _seed(self, registry: list[dict]) -> None:
        for entry in registry:
            existing = self._main_db.execute(
                "SELECT id FROM corpus_registry WHERE id = ?", (entry["id"],)
            ).fetchone()
            if not existing:
                self._main_db.execute(
                    "INSERT INTO corpus_registry"
                    "(id, name, source_type, source, topic_ids, size_mb, description) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (
                        entry["id"],
                        entry["name"],
                        entry["source_type"],
                        entry["source"],
                        json.dumps(entry.get("topics", [])),
                        entry.get("size_mb"),
                        entry.get("description", ""),
                    ),
                )
        self._main_db.commit()

    # ── Registry ──────────────────────────────────────────────────────────────

    def list_available(self) -> list[dict]:
        return [
            dict(r)
            for r in self._main_db.execute(
                "SELECT * FROM corpus_registry ORDER BY name"
            ).fetchall()
        ]

    def list_local(self) -> list[dict]:
        return [
            dict(r)
            for r in self._main_db.execute(
                "SELECT * FROM corpus_registry "
                "WHERE status IN ('downloaded','indexed') ORDER BY name"
            ).fetchall()
        ]

    def add(
        self,
        source: str,
        name: str = "",
        source_type: str = "url",
        topics: list | None = None,
        description: str = "",
    ) -> dict:
        cid = hashlib.md5(source.encode()).hexdigest()[:12]
        if not name:
            name = source.rsplit("/", 1)[-1].split(".")[0]
        self._main_db.execute(
            "INSERT OR REPLACE INTO corpus_registry"
            "(id, name, source_type, source, topic_ids, description) VALUES (?,?,?,?,?,?)",
            (cid, name, source_type, source, json.dumps(topics or []), description),
        )
        self._main_db.commit()
        return {"id": cid, "name": name, "source_type": source_type, "source": source}

    # ── Fetch ─────────────────────────────────────────────────────────────────

    def fetch(self, name_or_id: str) -> Path:
        """Download a corpus if not already local. Returns local path."""
        row = self._main_db.execute(
            "SELECT * FROM corpus_registry "
            "WHERE id = ? OR lower(name) = lower(?)",
            (name_or_id, name_or_id),
        ).fetchone()
        if not row:
            available = [r["name"] for r in self._main_db.execute(
                "SELECT name FROM corpus_registry ORDER BY name"
            ).fetchall()]
            raise ValueError(
                f"Unknown corpus: {name_or_id!r}. "
                f"Available: {available}"
            )
        entry = dict(row)
        dest = self._cache / entry["id"]

        if entry["status"] == "indexed" and dest.exists():
            return dest

        dest.mkdir(parents=True, exist_ok=True)
        print(f"Fetching corpus '{entry['name']}'...")
        if entry["source_type"] == "gutenberg":
            self._fetch_gutenberg(int(entry["source"]), dest)
        elif entry["source_type"] == "git":
            self._fetch_git(entry["source"], dest)
        else:
            self._fetch_url(entry["source"], dest)

        self._main_db.execute(
            "UPDATE corpus_registry SET status='downloaded', local_path=? WHERE id=?",
            (str(dest), entry["id"]),
        )
        self._main_db.commit()
        return dest

    def _fetch_gutenberg(self, book_id: int, dest: Path) -> None:
        fname = dest / f"{book_id}.txt"
        for suffix in [f"-0.txt", f".txt", f"-8.txt"]:
            url = f"https://www.gutenberg.org/files/{book_id}/{book_id}{suffix}"
            try:
                urllib.request.urlretrieve(url, fname)
                return
            except Exception:
                continue
        # Fallback: mirror
        url = f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt"
        try:
            urllib.request.urlretrieve(url, fname)
        except Exception as exc:
            raise RuntimeError(f"Could not download Gutenberg book {book_id}") from exc

    def _fetch_url(self, url: str, dest: Path) -> None:
        fname = dest / "corpus_download"
        urllib.request.urlretrieve(url, fname)
        try:
            shutil.unpack_archive(str(fname), str(dest))
            fname.unlink()
        except Exception:
            fname.rename(dest / "corpus.txt")

    def _fetch_git(self, url: str, dest: Path) -> None:
        if (dest / ".git").exists():
            subprocess.run(["git", "-C", str(dest), "pull", "--ff-only"], check=True)
        else:
            subprocess.run(
                ["git", "clone", "--depth=1", url, str(dest)], check=True
            )

    # ── Index ─────────────────────────────────────────────────────────────────

    def index(self, name_or_id: str) -> int:
        """Build per-corpus FTS index. Returns count of indexed documents."""
        row = self._main_db.execute(
            "SELECT * FROM corpus_registry WHERE id = ? OR lower(name) = lower(?)",
            (name_or_id, name_or_id),
        ).fetchone()
        if not row or not row["local_path"]:
            raise ValueError(f"Corpus '{name_or_id}' not downloaded. Call fetch() first.")
        entry = dict(row)
        corpus_db_path = self._cache / f"{entry['id']}.db"
        cdb = sqlite3.connect(str(corpus_db_path))
        cdb.row_factory = sqlite3.Row
        for stmt in CORPUS_DB_SCHEMA.strip().split(";"):
            s = stmt.strip()
            if s:
                cdb.execute(s)
        cdb.commit()

        count = 0
        local = Path(entry["local_path"])
        for txt_file in local.rglob("*.txt"):
            try:
                text = txt_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            tid = hashlib.md5(str(txt_file).encode()).hexdigest()[:16]
            cdb.execute(
                "INSERT OR REPLACE INTO texts(id, corpus_id, title, content, source_url) "
                "VALUES (?,?,?,?,?)",
                (tid, entry["id"], txt_file.stem, text, str(txt_file)),
            )
            # FTS: cap at 100k chars per doc to stay reasonable
            cdb.execute(
                "INSERT OR REPLACE INTO texts_fts(id, title, content) VALUES (?,?,?)",
                (tid, txt_file.stem, text[:100_000]),
            )
            count += 1
        cdb.commit()
        cdb.close()

        self._main_db.execute(
            "UPDATE corpus_registry SET status='indexed' WHERE id=?", (entry["id"],)
        )
        self._main_db.commit()
        self._corpus_conns.pop(entry["id"], None)  # force reconnect
        return count

    # ── Search ────────────────────────────────────────────────────────────────

    def _corpus_conn(self, corpus_id: str) -> sqlite3.Connection | None:
        if corpus_id not in self._corpus_conns:
            path = self._cache / f"{corpus_id}.db"
            if not path.exists():
                return None
            conn = sqlite3.connect(str(path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._corpus_conns[corpus_id] = conn
        return self._corpus_conns[corpus_id]

    def search(
        self,
        query: str,
        corpus_id: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """FTS search across indexed corpuses. Searches all if corpus_id is None."""
        results: list[dict] = []
        indexed = self._main_db.execute(
            "SELECT id FROM corpus_registry WHERE status='indexed'"
            + (" AND id=?" if corpus_id else ""),
            (corpus_id,) if corpus_id else (),
        ).fetchall()
        for row in indexed:
            cid = row["id"]
            cdb = self._corpus_conn(cid)
            if cdb is None:
                continue
            try:
                rows = cdb.execute(
                    """SELECT t.id, t.corpus_id, t.title, t.source_url,
                          snippet(texts_fts, 2, '[', ']', '...', 20) AS excerpt
                       FROM texts t
                       JOIN texts_fts ON t.id = texts_fts.id
                       WHERE texts_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = cdb.execute(
                    "SELECT id, corpus_id, title, source_url FROM texts "
                    "WHERE lower(content) LIKE lower(?) LIMIT ?",
                    (f"%{query}%", limit),
                ).fetchall()
            results.extend(dict(r) for r in rows)
            if len(results) >= limit:
                break
        return results[:limit]
