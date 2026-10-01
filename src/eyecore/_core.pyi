"""Type stubs for the `eyecore._core` Rust extension.

`sha256_hex` previously claimed to return a SHA-256 digest here while the Rust
computed a 16-character djb2 rolling hash. It now really is SHA-256, so this
stub is true rather than aspirational.
"""

def sha256_hex(data: bytes) -> str:
    """Return the SHA-256 hex digest of `data`, 64 lowercase hex characters."""
    ...

def score_text(haystack: str, query: str) -> float:
    """Tiered relevance: 1000.0 prefix, 500.0 contains, 40.0 fuzzy, else 0.0."""
    ...

def fuzzy_match(text: str, pattern: str) -> bool:
    """True when every character of `pattern` appears in `text`, in order."""
    ...
