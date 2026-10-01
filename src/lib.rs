//! Rust helpers for `eyecore`.
//!
//! The scoring helpers here must agree exactly with the Python fallbacks in
//! `src/eyecore/__init__.py`. They had drifted -- `score_text` awarded 40.0 for
//! a fuzzy subsequence hit while the Python returned 0.0 for the same input --
//! so which ranking you got depended on whether a wheel had been built, and
//! nothing reported which one was live. The tests at the bottom pin the tiers.

#[cfg(feature = "python")]
use pyo3::prelude::*;

use sha2::{Digest, Sha256};

/// Lowest score awarded for a fuzzy subsequence match.
///
/// Named rather than inlined because the Python fallback has to use the same
/// number, and a bare `40.0` in two files is how they drifted apart.
pub const FUZZY_SCORE: f64 = 40.0;

/// Score for `haystack` containing `query` anywhere.
pub const CONTAINS_SCORE: f64 = 500.0;

/// Score for `haystack` starting with `query`.
pub const PREFIX_SCORE: f64 = 1000.0;

/// SHA-256 hex digest of `data`.
///
/// # This function used to lie
///
/// It was named `sha256_hex`, documented as a SHA-256 digest, and typed in
/// `_core.pyi` as one -- but computed a djb2 rolling hash and returned 16 hex
/// characters instead of 64. The body even said so: *"Simple SHA-256 via manual
/// impl or just use a rolling hash"*.
///
/// That is dangerous rather than merely wrong. `src/eyecore/_remote_data.py`
/// verifies 58 MB downloaded snapshots with a real `hashlib.sha256`, and a
/// maintainer reaching for the "fast" in-house digest in that path would have
/// silently disabled integrity checking while every name in sight said the
/// check was still happening.
///
/// It now computes a real SHA-256. The known-answer tests below are the point
/// of the exercise: they fail loudly if anyone swaps the implementation for a
/// cheaper one again.
pub fn sha256_hex_impl(data: &[u8]) -> String {
    let digest = Sha256::digest(data);
    let out = format!("{digest:x}");
    debug_assert_eq!(out.len(), 64, "a SHA-256 digest is 64 hex characters");
    debug_assert!(
        out.bytes().all(|b| b.is_ascii_hexdigit()),
        "the digest must be hex"
    );
    out
}

/// Tiered text relevance score: prefix > contains > fuzzy.
///
/// Returns `0.0` when nothing matches. Must stay identical to the Python
/// fallback in `src/eyecore/__init__.py`.
pub fn score_text_impl(haystack: &str, query: &str) -> f64 {
    let h = haystack.to_lowercase();
    let q = query.to_lowercase();
    if q.is_empty() {
        return 0.0;
    }
    debug_assert!(!q.is_empty(), "the empty query returned above");
    if h.starts_with(&q) {
        return PREFIX_SCORE;
    }
    if h.contains(&q) {
        return CONTAINS_SCORE;
    }
    if fuzzy_contains(&h, &q) {
        return FUZZY_SCORE;
    }
    debug_assert!(!h.contains(&q), "a containing match should have returned");
    0.0
}

/// Whether every character of `pattern` appears in `text`, in order.
pub fn fuzzy_contains(text: &str, pattern: &str) -> bool {
    let mut pi = pattern.chars().peekable();
    for tc in text.chars() {
        if let Some(&pc) = pi.peek() {
            if tc == pc {
                pi.next();
            }
        } else {
            break;
        }
    }
    pi.peek().is_none()
}

// ---------------------------------------------------------------------------
// Python bindings
// ---------------------------------------------------------------------------

/// SHA-256 hex digest of bytes.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(name = "sha256_hex")]
fn py_sha256_hex(data: &[u8]) -> String {
    sha256_hex_impl(data)
}

/// Tiered text relevance score: prefix > contains > fuzzy.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(name = "score_text")]
fn py_score_text(haystack: &str, query: &str) -> f64 {
    score_text_impl(haystack, query)
}

/// Character-sequence fuzzy match.
#[cfg(feature = "python")]
#[pyfunction]
#[pyo3(name = "fuzzy_match")]
fn py_fuzzy_match(text: &str, pattern: &str) -> bool {
    fuzzy_contains(text, pattern)
}

#[cfg(feature = "python")]
#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(py_sha256_hex, m)?)?;
    m.add_function(wrap_pyfunction!(py_score_text, m)?)?;
    m.add_function(wrap_pyfunction!(py_fuzzy_match, m)?)?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn sha256_matches_the_published_known_answers() {
        // FIPS 180-4 vectors. These are the whole reason this function exists
        // in its current form: the previous implementation returned
        // "000000000b885c8b" for b"abc", which is neither the right value nor
        // the right length.
        assert_eq!(
            sha256_hex_impl(b"abc"),
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        );
        assert_eq!(
            sha256_hex_impl(b""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
        assert_eq!(
            sha256_hex_impl(b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"),
            "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"
        );
    }

    #[test]
    fn the_digest_is_the_right_shape() {
        // A rolling hash gave 16 characters. Anyone substituting one again
        // trips this even without knowing the expected digest.
        for input in [b"".as_slice(), b"x", b"the quick brown fox"] {
            let got = sha256_hex_impl(input);
            assert_eq!(got.len(), 64, "wrong digest length for {input:?}");
        }
    }

    #[test]
    fn the_digest_changes_with_a_single_bit() {
        assert_ne!(sha256_hex_impl(b"abc"), sha256_hex_impl(b"abd"));
    }

    #[test]
    fn scoring_tiers_are_ordered() {
        assert_eq!(score_text_impl("Odin", "odin"), PREFIX_SCORE);
        assert_eq!(score_text_impl("The Odin Stone", "odin"), CONTAINS_SCORE);
        assert_eq!(score_text_impl("Odin", "on"), FUZZY_SCORE);
        assert_eq!(score_text_impl("Odin", "zzz"), 0.0);
        // Asserted through returned values rather than by comparing the
        // constants directly, which folds to `assert!(true)` at compile time
        // and checks nothing.
        assert!(score_text_impl("Odin", "odin") > score_text_impl("The Odin Stone", "odin"));
        assert!(score_text_impl("The Odin Stone", "odin") > score_text_impl("Odin", "on"));
    }

    #[test]
    fn an_empty_query_scores_nothing() {
        // Not a prefix match: every string starts with "", so without the
        // guard this would return the top score for no query at all.
        assert_eq!(score_text_impl("Odin", ""), 0.0);
    }

    #[test]
    fn scoring_is_case_insensitive() {
        assert_eq!(score_text_impl("ODIN", "odin"), PREFIX_SCORE);
        assert_eq!(score_text_impl("odin", "ODIN"), PREFIX_SCORE);
    }

    #[test]
    fn fuzzy_matching_requires_order() {
        assert!(fuzzy_contains("odin", "on"));
        assert!(fuzzy_contains("odin", "odin"));
        assert!(!fuzzy_contains("odin", "no"), "order must matter");
        assert!(fuzzy_contains("odin", ""), "the empty pattern is contained");
    }

    #[test]
    fn scoring_handles_non_ascii_without_panicking() {
        // These names are ordinary in a mythology corpus.
        assert!(score_text_impl("Æsir", "æsir") > 0.0);
        assert!(score_text_impl("café Odin", "odin") > 0.0);
        assert_eq!(score_text_impl("Zeus \u{2014} Odin", "zzz"), 0.0);
    }
}
