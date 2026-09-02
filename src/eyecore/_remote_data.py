"""Remote data assets — lazy download of baked DBs + Firestore delta sync.

The suite's data model: a baked, compressed SQLite snapshot (the *last-pushed
state*) is hosted as a GitHub Release asset and downloaded on first use;
Firestore serves only the *diff layer* — documents whose ``updatedAt`` is
newer than the snapshot's ``generated_at``. This mirrors the website's
static+delta mode, so "diff since last push" means the same thing everywhere.

Stdlib-only (urllib) so eyecore keeps zero required dependencies.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import shutil
import sqlite3
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from eyecore._compress import cache_dir

META_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_FIRESTORE = "https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents"


# ── Lazy snapshot download ────────────────────────────────────────────────────

def ensure_db(app_name: str, url: str, dest_path: Path, sha256: str | None = None) -> Path:
    """Return a local ``.db.gz`` path, downloading *url* on first use.

    Tries *dest_path* (normally the package's ``_data/`` dir); if that
    location is not writable (system site-packages), falls back to the user
    cache dir. An existing file at either location short-circuits.

    When *sha256* is given (packages declare their snapshot's digest next to
    its ``remote_url``) the download is hashed as it streams and verified
    before anything is moved into place. A mismatch raises and leaves *no*
    file behind at either location, so a truncated or substituted asset can
    never be cached and then trusted forever by later runs. Without a digest
    the only integrity check is the gzip magic number, which a truncated
    download passes.
    """
    if dest_path.exists():
        return dest_path
    fallback = cache_dir(app_name) / dest_path.name
    if fallback.exists():
        return fallback

    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".db.gz")
    tmp = Path(tmp_name)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"eyecore/{app_name}"})
        # Hash while streaming — snapshots run to tens of MB, so never hold a
        # second full copy in memory just to digest it.
        digest = hashlib.sha256()
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp_fd, "wb") as out:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                digest.update(chunk)
                out.write(chunk)
        if sha256:
            expected = sha256.strip().lower()
            actual = digest.hexdigest()
            if actual != expected:
                raise OSError(
                    f"Checksum mismatch for {url}: expected {expected}, got {actual}"
                )
        # Sanity: must be a gzip file, not an HTML error page.
        with gzip.open(tmp, "rb") as gz:
            gz.read(16)
        for target in (dest_path, fallback):
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(tmp), str(target))
                return target
            except OSError:
                continue
        raise OSError(f"No writable location for {dest_path.name}")
    finally:
        if tmp.exists():
            tmp.unlink()


# ── Meta helpers ──────────────────────────────────────────────────────────────

def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    conn.execute(META_SCHEMA)
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(META_SCHEMA)
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


# ── Firestore value decoding (REST wire format → plain dicts) ─────────────────

def _decode_value(v: dict):
    if "stringValue" in v:
        return v["stringValue"]
    if "integerValue" in v:
        return int(v["integerValue"])
    if "doubleValue" in v:
        return v["doubleValue"]
    if "booleanValue" in v:
        return v["booleanValue"]
    if "timestampValue" in v:
        return v["timestampValue"]
    if "nullValue" in v:
        return None
    if "mapValue" in v:
        return {
            k: _decode_value(x)
            for k, x in (v["mapValue"].get("fields") or {}).items()
        }
    if "arrayValue" in v:
        return [_decode_value(x) for x in (v["arrayValue"].get("values") or [])]
    return None


def doc_to_dict(doc: dict) -> dict:
    """Convert a Firestore REST document to a plain dict with its id."""
    out = {k: _decode_value(v) for k, v in (doc.get("fields") or {}).items()}
    name = doc.get("name", "")
    if name and "id" not in out:
        out["id"] = name.rsplit("/", 1)[-1]
    return out


# ── Delta fetch ───────────────────────────────────────────────────────────────

def fetch_deltas(
    project_id: str,
    collections: list[str],
    since_iso: str,
    api_key: str = "",
) -> list[tuple[str, dict]]:
    """Fetch documents updated after *since_iso* from each collection.

    Uses the same public-read, key-in-querystring REST access as the bake
    scripts and the website's delta query (``updatedAt > since``). Documents
    without an ``updatedAt`` field are invisible to this query — identical
    to the website's behaviour. Returns ``[(collection, entity_dict), ...]``.
    """
    results: list[tuple[str, dict]] = []
    base = _FIRESTORE.format(project=project_id)
    for coll in collections:
        query = {
            "structuredQuery": {
                "from": [{"collectionId": coll}],
                "where": {
                    "fieldFilter": {
                        "field": {"fieldPath": "updatedAt"},
                        "op": "GREATER_THAN",
                        "value": {"timestampValue": since_iso},
                    }
                },
                "limit": 500,
            }
        }
        url = f"{base}:runQuery"
        if api_key:
            url += f"?key={api_key}"
        body = json.dumps(query).encode()
        for attempt in range(5):
            req = urllib.request.Request(
                url, data=body, headers={"Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    rows = json.load(resp)
                for row in rows:
                    doc = row.get("document")
                    if doc:
                        results.append((coll, doc_to_dict(doc)))
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 4:
                    time.sleep(2 ** attempt)
                    continue
                if exc.code in (400, 403, 404):
                    # Missing index / collection / auth — skip, like the website.
                    break
                raise
    return results


# ── Delta apply (shared entities schema) ──────────────────────────────────────

def _str_list(val) -> str:
    if not val:
        return ""
    if isinstance(val, list):
        return " ".join(str(v) for v in val if v)
    return str(val)


def _safe_str(val) -> str:
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        return _str_list(val)
    return ""


def entity_search_text(e: dict) -> str:
    """The bake scripts' search_text mapping — kept identical so delta rows
    rank the same as baked rows."""
    desc = e.get("description") or e.get("shortDescription") or e.get("longDescription") or ""
    alt_names = e.get("alternativeNames") or []
    alt = " ".join(a.get("name", "") for a in alt_names if isinstance(a, dict))
    parts = [
        _safe_str(e.get("name", "")),
        _safe_str(e.get("mythology") or e.get("primaryMythology") or ""),
        _safe_str(desc),
        _str_list(e.get("domains")),
        _str_list(e.get("abilities")),
        _str_list(e.get("titles")),
        _str_list(e.get("attributes")),
        _str_list(e.get("searchTerms")),
        _str_list(e.get("tags")),
        _safe_str(e.get("subtitle", "")),
        alt,
    ]
    return " ".join(p for p in parts if p)


def entity_domains_text(e: dict) -> str:
    parts = [
        _str_list(e.get("domains")),
        _str_list(e.get("abilities")),
        _str_list(e.get("powers")),
        _str_list(e.get("attributes")),
        _str_list(e.get("significance")),
        _str_list(e.get("tags")),
    ]
    return " ".join(p for p in parts if p).lower()


def apply_deltas(
    conn: sqlite3.Connection,
    docs: list[tuple[str, dict]],
    collection_types: dict[str, str],
    now_iso: str,
    type_fixes: dict[str, str] | None = None,
) -> int:
    """Upsert delta documents into the shared ``entities``/``entities_fts``
    schema and record the sync time in ``meta.last_sync``. Returns the number
    of rows applied.

    *type_fixes* maps a misspelt upstream ``type`` onto its canonical form,
    mirroring the bake scripts' ``TYPE_FIXES``. Without it a typo that the
    bake normalises away would be reintroduced, one delta at a time, by every
    Refresh().
    """
    applied = 0
    for coll, e in docs:
        ent_id = str(e.get("id") or "")
        if not ent_id:
            continue
        ent_type = e.get("type") or collection_types.get(coll, coll.rstrip("s"))
        if type_fixes:
            ent_type = type_fixes.get(ent_type, ent_type)
        # Keep the stored JSON agreeing with the indexed column, as the bake
        # scripts do — consumers read the type back out of ``data``.
        e["type"] = ent_type
        name = _safe_str(e.get("name")) or ent_id
        mythology = _safe_str(
            e.get("mythology") or e.get("primaryMythology") or ""
        ).lower()
        search = entity_search_text(e)
        conn.execute(
            "INSERT OR REPLACE INTO entities"
            "(id, name, type, mythology, domains_text, search_text, data) "
            "VALUES (?,?,?,?,?,?,?)",
            (ent_id, name, ent_type, mythology, entity_domains_text(e), search,
             json.dumps(e, ensure_ascii=False)),
        )
        conn.execute("DELETE FROM entities_fts WHERE id = ?", (ent_id,))
        conn.execute(
            "INSERT INTO entities_fts(id, search_text) VALUES (?,?)",
            (ent_id, search),
        )
        applied += 1
    set_meta(conn, "last_sync", now_iso)
    conn.commit()
    return applied
