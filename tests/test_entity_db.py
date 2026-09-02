"""Tests for eyecore._entity_db — entity type alias tolerance.

A published snapshot is an immutable release asset. When a bake stored a
misspelt entity type, every consumer filtering on the canonical spelling
silently misses those rows until a re-bake replaces the asset. `type_aliases`
lets a package declare the spellings its snapshot actually contains so the
rows stay reachable in the meantime.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from eyecore import EntityDB

ENTITY_SQL = """
CREATE TABLE entities (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL,
    mythology TEXT, domains_text TEXT, search_text TEXT, data TEXT NOT NULL
);
"""

ROWS = [
    ("achilles", "Achilles", "hero", "greek"),
    ("perseus", "Perseus", "hero", "greek"),
    ("seimei", "Abe no Seimei", "heroe", "japanese"),
    ("zeus", "Zeus", "deity", "greek"),
]


@pytest.fixture
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(ENTITY_SQL.strip())
    for eid, name, etype, myth in ROWS:
        conn.execute(
            "INSERT INTO entities"
            "(id, name, type, mythology, domains_text, search_text, data)"
            " VALUES (?,?,?,?,?,?,?)",
            (eid, name, etype, myth, "", name,
             json.dumps({"id": eid, "name": name, "type": etype, "mythology": myth})),
        )
    conn.commit()
    return conn


def _entity_db(db: sqlite3.Connection, aliases=None) -> EntityDB:
    """An EntityDB whose BaseDB is swapped for the in-memory fixture.

    BaseDB connects lazily, so the (absent) gz path is never touched.
    """
    from pathlib import Path
    from unittest.mock import MagicMock

    edb = EntityDB("test", Path("never-opened.db.gz"), type_aliases=aliases)
    base = MagicMock()
    base.conn = db
    base.fetchone.side_effect = lambda sql, params=(): db.execute(sql, params).fetchone()
    base.fetchall.side_effect = lambda sql, params=(): db.execute(sql, params).fetchall()
    edb._base = base
    return edb


def test_type_variants_defaults_to_the_type_itself(db):
    edb = _entity_db(db)
    assert edb.type_variants("hero") == ("hero",)


def test_type_variants_includes_canonical_spelling_once(db):
    edb = _entity_db(db, {"hero": ("hero", "heroe")})
    assert edb.type_variants("hero") == ("hero", "heroe")
    edb = _entity_db(db, {"hero": ("heroe",)})
    assert edb.type_variants("hero") == ("hero", "heroe")


def test_by_type_without_aliases_misses_the_misspelt_rows(db):
    """The defect this feature exists to cover."""
    edb = _entity_db(db)
    assert {r["name"] for r in edb.by_type("hero")} == {"Achilles", "Perseus"}


def test_by_type_count_random_and_all_span_every_spelling(db):
    edb = _entity_db(db, {"hero": ("hero", "heroe")})
    assert {r["name"] for r in edb.by_type("hero")} == {
        "Achilles", "Perseus", "Abe no Seimei"
    }
    assert edb.count("hero") == 3
    assert len(edb.get_all("hero")) == 3
    assert edb.get_random("hero") is not None
    assert edb.by_type("hero", "japanese")[0]["name"] == "Abe no Seimei"
    assert edb.get_all("hero", "japanese")[0]["name"] == "Abe no Seimei"
    assert edb.get_random("hero", "japanese")["name"] == "Abe no Seimei"


def test_unaliased_types_are_unaffected(db):
    edb = _entity_db(db, {"hero": ("hero", "heroe")})
    assert edb.count("deity") == 1
    assert edb.count("creature") == 0
