# eyecore

Shared foundation for the a range pypi data repositories — SQLite DB management, topic graph, corpus management, and LLM integration.

## Features

- **BaseDB** — lazy SQLite connection with transparent `.db.gz` decompression to user cache
- **TopicGraph** — generalized topic registry with parent/child relationships, BFS traversal, and typed links
- **CorpusManager** — on-demand corpus checkout (Project Gutenberg, URL, git) with FTS5 indexing
- **LLMClient** — lazy-loaded LLM wrapper with auto-detected backends (Ollama, llama-cpp, OpenAI-compatible)
- **compress_db / decompress_to_cache** — platform-aware compression utilities for bake scripts

## Installation

```bash
pip install eyecore
```

With optional extras:

```bash
pip install "eyecore[llm-ollama]"   # Ollama backend
pip install "eyecore[llm-cpp]"      # llama-cpp-python backend
pip install "eyecore[llm-openai]"   # OpenAI-compatible backend
pip install "eyecore[corpus]"       # corpus download support
```

## Quick start

```python
from pathlib import Path
from eyecore import BaseDB, TopicGraph, CorpusManager, LLMClient

# Lazy SQLite — decompresses .db.gz to user cache on first access
db = BaseDB("myapp", gz_path=Path("data/myapp.db.gz"))
rows = db.fetchall("SELECT * FROM entities LIMIT 10")

# Topic graph
graph = TopicGraph(db.conn)
related = graph.get_related("topic-id")
tree    = graph.subtree("root-id")

# LLM — auto-detects Ollama / llama-cpp / OpenAI
llm = LLMClient.get()
if llm.is_available():
    summary = llm.summarize("Some long text to summarize...")
    topics  = llm.extract_topics("Article text about AI and machine learning...")
    report  = llm.generate_report(articles, "Technology", "title", "summary")
```

## LLM configuration

Configure via environment variables:

| Variable | Default | Description |
|---|---|---|
| `LLM_BACKEND` | auto | `ollama`, `llama-cpp`, or `openai` |
| `LLM_MODEL` | `llama3` | Model name (Ollama) or model ID (OpenAI) |
| `LLM_HOST` | `http://localhost:11434` | Ollama server URL |
| `LLM_MODEL_PATH` | — | Path to GGUF model file (llama-cpp) |
| `OPENAI_API_KEY` | — | API key for OpenAI-compatible endpoints |
| `OPENAI_BASE_URL` | — | Base URL for OpenAI-compatible endpoints |


## License

MIT — see [LICENSE](LICENSE)
