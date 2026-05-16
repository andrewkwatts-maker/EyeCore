"""RSS/Atom feed scraper with site auto-discovery.

Each function takes app_name so sources and data are stored per-consumer namespace.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from time import mktime
from urllib.parse import urljoin, urlparse


def _sources_path(app_name: str) -> Path:
    from eyecore._feed_store import data_dir
    return data_dir(app_name) / "sources.json"


def load_sources(app_name: str) -> list[dict]:
    p = _sources_path(app_name)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def _save_sources(app_name: str, sources: list[dict]) -> None:
    _sources_path(app_name).write_text(json.dumps(sources, indent=2, ensure_ascii=False), encoding="utf-8")


def add_source(app_name: str, url: str, name: str = "", category: str = "general") -> dict:
    """Add a news source for app_name. Accepts RSS feed URL or website URL (auto-detects feed)."""
    try:
        import requests
        from bs4 import BeautifulSoup
        feed_url = _detect_feed(url, requests, BeautifulSoup) or url
    except ImportError:
        feed_url = url

    parsed = urlparse(url)
    source = {
        "url": feed_url,
        "site_url": url,
        "name": name or parsed.netloc,
        "category": category,
    }
    sources = load_sources(app_name)
    if not any(s["url"] == feed_url for s in sources):
        sources.append(source)
        _save_sources(app_name, sources)
    return source


def remove_source(app_name: str, url: str) -> bool:
    sources = load_sources(app_name)
    filtered = [s for s in sources if s["url"] != url and s.get("site_url") != url]
    if len(filtered) < len(sources):
        _save_sources(app_name, filtered)
        return True
    return False


def _detect_feed(url: str, requests_mod, bs4_mod) -> str | None:
    """Auto-discover RSS/Atom feed URL from a website."""
    parsed = urlparse(url)
    common_paths = ["/feed", "/rss", "/feed.xml", "/rss.xml", "/atom.xml",
                    "/feeds/posts/default", "/blog/feed", "/news/feed"]

    try:
        resp = requests_mod.get(url, timeout=10, headers={"User-Agent": "eyecore-feed/0.1 (feed-reader)"})
        if resp.ok:
            soup = bs4_mod(resp.text, "html.parser")
            for link in soup.find_all("link", type=["application/rss+xml", "application/atom+xml"]):
                href = link.get("href", "")
                if href:
                    return urljoin(url, href)
    except Exception:
        pass

    for path in common_paths:
        candidate = f"{parsed.scheme}://{parsed.netloc}{path}"
        try:
            r = requests_mod.get(candidate, timeout=5, headers={"User-Agent": "eyecore-feed/0.1"})
            ct = r.headers.get("content-type", "")
            if r.ok and ("xml" in ct or "rss" in ct or "atom" in ct):
                return candidate
        except Exception:
            continue

    return None


def _article_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _parse_time(entry) -> str:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime.fromtimestamp(mktime(entry.published_parsed), tz=timezone.utc).isoformat()
        except Exception:
            pass
    return entry.get("published", "")


def scrape_source(source: dict) -> list[dict]:
    """Parse a feed source, return list of article dicts ready for DB insert."""
    try:
        import feedparser
    except ImportError:
        raise ImportError("Install feed deps: pip install 'eyecore[feed]'")

    feed = feedparser.parse(
        source["url"],
        agent="eyecore-feed/0.1 (news-reader)",
    )
    articles = []

    for entry in feed.entries:
        url = entry.get("link") or entry.get("id", "")
        if not url:
            continue

        title = entry.get("title", "Untitled").strip()
        summary = (entry.get("summary") or entry.get("description") or "").strip()
        if len(summary) > 3000:
            summary = summary[:3000]

        published = _parse_time(entry)
        tags = json.dumps([t.get("term", "") for t in entry.get("tags", []) if t.get("term")])
        source_name = source.get("name", urlparse(url).netloc)
        category = source.get("category", "general")

        payload = {
            "id": _article_id(url),
            "url": url,
            "title": title,
            "source": source_name,
            "site_url": source.get("site_url", source["url"]),
            "category": category,
            "published": published,
            "summary": summary,
            "tags": json.loads(tags),
        }

        articles.append({
            "id": payload["id"],
            "url": url,
            "title": title,
            "source": source_name,
            "category": category,
            "published": published,
            "summary": summary,
            "content": "",
            "tags": tags,
            "data": json.dumps(payload, ensure_ascii=False),
        })

    return articles


def scrape_all(app_name: str, verbose: bool = False) -> dict[str, int]:
    """Scrape all configured sources for app_name into today's DB. Returns {source: new_count}."""
    from eyecore._feed_store import today_db, insert_articles, compress_old_days

    sources = load_sources(app_name)
    if not sources:
        if verbose:
            print(f"No sources configured for {app_name}.")
        return {}

    db = today_db(app_name)
    results: dict[str, int] = {}

    for source in sources:
        label = source.get("name", source["url"])
        if verbose:
            print(f"  {label}...", end=" ", flush=True)
        try:
            articles = scrape_source(source)
            new = insert_articles(app_name, articles, db)
            results[label] = new
            if verbose:
                print(f"{new} new ({len(articles)} fetched)")
        except Exception as exc:
            results[label] = -1
            if verbose:
                print(f"ERROR: {exc}")

    db.close()
    compressed = compress_old_days(app_name)
    if verbose and compressed:
        print(f"  Compressed: {', '.join(compressed)}")

    return results
