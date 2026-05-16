"""Tests for eyecore._db: BaseDB lazy-connecting SQLite wrapper."""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from eyecore._compress import compress_db
from eyecore._db import BaseDB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sqlite_db(path: Path, *, value: int = 99) -> Path:
    """Create a minimal SQLite database at *path* and return it."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE items (val INTEGER)")
    conn.execute("INSERT INTO items VALUES (?)", (value,))
    conn.commit()
    conn.close()
    return path


# ---------------------------------------------------------------------------
# gz_path (baked) mode
# ---------------------------------------------------------------------------

class TestBaseDBGzMode:
    @pytest.fixture
    def gz_db(self, tmp_path, monkeypatch):
        """Return a (gz_path, db_value) tuple with cache redirected to tmp_path."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        db_path = tmp_path / "baked.db"
        _make_sqlite_db(db_path, value=7)
        gz_path = compress_db(db_path)
        return gz_path

    def test_basedb_lazy(self, gz_db):
        """conn is None before first access."""
        db = BaseDB("test_lazy", gz_path=gz_db)
        assert db._conn is None

    def test_basedb_conn_not_none_after_access(self, gz_db):
        """After accessing .conn the internal connection is non-None."""
        db = BaseDB("test_conn_access", gz_path=gz_db)
        conn = db.conn
        assert conn is not None
        db.close()

    def test_basedb_execute(self, gz_db):
        """execute() runs SQL and returns a cursor."""
        db = BaseDB("test_execute", gz_path=gz_db)
        cur = db.execute("SELECT val FROM items")
        rows = cur.fetchall()
        assert len(rows) == 1
        assert rows[0]["val"] == 7
        db.close()

    def test_basedb_fetchone(self, gz_db):
        """fetchone() with and without params returns the expected row."""
        db = BaseDB("test_fetchone", gz_path=gz_db)

        row = db.fetchone("SELECT val FROM items")
        assert row is not None
        assert row["val"] == 7

        row2 = db.fetchone("SELECT val FROM items WHERE val = ?", (7,))
        assert row2 is not None
        assert row2["val"] == 7

        row3 = db.fetchone("SELECT val FROM items WHERE val = ?", (999,))
        assert row3 is None
        db.close()

    def test_basedb_fetchall(self, gz_db):
        """fetchall() returns a list of rows."""
        db = BaseDB("test_fetchall", gz_path=gz_db)
        rows = db.fetchall("SELECT val FROM items")
        assert isinstance(rows, list)
        assert len(rows) == 1
        assert rows[0]["val"] == 7
        db.close()

    def test_basedb_close(self, gz_db):
        """close() sets the internal conn back to None."""
        db = BaseDB("test_close", gz_path=gz_db)
        _ = db.conn          # trigger connection
        assert db._conn is not None
        db.close()
        assert db._conn is None

    def test_basedb_missing_gz(self, tmp_path):
        """FileNotFoundError is raised on conn access when gz file doesn't exist."""
        missing = tmp_path / "nonexistent.db.gz"
        db = BaseDB("test_missing", gz_path=missing)
        with pytest.raises(FileNotFoundError):
            _ = db.conn

    def test_basedb_no_paths_raises(self):
        """ValueError when neither gz_path nor db_path is supplied."""
        with pytest.raises(ValueError):
            BaseDB("test_no_paths")

    def test_basedb_gz_row_factory(self, gz_db):
        """Rows returned via gz mode support column-name access."""
        db = BaseDB("test_row_factory", gz_path=gz_db)
        row = db.fetchone("SELECT val FROM items")
        # sqlite3.Row supports both index and name access
        assert row[0] == 7
        assert row["val"] == 7
        db.close()


# ---------------------------------------------------------------------------
# db_path (live) mode
# ---------------------------------------------------------------------------

class TestBaseDBLiveMode:
    @pytest.fixture
    def live_db_path(self, tmp_path) -> Path:
        """Return path to a pre-populated .db file."""
        db_path = tmp_path / "live.db"
        _make_sqlite_db(db_path, value=55)
        return db_path

    def test_basedb_live_mode_conn(self, live_db_path):
        """db_path mode connects directly; no gz decompression needed."""
        db = BaseDB("test_live", db_path=live_db_path)
        row = db.fetchone("SELECT val FROM items")
        assert row is not None
        assert row["val"] == 55
        db.close()

    def test_basedb_live_mode_lazy(self, live_db_path):
        """conn is None before first access in live mode too."""
        db = BaseDB("test_live_lazy", db_path=live_db_path)
        assert db._conn is None

    def test_basedb_live_mode_close(self, live_db_path):
        """close() works in live mode."""
        db = BaseDB("test_live_close", db_path=live_db_path)
        _ = db.conn
        db.close()
        assert db._conn is None

    def test_basedb_commit(self, tmp_path):
        """commit() persists data written through the BaseDB connection."""
        db_path = tmp_path / "commit_test.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE things (v TEXT)")
        conn.commit()
        conn.close()

        db = BaseDB("test_commit", db_path=db_path)
        db.execute("INSERT INTO things VALUES ('hello')")
        db.commit()
        db.close()

        # Reopen and verify
        conn2 = sqlite3.connect(str(db_path))
        row = conn2.execute("SELECT v FROM things").fetchone()
        conn2.close()
        assert row[0] == "hello"
