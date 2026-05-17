"""BaseDB — lazy-connecting SQLite wrapper with transparent gz decompression."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from eyecore._compress import decompress_to_cache


class BaseDB:
    """SQLite connection with optional gz decompression on first access.

    Two modes:
    - *Baked* (gz_path provided): decompresses to user cache on first `.conn` access.
    - *Live* (db_path provided): connects directly to the given path.
    """

    def __init__(
        self,
        app_name: str,
        gz_path: Path | None = None,
        db_path: Path | None = None,
    ) -> None:
        if gz_path is None and db_path is None:
            raise ValueError("Provide either gz_path or db_path")
        self._app_name = app_name
        self._gz_path = gz_path
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            if self._gz_path is not None:
                if not self._gz_path.exists():
                    raise FileNotFoundError(
                        f"Database not found: {self._gz_path}\n"
                        "Run: python scripts/bake.py"
                    )
                path = decompress_to_cache(self._gz_path, self._app_name)
            else:
                path = self._db_path  # type: ignore[assignment]
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ── Convenience delegators ────────────────────────────────────────────────

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def commit(self) -> None:
        self.conn.commit()
