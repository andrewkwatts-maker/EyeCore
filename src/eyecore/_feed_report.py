"""LLM-powered topic clustering and daily report generation for feed-based scrapers."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date as date_class

from eyecore._llm import LLMClient

_STOP_WORDS = {
    "the", "a", "an", "is", "are", "was", "were", "in", "on", "at", "to",
    "for", "of", "and", "or", "but", "with", "from", "by", "has", "have",
    "had", "be", "been", "will", "can", "that", "this", "it", "its", "as",
    "up", "about",
}


def cluster_by_keyword(
    articles: list[dict], min_cluster: int = 3
) -> dict[str, list[dict]]:
    """Simple keyword-frequency clustering — no LLM needed.

    Groups articles by their most-common title words. Returns {topic: [articles]}.
    """
    # Build word frequency dict across all titles, excluding stop words
    word_freq: dict[str, int] = defaultdict(int)
    for article in articles:
        title = article.get("title", "").lower()
        words = [
            w.strip(".,!?;:\"'()[]{}") for w in title.split()
        ]
        for word in words:
            if word and word not in _STOP_WORDS and len(word) > 2:
                word_freq[word] += 1

    # Take top 10 most-frequent words as cluster labels
    top_labels = [
        word
        for word, _ in sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:10]
    ]

    clusters: dict[str, list[dict]] = {label: [] for label in top_labels}
    clusters["general"] = []

    for article in articles:
        title = article.get("title", "").lower()
        assigned = False
        for label in top_labels:
            if label in title.split() or f" {label}" in title or f"{label} " in title:
                clusters[label].append(article)
                assigned = True
                break
        if not assigned:
            clusters["general"].append(article)

    # Remove empty clusters (except 'general')
    result: dict[str, list[dict]] = {}
    for label, arts in clusters.items():
        if arts or label == "general":
            if arts:
                result[label] = arts

    # If general is empty, omit it too
    if not result:
        result["general"] = articles

    # Drop clusters below min_cluster threshold (move to general)
    final: dict[str, list[dict]] = {}
    overflow: list[dict] = []
    for label, arts in result.items():
        if label == "general" or len(arts) >= min_cluster:
            final[label] = arts
        else:
            overflow.extend(arts)

    if overflow:
        final.setdefault("general", []).extend(overflow)

    # Drop empty general
    if "general" in final and not final["general"]:
        del final["general"]

    return final if final else {"general": articles}


def cluster_with_llm(
    articles: list[dict], max_clusters: int = 10
) -> dict[str, list[dict]]:
    """LLM-powered clustering. Falls back to keyword clustering if LLM unavailable."""
    llm = LLMClient.get()
    if not llm.is_available():
        return cluster_by_keyword(articles)

    # Build numbered title list
    titles_list = "\n".join(
        f"{i + 1}. {a.get('title', '')}"
        for i, a in enumerate(articles)
    )

    # Ask LLM for top N topics
    prompt = (
        f"Given these news article titles, identify the top {max_clusters} main "
        f"topics/themes as a comma-separated list:\n{titles_list}"
    )
    response = llm.complete(prompt)

    # Parse comma-separated cluster names, stripping numbers/bullets/quotes
    raw_names = [
        name.strip().strip("\"'1234567890.-) ").strip()
        for name in response.split(",")
    ]
    cluster_names = [n for n in raw_names if n][:max_clusters]

    if not cluster_names:
        return cluster_by_keyword(articles)

    # Assign each article to a topic using LLM categorize
    clusters: dict[str, list[dict]] = defaultdict(list)
    for article in articles:
        title = article.get("title", "")
        if not title:
            clusters["general"].append(article)
            continue
        assigned = llm.categorize(title, cluster_names)
        # Normalize: match against known cluster names (case-insensitive)
        matched = None
        assigned_lower = assigned.strip().lower()
        for name in cluster_names:
            if name.lower() in assigned_lower or assigned_lower in name.lower():
                matched = name
                break
        if matched is None:
            matched = "general"
        clusters[matched].append(article)

    return dict(clusters) if clusters else cluster_by_keyword(articles)


def generate_topic_report(topic: str, articles: list[dict]) -> dict:
    """Generate a report dict for a topic cluster.

    Returns:
        {topic, summary, article_count, links: [{title, url}], generated_at}
    """
    llm = LLMClient.get()
    if llm.is_available():
        summary = llm.generate_report(
            articles,
            topic,
            title_field="title",
            body_field="summary",
            max_words=400,
        )
    else:
        summaries = [f"- {a.get('title', '')}" for a in articles[:10]]
        summary = f"**{topic}** — {len(articles)} articles\n" + "\n".join(summaries)

    links = [
        {"title": a.get("title", ""), "url": a.get("url", "")}
        for a in articles[:20]
        if a.get("url")
    ]
    return {
        "topic": topic,
        "summary": summary,
        "article_count": len(articles),
        "links": links,
    }


def generate_daily_reports(
    app_name: str,
    target_date: str | None = None,
    use_llm: bool = True,
    verbose: bool = False,
) -> list[dict]:
    """Generate topic reports for all articles on a given date for app_name.

    target_date: YYYY-MM-DD string, defaults to today.
    Returns list of report dicts.
    """
    from eyecore._feed_store import open_day, insert_report

    if target_date is None:
        target_date = date_class.today().isoformat()

    try:
        db = open_day(app_name, target_date)
    except FileNotFoundError:
        return []

    rows = db.execute("SELECT data FROM articles").fetchall()
    articles = []
    for r in rows:
        try:
            articles.append(json.loads(r["data"]))
        except Exception:
            pass

    if not articles:
        return []

    if verbose:
        print(f"Clustering {len(articles)} articles for {target_date}...")

    clusters = cluster_with_llm(articles) if use_llm else cluster_by_keyword(articles)

    reports = []
    for topic, cluster_articles in clusters.items():
        if verbose:
            print(f"  Generating report: {topic} ({len(cluster_articles)} articles)")
        report = generate_topic_report(topic, cluster_articles)
        report["date"] = target_date
        insert_report(app_name, db, topic, target_date, report["summary"], cluster_articles)
        reports.append(report)

    return reports
