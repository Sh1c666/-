import { useState } from "react";
import type { AgentEvent, Severity } from "../types";

type FinalEvent = Extract<AgentEvent, { type: "final" }>;

interface TrailStep {
  name: string;
  summary_zh: string;
  severity: Severity;
  duration_ms: number;
}

interface Props {
  ev: FinalEvent;
  symptom?: string;
  trail?: TrailStep[];
}

/** Render the run into a paste-anywhere Markdown report (ticket / wiki / PR). */
function buildMarkdown(ev: FinalEvent, symptom: string, trail: TrailStep[]): string {
  const verdict = ev.is_network_issue === null ? "未明确" : ev.is_network_issue ? "网络问题" : "非网络问题";
  const esc = (s: string) => s.replace(/\|/g, "\\|");
  const L: string[] = ["# NetPilot 排查报告", ""];

  L.push("| 项目 | 内容 |");
  L.push("|---|---|");
  if (symptom) L.push(`| 故障现象 | ${esc(symptom)} |`);
  L.push(`| 结论 | ${verdict} |`);
  L.push(`| 故障层级 | ${ev.layer} |`);
  if (ev.confidence) L.push(`| 置信度 | ${ev.confidence} |`);
  L.push("");

  if (ev.root_cause) {
    L.push("## 根因", "", ev.root_cause, "");
  }
  if (ev.evidence.length) {
    L.push("## 证据", "");
    ev.evidence.forEach((e) => L.push(`- ${e}`));
    L.push("");
  }
  if (ev.recommendation) {
    L.push("## 处置建议", "", ev.recommendation, "");
  }
  if (trail.length) {
    L.push(`## 排查过程（共 ${trail.length} 次工具调用）`, "");
    trail.forEach((t, i) => {
      L.push(`${i + 1}. \`${t.name}\` — ${t.summary_zh}（${t.severity}，${t.duration_ms.toFixed(0)}ms）`);
    });
    L.push("");
  }

  L.push("---", "", `_由 NetPilot 生成 · ${new Date().toLocaleString("zh-CN")}_`);
  return L.join("\n");
}

export default function FinalReport({ ev, symptom = "", trail = [] }: Props) {
  const [copied, setCopied] = useState(false);
  const net = ev.is_network_issue;

  const report = [
    `【排查结论】${net === null ? "未明确" : net ? "网络问题" : "非网络问题"}(层级:${ev.layer})`,
    ev.root_cause ? `根因:${ev.root_cause}` : "",
    ev.evidence.length ? "证据:\n" + ev.evidence.map((e) => `  - ${e}`).join("\n") : "",
    ev.recommendation ? `建议:${ev.recommendation}` : "",
    ev.confidence ? `置信度:${ev.confidence}` : "",
  ]
    .filter(Boolean)
    .join("\n");

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(report);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard may be blocked */
    }
  };

  const exportMd = () => {
    const md = buildMarkdown(ev, symptom, trail);
    const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `netpilot-report-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="final">
      <div className="final-verdict">
        <span className={`verdict-flag ${net ? "net" : "notnet"}`}>
          {net === null ? "结论待确认" : net ? "判定为网络问题" : "判定为非网络问题"}
        </span>
        <span className="layer-chip">{ev.layer}</span>
        {ev.confidence && <span className="confidence">置信度 {ev.confidence}</span>}
      </div>

      {ev.root_cause && <p style={{ margin: "8px 0 0" }}>{ev.root_cause}</p>}

      {ev.evidence.length > 0 && (
        <div className="final-section">
          <h4>证据</h4>
          <ul>
            {ev.evidence.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {ev.recommendation && (
        <div className="final-section">
          <h4>处置建议</h4>
          <p style={{ margin: 0, color: "var(--text)" }}>{ev.recommendation}</p>
        </div>
      )}

      {!ev.root_cause && !ev.evidence.length && ev.text && (
        <div className="final-section">
          <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{ev.text}</p>
        </div>
      )}

      <div className="final-actions">
        <button className="btn-ghost" onClick={copy}>
          {copied ? "已复制" : "复制报告"}
        </button>
        <button className="btn-ghost" onClick={exportMd}>
          导出 Markdown
        </button>
      </div>
    </div>
  );
}
