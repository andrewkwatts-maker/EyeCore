# Changelog

All notable changes to `eyecore` are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/); versioning: SemVer.

## [1.1.0] — 2026-08-30

### Added
- `eyecore._remote_data` — the suite's lazy-load standard:
  - `ensure_db(app_name, url, dest_path, sha256=None)` downloads a baked
    `.db.gz` release asset on first use (package `_data/` dir, falling back
    to the user cache dir when site-packages is read-only).
  - `fetch_deltas(project_id, collections, since_iso, api_key="")` pulls
    Firestore documents with `updatedAt > since` via the public REST API
    (stdlib urllib, 429 backoff) — the same diff semantics as the website's
    static+delta mode.
  - `apply_deltas(conn, docs, collection_types, now_iso)` upserts into the
    shared `entities`/`entities_fts` schema and records `meta.last_sync`.
  - `doc_to_dict`, `entity_search_text`, `entity_domains_text`, `get_meta`,
    `set_meta`, `META_SCHEMA` helpers shared with the bake scripts.
- `BaseDB`/`EntityDB` accept `remote_url`/`remote_sha256`; a missing baked
  snapshot is fetched automatically before the existing decompress-to-cache
  path. `EntityDB.sync_deltas()` gives domain packages a one-call `Refresh()`.

### Changed
- Compiled bytecode is no longer tracked; `__pycache__/` ignored.

## [1.0.0] — 2026-05-17

Initial release: `BaseDB`, `EntityDB`, `TopicGraph`, `CorpusManager`,
`LLMClient`, feed store/scraper/report modules, compression utilities.
