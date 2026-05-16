"""Tests for eyecore._compress: cache_dir, compress_db, decompress_to_cache."""
from __future__ import annotations

import gzip
import sqlite3
import time
from pathlib import Path

import pytest

from eyecore._compress import cache_dir, compress_db, decompress_to_cache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sqlite_db(path: Path) -> Path:
    """Create a minimal SQLite database at *path* and return it."""
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    conn.close()
    return path


# ---------------------------------------------------------------------------
# cache_dir
# ---------------------------------------------------------------------------

class TestCacheDir:
    def test_cache_dir_creates_directory(self, tmp_path, monkeypatch):
        """cache_dir() creates the directory under the appropriate base."""
        # Redirect LOCALAPPDATA / XDG_CACHE_HOME so we don't touch the real cache.
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        result = cache_dir("test_eyecore_xyz")

        assert result.exists(), "cache_dir() must create the directory"
        assert result.is_dir(), "cache_dir() result must be a directory"
        assert result.name == "test_eyecore_xyz"

    def test_cache_dir_idempotent(self, tmp_path, monkeypatch):
        """Calling cache_dir() twice returns the same path without error."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        p1 = cache_dir("test_eyecore_idempotent")
        p2 = cache_dir("test_eyecore_idempotent")
        assert p1 == p2


# ---------------------------------------------------------------------------
# compress_db
# ---------------------------------------------------------------------------

class TestCompressDb:
    def test_compress_db_creates_gz(self, tmp_path):
        """compress_db() creates a .db.gz file."""
        db_path = tmp_path / "sample.db"
        _make_sqlite_db(db_path)

        gz_path = compress_db(db_path)

        assert gz_path.exists(), ".db.gz should exist after compression"
        assert gz_path.suffix == ".gz"
        assert str(gz_path).endswith(".db.gz")

    def test_compress_db_removes_original(self, tmp_path):
        """compress_db() deletes the original .db file."""
        db_path = tmp_path / "sample.db"
        _make_sqlite_db(db_path)

        compress_db(db_path)

        assert not db_path.exists(), "Original .db should be deleted after compression"

    def test_compress_db_valid_gzip(self, tmp_path):
        """The output file is readable as gzip."""
        db_path = tmp_path / "sample.db"
        _make_sqlite_db(db_path)
        gz_path = compress_db(db_path)

        with gzip.open(gz_path, "rb") as f:
            data = f.read()

        # SQLite magic header
        assert data[:6] == b"SQLite", "Decompressed data should start with SQLite magic"

    def test_compress_db_returns_path(self, tmp_path):
        """compress_db() returns the gz Path object."""
        db_path = tmp_path / "sample.db"
        _make_sqlite_db(db_path)
        result = compress_db(db_path)
        assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# decompress_to_cache
# ---------------------------------------------------------------------------

class TestDecompressToCache:
    def test_decompress_to_cache_returns_readable_sqlite(self, tmp_path, monkeypatch):
        """decompress_to_cache() returns a path that can be opened as SQLite."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        db_path = tmp_path / "mydb.db"
        _make_sqlite_db(db_path)
        gz_path = compress_db(db_path)

        result = decompress_to_cache(gz_path, "test_decompress_app")

        assert result.exists(), "Decompressed file must exist"
        conn = sqlite3.connect(str(result))
        row = conn.execute("SELECT x FROM t").fetchone()
        conn.close()
        assert row[0] == 42

    def test_decompress_to_cache_file_in_cache_subdir(self, tmp_path, monkeypatch):
        """Decompressed file lands inside the cache_dir for app_name."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        db_path = tmp_path / "mydb2.db"
        _make_sqlite_db(db_path)
        gz_path = compress_db(db_path)

        result = decompress_to_cache(gz_path, "test_subdir_app")
        expected_parent = cache_dir("test_subdir_app")
        assert result.parent == expected_parent

    def test_decompress_reuses_cache(self, tmp_path, monkeypatch):
        """Calling decompress_to_cache() twice does not re-extract the file."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        db_path = tmp_path / "mydb3.db"
        _make_sqlite_db(db_path)
        gz_path = compress_db(db_path)

        result1 = decompress_to_cache(gz_path, "test_reuse_app")
        mtime1 = result1.stat().st_mtime

        # Small pause to ensure mtime would differ if re-written
        time.sleep(0.05)

        result2 = decompress_to_cache(gz_path, "test_reuse_app")
        mtime2 = result2.stat().st_mtime

        assert result1 == result2, "Both calls must return the same path"
        assert mtime1 == mtime2, "File must not be overwritten on second call"

        # Only one .db file in the cache dir
        cache = cache_dir("test_reuse_app")
        db_files = list(cache.glob("*.db"))
        assert len(db_files) == 1, "Cache dir should contain exactly one .db file"
