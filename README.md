# NetPilot · AI 网络故障排查 Copilot

[![CI](https://github.com/Sh1c666/netpilot/actions/workflows/ci.yml/badge.svg)](https://github.com/Sh1c666/netpilot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![React](https://img.shields.io/badge/frontend-React%2BTS-61dafb.svg)](https://react.dev/)

> 应用一慢、一挂,**网络总是第一个背锅**。
> NetPilot 用大模型驱动的 Agent,在 30 秒内帮你判断:**这到底是不是网络问题?如果是,在哪一层?如果不是,锅该甩给谁?**

NetPilot 是一个开源、跨平台的网络故障排查 Copilot。它不是又一个"网络工具大杂烩",而是把运维老手脑子里的**假设—验证决策树**交给 LLM,让 Agent 自动调用诊断工具(DNS / Ping / Traceroute / 端口扫描 / TLS / HTTP / 本机自检),逐层收敛、给出**带证据的结论**。

灵感来源于 [NETworkManager](https://github.com/BornToBeRoot/NETworkManager)——它把"工具集成"做到了极致,而 NetPilot 的差异化在于 **LLM 辅助排查本身**:工具不会告诉你"下一步该查什么、结果意味着什么",NetPilot 会。

---

## ✨ 特性

- 🤖 **Agent 模式(ReAct + Function Calling)**:LLM 自主决定调用哪个工具、解读结果、决定下一步,不是一问一答的聊天框。
- 🌳 **分诊决策树**:按 `本机 → DNS → 连通性 → 路径 → 端口 → TLS → HTTP` 分层排查,杜绝跳步与瞎猜。
- 🧰 **9 个结构化诊断工具**:每个工具返回**结构化数据 + 中文摘要**(`summary_zh` 是减少幻觉的"灵魂字段")。
- 📚 **知识库 RAG**:常见故障模式做成知识库,Agent 可调用 `kb_search` 检索;并在每次排查开始时自动注入最相关的条目。采用**纯词法检索(BM25,中文双字词)**,免 embedding、免费用、离线可跑。
- 🛡️ **隐私脱敏**:发送给云端模型前,自动把内网 IP 替换为 `[内网IP-1]` 占位符;真实地址仅留在本地。也支持切换本地模型。
- 📋 **带证据的结论**:每条判断都引用"哪个工具的哪个指标",可直接用于工单汇报;一键复制报告。
- 🖥️ **跨平台 + 桌面级 UI**:Python(FastAPI)后端 + React/TS 前端,暗色专业运维控制台风格。
- ⚡ **流式体验**:排查过程实时展示"思考 → 调工具 → 出结果 → 下一步"。
- 🐳 **一键 Docker**:`docker compose up` 即用,镜像内建前端,无需本地装 Python / Node。

---

## 🧠 它解决什么真实痛点

| 用户报的现象 | NetPilot 能给出的判断 |
|---|---|
| "XX 打不开/连不上" | DNS 失败?端口被拦?服务没起?证书过期? |
| "卡 / 慢" | 是丢包/重传(网络),还是后端慢(应用)?对比 TCP RTT 与 HTTP 延迟 |
| "时通时不通" | ARP 冲突 / DNS 轮询到死节点 / 连接数耗尽 |
| "刚上线就挂" | DNS 改动 / 防火墙规则 / 证书未续 / 路由变更 |
| HTTPS 报错 | 证书过期 / 链不全 / 域名不符 / TLS 版本 |

**几个被写进知识库的反直觉判断**(新手最容易踩的坑):

- `ping` 不通 ≠ 网络不通——大量云主机禁 ICMP,要用 `tcp_ping` 复核。
- DNS 解析到 IP ≠ 解析正确——可能是陈旧/被污染的 IP。
- HTTP **5xx = 应用侧问题**,请求已到达后端,网络没问题,工单应还给应用团队。
- "慢"常常不是带宽,而是 1% 丢包导致的 TCP 吞吐崩塌。

---

## 🏗️ 架构

```
┌──────────────────────────────────────────────────────┐
│  浏览器 / 桌面 (React + TypeScript + Vite)            │
│   对话时间线 · 工具结果卡片 · Profile · 设置          │
└───────────────────────┬──────────────────────────────┘
                        │  SSE (POST /api/diagnose)  + REST
┌───────────────────────▼──────────────────────────────┐
│  Python 后端 (FastAPI)                                │
│  ┌──────────────┐   ┌─────────────────────────────┐   │
│  │ Agent 编排    │   │ 工具层 (8 个诊断工具)        │   │
│  │ ReAct 循环    │──▶│ dns/ping/traceroute/...     │   │
│  │ 证据约束      │   │ 结构化输出 + summary_zh      │   │
│  └──────┬───────┘   └─────────────────────────────┘   │
│         │ LLM (任意 OpenAI 兼容端点) Function Calling   │
│  ┌──────▼───────┐   ┌─────────────────────────────┐   │
│  │ 隐私脱敏层    │   │ Profile 存储 / 配置 (JSON)   │   │
│  └──────────────┘   └─────────────────────────────┘   │
└──────────────────────────────────────────────────────┘
```

**关键设计**:LLM 看到的是**脱敏后**的上下文(内网 IP 已替换);工具**执行时**用的是**真实地址**(系统自动还原占位符);回传给运维的是**真实结果**。三者分离,隐私与可用性兼得。

更详细的架构与事件协议见 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)。

---

## 🚀 快速开始

### 环境要求

- Python ≥ 3.10
- Node.js ≥ 18(仅开发/构建前端时需要)
- 一个**支持 Function Calling** 的 OpenAI 兼容 API Key —— DeepSeek / OpenAI / GLM(智谱) / Ollama 任选,见下方「Provider 兼容性」

### 准备:后端依赖与配置(两种运行方式都要先做)

```bash
cd backend
python -m venv .venv
# Windows (Git Bash): ./.venv/Scripts/python.exe -m pip install -e ".[dev]"
# macOS / Linux:      .venv/bin/pip install -e ".[dev]"
./.venv/Scripts/python.exe -m pip install -e ".[dev]"

cp .env.example .env
# 编辑 .env,填入 NETPILOT_LLM_API_KEY + 选 provider(也可启动后在 UI 设置里填,有预设下拉)
```

> ⚠️ **后端必须开。** 下面两种方式无论选哪种,都得先有一个终端把后端跑起来——前端只是网页外壳,真正调 LLM、跑诊断工具、做隐私脱敏的都是后端。只开前端不开后端,页面能进但排查会失败。

### 方式 A · 自用 / 部署:单进程,访问 http://127.0.0.1:8000 ✅

构建一次前端,之后后端会自动托管它,**日常只开一个进程**:

```bash
# 1) 构建前端(只需一次;以后改了前端代码再重新 build)
cd frontend
npm install
npm run build          # 产物输出到 frontend/dist

# 2) 启动后端(它会托管刚构建好的前端)
cd ../backend
./.venv/Scripts/python.exe -m netpilot.main
```

打开 **http://127.0.0.1:8000**。如果打开是一段 JSON(写着 “Frontend not built yet”),说明第 1 步没成功生成 `frontend/dist`,回到 `cd frontend && npm run build` 重做一次。

### 方式 B · 开发前端:双进程,访问 http://localhost:5173

改前端代码、要热更新时用。**两个终端都要开**:

```bash
# 终端 1:后端(一直开着别关)
cd backend
./.venv/Scripts/python.exe -m netpilot.main

# 终端 2:前端热更新(另开一个终端)
cd frontend
npm install
npm run dev            # Vite 在 http://localhost:5173,/api 自动代理到 :8000
```

打开 **http://localhost:5173**。Vite 把所有 `/api` 请求转发给后端,排查功能照常工作;改前端代码即时刷新。

> 💡 **为什么 5173 能打开、8000 打不开?** 在方式 B 里,8000 是后端(不直接出网页),网页在 5173。如果你只跑了 `npm run dev` 而没开终端 1 的后端,5173 能进界面但一排查就报错。想"打开 8000 直接看到完整界面",用方式 A。

两种方式进入后,都在「设置」里确认模型与 API Key,在输入框描述故障现象(或点示例),点 **开始排查**。

### 3. Docker(最省事)

不想装 Python / Node?一行起,镜像里已内建前端:

```bash
docker compose up --build      # 首次会构建镜像(npm + pip 安装),之后直接 docker compose up
```

打开 http://localhost:8000,在「设置」里填 API Key(DeepSeek 默认),开始排查。Profile 与设置持久化在 `netpilot-data` 卷里,重启不丢。

也可以不写 compose,直接 `docker run`:

```bash
docker build -t netpilot .
docker run -p 8000:8000 -v netpilot-data:/app/backend/data netpilot
```

> 📌 容器内 `local_check` 检查的是**容器自身**的本机配置(hosts / DNS),不是你宿主机的;远程诊断(DNS / ping / traceroute / 端口 / TLS / HTTP)正常工作。需要排查**本机**网络时,建议用上面 1+2 的本地方式起。

---

## ⚙️ 配置

所有配置优先级:**UI 设置 > .env > 默认值**。UI 修改会持久化到 `backend/data/settings.json`。

| 变量 | 默认 | 说明 |
|---|---|---|
| `NETPILOT_LLM_API_KEY` | (空) | LLM API Key |
| `NETPILOT_LLM_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容端点 |
| `NETPILOT_LLM_MODEL` | `deepseek-chat` | 模型 id,**需支持 Function Calling** |
| `NETPILOT_AGENT_MAX_STEPS` | `12` | 单次排查最大工具调用次数(防失控) |
| `NETPILOT_PRIVACY_MASK_INTERNAL_IPS` | `true` | 内网 IP 脱敏开关 |
| `NETPILOT_HOST` / `NETPILOT_PORT` | `127.0.0.1` / `8000` | 监听地址 |

### 🔌 Provider 兼容性

NetPilot 用官方 [`openai`](https://github.com/openai/openai-python) SDK 指向**任意 `base_url`**——只要对方是 OpenAI 兼容协议就能跑。这是架构的通用性所在,也是卖点:不绑定单一厂商。设置面板里有 **provider 预设下拉**,一键填好端点和模型。

| Provider | `NETPILOT_LLM_BASE_URL` | 推荐 `MODEL` | 备注 |
|---|---|---|---|
| **DeepSeek**(默认) | `https://api.deepseek.com` | `deepseek-chat` | ✅ 默认配置。`deepseek-reasoner`(R1)**不支持**工具调用,别选 |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` | |
| GLM(智谱) | `https://open.bigmodel.cn/api/paas/v4/` | `glm-4.5` | |
| Ollama(本地) | `http://localhost:11434/v1` | `qwen2.5` | 零数据外发;API Key 随便填一个非空串即可 |

> ⚠️ **Function Calling 是硬要求**:Agent 靠模型主动调用诊断工具来收敛排查。纯对话/纯推理模型(如 DeepSeek-R1)只会输出文本,排查闭环会失效。

---

## 🧰 工具一览

| 工具 | 作用 | 关键输出 |
|---|---|---|
| `local_check` | 本机自检 | 代理 / hosts 覆盖 / DNS 服务器 |
| `dns_lookup` | DNS 解析 | 解析状态、IP 列表、TTL |
| `icmp_ping` | ICMP 探测 | 丢包率、RTT、是否不可达 |
| `tcp_ping` | TCP 端口探测(免权限) | 可达性、握手 RTT——复核"禁 ICMP" |
| `traceroute` | 路径追踪 | 跳列表、断点在第几跳 |
| `port_scan` | 端口扫描 | open / closed / **filtered** |
| `tls_inspect` | 证书与 TLS | 剩余天数、域名匹配、TLS 版本 |
| `http_probe` | HTTP 探测 | 状态码、延迟、重定向链 |
| `kb_search` | 知识库检索(RAG) | 命中的故障模式条目 + 相关度 |

详见 [`docs/TOOLS.md`](docs/TOOLS.md),排查决策树见 [`docs/DECISION_TREE.md`](docs/DECISION_TREE.md)。

---

## 🧪 测试

```bash
cd backend
./.venv/Scripts/python.exe -m pytest
```

覆盖:隐私脱敏、ping/traceroute 输出解析、端口扫描(本地回环)、Agent 循环(假 LLM + 假工具)。

---

## 📁 项目结构

```
AI_NetworkManage/
├── backend/
│   ├── netpilot/
│   │   ├── main.py              # FastAPI 入口,托管 SPA
│   │   ├── config.py            # 分层配置(启动配置 + 运行时可写)
│   │   ├── api/                 # 路由 + schema(diagnose SSE / profiles / settings)
│   │   ├── agent/               # 编排器 + LLM 客户端 + System Prompt + 事件
│   │   ├── tools/               # 8 个诊断工具 + 注册表
│   │   ├── core/                # 隐私脱敏
│   │   └── store/               # Profile JSON 存储
│   ├── tests/
│   ├── pyproject.toml
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.tsx              # 状态与布局编排
│   │   ├── api.ts               # SSE-over-POST 客户端 + REST
│   │   ├── components/          # 时间线 / 工具卡片 / 最终报告 / 设置
│   │   └── styles/global.css    # 暗色设计系统
│   └── ...
└── docs/                        # 架构 / 决策树 / 工具 / 知识库
```

---

## 🗺️ 路线图

- [x] MVP:Agent 闭环 + 诊断工具 + 流式 UI + 隐私脱敏
- [x] 知识库 RAG(BM25 词法检索 + 自动注入,见 `docs/knowledge/`)
- [x] 多 provider 兼容(DeepSeek / OpenAI / GLM / Ollama,任意 OpenAI 兼容端点 + UI 预设下拉)
- [ ] embedding 检索后端(账号有 embedding 额度时,在 `core/kb.py` 换一个 Retriever 实现即可)
- [ ] 结果可视化增强(路径图、延迟时序图)
- [x] 排查报告导出(Markdown,一键下载,含结论/证据/完整排查过程)
- [ ] 历史会话
- [ ] Tauri 打包为单文件桌面应用

---

## 🙏 致谢

- [NETworkManager](https://github.com/BornToBeRoot/NETworkManager) —— 工具集成与 Profile 设计的灵感来源。
- [DeepSeek](https://www.deepseek.com/) / [智谱 GLM](https://open.bigmodel.cn/) / [OpenAI](https://openai.com/) —— 提供大模型与 OpenAI 兼容接口(默认配置指向 DeepSeek)。
- [openai-python](https://github.com/openai/openai-python) —— 用单一 SDK 连接任意 OpenAI 兼容端点,是本项目 provider 无关的基础。

## 📄 License

[MIT](LICENSE)
