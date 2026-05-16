"""Tests for eyecore._graph: TopicGraph — SQLite-backed topic registry."""
from __future__ import annotations

import sqlite3

import pytest

from eyecore._graph import TopicGraph


# ---------------------------------------------------------------------------
# Fixture: fresh in-memory TopicGraph for each test
# ---------------------------------------------------------------------------

@pytest.fixture
def graph():
    """A TopicGraph backed by an in-memory SQLite connection."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    g = TopicGraph(conn)
    yield g
    conn.close()


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------

class TestUpsertGet:
    def test_upsert_get(self, graph):
        """upsert_topic() stores a topic; get() retrieves it by id."""
        graph.upsert_topic("t1", "Alpha", type="concept", description="First topic")
        graph.commit()

        result = graph.get("t1")
        assert result is not None
        assert result["id"] == "t1"
        assert result["name"] == "Alpha"
        assert result["type"] == "concept"
        assert result["description"] == "First topic"

    def test_get_nonexistent_returns_none(self, graph):
        """get() returns None for an unknown id."""
        assert graph.get("does-not-exist") is None

    def test_upsert_replaces_existing(self, graph):
        """upsert_topic() with the same id overwrites the old record."""
        graph.upsert_topic("t1", "Alpha")
        graph.upsert_topic("t1", "Alpha Updated", type="event")
        graph.commit()

        result = graph.get("t1")
        assert result["name"] == "Alpha Updated"
        assert result["type"] == "event"


# ---------------------------------------------------------------------------
# find()
# ---------------------------------------------------------------------------

class TestFind:
    def test_find_exact(self, graph):
        """find() returns a topic by exact (case-insensitive) name."""
        graph.upsert_topic("f1", "Project Gutenberg")
        graph.commit()

        result = graph.find("project gutenberg")
        assert result is not None
        assert result["id"] == "f1"

    def test_find_fuzzy(self, graph):
        """find() falls back to partial matching when no exact match."""
        graph.upsert_topic("f2", "Ancient Civilizations")
        graph.commit()

        result = graph.find("civil")
        assert result is not None
        assert result["id"] == "f2"

    def test_find_missing_returns_none(self, graph):
        """find() returns None when nothing matches."""
        assert graph.find("xyzzy_no_match") is None


# ---------------------------------------------------------------------------
# Parent / child hierarchy
# ---------------------------------------------------------------------------

class TestParentChild:
    def test_parent_child(self, graph):
        """Children link to parent via parent_id; get_children / get_ancestors work."""
        graph.upsert_topic("root", "Root Topic")
        graph.upsert_topic("child1", "Child One", parent_id="root")
        graph.upsert_topic("child2", "Child Two", parent_id="root")
        graph.upsert_topic("grandchild", "Grandchild", parent_id="child1")
        graph.commit()

        children = graph.get_children("root")
        child_ids = {c["id"] for c in children}
        assert child_ids == {"child1", "child2"}

        ancestors = graph.get_ancestors("grandchild")
        ancestor_ids = [a["id"] for a in ancestors]
        # ancestors walks up: child1, root
        assert "child1" in ancestor_ids
        assert "root" in ancestor_ids

    def test_get_children_empty(self, graph):
        """get_children() returns an empty list for a leaf node."""
        graph.upsert_topic("leaf", "Leaf")
        graph.commit()
        assert graph.get_children("leaf") == []

    def test_get_ancestors_root(self, graph):
        """get_ancestors() on a root node returns an empty list."""
        graph.upsert_topic("root2", "Root 2")
        graph.commit()
        assert graph.get_ancestors("root2") == []


# ---------------------------------------------------------------------------
# Links and get_related()
# ---------------------------------------------------------------------------

class TestLinks:
    def test_upsert_link_get_related(self, graph):
        """Linking two topics; get_related() returns the linked topic."""
        graph.upsert_topic("a", "Alpha")
        graph.upsert_topic("b", "Beta")
        graph.upsert_link("a", "b", relation="related")
        graph.commit()

        related = graph.get_related("a")
        assert len(related) == 1
        assert related[0]["id"] == "b"

    def test_upsert_link_with_relation_filter(self, graph):
        """get_related() filters by relation type."""
        graph.upsert_topic("x", "X")
        graph.upsert_topic("y", "Y")
        graph.upsert_topic("z", "Z")
        graph.upsert_link("x", "y", relation="causes")
        graph.upsert_link("x", "z", relation="related")
        graph.commit()

        causes = graph.get_related("x", relation="causes")
        assert len(causes) == 1
        assert causes[0]["id"] == "y"

        related = graph.get_related("x", relation="related")
        assert len(related) == 1
        assert related[0]["id"] == "z"

    def test_get_related_empty(self, graph):
        """get_related() returns an empty list when there are no links."""
        graph.upsert_topic("lonely", "Lonely")
        graph.commit()
        assert graph.get_related("lonely") == []


# ---------------------------------------------------------------------------
# get_path()
# ---------------------------------------------------------------------------

class TestGetPath:
    def test_get_path_same_node(self, graph):
        """get_path(a, a) returns [a]."""
        graph.upsert_topic("s", "Self")
        graph.commit()
        assert graph.get_path("s", "s") == ["s"]

    def test_get_path_direct(self, graph):
        """Two directly linked nodes: get_path returns [a, b]."""
        graph.upsert_topic("a", "A")
        graph.upsert_topic("b", "B")
        graph.upsert_link("a", "b")
        graph.commit()

        path = graph.get_path("a", "b")
        assert path == ["a", "b"]

    def test_get_path_indirect(self, graph):
        """Three nodes a->b->c: get_path(a, c) returns [a, b, c]."""
        graph.upsert_topic("a", "A")
        graph.upsert_topic("b", "B")
        graph.upsert_topic("c", "C")
        graph.upsert_link("a", "b")
        graph.upsert_link("b", "c")
        graph.commit()

        path = graph.get_path("a", "c")
        assert path == ["a", "b", "c"]

    def test_get_path_undirected(self, graph):
        """get_path traverses links in both directions."""
        graph.upsert_topic("a", "A")
        graph.upsert_topic("b", "B")
        # Link is b -> a, but BFS should still find path from a to b
        graph.upsert_link("b", "a")
        graph.commit()

        path = graph.get_path("a", "b")
        assert path is not None
        assert set(path) == {"a", "b"}

    def test_get_path_none(self, graph):
        """Disconnected nodes: get_path returns None."""
        graph.upsert_topic("island1", "Island 1")
        graph.upsert_topic("island2", "Island 2")
        graph.commit()

        assert graph.get_path("island1", "island2") is None


# ---------------------------------------------------------------------------
# subtree()
# ---------------------------------------------------------------------------

class TestSubtree:
    def test_subtree(self, graph):
        """Root with 2 children each with 1 grandchild has correct nesting."""
        graph.upsert_topic("root", "Root")
        graph.upsert_topic("c1", "Child 1", parent_id="root")
        graph.upsert_topic("c2", "Child 2", parent_id="root")
        graph.upsert_topic("gc1", "Grandchild 1", parent_id="c1")
        graph.upsert_topic("gc2", "Grandchild 2", parent_id="c2")
        graph.commit()

        tree = graph.subtree("root")
        assert tree["id"] == "root"
        assert len(tree["children"]) == 2

        child_ids = {c["id"] for c in tree["children"]}
        assert child_ids == {"c1", "c2"}

        for child in tree["children"]:
            assert len(child["children"]) == 1

    def test_subtree_leaf(self, graph):
        """subtree() on a leaf returns a node with an empty children list."""
        graph.upsert_topic("leaf", "Leaf Node")
        graph.commit()

        tree = graph.subtree("leaf")
        assert tree["id"] == "leaf"
        assert tree["children"] == []

    def test_subtree_nonexistent(self, graph):
        """subtree() returns {} for an unknown id."""
        assert graph.subtree("ghost") == {}


# ---------------------------------------------------------------------------
# all_roots()
# ---------------------------------------------------------------------------

class TestAllRoots:
    def test_all_roots(self, graph):
        """Only nodes with parent_id=None are returned."""
        graph.upsert_topic("r1", "Root 1")
        graph.upsert_topic("r2", "Root 2")
        graph.upsert_topic("child", "Child", parent_id="r1")
        graph.commit()

        roots = graph.all_roots()
        root_ids = {r["id"] for r in roots}
        assert root_ids == {"r1", "r2"}
        assert "child" not in root_ids

    def test_all_roots_empty(self, graph):
        """all_roots() returns an empty list when the graph is empty."""
        assert graph.all_roots() == []


# ---------------------------------------------------------------------------
# search()
# ---------------------------------------------------------------------------

class TestSearch:
    def test_search_by_name(self, graph):
        """search() matches by partial name."""
        graph.upsert_topic("q1", "Quantum Mechanics")
        graph.upsert_topic("q2", "Classical Physics")
        graph.commit()

        results = graph.search("quantum")
        assert len(results) == 1
        assert results[0]["id"] == "q1"

    def test_search_by_description(self, graph):
        """search() matches by partial description."""
        graph.upsert_topic(
            "d1", "Biology",
            description="Study of living organisms and their interactions"
        )
        graph.upsert_topic("d2", "Geology", description="Study of rocks and earth")
        graph.commit()

        results = graph.search("organisms")
        assert len(results) == 1
        assert results[0]["id"] == "d1"

    def test_search_no_match(self, graph):
        """search() returns an empty list when nothing matches."""
        graph.upsert_topic("z1", "Zoology")
        graph.commit()
        assert graph.search("xyznomatch") == []

    def test_search_limit(self, graph):
        """search() respects the limit parameter."""
        for i in range(10):
            graph.upsert_topic(f"limit{i}", f"Matching Topic {i}")
        graph.commit()

        results = graph.search("Matching", limit=3)
        assert len(results) <= 3


# ---------------------------------------------------------------------------
# commit() persistence
# ---------------------------------------------------------------------------

class TestCommit:
    def test_commit_persists(self, graph):
        """Data written without commit is present after commit()."""
        graph.upsert_topic("persist1", "Persistent Topic")
        # Data is in-memory but not yet committed; TopicGraph.__init__
        # already called conn.commit(), so subsequent upserts are
        # in an implicit transaction.  After our commit they survive re-query.
        graph.commit()

        # Re-query the same connection
        result = graph.get("persist1")
        assert result is not None
        assert result["name"] == "Persistent Topic"

    def test_upsert_without_commit_visible_in_same_conn(self, graph):
        """Within the same connection, upserted data is readable before commit."""
        graph.upsert_topic("uncommitted", "Not Yet Committed")
        # Still readable via the same SQLite connection (autocommit off, dirty read)
        result = graph.get("uncommitted")
        assert result is not None

    def test_commit_method_on_graph(self, graph):
        """TopicGraph.commit() delegates to the underlying connection."""
        graph.upsert_topic("cm1", "Commit Method Test")
        graph.commit()
        assert graph.get("cm1") is not None
