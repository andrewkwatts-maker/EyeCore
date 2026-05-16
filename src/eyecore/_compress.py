"""Shared compression / cache utilities — used by all libs in the suite."""
from __future__ import annotations

import gzip
import os
import platform
import shutil
from pathlib import Path


def cache_dir(app_name: str) -> Path:
    """Platform-appropriate user cache directory for *app_name*."""
    system = platform.system()
    if system == "Windows":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif system == "Darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    d = base / app_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def compress_db(db_path: Path, compresslevel: int = 9) -> Path:
    """Compress *db_path* to *.db.gz* and delete the original. Returns gz path."""
    gz = db_path.with_suffix(".db.gz")
    with open(db_path, "rb") as src, gzip.open(gz, "wb", compresslevel=compresslevel) as dst:
        shutil.copyfileobj(src, dst)
    db_path.unlink()
    return gz


def decompress_to_cache(gz_path: Path, app_name: str) -> Path:
    """Decompress *.db.gz* to the user cache dir on first use.

    Cache key = gz file size — stable across pip installs, invalidates on re-bake.
    Returns the path to the uncompressed *.db* file.
    """
    dest = cache_dir(app_name) / f"{app_name}-{gz_path.stat().st_size}.db"
    if not dest.exists():
        with gzip.open(gz_path, "rb") as src, open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
    return dest
