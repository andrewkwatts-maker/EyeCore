"""
eyecore — Shared foundation for the Eyes of Azrael library suite.

Provides:
  BaseDB        — lazy SQLite connection with transparent gz decompression
  TopicGraph    — generalized topic registry with PK/FK parent/child links
  CorpusManager — on-demand corpus download (Gutenberg / URL / git) + FTS indexing
  LLMClient     — lazy-loaded LLM wrapper (ollama / llama-cpp / openai-compatible)
  EntityDB      — base class for baked SQLite entity databases
  cache_dir     — platform-appropriate user cache directory
  compress_db   — compress a .db file to .db.gz
  decompress_to_cache — decompress .db.gz to user cache on first use

Corpus registry (shared reference texts, usable by any module):
  from eyecore.corpus_registry import MYTHOLOGY_CORPUSES, ESOTERIC_CORPUSES
  from eyecore.corpus_registry import ALL_CORPUSES, get_by_topic, get_by_id

Feed infrastructure (requires eyecore[feed]):
  feed_data_dir, today_db, open_day, available_days, compress_old_days, insert_articles
  add_source, remove_source, load_sources, scrape_all
  cluster_by_keyword, cluster_with_llm, generate_topic_report, generate_daily_reports
"""
from __future__ import annotations

from ._compress import cache_dir, compress_db, decompress_to_cache
from ._db import BaseDB
from ._graph import TopicGraph, GRAPH_SCHEMA
from ._corpus import CorpusManager, CORPUS_REGISTRY_SCHEMA
from ._llm import LLMClient
from ._entity_db import EntityDB
from ._feed_store import (
    data_dir as feed_data_dir,
    today_db,
    open_day,
    available_days,
    compress_old_days,
    insert_articles,
)
from ._feed_scraper import add_source, remove_source, load_sources, scrape_all
from ._feed_report import cluster_by_keyword, cluster_with_llm, generate_topic_report, generate_daily_reports

__version__ = "1.0.0a0"

__all__ = [
    "BaseDB",
    "TopicGraph",
    "CorpusManager",
    "LLMClient",
    "EntityDB",
    "cache_dir",
    "compress_db",
    "decompress_to_cache",
    "GRAPH_SCHEMA",
    "CORPUS_REGISTRY_SCHEMA",
    # Feed store
    "feed_data_dir",
    "today_db",
    "open_day",
    "available_days",
    "compress_old_days",
    "insert_articles",
    # Feed scraper
    "add_source",
    "remove_source",
    "load_sources",
    "scrape_all",
    # Feed report
    "cluster_by_keyword",
    "cluster_with_llm",
    "generate_topic_report",
    "generate_daily_reports",
    "__version__",
]
