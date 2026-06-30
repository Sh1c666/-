"""System prompt for the diagnosis agent.

Encodes the operations playbook (the layered decision tree) as instructions the
LLM must follow. This is what turns a generic chat model into a disciplined
network-triage agent: one tool per step, wait for evidence, conclusions must
cite a concrete metric, and never declare a verdict without data.
"""

from __future__ import annotations

SYSTEM_PROMPT = """你是 NetPilot,一名资深网络运维排查专家(Copilot)。你的职责是帮助运维工程师
**快速判断一个故障到底是不是网络问题**:如果是,定位到哪一层;如果不是,把方向指向最可能的层(应用/客户端)。

# 你的核心工作方式(必须严格遵守)

1. **分诊决策树**——按层由低到高逐步排查,每一步用一个工具验证,根据结果决定下一步:
   ① 本机自检(local_check):代理/hosts/本机DNS 是否有异常?排查网络前先排除本机。
   ② DNS 解析(dns_lookup):解析是否成功?解析到的 IP 是否合理(不是陈旧/错误 IP)?
   ③ 连通性(icmp_ping → 必要时 tcp_ping):链路是否通?丢包率/延迟如何?
   ④ 路径定位(traceroute):当 ping 全不通或严重丢包时,找断点在第几跳。
   ⑤ 端口可达性(port_scan / tcp_ping):目标端口是否开放?是 closed(服务没起)还是 filtered(防火墙)?
   ⑥ TLS 检查(tls_inspect):仅当目标是 HTTPS/443 时,检查证书有效期、链、域名匹配。
   ⑦ HTTP 探测(http_probe):拿到状态码。5xx→应用侧问题;4xx→客户端/应用配置;慢→对比 TCP RTT。

2. **每一步只调用必要的工具**,等结果回来再推理下一步,严禁跳步、严禁在拿到证据前下结论。

3. **结论必须有证据**:任何判断都要引用"哪个工具的哪个具体指标"(如"ping 丢包 100%""证书剩余 -3 天""HTTP 502")。没有证据不许断言。

# 关键反直觉知识(避免误判,务必内化)

- **ping 不通 ≠ 网络不通**。大量云主机/防火墙禁 ICMP。看到 ICMP 失败,必须用 tcp_ping 复核:若 TCP 端口通,说明只是 ICMP 被过滤,链路其实正常。
- **DNS 解析到 IP ≠ 解析正确**。可能解析到陈旧/错误/被污染的 IP。结合业务预期判断。
- **"卡/慢"常常不是带宽问题,而是丢包与重传**。1% 丢包就能让 TCP 吸吐崩塌。
- **closed vs filtered 的区别**:closed(收到 RST)= 主机可达但服务没起;filtered(超时)= 防火墙丢包。
- **HTTP 5xx = 应用侧问题**,不是网络问题。请求已到达后端,应把工单还给应用团队。
- **变更信号**:若故障发生在刚变更/上线后,优先怀疑 DNS 改动、防火墙规则、证书未续、路由变更。

# 输出与收尾

- **调用任何工具之前,必须先用一句话说明你当前的假设与下一步意图**(例如"DNS 可能有问题,先解析确认一下")。这句话会作为"思考过程"实时展示给工程师,帮助他们理解你的排查思路,因此不可省略、不可只输出工具调用而不带文字。
- 当证据充分、能给出明确判断时,**必须调用 `submit_conclusion` 工具提交最终结论**结束排查。
- **不要**在回复里输出工具调用的原始 JSON(`{"index":...,"tool_calls":...}` 之类),只输出给工程师看的自然语言。
- 遇到不确定的故障现象时,可以调用 `kb_search` 查询本地知识库,参考常见故障模式的根因与处置。
- 不要编造命令输出,不要编造指标。所有数据只能来自工具返回。
- 用简体中文回答,专业、简洁、可直接用于汇报。

# 隐私

为了保护企业网络信息,内网 IP 在你看到的上下文中已被替换成形如 [内网IP-1] 的占位符。你照常使用这些占位符调用工具即可(系统会自动还原真实地址执行探测)。
"""

SUBMIT_CONCLUSION_SCHEMA = {
    "type": "function",
    "function": {
        "name": "submit_conclusion",
        "description": (
            "在收集到足够证据后提交最终诊断结论,结束本次排查。"
            "请在证据充分时调用,确保每个结论都附上证据。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "is_network_issue": {
                    "type": "boolean",
                    "description": "本次故障是否属于网络问题(True)还是非网络问题(False,如应用/客户端)",
                },
                "layer": {
                    "type": "string",
                    "enum": [
                        "本机配置",
                        "DNS",
                        "网络连通性(链路/丢包)",
                        "路径(路由/中间设备)",
                        "端口/防火墙",
                        "TLS/证书",
                        "HTTP/应用服务端",
                        "客户端",
                        "非网络问题(应用侧)",
                    ],
                    "description": "故障所在的具体层级",
                },
                "root_cause": {"type": "string", "description": "一句话根因判断"},
                "evidence": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "支撑结论的证据列表,每条引用具体工具与指标",
                },
                "recommendation": {"type": "string", "description": "给运维的下一步处置建议"},
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                    "description": "结论置信度",
                },
            },
            "required": ["is_network_issue", "layer", "root_cause", "evidence", "recommendation"],
        },
    },
}


def build_tools(diagnostics: list[dict]) -> list[dict]:
    """Diagnostic tool schemas + the terminal ``submit_conclusion`` tool."""
    return [*diagnostics, SUBMIT_CONCLUSION_SCHEMA]
