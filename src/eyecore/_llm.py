"""LLMClient — lazy-loaded, multi-backend LLM wrapper.

Backend resolution order (when backend='auto'):
  1. Ollama  — tries localhost:11434; uses if reachable
  2. llama-cpp — uses if LLM_MODEL_PATH env var points to a .gguf file
  3. OpenAI-compatible — falls back to openai client (works with LM Studio)

All backends expose the same `.complete()` / `.categorize()` / `.summarize()` /
`.extract_topics()` / `.generate_report()` interface.

Environment variables:
  LLM_BACKEND     — 'auto' | 'ollama' | 'llama-cpp' | 'openai'  (default: auto)
  LLM_MODEL       — model name for ollama/openai   (default: llama3.2)
  LLM_HOST        — base URL                       (default: http://localhost:11434)
  LLM_API_KEY     — API key for openai backend     (default: 'ollama')
  LLM_MODEL_PATH  — path to .gguf file for llama-cpp
"""
from __future__ import annotations

import os
import urllib.request
from typing import Any

_DEFAULT_MODEL = "llama3.2"
_DEFAULT_HOST = "http://localhost:11434"


class LLMClient:
    """Singleton LLM client with lazy backend loading."""

    _instance: "LLMClient | None" = None

    def __init__(
        self,
        backend: str = "auto",
        model: str | None = None,
        host: str | None = None,
        model_path: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._backend = backend
        self._model = model or os.getenv("LLM_MODEL", _DEFAULT_MODEL)
        self._host = host or os.getenv("LLM_HOST", _DEFAULT_HOST)
        self._model_path = model_path or os.getenv("LLM_MODEL_PATH")
        self._api_key = api_key or os.getenv("LLM_API_KEY", "ollama")
        self._client: Any = None
        self._resolved: str | None = None

    # ── Singleton ─────────────────────────────────────────────────────────────

    @classmethod
    def get(cls) -> "LLMClient":
        if cls._instance is None:
            cls._instance = cls(backend=os.getenv("LLM_BACKEND", "auto"))
        return cls._instance

    @classmethod
    def configure(
        cls,
        backend: str = "auto",
        model: str | None = None,
        host: str | None = None,
        model_path: str | None = None,
        api_key: str | None = None,
    ) -> "LLMClient":
        cls._instance = cls(
            backend=backend,
            model=model,
            host=host,
            model_path=model_path,
            api_key=api_key,
        )
        return cls._instance

    # ── Backend resolution ────────────────────────────────────────────────────

    def _resolve_backend(self) -> str:
        if self._backend != "auto":
            return self._backend
        # 1. Ollama — probe /api/tags
        try:
            urllib.request.urlopen(f"{self._host}/api/tags", timeout=1)
            return "ollama"
        except Exception:
            pass
        # 2. llama-cpp — needs model path
        if self._model_path and os.path.exists(self._model_path):
            return "llama-cpp"
        # 3. OpenAI-compatible (LM Studio, etc.)
        return "openai"

    def _load(self) -> None:
        self._resolved = self._resolve_backend()
        if self._resolved == "ollama":
            try:
                import ollama  # type: ignore[import]
                self._client = ollama.Client(host=self._host)
            except ImportError:
                raise ImportError(
                    "Ollama backend selected but 'ollama' package not installed.\n"
                    "Install with: pip install 'eyecore[llm-ollama]'"
                )
        elif self._resolved == "llama-cpp":
            try:
                from llama_cpp import Llama  # type: ignore[import]
                self._client = Llama(
                    model_path=self._model_path,
                    n_ctx=4096,
                    verbose=False,
                )
            except ImportError:
                raise ImportError(
                    "llama-cpp backend selected but 'llama-cpp-python' not installed.\n"
                    "Install with: pip install 'eyecore[llm-cpp]'"
                )
        elif self._resolved == "openai":
            try:
                from openai import OpenAI  # type: ignore[import]
                base_url = self._host
                if not base_url.endswith("/v1"):
                    base_url = base_url.rstrip("/") + "/v1"
                self._client = OpenAI(api_key=self._api_key, base_url=base_url)
            except ImportError:
                raise ImportError(
                    "OpenAI backend selected but 'openai' package not installed.\n"
                    "Install with: pip install 'eyecore[llm-openai]'"
                )

    def is_available(self) -> bool:
        try:
            self._load()
            return self._client is not None
        except Exception:
            return False

    # ── Unified interface ─────────────────────────────────────────────────────

    def complete(self, prompt: str, system: str | None = None, **kwargs) -> str:
        if self._client is None:
            self._load()
        messages: list[dict] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        if self._resolved == "ollama":
            resp = self._client.chat(model=self._model, messages=messages)
            return resp["message"]["content"]

        if self._resolved == "llama-cpp":
            full = ""
            if system:
                full += f"<|system|>{system}\n"
            full += f"<|user|>{prompt}\n<|assistant|>"
            resp = self._client(full, max_tokens=kwargs.get("max_tokens", 1024))
            return resp["choices"][0]["text"]

        if self._resolved == "openai":
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                **kwargs,
            )
            return resp.choices[0].message.content

        raise RuntimeError(f"Unknown resolved backend: {self._resolved!r}")

    def categorize(self, text: str, categories: list[str]) -> str:
        """Classify text into one of the given category strings."""
        cats = ", ".join(f'"{c}"' for c in categories)
        prompt = (
            f"Classify the following text into exactly one of these categories: {cats}.\n"
            f"Respond with only the category name — nothing else.\n\nText:\n{text[:2000]}"
        )
        result = self.complete(prompt).strip().strip('"').strip("'")
        lower = result.lower()
        for cat in categories:
            if cat.lower() == lower:
                return cat
        # Partial-match fallback
        for cat in categories:
            if cat.lower() in lower or lower in cat.lower():
                return cat
        return categories[0]

    def summarize(self, text: str, max_words: int = 200) -> str:
        prompt = (
            f"Summarize the following in {max_words} words or fewer. "
            f"Be factual, objective, and concise.\n\nText:\n{text[:4000]}"
        )
        return self.complete(prompt).strip()

    def extract_topics(self, text: str) -> list[str]:
        prompt = (
            "Extract the main topics from this text as a comma-separated list. "
            "Return only the topic keywords, no explanations or numbering.\n\nText:\n"
            + text[:2000]
        )
        result = self.complete(prompt).strip()
        return [t.strip() for t in result.split(",") if t.strip()]

    def generate_report(
        self,
        items: list[dict],
        topic: str,
        title_field: str = "title",
        body_field: str = "summary",
        max_words: int = 800,
    ) -> str:
        """Generate a multi-paragraph report on *topic* from a list of content items."""
        excerpts = "\n\n".join(
            f"- {item.get(title_field, '')}: {str(item.get(body_field, ''))[:300]}"
            for item in items[:25]
        )
        prompt = (
            f"Write a {max_words}-word analytical report on '{topic}' based on the "
            f"following items. Cover key themes, developments, and significance. "
            f"End with a bullet-point list of the most important sources/references.\n\n"
            f"Items:\n{excerpts}"
        )
        return self.complete(prompt).strip()
