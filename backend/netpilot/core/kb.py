"""Knowledge-base retrieval (RAG) — lexical, embedding-free.

Why lexical instead of embeddings?
    * GLM's `embedding-3` is billable; many accounts (and all offline / air-gapped
      deployments) can't use it. A BM25 retriever has **no API cost, no extra
      dependency, runs offline**, and is fully unit-testable.
    * The interface (:class:`Retriever`) is narrow on purpose — swapping in an
      embedding backend later is a drop-in replacement that only changes how
      documents and the query are vectorized; the ranking/caller code stays.

Chinese tokenization uses ASCII words + CJK unigrams **and bigrams**, so a query
for "网络丢包" matches a chunk about "丢包与重传" via the shared bigram.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from ..config import PROJECT_DIR

KB_DIR = PROJECT_DIR / "docs" / "knowledge"

_CJK_RUN = re.compile(r"[一-鿿]+")
_ASCII_WORD = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    """ASCII words + CJK unigrams & bigrams (lowercased)."""
    lowered = text.lower()
    toks: list[str] = list(_ASCII_WORD.findall(lowered))
    for run in _CJK_RUN.findall(lowered):
        toks.extend(run)                                  # unigrams (单字)
        toks.extend(run[i : i + 2] for i in range(len(run) - 1))  # bigrams (双字词)
    return toks


class KBChunk(BaseModel):
    id: str
    title: str
    source: str          # source file name
    text: str


class Retriever(Protocol):
    def search(self, query: str, k: int = 4) -> list[tuple[KBChunk, float]]: ...


class LexicalRetriever:
    """BM25 over tokenized chunks. Zero external dependencies."""

    def __init__(self, chunks: list[KBChunk], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1 = k1
        self.b = b
        self.doc_tokens: list[list[str]] = [
            tokenize(f"{c.title} {c.text}") for c in chunks
        ]
        n = len(chunks)
        df: Counter[str] = Counter()
        for toks in self.doc_tokens:
            df.update(set(toks))
        self.idf: dict[str, float] = {t: math.log(1 + n / (1 + d)) for t, d in df.items()}
        lengths = [len(t) for t in self.doc_tokens]
        self.avg_len = (sum(lengths) / n) if n else 1.0

    def search(self, query: str, k: int = 4) -> list[tuple[KBChunk, float]]:
        if not self.chunks:
            return []
        qtoks = tokenize(query)
        scored: list[tuple[float, int]] = []
        for i, dtoks in enumerate(self.doc_tokens):
            if not dtoks:
                continue
            tf = Counter(dtoks)
            norm = self.k1 * (1 - self.b + self.b * len(dtoks) / self.avg_len)
            s = 0.0
            for t in qtoks:
                f = tf.get(t)
                if f is None:
                    continue
                idf = self.idf.get(t, 0.0)
                s += idf * (f * (self.k1 + 1)) / (f + norm)
            if s > 0:
                scored.append((s, i))
        scored.sort(reverse=True)
        return [(self.chunks[i], s) for s, i in scored[:k]]


# --------------------------------------------------------------------------- loading
def _short_hash(text: str) -> str:
    import hashlib

    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def load_chunks(directory: Path = KB_DIR) -> list[KBChunk]:
    """Split each markdown file by ``## `` headings into KB chunks."""
    if not directory.exists():
        return []
    chunks: list[KBChunk] = []
    for path in sorted(directory.glob("*.md")):
        content = path.read_text(encoding="utf-8", errors="replace")
        # Split into (heading, body) pairs on level-2 headings.
        parts = re.split(r"(?m)^(## .+)$", content)
        # parts[0] is the preamble (H1 + intro). Turn it into one chunk.
        preamble = parts[0].strip()
        if preamble:
            m = re.match(r"^#\s+(.+?)\s*$", preamble, re.M)
            title = (m.group(1) if m else path.stem).strip()
            body = re.sub(r"^#\s+.+\s*", "", preamble, count=1, flags=re.M).strip()
            if body:
                chunks.append(
                    KBChunk(id=_short_hash(f"{path.name}:{title}"), title=title,
                            source=path.name, text=body[:1200])
                )
        # Each subsequent pair is (## heading, body).
        for j in range(1, len(parts) - 1, 2):
            heading = parts[j].strip().lstrip("#").strip()
            body = parts[j + 1].strip()
            if body:
                chunks.append(
                    KBChunk(id=_short_hash(f"{path.name}:{heading}"), title=heading,
                            source=path.name, text=body[:1200])
                )
    return chunks


# Module-level singleton — built once at import (pure Python, cheap).
retriever: Retriever = LexicalRetriever(load_chunks())


def rebuild_retriever(directory: Path = KB_DIR) -> None:
    """Rebuild the singleton (used after KB files change, e.g. in tests)."""
    global retriever
    retriever = LexicalRetriever(load_chunks(directory))


__all__ = [
    "KBChunk",
    "Retriever",
    "LexicalRetriever",
    "tokenize",
    "load_chunks",
    "retriever",
    "rebuild_retriever",
    "KB_DIR",
]
