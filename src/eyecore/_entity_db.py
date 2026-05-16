"""EntityDB — base class for baked SQLite entity databases.

All consumer packages (azrael, synomosia-entities, etc.) subclass this and pass
their own app_name and gz_path so the pattern is not repeated in each package.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from eyecore._db import BaseDB
from eyecore._graph import TopicGraph
from eyecore._corpus import CorpusManager


class EntityDB:
    """Base class for baked SQLite entity databases.

    Subclass and call super().__init__(app_name, gz_path, default_corpuses)
    from __init__. All shared query methods are provided here.
    """

    def __init__(
        self,
        app_name: str,
        gz_path: Path,
        default_corpuses: list[dict] | None = None,
    ) -> None:
        self._app_name = app_name
        self._base = BaseDB(app_name, gz_path=gz_path)
        self._graph: TopicGraph | None = None
        self._corpus: CorpusManager | None = None
        self._default_corpuses = default_corpuses

    # ── Lazy singletons ───────────────────────────────────────────────────────

    def _get_graph(self) -> TopicGraph:
        if self._graph is None:
            self._graph = TopicGraph(self._base.conn)
        return self._graph

    def _get_corpus(self) -> CorpusManager:
        if self._corpus is None:
            self._corpus = CorpusManager(
                self._app_name,
                self._base.conn,
                default_registry=self._default_corpuses,
            )
        return self._corpus

    # ── Internal row helpers ──────────────────────────────────────────────────

    def _row_data(self, row) -> dict | None:
        return json.loads(row["data"]) if row else None

    def _rows_data(self, rows) -> list[dict]:
        return [json.loads(r["data"]) for r in rows]

    # ── Core query methods ────────────────────────────────────────────────────

    def get(self, name: str) -> dict | None:
        """Find any entity by exact name, then fuzzy name match."""
        row = self._base.fetchone(
            "SELECT data FROM entities WHERE lower(name) = lower(?)", (name,)
        )
        if row:
            return self._row_data(row)
        row = self._base.fetchone(
            "SELECT data FROM entities WHERE lower(name) LIKE lower(?)", (f"%{name}%",)
        )
        return self._row_data(row)

    def _typed(self, query: str, *types: str) -> dict | None:
        ph = ",".join("?" * len(types))
        row = self._base.fetchone(
            f"SELECT data FROM entities WHERE lower(name) = lower(?) AND type IN ({ph})",
            (query, *types),
        )
        if row:
            return self._row_data(row)
        row = self._base.fetchone(
            f"SELECT data FROM entities WHERE lower(name) LIKE lower(?) AND type IN ({ph})",
            (f"%{query}%", *types),
        )
        if row:
            return self._row_data(row)
        row = self._base.fetchone(
            f"SELECT data FROM entities WHERE lower(domains_text) LIKE lower(?) AND type IN ({ph})",
            (f"%{query}%", *types),
        )
        return self._row_data(row)

    def search(self, query: str, limit: int = 20, mythology: str | None = None) -> list[dict]:
        """Full-text search across all entities, ranked by relevance."""
        try:
            if mythology:
                rows = self._base.fetchall(
                    """SELECT e.data FROM entities e
                       INNER JOIN (
                           SELECT id, rank FROM entities_fts WHERE entities_fts MATCH ?
                           ORDER BY rank
                       ) fts ON e.id = fts.id
                       WHERE lower(e.mythology) = lower(?)
                       LIMIT ?""",
                    (query, mythology, limit),
                )
            else:
                rows = self._base.fetchall(
                    """SELECT e.data FROM entities e
                       INNER JOIN (
                           SELECT id, rank FROM entities_fts WHERE entities_fts MATCH ?
                           ORDER BY rank
                       ) fts ON e.id = fts.id
                       LIMIT ?""",
                    (query, limit),
                )
            return self._rows_data(rows)
        except sqlite3.OperationalError:
            if mythology:
                rows = self._base.fetchall(
                    "SELECT data FROM entities "
                    "WHERE lower(search_text) LIKE lower(?) AND lower(mythology) = lower(?) LIMIT ?",
                    (f"%{query}%", mythology, limit),
                )
            else:
                rows = self._base.fetchall(
                    "SELECT data FROM entities WHERE lower(search_text) LIKE lower(?) LIMIT ?",
                    (f"%{query}%", limit),
                )
            return self._rows_data(rows)

    def by_type(self, entity_type: str, mythology: str | None = None, limit: int = 500) -> list[dict]:
        """Return all entities of a given type, optionally filtered by mythology."""
        if mythology:
            rows = self._base.fetchall(
                "SELECT data FROM entities WHERE type = ? AND lower(mythology) = lower(?) LIMIT ?",
                (entity_type, mythology, limit),
            )
        else:
            rows = self._base.fetchall(
                "SELECT data FROM entities WHERE type = ? LIMIT ?",
                (entity_type, limit),
            )
        return self._rows_data(rows)

    def by_mythology(self, mythology: str, limit: int = 500) -> list[dict]:
        """Return all entities from a given mythology."""
        rows = self._base.fetchall(
            "SELECT data FROM entities WHERE lower(mythology) = lower(?) LIMIT ?",
            (mythology, limit),
        )
        return self._rows_data(rows)

    def count(self, entity_type: str | None = None) -> int:
        """Count entities, optionally filtered by type."""
        if entity_type:
            return self._base.fetchone(
                "SELECT COUNT(*) FROM entities WHERE type = ?", (entity_type,)
            )[0]
        return self._base.fetchone("SELECT COUNT(*) FROM entities")[0]

    def get_random(self, entity_type: str | None = None, mythology: str | None = None) -> dict | None:
        """Return a random entity, optionally filtered by type and/or mythology."""
        if entity_type and mythology:
            row = self._base.fetchone(
                "SELECT data FROM entities WHERE type=? AND lower(mythology)=lower(?) ORDER BY RANDOM() LIMIT 1",
                (entity_type, mythology),
            )
        elif entity_type:
            row = self._base.fetchone(
                "SELECT data FROM entities WHERE type=? ORDER BY RANDOM() LIMIT 1",
                (entity_type,),
            )
        elif mythology:
            row = self._base.fetchone(
                "SELECT data FROM entities WHERE lower(mythology)=lower(?) ORDER BY RANDOM() LIMIT 1",
                (mythology,),
            )
        else:
            row = self._base.fetchone(
                "SELECT data FROM entities ORDER BY RANDOM() LIMIT 1"
            )
        return self._row_data(row)

    def get_fuzzy(self, query: str, limit: int = 5) -> list[dict]:
        """Fuzzy name search — prefix FTS matching with LIKE fallback."""
        try:
            rows = self._base.fetchall(
                """SELECT e.data FROM entities e
                   INNER JOIN (
                       SELECT id, rank FROM entities_fts WHERE name MATCH ?
                       ORDER BY rank
                   ) fts ON e.id = fts.id
                   LIMIT ?""",
                (query + "*", limit),
            )
            if rows:
                return self._rows_data(rows)
        except sqlite3.OperationalError:
            pass
        rows = self._base.fetchall(
            "SELECT data FROM entities WHERE lower(name) LIKE lower(?) LIMIT ?",
            (f"%{query}%", limit),
        )
        return self._rows_data(rows)

    def get_most(self, field: str = "mythology", limit: int = 10) -> list[dict]:
        """Top groupings by entity count.

        get_most("mythology") -> [{mythology: "greek", count: 1200}, ...]
        get_most("type")      -> [{type: "deity", count: 2222}, ...]
        """
        if field not in ("mythology", "type"):
            raise ValueError("field must be 'mythology' or 'type'")
        rows = self._base.fetchall(
            f"SELECT {field}, COUNT(*) as count FROM entities "
            f"WHERE {field} IS NOT NULL GROUP BY {field} ORDER BY count DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in rows]

    def get_all(self, entity_type: str | None = None, mythology: str | None = None) -> list[dict]:
        """Return every matching entity with no row limit. Large result sets possible."""
        if entity_type and mythology:
            rows = self._base.fetchall(
                "SELECT data FROM entities WHERE type=? AND lower(mythology)=lower(?)",
                (entity_type, mythology),
            )
        elif entity_type:
            rows = self._base.fetchall(
                "SELECT data FROM entities WHERE type=?", (entity_type,)
            )
        elif mythology:
            rows = self._base.fetchall(
                "SELECT data FROM entities WHERE lower(mythology)=lower(?)", (mythology,)
            )
        else:
            rows = self._base.fetchall("SELECT data FROM entities")
        return self._rows_data(rows)

    # ── Topic graph methods ───────────────────────────────────────────────────

    def get_topics(self, query: str | None = None, limit: int = 50) -> list[dict]:
        """List topics, optionally filtered by name query."""
        graph = self._get_graph()
        if query:
            return graph.search(query, limit=limit)
        roots = graph.all_roots()
        if len(roots) >= limit:
            return roots[:limit]
        try:
            rows = self._base.fetchall(
                "SELECT id, name, type, parent_id, description FROM topics LIMIT ?", (limit,)
            )
            return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            return roots[:limit]

    def get_related(self, name_or_id: str, relation: str | None = None) -> list[dict]:
        """Get topics related to the given topic."""
        graph = self._get_graph()
        topic = graph.find(name_or_id) or graph.get(name_or_id)
        if not topic:
            return []
        return graph.get_related(topic["id"], relation=relation)

    def get_topic_tree(self, root: str) -> dict:
        """Return the full subtree for a topic as a nested dict."""
        graph = self._get_graph()
        topic = graph.find(root) or graph.get(root)
        if not topic:
            return {}
        return graph.subtree(topic["id"])

    # ── Corpus methods ────────────────────────────────────────────────────────

    def search_corpus(self, query: str, corpus: str | None = None, limit: int = 20) -> list[dict]:
        """Search across downloaded text corpuses."""
        return self._get_corpus().search(query, corpus_id=corpus, limit=limit)

    def fetch_corpus(self, name: str) -> str:
        """Download and index a named corpus. Returns local path string."""
        corpus = self._get_corpus()
        path = corpus.fetch(name)
        corpus.index(name)
        return str(path)

    def list_corpuses(self) -> list[dict]:
        """List all available corpuses and their download status."""
        return self._get_corpus().list_available()
