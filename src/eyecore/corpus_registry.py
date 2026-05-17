"""
eyecore.corpus_registry — shared corpus registration framework.

Consumer packages register their own corpus lists at import time:

    from eyecore import corpus_registry
    corpus_registry.register("mythology", MYTHOLOGY_CORPUSES)

Any code can then query across all registered corpora:

    from eyecore import corpus_registry
    corpus_registry.get("mythology")
    corpus_registry.get_by_topic("greek", "ritual")
    corpus_registry.get_by_id("gutenberg-iliad")
    corpus_registry.all_corpora()
"""

from __future__ import annotations

_registry: dict[str, list[dict]] = {}


def register(name: str, corpuses: list[dict]) -> None:
    """Register a named corpus list. Merges if name already exists."""
    existing = _registry.get(name, [])
    seen_ids = {c["id"] for c in existing}
    _registry[name] = existing + [c for c in corpuses if c["id"] not in seen_ids]


def get(name: str) -> list[dict]:
    """Return a registered corpus list by name, or [] if not found."""
    return list(_registry.get(name, []))


def registered_names() -> list[str]:
    """Return all registered corpus list names."""
    return list(_registry.keys())


def all_corpora() -> list[dict]:
    """Return every registered corpus entry across all namespaces."""
    seen: set[str] = set()
    result = []
    for corpora in _registry.values():
        for c in corpora:
            if c["id"] not in seen:
                seen.add(c["id"])
                result.append(c)
    return result


def get_by_topic(*topics: str) -> list[dict]:
    """Return all registered corpus entries tagged with ANY of the given topics."""
    topic_set = set(topics)
    return [c for c in all_corpora() if topic_set.intersection(c.get("topics", []))]


def get_by_id(corpus_id: str) -> dict | None:
    """Return a single corpus entry by its stable ID, or None."""
    return next((c for c in all_corpora() if c["id"] == corpus_id), None)


def clear() -> None:
    """Clear all registrations. Intended for tests only."""
    _registry.clear()
