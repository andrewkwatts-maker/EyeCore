"""Shared fixtures for eyecore tests."""
import sqlite3
import tempfile
from pathlib import Path
import pytest


@pytest.fixture
def tmp_path_custom(tmp_path):
    return tmp_path


@pytest.fixture
def mem_db():
    """In-memory SQLite connection with row_factory set."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()
