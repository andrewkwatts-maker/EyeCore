"""EntityDB — base class for baked SQLite entity databases.

Consumer packages subclass this and pass their own app_name and gz_path so the
pattern is not repeated in each package.
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
        remote_url: str | None = None,
        remote_sha256: str | None = None,
        type_aliases: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._app_name = app_name
        self._base = BaseDB(
            app_name,
            gz_path=gz_path,
            remote_url=remote_url,
            remote_sha256=remote_sha256,
        )
        self._graph: TopicGraph | None = None
        self._corpus: CorpusManager | None = None
        self._default_corpuses = default_corpuses
        self._type_aliases = type_aliases or {}

    # ── Entity type spellings ─────────────────────────────────────────────────

    def type_variants(self, entity_type: str) -> tuple[str, ...]:
        """Every spelling of *entity_type* that may appear in the snapshot.

        A snapshot baked before a type typo was fixed still stores the typo,
        and the snapshot is a published release asset that cannot be edited in
        place. Declaring the alias here keeps those rows reachable from the
        canonical type until a re-bake replaces the asset.
        """
        variants = self._type_aliases.get(entity_type)
        if not variants:
            return (entity_type,)
        return tuple(dict.fromkeys((entity_type, *variants)))

    def _type_clause(self, entity_type: str) -> tuple[str, tuple[str, ...]]:
        """SQL predicate + bind params matching every spelling of a type."""
        variants = self.type_variants(entity_type)
        return f"type IN ({','.join('?' * len(variants))})", variants

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

    # ── Delta sync ────────────────────────────────────────────────────────────

    def sync_deltas(
        self,
        project_id: str,
        collections: list[str],
        collection_types: dict[str, str] | None = None,
        api_key: str = "",
        type_fixes: dict[str, str] | None = None,
    ) -> int:
        """Pull documents updated in Firestore since the last bake/sync and
        upsert them locally. Returns the number of entities applied.

        The baked snapshot must carry a ``meta.generated_at`` row (written by
        the bake scripts); subsequent syncs advance ``meta.last_sync``.
        """
        from datetime import datetime, timezone

        from eyecore._remote_data import apply_deltas, fetch_deltas, get_meta

        conn = self._base.conn
        since = get_meta(conn, "last_sync") or get_meta(conn, "generated_at")
        if not since:
            raise RuntimeError(
                "This database predates delta support — re-bake with a "
                "scripts/bake.py that writes meta.generated_at."
            )
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        docs = fetch_deltas(project_id, collections, since, api_key)
        return apply_deltas(conn, docs, collection_types or {}, now, type_fixes)

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
        clause, types = self._type_clause(entity_type)
        if mythology:
            rows = self._base.fetchall(
                f"SELECT data FROM entities WHERE {clause} AND lower(mythology) = lower(?) LIMIT ?",
                (*types, mythology, limit),
            )
        else:
            rows = self._base.fetchall(
                f"SELECT data FROM entities WHERE {clause} LIMIT ?",
                (*types, limit),
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
            clause, types = self._type_clause(entity_type)
            return self._base.fetchone(
                f"SELECT COUNT(*) FROM entities WHERE {clause}", types
            )[0]
        return self._base.fetchone("SELECT COUNT(*) FROM entities")[0]

    def get_random(self, entity_type: str | None = None, mythology: str | None = None) -> dict | None:
        """Return a random entity, optionally filtered by type and/or mythology."""
        clause, types = self._type_clause(entity_type) if entity_type else ("", ())
        if entity_type and mythology:
            row = self._base.fetchone(
                f"SELECT data FROM entities WHERE {clause} AND lower(mythology)=lower(?) "
                "ORDER BY RANDOM() LIMIT 1",
                (*types, mythology),
            )
        elif entity_type:
            row = self._base.fetchone(
                f"SELECT data FROM entities WHERE {clause} ORDER BY RANDOM() LIMIT 1",
                types,
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
        clause, types = self._type_clause(entity_type) if entity_type else ("", ())
        if entity_type and mythology:
            rows = self._base.fetchall(
                f"SELECT data FROM entities WHERE {clause} AND lower(mythology)=lower(?)",
                (*types, mythology),
            )
        elif entity_type:
            rows = self._base.fetchall(
                f"SELECT data FROM entities WHERE {clause}", types
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
