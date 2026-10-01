"""The Python fallbacks in eyecore/__init__.py must answer exactly as the Rust core.

They had drifted: the fallback `sha256_hex` was a 16-character djb2 hash while
the Rust computed SHA-256, and the fallback `score_text` had no fuzzy tier.
Which answer you got depended on whether the extension loaded.

The fallbacks only exist when `eyecore._core` fails to import, so they are run
in a subprocess with the extension blocked, and compared with hashlib, with the
documented tiers, and -- when the extension is loaded here -- with the Rust.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys

import pytest

import eyecore

DIGEST_INPUTS = ["", "abc", "the quick brown fox", "Æsir"]

SCORE_CASES = [
    ("Odin", "odin"),
    ("The Odin Stone", "odin"),
    ("Odin", "on"),
    ("Odin", "no"),
    ("Odin", "zzz"),
    ("Odin", ""),
    ("ODIN", "odin"),
    ("Æsir", "æsir"),
    ("café Odin", "odin"),
]

_FALLBACK_SCRIPT = """
import json, sys
sys.modules["eyecore._core"] = None  # force the ImportError path
import eyecore
assert not eyecore._RUST_CORE
cases = json.loads(sys.stdin.read())
print(json.dumps({
    "digests": [eyecore.sha256_hex(s.encode("utf-8")) for s in cases["digests"]],
    "scores": [eyecore.score_text(h, q) for h, q in cases["scores"]],
}))
"""


def _fallback_answers() -> dict:
    payload = json.dumps({"digests": DIGEST_INPUTS, "scores": SCORE_CASES})
    out = subprocess.run(
        [sys.executable, "-c", _FALLBACK_SCRIPT],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(out.stdout)


def test_fallback_sha256_hex_is_real_sha256():
    got = _fallback_answers()["digests"]
    assert got == [hashlib.sha256(s.encode("utf-8")).hexdigest() for s in DIGEST_INPUTS]


def test_fallback_score_text_has_every_tier():
    scores = dict(zip(map(tuple, SCORE_CASES), _fallback_answers()["scores"]))
    assert scores[("Odin", "odin")] == 1000.0
    assert scores[("The Odin Stone", "odin")] == 500.0
    assert scores[("Odin", "on")] == 40.0
    assert scores[("Odin", "no")] == 0.0
    assert scores[("Odin", "")] == 0.0


def test_fallback_agrees_with_the_loaded_rust_core():
    if not eyecore._RUST_CORE:
        pytest.skip("eyecore._core is not loaded; nothing to compare against")
    answers = _fallback_answers()
    assert answers["digests"] == [eyecore.sha256_hex(s.encode("utf-8")) for s in DIGEST_INPUTS]
    assert answers["scores"] == [eyecore.score_text(h, q) for h, q in SCORE_CASES]
