"""Tests for eyecore._corpus: CorpusManager."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from eyecore._corpus import CorpusManager


# ---------------------------------------------------------------------------
# Default registry entry used across tests
# ---------------------------------------------------------------------------

DEFAULT_REGISTRY = [
    {
        "id": "test-corpus",
        "name": "Test Corpus",
        "source_type": "url",
        "source": "http://example.com/test.zip",
        "topics": ["test"],
        "description": "A test corpus entry",
    }
]


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def mem_db():
    """Bare in-memory SQLite connection (row_factory set)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


@pytest.fixture
def corpus_mgr(mem_db, tmp_path, monkeypatch):
    """CorpusManager with cache redirected to tmp_path and a test registry entry."""
    # Redirect platform cache dirs so CorpusManager writes into tmp_path
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

    mgr = CorpusManager(
        app_name="test_eyecore_corpus",
        main_db=mem_db,
        default_registry=DEFAULT_REGISTRY,
    )
    return mgr


# ---------------------------------------------------------------------------
# list_available()
# ---------------------------------------------------------------------------

class TestListAvailable:
    def test_list_available_contains_registry_entry(self, corpus_mgr):
        """Default registry entry appears in list_available()."""
        entries = corpus_mgr.list_available()
        ids = [e["id"] for e in entries]
        assert "test-corpus" in ids

    def test_list_available_name(self, corpus_mgr):
        """Registry entry has the correct name."""
        entries = corpus_mgr.list_available()
        names = [e["name"] for e in entries]
        assert "Test Corpus" in names

    def test_list_available_empty_when_no_registry(self, mem_db, tmp_path, monkeypatch):
        """list_available() is empty when no default_registry is provided."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        mgr = CorpusManager("test_empty_corpus", mem_db)
        assert mgr.list_available() == []


# ---------------------------------------------------------------------------
# add()
# ---------------------------------------------------------------------------

class TestAdd:
    def test_add_appears_in_list_available(self, corpus_mgr):
        """add() inserts a new entry and it shows up in list_available()."""
        result = corpus_mgr.add(
            source="http://example.com/extra.zip",
            name="Extra Corpus",
            source_type="url",
        )
        entries = corpus_mgr.list_available()
        ids = [e["id"] for e in entries]
        assert result["id"] in ids

    def test_add_returns_dict_with_expected_keys(self, corpus_mgr):
        """add() return value contains id, name, source_type, source."""
        result = corpus_mgr.add("http://example.com/book.txt", name="My Book")
        assert "id" in result
        assert "name" in result
        assert result["name"] == "My Book"
        assert result["source"] == "http://example.com/book.txt"

    def test_add_auto_name_from_url(self, corpus_mgr):
        """add() derives name from URL when name is not provided."""
        result = corpus_mgr.add("http://example.com/my_awesome_book.zip")
        assert result["name"] == "my_awesome_book"

    def test_add_idempotent_by_source(self, corpus_mgr):
        """Adding the same source twice returns the same id (INSERT OR REPLACE)."""
        r1 = corpus_mgr.add("http://example.com/dupe.txt", name="Dupe")
        r2 = corpus_mgr.add("http://example.com/dupe.txt", name="Dupe Again")
        assert r1["id"] == r2["id"]


# ---------------------------------------------------------------------------
# fetch() — url source_type
# ---------------------------------------------------------------------------

class TestFetchUrl:
    def _make_fake_urlretrieve(self, dest_dir_ref: list):
        """Returns a mock urlretrieve that writes a plain .txt file to dest."""
        def fake_urlretrieve(url, dest):
            dest_path = Path(dest)
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            # Write a plain text file so _fetch_url renames it to corpus.txt
            dest_path.write_text("Hello world test content.", encoding="utf-8")
            dest_dir_ref.append(dest_path.parent)
        return fake_urlretrieve

    def test_fetch_url_status_downloaded(self, corpus_mgr):
        """fetch() with mocked urlretrieve sets status='downloaded'."""
        dest_holder = []
        fake_retrieve = self._make_fake_urlretrieve(dest_holder)

        with patch("urllib.request.urlretrieve", side_effect=fake_retrieve), \
             patch("shutil.unpack_archive", side_effect=Exception("not an archive")):
            corpus_mgr.fetch("test-corpus")

        entries = corpus_mgr.list_available()
        entry = next(e for e in entries if e["id"] == "test-corpus")
        assert entry["status"] == "downloaded"

    def test_fetch_url_local_path_set(self, corpus_mgr):
        """fetch() sets local_path in the registry."""
        dest_holder = []
        fake_retrieve = self._make_fake_urlretrieve(dest_holder)

        with patch("urllib.request.urlretrieve", side_effect=fake_retrieve), \
             patch("shutil.unpack_archive", side_effect=Exception("not an archive")):
            local_path = corpus_mgr.fetch("test-corpus")

        assert local_path is not None
        assert Path(local_path).is_dir()

    def test_fetch_unknown_corpus_raises(self, corpus_mgr):
        """fetch() raises ValueError for unknown corpus name."""
        with pytest.raises(ValueError, match="Unknown corpus"):
            corpus_mgr.fetch("no-such-corpus")

    def test_fetch_by_name_case_insensitive(self, corpus_mgr):
        """fetch() accepts corpus name case-insensitively."""
        dest_holder = []
        fake_retrieve = self._make_fake_urlretrieve(dest_holder)

        with patch("urllib.request.urlretrieve", side_effect=fake_retrieve), \
             patch("shutil.unpack_archive", side_effect=Exception("not an archive")):
            # "test corpus" vs "Test Corpus"
            corpus_mgr.fetch("test corpus")

        entries = corpus_mgr.list_available()
        entry = next(e for e in entries if e["id"] == "test-corpus")
        assert entry["status"] == "downloaded"


# ---------------------------------------------------------------------------
# fetch() — gutenberg source_type
# ---------------------------------------------------------------------------

class TestFetchGutenberg:
    def test_fetch_gutenberg_writes_txt(self, mem_db, tmp_path, monkeypatch):
        """Gutenberg fetch writes a .txt file into the dest directory."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        mgr = CorpusManager(
            "test_gutenberg",
            mem_db,
            default_registry=[
                {
                    "id": "gb-84",
                    "name": "Frankenstein",
                    "source_type": "gutenberg",
                    "source": "84",
                    "topics": [],
                }
            ],
        )

        written_files = []

        def fake_urlretrieve(url, fname):
            p = Path(fname)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("It was a dark and stormy night...", encoding="utf-8")
            written_files.append(p)

        with patch("urllib.request.urlretrieve", side_effect=fake_urlretrieve):
            dest = mgr.fetch("Frankenstein")

        txt_files = list(Path(dest).glob("*.txt"))
        assert len(txt_files) >= 1, "At least one .txt file should exist after Gutenberg fetch"

    def test_fetch_gutenberg_status_downloaded(self, mem_db, tmp_path, monkeypatch):
        """Gutenberg fetch sets status='downloaded' in registry."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        mgr = CorpusManager(
            "test_gutenberg2",
            mem_db,
            default_registry=[
                {
                    "id": "gb-11",
                    "name": "Alice in Wonderland",
                    "source_type": "gutenberg",
                    "source": "11",
                    "topics": [],
                }
            ],
        )

        def fake_urlretrieve(url, fname):
            p = Path(fname)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("Alice was beginning to get very tired...", encoding="utf-8")

        with patch("urllib.request.urlretrieve", side_effect=fake_urlretrieve):
            mgr.fetch("Alice in Wonderland")

        entries = mgr.list_available()
        entry = next(e for e in entries if e["id"] == "gb-11")
        assert entry["status"] == "downloaded"


# ---------------------------------------------------------------------------
# index() and search()
# ---------------------------------------------------------------------------

class TestIndexAndSearch:
    def test_index_and_search(self, mem_db, tmp_path, monkeypatch):
        """index() indexes .txt files; search() returns results from FTS."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        mgr = CorpusManager(
            "test_index_search",
            mem_db,
            default_registry=[
                {
                    "id": "idx-test",
                    "name": "Index Test Corpus",
                    "source_type": "url",
                    "source": "http://example.com/idx.txt",
                    "topics": [],
                }
            ],
        )

        # Simulate a fetched corpus: create the local directory + txt file
        corpus_dir = mgr._cache / "idx-test"
        corpus_dir.mkdir(parents=True, exist_ok=True)
        sample_txt = corpus_dir / "document.txt"
        sample_txt.write_text(
            "The quick brown fox jumps over the lazy dog. "
            "This is a test document for full-text search.",
            encoding="utf-8",
        )

        # Manually mark as downloaded in the registry
        mem_db.execute(
            "UPDATE corpus_registry SET status='downloaded', local_path=? WHERE id='idx-test'",
            (str(corpus_dir),),
        )
        mem_db.commit()

        count = mgr.index("idx-test")
        assert count == 1, "One .txt file should be indexed"

        results = mgr.search("quick brown fox")
        assert len(results) >= 1
        assert any("idx-test" in r.get("corpus_id", "") for r in results)

    def test_index_raises_without_fetch(self, corpus_mgr):
        """index() raises ValueError when corpus has not been fetched."""
        with pytest.raises(ValueError, match="not downloaded"):
            corpus_mgr.index("test-corpus")

    def test_index_returns_zero_for_empty_dir(self, mem_db, tmp_path, monkeypatch):
        """index() returns 0 when the corpus directory has no .txt files."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        mgr = CorpusManager(
            "test_empty_index",
            mem_db,
            default_registry=[
                {
                    "id": "empty-idx",
                    "name": "Empty Corpus",
                    "source_type": "url",
                    "source": "http://example.com/empty.zip",
                    "topics": [],
                }
            ],
        )

        empty_dir = mgr._cache / "empty-idx"
        empty_dir.mkdir(parents=True, exist_ok=True)

        mem_db.execute(
            "UPDATE corpus_registry SET status='downloaded', local_path=? WHERE id='empty-idx'",
            (str(empty_dir),),
        )
        mem_db.commit()

        count = mgr.index("empty-idx")
        assert count == 0


# ---------------------------------------------------------------------------
# list_local()
# ---------------------------------------------------------------------------

class TestListLocal:
    def test_list_local_after_fetch_and_index(self, mem_db, tmp_path, monkeypatch):
        """After fetch+index, corpus appears in list_local()."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        mgr = CorpusManager(
            "test_list_local",
            mem_db,
            default_registry=[
                {
                    "id": "local-test",
                    "name": "Local Test Corpus",
                    "source_type": "url",
                    "source": "http://example.com/local.txt",
                    "topics": [],
                }
            ],
        )

        # Initially not in list_local (status='available')
        assert mgr.list_local() == []

        # Set up a fetched+indexed corpus
        corpus_dir = mgr._cache / "local-test"
        corpus_dir.mkdir(parents=True, exist_ok=True)
        (corpus_dir / "text.txt").write_text("Some local text content.", encoding="utf-8")

        mem_db.execute(
            "UPDATE corpus_registry SET status='downloaded', local_path=? WHERE id='local-test'",
            (str(corpus_dir),),
        )
        mem_db.commit()

        mgr.index("local-test")

        local = mgr.list_local()
        ids = [e["id"] for e in local]
        assert "local-test" in ids

    def test_list_local_empty_initially(self, corpus_mgr):
        """list_local() is empty before any corpus is fetched."""
        assert corpus_mgr.list_local() == []

    def test_list_local_shows_downloaded_status(self, mem_db, tmp_path, monkeypatch):
        """list_local() includes corpora with status='downloaded' (not just 'indexed')."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        mgr = CorpusManager(
            "test_list_local_dl",
            mem_db,
            default_registry=[
                {
                    "id": "dl-only",
                    "name": "Downloaded Only",
                    "source_type": "url",
                    "source": "http://example.com/dl.txt",
                    "topics": [],
                }
            ],
        )

        mem_db.execute(
            "UPDATE corpus_registry SET status='downloaded', local_path='/fake' WHERE id='dl-only'"
        )
        mem_db.commit()

        local = mgr.list_local()
        ids = [e["id"] for e in local]
        assert "dl-only" in ids


# ---------------------------------------------------------------------------
# search() across multiple corpuses
# ---------------------------------------------------------------------------

class TestSearch:
    def test_search_returns_empty_when_nothing_indexed(self, corpus_mgr):
        """search() returns [] when no corpus has been indexed."""
        results = corpus_mgr.search("anything")
        assert results == []

    def test_search_with_corpus_id_filter(self, mem_db, tmp_path, monkeypatch):
        """search() with corpus_id only searches the specified corpus."""
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        mgr = CorpusManager(
            "test_search_filter",
            mem_db,
            default_registry=[
                {
                    "id": "sf-1",
                    "name": "Science Fiction",
                    "source_type": "url",
                    "source": "http://example.com/sf.txt",
                    "topics": [],
                },
                {
                    "id": "sf-2",
                    "name": "Fantasy",
                    "source_type": "url",
                    "source": "http://example.com/fantasy.txt",
                    "topics": [],
                },
            ],
        )

        for cid in ["sf-1", "sf-2"]:
            corpus_dir = mgr._cache / cid
            corpus_dir.mkdir(parents=True, exist_ok=True)
            (corpus_dir / "text.txt").write_text(
                f"Unique content for corpus {cid}: rockets and starships.",
                encoding="utf-8",
            )
            mem_db.execute(
                "UPDATE corpus_registry SET status='downloaded', local_path=? WHERE id=?",
                (str(corpus_dir), cid),
            )
        mem_db.commit()

        mgr.index("sf-1")
        mgr.index("sf-2")

        results = mgr.search("rockets", corpus_id="sf-1")
        assert all(r["corpus_id"] == "sf-1" for r in results)
