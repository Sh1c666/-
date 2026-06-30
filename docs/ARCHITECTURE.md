# NetPilot 架构设计

本文档描述 NetPilot 的分层架构、Agent 编排循环、事件协议,以及扩展方式。

## 分层

```
交互层   React UI        —— 时间线 / 工具卡片 / 报告 / 设置
编排层   Agent (FastAPI) —— ReAct 循环、证据约束、隐私脱敏、流式事件
能力层   Tools           —— 8 个诊断工具,各自结构化输出
模型层   LLM (任意 OpenAI 兼容端点)—— Function Calling 决定下一步
```

后端是单一可信源:工具执行、隐私脱敏、结论生成都发生在后端,前端只负责展示。这样未来把后端改成 SaaS、或换 CLI/Tauri 壳,核心都能复用。

## Agent 编排循环

`netpilot/agent/orchestrator.py` 中的 `run_diagnosis()` 是一个异步生成器,产出 SSE 事件:

```
1. 脱敏用户症状(内网 IP → [内网IP-N]),组装 messages
2. 循环:
   a. 调 LLM(messages, tools)            # tools = 8 诊断工具 + submit_conclusion
   b. 若返回文本推理 → 产出 message 事件(对用户还原真实 IP)
   c. 若返回 tool_calls:
        对每个调用:
          - 还原参数中的占位符为真实地址
          - 产出 tool_call 事件
          - 执行工具(真实地址)
          - 产出 tool_result 事件(真实结果)
          - 把"脱敏后"的工具结果塞回 messages 喂给 LLM
          - 若是 submit_conclusion → 产出 final 事件,跳出
   d. 若无 tool_calls → 文本即结论,产出 final,跳出
   e. 超过 max_steps → 产出兜底 final,跳出
3. 产出 done 事件(步数 / 总耗时)
```

**控制幻觉的三道闸:**

1. 工具返回结构化数据 + `summary_zh`,而不是裸命令输出。
2. System Prompt 强制"结论必须引用具体工具的具体指标"。
3. 终止必须通过 `submit_conclusion`(结构化字段:层级/根因/证据/建议/置信度),或在无工具调用时退化成文本结论。

## 事件协议(SSE)

`POST /api/diagnose` 返回 `text/event-stream`,每帧 `data: {JSON}\n\n`。事件类型见 `netpilot/agent/events.py`,前端镜像在 `frontend/src/types.ts`:

| type | 含义 |
|---|---|
| `meta` | 会话开始:session_id、症状、是否脱敏 |
| `message` | Agent 的中间推理(自然语言) |
| `tool_call` | 决定调用某工具(含参数) |
| `tool_result` | 工具结构化结果(severity / summary_zh / data / duration) |
| `final` | 最终结论(is_network_issue / layer / root_cause / evidence / recommendation) |
| `error` | 出错(如未配置 Key) |
| `done` | 结束(步数 / 总耗时) |

## 隐私脱敏数据流

```
用户症状 "10.0.0.5 打不开"
   │  PrivacyMask.mask()
   ▼
LLM 看到 "[内网IP-1] 打不开" ──┐
   │  LLM 调 dns_lookup(host="[内网IP-1]")
   ▼                          │
还原占位符 → 真实 host=10.0.0.5 │
   │  工具用真实地址执行        │
   ▼                          │
工具结果(含 10.0.0.5)          │
   ├─ mask() → 喂回 LLM(只见 [内网IP-1])
   └─ unmask() → 展示给运维(看到 10.0.0.5)
```

公网 IP 不脱敏(Agent 需要它判断运营商跳)。脱敏映射仅存在于单次会话内存中,不落盘。

## 扩展:加一个新诊断工具

1. 在 `netpilot/tools/` 新建类,继承 `Tool`,实现 `name / description / parameters / async run()`。`run` 返回 `ToolResult`,务必填 `severity`、`data`、`summary_zh`。
2. 在 `netpilot/tools/__init__.py` 的 `_REGISTRY` 注册一个实例。

注册后:LLM 的 `tools` schema、UI 工具列表、调度都自动生效,无需改别处。前端工具结果卡片若想针对性可视化,在 `frontend/src/components/ToolCard.tsx` 的 `renderMetrics` 加一个 `case`。

## 配置分层

- `config.Settings`:启动时从环境/`.env` 读取的不可变默认值。
- `config.runtime`:运行时可写的 `RuntimeConfig`,UI 修改后持久化到 `data/settings.json`。LLM 客户端、Agent、隐私层都在调用时读 `runtime`,所以改设置无需重启。

## 知识库 / RAG

`core/kb.py` 把 `docs/knowledge/*.md` 按 `## ` 标题切成 chunk,用 **BM25**(中文双字词 + ASCII 词)做检索:

- **两种入口**:① Agent 主动调用 `kb_search` 工具;② 编排器在每次排查开始时,自动把与症状最相关的 top-2 条目注入 System Prompt(`_kb_context`)。
- **为何不用 embedding**:各家厂商的 embedding API(如 GLM `embedding-3`、OpenAI `text-embedding-3`)需要付费额度,且离线/内网环境不可用。BM25 零成本、零依赖、可单测、与 provider 无关。`Retriever` 是个 Protocol,日后要换向量检索只需实现一个新类替换单例,调用方不变。
- 知识库内容即普通 Markdown,运维直接增删 `docs/knowledge/` 文件即可扩充,无需改代码。

