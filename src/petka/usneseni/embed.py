"""Embeddings from a llama.cpp server running BAAI/bge-m3 (GGUF), OpenAI-compatible API.

bge-m3 needs no query/document prefixes. EMBED_URL is the server base URL; unset disables
semantic search (the web and MCP fall back to full text and say so).
"""

import logging
import os
from functools import lru_cache

import httpx

log = logging.getLogger(__name__)

URL = os.environ.get("EMBED_URL", "")
MODEL = os.environ.get("EMBED_MODEL", "bge-m3")
MAX_CHARS = 6000
QUERY_TIMEOUT = float(os.environ.get("EMBED_QUERY_TIMEOUT", "2"))  # a search never waits longer


def enabled() -> bool:
    return bool(URL)


def document_text(r: dict) -> str:
    parts = [r.get("title") or "", r.get("summary") or "", ", ".join(r.get("keywords") or []),
             r.get("agenda_title") or "", r["text"]]
    return "\n".join(p for p in parts if p)[:MAX_CHARS]


def _call(texts: list[str], timeout: float = 300) -> list[list[float]]:
    r = httpx.post(f"{URL.rstrip('/')}/v1/embeddings", json={"model": MODEL, "input": texts},
                   timeout=timeout)
    r.raise_for_status()
    data = sorted(r.json()["data"], key=lambda d: d["index"])
    return [d["embedding"] for d in data]


def embed_documents(texts: list[str]) -> list[list[float]]:
    if not enabled():
        raise RuntimeError("EMBED_URL not set")
    return _call(texts)


def embed_query(q: str) -> list[float] | None:
    """Query vector, or None when semantic search is off or the embedder is down (starting,
    restarting) – search then falls back to full text and says so."""
    if not enabled():
        return None
    try:
        return list(_query_vector(" ".join(q.split())[:2000].lower()))
    except httpx.HTTPError as e:
        log.warning("embedder unavailable or busy: %r", e)
        return None


@lru_cache(maxsize=1024)
def _query_vector(q: str) -> tuple[float, ...]:
    # short timeout: when the server is busy (bulk embedding) search falls back to full text
    return tuple(_call([q], timeout=QUERY_TIMEOUT)[0])
