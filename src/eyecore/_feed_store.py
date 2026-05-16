"""Daily DB storage layer for feed-based scrapers — one SQLite file per day, older days compressed.

Each consumer passes app_name so they get their own isolated data directory.
"""
from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from eyecore._compress import cache_dir
from eyecore._graph import GRAPH_SCHEMA


def data_dir(app_name: str) -> Path:
    """Return the user data directory for app_name (platform-appropriate)."""
    return cache_dir(app_name)


SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id       TEXT PRIMARY KEY,
    url      TEXT UNIQUE NOT NULL,
    title    TEXT NOT NULL,
    source   TEXT,
    category TEXT,
    published TEXT,
    summary  TEXT,
    content  TEXT,
    tags     TEXT,
    data     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_source    ON articles(source);
CREATE INDEX IF NOT EXISTS idx_category  ON articles(category);
CREATE INDEX IF NOT EXISTS idx_published ON articles(published);
CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    id UNINDEXED,
    title,
    summary,
    tags,
    tokenize='unicode61 remove_diacritics 1'
);
"""

_EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS article_topics (
    article_id TEXT NOT NULL REFERENCES articles(id),
    topic_id   TEXT NOT NULL REFERENCES topics(id),
    PRIMARY KEY (article_id, topic_id)
);

CREATE TABLE IF NOT EXISTS topic_reports (
    id           TEXT PRIMARY KEY,
    topic        TEXT NOT NULL,
    date         TEXT NOT NULL,
    summary      TEXT,
    article_count INTEGER DEFAULT 0,
    links        TEXT,
    generated_at TEXT DEFAULT (datetime('now'))
);
"""

# Full schema applied to every daily DB: articles + topic graph tables + report tables
_FULL_SCHEMA = SCHEMA + GRAPH_SCHEMA + _EXTRA_SCHEMA


def _init_conn(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path), check_same_thread=False)
    db.row_factory = sqlite3.Row
    for stmt in _FULL_SCHEMA.strip().split(";"):
        s = stmt.strip()
        if s:
            db.execute(s)
    db.commit()
    return db


def today_db(app_name: str) -> sqlite3.Connection:
    """Open (or create) today's article DB for app_name."""
    return _init_conn(data_dir(app_name) / f"{date.today().isoformat()}.db")


def open_day(app_name: str, target: str | date) -> sqlite3.Connection:
    """Open a specific day's DB for app_name, decompressing from .gz if needed."""
    if isinstance(target, str):
        target = date.fromisoformat(target)
    d = data_dir(app_name)
    db_path = d / f"{target.isoformat()}.db"
    gz_path = db_path.with_suffix(".db.gz")

    if db_path.exists():
        return _init_conn(db_path)

    if gz_path.exists():
        with gzip.open(gz_path, "rb") as src, open(db_path, "wb") as dst:
            shutil.copyfileobj(src, dst)
        return _init_conn(db_path)

    raise FileNotFoundError(f"No {app_name} data for {target}")


def available_days(app_name: str, include_compressed: bool = True) -> list[str]:
    """All available day keys (YYYY-MM-DD) for app_name, most recent first."""
    d = data_dir(app_name)
    days: set[str] = {f.stem for f in d.glob("????-??-??.db")}
    if include_compressed:
        for gz in d.glob("????-??-??.db.gz"):
            days.add(gz.name[: -len(".db.gz")])
    return sorted(days, reverse=True)


def compress_old_days(app_name: str, keep_uncompressed: int = 2) -> list[str]:
    """Gzip daily DBs older than keep_uncompressed days for app_name. Returns compressed filenames."""
    cutoff = date.today() - timedelta(days=keep_uncompressed)
    compressed = []
    for db_file in data_dir(app_name).glob("????-??-??.db"):
        try:
            day = date.fromisoformat(db_file.stem)
        except ValueError:
            continue
        if day < cutoff:
            gz = db_file.with_suffix(".db.gz")
            with open(db_file, "rb") as src, gzip.open(gz, "wb", compresslevel=6) as dst:
                shutil.copyfileobj(src, dst)
            db_file.unlink()
            compressed.append(gz.name)
    return compressed


def insert_articles(app_name: str, articles: list[dict], db: sqlite3.Connection | None = None) -> int:
    """Bulk-insert articles into the given connection (or today's DB if not provided).

    Returns new article count.
    """
    if db is None:
        db = today_db(app_name)
    new = 0
    for a in articles:
        cur = db.execute(
            "INSERT OR IGNORE INTO articles"
            "(id, url, title, source, category, published, summary, content, tags, data) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (a["id"], a["url"], a["title"], a.get("source", ""), a.get("category", ""),
             a.get("published", ""), a.get("summary", ""), a.get("content", ""),
             a.get("tags", "[]"), a["data"]),
        )
        if cur.rowcount:
            db.execute(
                "INSERT OR IGNORE INTO articles_fts(id, title, summary, tags) VALUES (?,?,?,?)",
                (a["id"], a["title"], a.get("summary", ""), a.get("tags", "[]")),
            )
            new += 1
    db.commit()
    return new


def insert_report(
    app_name: str,
    db: sqlite3.Connection,
    topic: str,
    date_str: str,
    summary: str,
    articles: list[dict],
) -> None:
    """Upsert a topic report into the topic_reports table."""
    import hashlib

    report_id = hashlib.sha256(f"{topic}:{date_str}".encode()).hexdigest()[:16]
    links = json.dumps(
        [
            {"title": a.get("title", ""), "url": a.get("url", "")}
            for a in articles[:20]
            if a.get("url")
        ]
    )
    db.execute(
        "INSERT OR REPLACE INTO topic_reports"
        "(id, topic, date, summary, article_count, links) "
        "VALUES (?,?,?,?,?,?)",
        (report_id, topic, date_str, summary, len(articles), links),
    )
    db.commit()
