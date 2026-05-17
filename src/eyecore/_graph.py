"""TopicGraph — SQLite-backed topic registry with PK/FK parent/child links."""
from __future__ import annotations

import json
import sqlite3
from collections import deque

GRAPH_SCHEMA = """
CREATE TABLE IF NOT EXISTS topics (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    type        TEXT,
    parent_id   TEXT REFERENCES topics(id),
    description TEXT,
    data        TEXT
);
CREATE INDEX IF NOT EXISTS idx_topics_name   ON topics(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_topics_parent ON topics(parent_id);
CREATE INDEX IF NOT EXISTS idx_topics_type   ON topics(type);

CREATE TABLE IF NOT EXISTS topic_links (
    from_id  TEXT    NOT NULL REFERENCES topics(id),
    to_id    TEXT    NOT NULL REFERENCES topics(id),
    relation TEXT    NOT NULL DEFAULT 'related',
    weight   REAL    DEFAULT 1.0,
    PRIMARY KEY (from_id, to_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_links_from ON topic_links(from_id);
CREATE INDEX IF NOT EXISTS idx_links_to   ON topic_links(to_id);
"""


class TopicGraph:
    """Generalized topic registry graph embedded in any eyecore SQLite database.

    Fully generic — the schema uses plain `topics` and `topic_links` tables with no
    consumer-specific columns, making it reusable across any eyecore-based package.
    """

    def __init__(self, db: sqlite3.Connection) -> None:
        self._db = db
        for stmt in GRAPH_SCHEMA.strip().split(";"):
            s = stmt.strip()
            if s:
                db.execute(s)
        db.commit()

    # ── Read ──────────────────────────────────────────────────────────────────

    def get(self, topic_id: str) -> dict | None:
        row = self._db.execute(
            "SELECT * FROM topics WHERE id = ?", (topic_id,)
        ).fetchone()
        return dict(row) if row else None

    def find(self, name: str) -> dict | None:
        row = self._db.execute(
            "SELECT * FROM topics WHERE lower(name) = lower(?)", (name,)
        ).fetchone()
        if row:
            return dict(row)
        row = self._db.execute(
            "SELECT * FROM topics WHERE lower(name) LIKE lower(?)", (f"%{name}%",)
        ).fetchone()
        return dict(row) if row else None

    def get_related(
        self,
        topic_id: str,
        relation: str | None = None,
        depth: int = 1,
    ) -> list[dict]:
        if relation:
            rows = self._db.execute(
                """SELECT t.* FROM topics t
                   JOIN topic_links l ON t.id = l.to_id
                   WHERE l.from_id = ? AND l.relation = ?
                   ORDER BY l.weight DESC""",
                (topic_id, relation),
            ).fetchall()
        else:
            rows = self._db.execute(
                """SELECT t.* FROM topics t
                   JOIN topic_links l ON t.id = l.to_id
                   WHERE l.from_id = ?
                   ORDER BY l.weight DESC""",
                (topic_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_children(self, parent_id: str) -> list[dict]:
        rows = self._db.execute(
            "SELECT * FROM topics WHERE parent_id = ? ORDER BY name",
            (parent_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_ancestors(self, topic_id: str) -> list[dict]:
        """Walk up parent_id chain. Returns [immediate_parent, ..., root]."""
        ancestors: list[dict] = []
        current = topic_id
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            row = self._db.execute(
                "SELECT * FROM topics WHERE id = ?", (current,)
            ).fetchone()
            if not row:
                break
            d = dict(row)
            ancestors.append(d)
            current = d.get("parent_id") or ""
        return ancestors[1:]  # exclude starting node

    def get_path(self, from_id: str, to_id: str) -> list[str] | None:
        """BFS shortest undirected path between two topics. Returns list of ids or None."""
        if from_id == to_id:
            return [from_id]
        queue: deque[tuple[str, list[str]]] = deque([(from_id, [from_id])])
        visited = {from_id}
        while queue:
            node, path = queue.popleft()
            neighbors = self._db.execute(
                "SELECT to_id AS id FROM topic_links WHERE from_id = ? "
                "UNION "
                "SELECT from_id AS id FROM topic_links WHERE to_id = ?",
                (node, node),
            ).fetchall()
            for row in neighbors:
                nid = row[0]
                if nid not in visited:
                    new_path = path + [nid]
                    if nid == to_id:
                        return new_path
                    visited.add(nid)
                    queue.append((nid, new_path))
        return None

    def search(self, query: str, limit: int = 20) -> list[dict]:
        rows = self._db.execute(
            "SELECT * FROM topics "
            "WHERE lower(name) LIKE lower(?) OR lower(description) LIKE lower(?) "
            "LIMIT ?",
            (f"%{query}%", f"%{query}%", limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def all_roots(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT * FROM topics WHERE parent_id IS NULL ORDER BY name"
        ).fetchall()
        return [dict(r) for r in rows]

    def subtree(self, root_id: str, max_depth: int = 5) -> dict:
        root = self.get(root_id)
        if not root:
            return {}
        root["children"] = []
        if max_depth > 0:
            for child in self.get_children(root_id):
                root["children"].append(self.subtree(child["id"], max_depth - 1))
        return root

    # ── Write ─────────────────────────────────────────────────────────────────

    def upsert_topic(
        self,
        id: str,
        name: str,
        type: str | None = None,
        parent_id: str | None = None,
        description: str | None = None,
        data: dict | None = None,
    ) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO topics(id, name, type, parent_id, description, data) "
            "VALUES (?,?,?,?,?,?)",
            (id, name, type, parent_id, description, json.dumps(data) if data else None),
        )

    def upsert_link(
        self,
        from_id: str,
        to_id: str,
        relation: str = "related",
        weight: float = 1.0,
    ) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO topic_links(from_id, to_id, relation, weight) "
            "VALUES (?,?,?,?)",
            (from_id, to_id, relation, weight),
        )

    def commit(self) -> None:
        self._db.commit()
