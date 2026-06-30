"""Tests for the knowledge-base retriever (chunking, tokenization, BM25)."""

from __future__ import annotations

from pathlib import Path

from netpilot.core import kb
from netpilot.core.kb import KBChunk, LexicalRetriever, load_chunks, tokenize

KB_DIR = Path(__file__).resolve().parents[2] / "docs" / "knowledge"


# --------------------------------------------------------------------------- tokenize
def test_tokenize_ascii_and_cjk():
    toks = tokenize("ping 不通 TCP 重传")
    assert "ping" in toks and "tcp" in toks
    assert "不通" in toks          # CJK bigram
    assert "重传" in toks
    assert "通" in toks            # CJK unigram


def test_tokenize_case_insensitive():
    assert "https" in tokenize("HTTPS 443")
    assert "443" in tokenize("HTTPS 443")


# --------------------------------------------------------------------------- BM25
def test_bm25_ranks_relevant_chunk_first():
    chunks = [
        KBChunk(id="a", title="ICMP 过滤", source="f.md",
                text="ping 不通但 TCP 端口可达,目标禁用了 ICMP"),
        KBChunk(id="b", title="证书过期", source="f.md",
                text="HTTPS 证书已过期导致浏览器报错"),
        KBChunk(id="c", title="TIME_WAIT", source="f.md",
                text="短连接耗尽端口,新连接被拒"),
    ]
    r = LexicalRetriever(chunks)
    hits = r.search("ping 不通但端口通", k=2)
    assert hits[0][0].id == "a"
    assert all(s > 0 for _, s in hits)


def test_bm25_empty_and_no_match():
    r = LexicalRetriever([])
    assert r.search("anything") == []
    chunks = [KBChunk(id="a", title="x", source="f.md", text="证书过期")]
    r2 = LexicalRetriever(chunks)
    assert r2.search("zzznomatch") == []


# --------------------------------------------------------------------------- load_chunks
def test_load_chunks_from_real_kb():
    chunks = load_chunks(KB_DIR)
    assert len(chunks) >= 8
    # each chunk has stable fields
    for c in chunks:
        assert c.title and c.source.endswith(".md") and c.text


def test_real_kb_retrieves_relevant_failure_mode():
    chunks = load_chunks(KB_DIR)
    r = LexicalRetriever(chunks)
    hits = r.search("HTTPS 证书过期报错", k=1)
    assert hits, "expected at least one match in the KB"
    assert "证书" in hits[0][0].title or "证书" in hits[0][0].text


def test_rebuild_retriever_singleton():
    """The module singleton should reflect the real KB after a rebuild."""
    kb.rebuild_retriever(KB_DIR)
    assert isinstance(kb.retriever, LexicalRetriever)
    assert kb.retriever.search("MTU 黑洞", k=1)
