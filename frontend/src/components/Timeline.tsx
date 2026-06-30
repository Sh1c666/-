import { useMemo } from "react";
import type { AgentEvent, Severity } from "../types";
import ToolCard from "./ToolCard";
import FinalReport from "./FinalReport";

interface Props {
  events: AgentEvent[];
  running: boolean;
  done?: Extract<AgentEvent, { type: "done" }>;
}

type Entry =
  | { kind: "msg"; text: string }
  | {
      kind: "tool";
      id: string;
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
  | { kind: "final"; ev: Extract<AgentEvent, { type: "final" }> }
  | { kind: "error"; message: string };

/** One diagnostic step, surfaced into the exported report. */
export interface TrailStep {
  name: string;
  summary_zh: string;
  severity: Severity;
  duration_ms: number;
}

export default function Timeline({ events, running, done }: Props) {
  const entries = useMemo(() => {
    const out: Entry[] = [];
    const toolIndex = new Map<string, number>();
    for (const ev of events) {
      if (ev.type === "message") {
        out.push({ kind: "msg", text: ev.text });
      } else if (ev.type === "tool_call") {
        const entry: Entry = { kind: "tool", id: ev.id, name: ev.name, args: ev.arguments };
        toolIndex.set(ev.id, out.length);
        out.push(entry);
      } else if (ev.type === "tool_result") {
        const idx = toolIndex.get(ev.id);
        if (idx !== undefined && out[idx].kind === "tool") {
          (out[idx] as Extract<Entry, { kind: "tool" }>).result = {
            severity: ev.severity,
            ok: ev.ok,
            summary_zh: ev.summary_zh,
            data: ev.data,
            duration_ms: ev.duration_ms,
            error: ev.error,
          };
        }
      } else if (ev.type === "final") {
        out.push({ kind: "final", ev });
      } else if (ev.type === "error") {
        out.push({ kind: "error", message: ev.message });
      }
    }
    return out;
  }, [events]);

  // Feed the export: original symptom + the ordered diagnostic trail.
  const symptom = useMemo(
    () => (events.find((e) => e.type === "meta") as Extract<AgentEvent, { type: "meta" }> | undefined)?.symptom ?? "",
    [events]
  );
  const trail = useMemo<TrailStep[]>(
    () =>
      entries
        .filter((e): e is Extract<Entry, { kind: "tool" }> => e.kind === "tool" && !!e.result)
        .map((e) => ({
          name: e.name,
          summary_zh: e.result!.summary_zh,
          severity: e.result!.severity,
          duration_ms: e.result!.duration_ms,
        })),
    [entries]
  );

  const empty = entries.length === 0 && !running;

  if (empty) {
    return (
      <div className="timeline-wrap">
        <div className="timeline-empty">
          <div className="empty-panel">
            <span className="eyebrow">准备开始</span>
            <h3>输入一个需要排查的问题</h3>
            <p className="empty-hint">支持域名打不开、证书异常、接口延迟波动、端口不可达等常见场景。</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="timeline-wrap">
      <div className="timeline">
        {entries.map((e, i) => {
          if (e.kind === "msg") {
            return (
              <div className="entry enter" key={i}>
                <div className="msg thought">
                  <div className="msg-role">过程记录</div>
                  <div className="msg-body">{e.text}</div>
                </div>
              </div>
            );
          }
          if (e.kind === "tool") {
            return (
              <div className="entry enter" key={i}>
                <ToolCard name={e.name} args={e.args} result={e.result} />
              </div>
            );
          }
          if (e.kind === "final") {
            return (
              <div className="entry enter" key={i}>
                <FinalReport ev={e.ev} symptom={symptom} trail={trail} />
              </div>
            );
          }
          return (
            <div className="entry enter" key={i}>
              <div className="error-banner">⚠ {e.message}</div>
            </div>
          );
        })}

        {running && (
          <div className="entry">
            <div className="thinking">
              <span /> <span /> <span /> 正在分析…
            </div>
          </div>
        )}

        {done && (
          <div className="run-foot">
            排查完成 · {done.steps} 次工具调用 · 耗时 {(done.total_ms / 1000).toFixed(1)}s
          </div>
        )}
      </div>
    </div>
  );
}
