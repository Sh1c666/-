# 工具参考

每个工具都是给 LLM 的一个 function,返回**结构化数据 + 中文摘要(`summary_zh`)**。本文档列出每个工具的入参与关键输出字段,便于理解结果或扩展。

---

## `local_check` — 本机自检

排查网络前先排除本机。读取代理环境变量、`hosts` 中目标域名的静态映射、本机 DNS 服务器。

| 字段 | 含义 |
|---|---|
| `proxy_active` | 是否配置了 HTTP/HTTPS 代理 |
| `hosts_entries` | hosts 中匹配目标的条目(`{ip, host}`) |
| `hosts_override_present` | 是否存在 hosts 静态映射(会绕过 DNS) |
| `dns_servers` | 本机使用的 DNS 服务器列表 |

---

## `dns_lookup` — DNS 解析

| 参数 | 说明 |
|---|---|
| `host` | 域名 |
| `rdtype` | `A`(默认) / `AAAA` / `CNAME` / `MX` |
| `timeout` | 单次查询超时(秒) |

| 字段 | 含义 |
|---|---|
| `status` | `OK` / `NXDOMAIN` / `NO_ANSWER` / `NoNameservers` / `Timeout` |
| `resolved_ips` | 解析到的 IP 列表 |
| `ttl` | 记录 TTL |
| `records` | 原始记录 |

---

## `icmp_ping` — ICMP 探测

通过 OS 原生命令(`ping`/Windows 同名)执行,跨平台解析。

| 参数 | 说明 |
|---|---|
| `host` | IP 或域名 |
| `count` | 包数(默认 4) |
| `timeout` | 每个回包等待秒数(默认 2) |

| 字段 | 含义 |
|---|---|
| `loss_pct` | 丢包率(%) |
| `sent` / `received` | 发送 / 接收数 |
| `rtt_avg_ms` / `rtt_min_ms` / `rtt_max_ms` | 往返延迟 |
| `unreachable` | 是否"目标主机不可达" |

> ⚠️ ping 失败时务必用 `tcp_ping` 复核——目标可能只是禁了 ICMP。

---

## `tcp_ping` — TCP 端口探测(免权限)

纯 socket 连接,无需管理员/root。用于复核"禁 ICMP"。

| 参数 | 说明 |
|---|---|
| `host` / `port` | 目标与端口 |
| `timeout` | 连接超时(默认 3) |

| 字段 | 含义 |
|---|---|
| `reachable` | 端口是否可达 |
| `rtt_ms` | TCP 握手 RTT |

---

## `traceroute` — 路径追踪

OS 原生命令:Windows `tracert`,POSIX `traceroute`(无则 `tracepath`)。

| 参数 | 说明 |
|---|---|
| `host` | 目标 |
| `max_hops` | 最大跳数(默认 20) |

| 字段 | 含义 |
|---|---|
| `hops` | `[{n, ip, rtt_ms}]` 每跳信息(`ip` 为 null 表示超时) |
| `status` | `REACHED` / `BROKEN` / `PARTIAL` / `timeout` |
| `break_at_hop` | 路径中断的跳号(若有) |

---

## `port_scan` — 端口扫描

纯 Python 并发 connect 扫描,无 nmap 依赖、免权限。

| 参数 | 说明 |
|---|---|
| `host` | 目标 |
| `ports` | 预置集 `web`/`remote`/`db`/`mail`/`common`,或 `80,443`,或 `8000-8100` |
| `timeout` / `concurrency` | 单端口超时 / 并发数 |

| 字段 | 含义 |
|---|---|
| `open` / `closed` / `filtered` | 开放 / 收到 RST / 超时(防火墙) |
| `scanned_count` | 扫描端口数 |

> `filtered` 强烈提示防火墙/安全组;`closed` 表示主机可达但无服务监听。

---

## `tls_inspect` — 证书与 TLS 检查

| 参数 | 说明 |
|---|---|
| `host` | 域名(IP 会致域名不匹配) |
| `port` | TLS 端口(默认 443) |

| 字段 | 含义 |
|---|---|
| `valid_from` / `valid_to` | 证书生效 / 到期 |
| `days_left` | 剩余天数(<0 已过期) |
| `subject_cn` / `san` / `issuer_cn` | 主体 CN / SAN / 签发者 |
| `hostname_matches` | 域名是否匹配证书 |
| `verify_error` | 校验失败原因(过期/不匹配/自签名…) |
| `tls_version` / `cipher` | 协商的版本与加密套件 |

---

## `http_probe` — HTTP 探测

| 参数 | 说明 |
|---|---|
| `url` | 完整 URL(无协议默认补 http) |
| `method` | `GET`(默认) / `HEAD` |
| `timeout` / `follow_redirects` | 超时 / 是否跟随重定向 |

| 字段 | 含义 |
|---|---|
| `status_code` | HTTP 状态码(5xx→应用侧) |
| `latency_ms` | 响应延迟 |
| `final_url` / `redirects` | 终点 URL / 重定向链 |
| `server` / `content_type` / `body_bytes` | 响应头与大小 |

---

## `kb_search` — 知识库检索(RAG)

检索本地故障知识库(`docs/knowledge/*.md`),返回最相关的条目。检索为**纯词法 BM25**(中文双字词 + ASCII 词),免 embedding、免费用、离线可跑。

| 参数 | 说明 |
|---|---|
| `query` | 故障特征描述,如 `HTTPS 证书过期` |
| `k` | 返回条数(默认 4) |

| 字段 | 含义 |
|---|---|
| `results` | `[{title, source, text, score}]` |
| `count` | 命中条数 |

除了工具形式,编排器在每次排查开始时还会**自动**把 top-2 相关条目注入 System Prompt(`orchestrator._kb_context`),即使 Agent 没有显式调用工具也能受益。知识库内容见 [`docs/knowledge/`](knowledge/)。

> 想换 embedding 检索?`core/kb.py` 的 `Retriever` 是个 Protocol,实现一个向量版替换 `LexicalRetriever` 单例即可,调用方无需改动。

---

## 扩展新工具

1. 在 `netpilot/tools/` 继承 `Tool`,实现 `name`/`description`/`parameters`/`async run()`,返回带 `summary_zh` 的 `ToolResult`。
2. 在 `netpilot/tools/__init__.py` 的 `_REGISTRY` 注册实例。

LLM 的 tools schema 与调度会自动包含它。
