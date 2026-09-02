"""Tests for eyecore._remote_data — lazy snapshot download + delta sync."""
from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from eyecore import GRAPH_SCHEMA
from eyecore._compress import cache_dir
from eyecore._remote_data import (
    META_SCHEMA,
    apply_deltas,
    doc_to_dict,
    ensure_db,
    entity_search_text,
    fetch_deltas,
    get_meta,
    set_meta,
)

ENTITY_SQL = """
CREATE TABLE entities (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL,
    mythology TEXT, domains_text TEXT, search_text TEXT, data TEXT
);
CREATE VIRTUAL TABLE entities_fts USING fts5(
    id UNINDEXED, search_text, tokenize='unicode61 remove_diacritics 1'
);
"""


def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    for stmt in (GRAPH_SCHEMA + ENTITY_SQL + META_SCHEMA).split(";"):
        if stmt.strip():
            conn.execute(stmt)
    return conn


# ── meta ──────────────────────────────────────────────────────────────────────

def test_meta_roundtrip():
    conn = _make_conn()
    assert get_meta(conn, "generated_at") is None
    set_meta(conn, "generated_at", "2026-08-30T00:00:00Z")
    assert get_meta(conn, "generated_at") == "2026-08-30T00:00:00Z"
    set_meta(conn, "generated_at", "2026-08-31T00:00:00Z")
    assert get_meta(conn, "generated_at") == "2026-08-31T00:00:00Z"


# ── firestore decoding ────────────────────────────────────────────────────────

def test_doc_to_dict_decodes_wire_values():
    doc = {
        "name": "projects/p/databases/(default)/documents/deities/zeus",
        "fields": {
            "name": {"stringValue": "Zeus"},
            "rank": {"integerValue": "1"},
            "active": {"booleanValue": True},
            "tags": {"arrayValue": {"values": [{"stringValue": "sky"}]}},
            "attrs": {"mapValue": {"fields": {"realm": {"stringValue": "Olympus"}}}},
            "missing": {"nullValue": None},
        },
    }
    out = doc_to_dict(doc)
    assert out["id"] == "zeus"
    assert out["name"] == "Zeus"
    assert out["rank"] == 1
    assert out["active"] is True
    assert out["tags"] == ["sky"]
    assert out["attrs"] == {"realm": "Olympus"}
    assert out["missing"] is None


# ── apply_deltas ──────────────────────────────────────────────────────────────

def test_apply_deltas_upserts_and_stamps_sync():
    conn = _make_conn()
    docs = [
        ("deities", {"id": "zeus", "name": "Zeus", "mythology": "Greek",
                     "description": "Sky father", "domains": ["sky", "thunder"]}),
        ("creatures", {"id": "hydra", "name": "Hydra", "mythology": "Greek"}),
    ]
    n = apply_deltas(conn, docs, {"deities": "god"}, "2026-08-30T12:00:00Z")
    assert n == 2
    row = conn.execute("SELECT * FROM entities WHERE id='zeus'").fetchone()
    assert row is not None
    assert row[1] == "Zeus" and row[2] == "god" and row[3] == "greek"
    assert get_meta(conn, "last_sync") == "2026-08-30T12:00:00Z"

    # Update wins over the old row, FTS follows.
    docs2 = [("deities", {"id": "zeus", "name": "Zeus Olympios",
                          "mythology": "Greek", "description": "Renamed"})]
    apply_deltas(conn, docs2, {"deities": "god"}, "2026-08-30T13:00:00Z")
    assert conn.execute("SELECT COUNT(*) FROM entities WHERE id='zeus'").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM entities_fts WHERE id='zeus'"
    ).fetchone()[0] == 1
    hit = conn.execute(
        "SELECT id FROM entities_fts WHERE entities_fts MATCH 'Olympios'"
    ).fetchone()
    assert hit[0] == "zeus"


def test_apply_deltas_normalises_typed_typos():
    """A misspelt upstream type is folded onto its canonical form, in both the
    indexed column and the stored JSON, so Refresh() cannot reintroduce a typo
    the bake scripts normalise away."""
    conn = _make_conn()
    docs = [("heroes", {"id": "achilles", "name": "Achilles", "type": "heroe"})]
    apply_deltas(conn, docs, {"heroes": "hero"}, "2026-09-03T00:00:00Z",
                 {"heroe": "hero"})
    row = conn.execute("SELECT type, data FROM entities WHERE id='achilles'").fetchone()
    assert row[0] == "hero"
    assert json.loads(row[1])["type"] == "hero"

    # Without the fix map the upstream spelling is stored verbatim.
    apply_deltas(conn, [("heroes", {"id": "hector", "name": "Hector", "type": "heroe"})],
                 {"heroes": "hero"}, "2026-09-03T00:00:00Z")
    assert conn.execute(
        "SELECT type FROM entities WHERE id='hector'"
    ).fetchone()[0] == "heroe"


def test_search_text_matches_bake_mapping():
    e = {"name": "Zeus", "mythology": "Greek", "description": "Sky father",
         "domains": ["sky"], "titles": ["King of the Gods"]}
    text = entity_search_text(e)
    for token in ("Zeus", "Greek", "Sky father", "sky", "King of the Gods"):
        assert token in text


# ── ensure_db ─────────────────────────────────────────────────────────────────

def test_ensure_db_short_circuits_existing(tmp_path: Path):
    dest = tmp_path / "x.db.gz"
    dest.write_bytes(gzip.compress(b"hello"))
    assert ensure_db("test-app", "http://invalid.invalid/x.db.gz", dest) == dest


def test_ensure_db_downloads_and_verifies(tmp_path: Path, monkeypatch):
    payload = gzip.compress(b"database bytes")
    served = {"count": 0}

    class FakeResponse:
        def __init__(self):
            self._data = payload
        def read(self, n=-1):
            d, self._data = self._data, b""
            return d
        def __enter__(self):
            served["count"] += 1
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda req, timeout=0: FakeResponse()
    )
    dest = tmp_path / "sub" / "y.db.gz"
    good = hashlib.sha256(payload).hexdigest()
    out = ensure_db("test-app", "http://example/y.db.gz", dest, sha256=good)
    assert out.exists() and out.read_bytes() == payload
    assert served["count"] == 1

    bad_dest = tmp_path / "z.db.gz"
    with pytest.raises(OSError, match="Checksum mismatch"):
        ensure_db("test-app", "http://example/z.db.gz", bad_dest, sha256="0" * 64)
    assert not bad_dest.exists()


def test_ensure_db_mismatch_caches_nothing_anywhere(tmp_path: Path, monkeypatch):
    """A bad download must not survive at the destination *or* in the user
    cache fallback — a cached corrupt snapshot would short-circuit every later
    call and never be re-verified."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    payload = gzip.compress(b"truncated snapshot")

    class FakeResponse:
        def __init__(self):
            self._data = payload
        def read(self, n=-1):
            d, self._data = self._data, b""
            return d
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=0: FakeResponse())
    dest = tmp_path / "pkg" / "_data" / "w.db.gz"
    wrong = hashlib.sha256(b"a different snapshot entirely").hexdigest()
    with pytest.raises(OSError, match="Checksum mismatch"):
        ensure_db("mismatch-app", "http://example/w.db.gz", dest, sha256=wrong)
    assert not dest.exists()
    assert not (cache_dir("mismatch-app") / "w.db.gz").exists()


def test_ensure_db_accepts_uppercase_digest(tmp_path: Path, monkeypatch):
    """Digests are compared case-insensitively — hex case is not meaningful."""
    payload = gzip.compress(b"database bytes")

    class FakeResponse:
        def __init__(self):
            self._data = payload
        def read(self, n=-1):
            d, self._data = self._data, b""
            return d
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=0: FakeResponse())
    dest = tmp_path / "upper.db.gz"
    out = ensure_db("test-app", "http://example/upper.db.gz", dest,
                    sha256=hashlib.sha256(payload).hexdigest().upper())
    assert out.read_bytes() == payload


# ── fetch_deltas (offline behaviour) ──────────────────────────────────────────

def test_fetch_deltas_skips_missing_collections(monkeypatch):
    import io
    import urllib.error

    def fake_urlopen(req, timeout=0):
        raise urllib.error.HTTPError(
            req.full_url, 404, "not found", None, io.BytesIO(b"{}")
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    out = fetch_deltas("proj", ["nope"], "2026-01-01T00:00:00Z")
    assert out == []
