import type { Severity } from "../types";

interface Props {
  name: string;
  args: Record<string, unknown>;
  result?: {
    severity: Severity;
    ok: boolean;
    summary_zh: string;
    data: Record<string, unknown>;
    duration_ms: number;
    error: string | null;
  };
}

const num = (v: unknown): number => Number(v) || 0;
const str = (v: unknown): string => (v == null ? "-" : String(v));

function Metric({ k, v, tone }: { k: string; v: string | number; tone?: string }) {
  return (
    <div className="metric">
      <span className="k">{k}</span>
      <span className="v" style={tone ? { color: tone } : undefined}>
        {v}
      </span>
    </div>
  );
}

function renderMetrics(name: string, d: Record<string, unknown>) {
  switch (name) {
    case "dns_lookup":
      return (
        <div className="metrics">
          <Metric k="状态" v={str(d.status)} tone={d.status === "OK" ? "var(--ok)" : "var(--fail)"} />
          <Metric k="TTL" v={`${str(d.ttl)}s`} />
          {Array.isArray(d.resolved_ips) && d.resolved_ips.length > 0 && (
            <Metric k="解析IP" v={(d.resolved_ips as string[]).join(", ")} />
          )}
        </div>
      );
    case "icmp_ping":
      return (
        <div className="metrics">
          <Metric k="丢包" v={`${num(d.loss_pct)}%`} tone={num(d.loss_pct) > 0 ? "var(--warn)" : "var(--ok)"} />
          <Metric k="收/发" v={`${num(d.received)}/${num(d.sent)}`} />
          {d.rtt_avg_ms != null && <Metric k="平均RTT" v={`${Math.round(num(d.rtt_avg_ms))}ms`} />}
          {Boolean(d.unreachable) && <Metric k="主机不可达" v="是" tone="var(--fail)" />}
        </div>
      );
    case "tcp_ping":
      return (
        <div className="metrics">
          <Metric k="可达" v={d.reachable ? "是" : "否"} tone={d.reachable ? "var(--ok)" : "var(--fail)"} />
          <Metric k="端口" v={num(d.port)} />
          {d.rtt_ms != null && <Metric k="握手RTT" v={`${Math.round(num(d.rtt_ms))}ms`} />}
        </div>
      );
    case "port_scan":
      return (
        <div>
          <div className="metrics">
            <Metric k="扫描" v={`${num(d.scanned_count)} 个`} />
            <Metric k="开放" v={(d.open as unknown[] | undefined)?.length ?? 0} tone="var(--ok)" />
            <Metric k="closed" v={(d.closed as unknown[] | undefined)?.length ?? 0} />
            <Metric k="filtered" v={(d.filtered as unknown[] | undefined)?.length ?? 0} tone="var(--warn)" />
          </div>
          {Array.isArray(d.open) && (d.open as number[]).length > 0 && (
            <div className="port-chips">
              {(d.open as number[]).map((p) => (
                <span key={p} className="port-chip open">
                  {p}
                </span>
              ))}
            </div>
          )}
        </div>
      );
    case "tls_inspect":
      return (
        <div className="metrics">
          <Metric
            k="剩余"
            v={`${num(d.days_left)} 天`}
            tone={num(d.days_left) < 0 ? "var(--fail)" : num(d.days_left) <= 30 ? "var(--warn)" : "var(--ok)"}
          />
          <Metric k="到期" v={str(d.valid_to).slice(0, 10)} />
          <Metric k="域名匹配" v={d.hostname_matches ? "是" : "否"} tone={d.hostname_matches ? "var(--ok)" : "var(--fail)"} />
          {Boolean(d.tls_version) && <Metric k="TLS" v={str(d.tls_version)} />}
        </div>
      );
    case "http_probe":
      return (
        <div className="metrics">
          <Metric
            k="状态码"
            v={num(d.status_code)}
            tone={num(d.status_code) >= 500 ? "var(--fail)" : num(d.status_code) >= 400 ? "var(--warn)" : "var(--ok)"}
          />
          <Metric k="延迟" v={`${num(d.latency_ms)}ms`} />
          {d.server ? <Metric k="Server" v={str(d.server)} /> : null}
          {Array.isArray(d.redirects) && (d.redirects as string[]).length > 0 && (
            <Metric k="重定向" v={`${(d.redirects as string[]).length} 跳`} />
          )}
        </div>
      );
    case "local_check":
      return (
        <div className="metrics">
          <Metric k="代理" v={d.proxy_active ? "已配置" : "无"} tone={d.proxy_active ? "var(--warn)" : "var(--ok)"} />
          <Metric k="hosts覆盖" v={d.hosts_override_present ? "存在" : "无"} tone={d.hosts_override_present ? "var(--warn)" : "var(--ok)"} />
          {Array.isArray(d.dns_servers) && <Metric k="DNS" v={(d.dns_servers as string[]).join(", ")} />}
        </div>
      );
    case "kb_search":
      return (
        <div>
          <div className="metrics">
            <Metric k="命中" v={`${num(d.count)} 条`} />
          </div>
          {Array.isArray(d.results) && (d.results as any[]).length > 0 && (
            <div className="port-chips" style={{ flexDirection: "column", alignItems: "stretch", gap: 8, marginTop: 10 }}>
              {(d.results as any[]).map((r, i) => (
                <div
                  key={i}
                  className="metric"
                  style={{ display: "block", lineHeight: 1.5 }}
                >
                  <div>
                    <span className="k">相关度</span>
                    <span className="v" style={{ color: "var(--accent)" }}>
                      {num(r.score)}
                    </span>{" "}
                    · <span style={{ color: "var(--text)" }}>{str(r.title)}</span>{" "}
                    <span className="k">({str(r.source)})</span>
                  </div>
                  <div className="k" style={{ marginTop: 2 }}>
                    {str(r.text).slice(0, 140)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      );
    default:
      return null;
  }
}

export default function ToolCard({ name, args, result }: Props) {
  const argPairs = Object.entries(args);
  return (
    <div className="tool">
      <div className="tool-head">
        <div className="tool-icon">::</div>
        <div>
          <div className="tool-name">{name}</div>
          {argPairs.length > 0 && (
            <div className="tool-args">
              {argPairs.map(([k, v]) => (
                <span key={k}>
                  {k}=<span style={{ color: "var(--accent-2)" }}>{str(v)}</span>{" "}
                </span>
              ))}
            </div>
          )}
        </div>
        {result && (
          <>
            <span className={`sev ${result.severity}`}>{result.severity}</span>
            <span className="duration">{Math.round(result.duration_ms)}ms</span>
          </>
        )}
      </div>
      <div className="tool-body">
        {!result ? (
          <div className="thinking">
            <span /> <span /> <span /> 正在执行…
          </div>
        ) : result.ok ? (
          <>
            <div className={`tool-summary ${result.severity}`}>{result.summary_zh}</div>
            {renderMetrics(name, result.data)}
          </>
        ) : (
          <div className="tool-summary fail">执行失败:{result.error}</div>
        )}
      </div>
    </div>
  );
}
