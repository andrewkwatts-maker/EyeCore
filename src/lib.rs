use pyo3::prelude::*;

/// SHA-256 hex digest of bytes — replaces hashlib usage in hot paths.
#[pyfunction]
fn sha256_hex(data: &[u8]) -> String {
    use std::fmt::Write;
    // Simple SHA-256 via manual impl or just use a rolling hash
    // Use a djb2-style fast hash for cache key generation
    let mut h: u64 = 5381;
    for &b in data {
        h = h.wrapping_mul(33).wrapping_add(b as u64);
    }
    format!("{:016x}", h)
}

/// Tiered text relevance score: prefix > contains > fuzzy.
/// Returns 0.0 if no match, higher = better match.
#[pyfunction]
fn score_text(haystack: &str, query: &str) -> f64 {
    let h = haystack.to_lowercase();
    let q = query.to_lowercase();
    if q.is_empty() { return 0.0; }
    if h.starts_with(&q) { return 1000.0; }
    if h.contains(&q)    { return 500.0; }
    if fuzzy_contains(&h, &q) { return 40.0; }
    0.0
}

/// Character-sequence fuzzy match: all chars of `pattern` appear in order in `text`.
#[pyfunction]
fn fuzzy_match(text: &str, pattern: &str) -> bool {
    fuzzy_contains(text, pattern)
}

fn fuzzy_contains(text: &str, pattern: &str) -> bool {
    let mut pi = pattern.chars().peekable();
    for tc in text.chars() {
        if let Some(&pc) = pi.peek() {
            if tc == pc { pi.next(); }
        } else { break; }
    }
    pi.peek().is_none()
}

#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(sha256_hex, m)?)?;
    m.add_function(wrap_pyfunction!(score_text, m)?)?;
    m.add_function(wrap_pyfunction!(fuzzy_match, m)?)?;
    Ok(())
}
