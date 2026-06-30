"""Knowledge-base search tool.

Exposes the local RAG retriever to the agent as a function it can call on
demand — e.g. when it hits an unfamiliar symptom (MTU black hole, ARP conflict,
TLS handshake quirks) and wants a refresher on root cause and remediation.

Retrieval is lexical (BM25) and runs entirely locally; see ``core/kb.py``.
"""

from __future__ import annotations

from typing import Any

from ..core.kb import retriever
from .base import Severity, Tool, ToolResult, _Timer


class KbSearchTool(Tool):
    name = "kb_search"
    description = (
        "检索本地网络故障知识库,获取常见故障模式的根因与处置参考。"
        "遇到不确定的现象(如 MTU 黑洞、ARP 冲突、证书链问题、TIME_WAIT 耗尽等)或想参考历史经验时调用。"
        "用一句话描述你想查的故障特征作为 query。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "故障特征描述,如 'HTTPS 证书过期' 或 'ping 不通但端口通'"},
            "k": {"type": "integer", "description": "返回条数,默认 4", "default": 4},
        },
        "required": ["query"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        query = str(kwargs.get("query", "")).strip()
        k = int(kwargs.get("k", 4))
        if not query:
            return ToolResult(tool=self.name, ok=False, error="缺少参数 query")

        with _Timer() as t:
            hits = retriever.search(query, k=k)

        if not hits:
            return ToolResult(
                tool=self.name,
                severity=Severity.INFO,
                summary_zh="知识库为空或无相关条目。",
                data={"query": query, "results": [], "count": 0},
                duration_ms=t.ms,
            )

        results = [
            {
                "title": c.title,
                "source": c.source,
                "text": c.text,
                "score": round(s, 3),
            }
            for c, s in hits
        ]
        preview = "\n".join(
            f"- {r['title']}({r['source']}, 相关度{r['score']}): {r['text'][:80]}"
            for r in results
        )
        return ToolResult(
            tool=self.name,
            severity=Severity.INFO,
            summary_zh=f"检索到 {len(results)} 条相关知识:\n{preview}",
            data={"query": query, "results": results, "count": len(results)},
            duration_ms=t.ms,
        )
