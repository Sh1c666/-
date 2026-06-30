import { useMemo, useState } from "react";
import type { ToolMeta, ToolRunResult } from "../types";
import { runTool } from "../api";
import ToolCard from "./ToolCard";

interface Props {
  tool: ToolMeta;
  onClose: () => void;
}

interface PropSchema {
  type?: string;
  description?: string;
  default?: unknown;
  enum?: string[];
}

/** Coerce the raw form strings/booleans into the types the backend expects. */
function coerce(values: Record<string, string | boolean>, props: Record<string, PropSchema>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, schema] of Object.entries(props)) {
    const raw = values[k];
    const isEmpty = raw === undefined || raw === "";
    if (isEmpty) continue; // omit empties; backend applies its own defaults
    switch (schema.type) {
      case "integer":
        out[k] = parseInt(String(raw), 10);
        break;
      case "number":
        out[k] = parseFloat(String(raw));
        break;
      case "boolean":
        out[k] = Boolean(raw);
        break;
      default:
        out[k] = String(raw);
    }
  }
  return out;
}

export default function ToolRunnerModal({ tool, onClose }: Props) {
  const props = useMemo<Record<string, PropSchema>>(() => {
    const p = (tool.parameters as { properties?: Record<string, PropSchema> } | undefined)?.properties;
    return p ?? {};
  }, [tool]);
  const required = useMemo(
    () => ((tool.parameters as { required?: string[] } | undefined)?.required) ?? [],
    [tool]
  );

  const [values, setValues] = useState<Record<string, string | boolean>>(() => {
    const init: Record<string, string | boolean> = {};
    for (const [k, schema] of Object.entries(props)) {
      init[k] =
        schema.type === "boolean"
          ? Boolean(schema.default)
          : schema.default != null
            ? String(schema.default)
            : "";
    }
    return init;
  });
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ToolRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canRun = required.every((k) => {
    const v = values[k];
    return v !== undefined && v !== "";
  });

  const run = async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const args = coerce(values, props);
      setResult(await runTool(tool.name, args));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="tool-icon" style={{ width: 24, height: 24, fontSize: 11 }}>⚙</div>
          <h3 style={{ marginLeft: 8, fontFamily: "var(--mono)" }}>{tool.name}</h3>
          <div className="spacer" style={{ flex: 1 }} />
          <button className="btn-ghost" onClick={onClose} style={{ padding: "6px 10px" }}>
            关闭
          </button>
        </div>
        <div className="modal-body">
          <p style={{ margin: 0, color: "var(--text-muted)", fontSize: 13 }}>{tool.description}</p>

          {Object.keys(props).length === 0 && (
            <div className="hint">该工具无需参数,直接点击执行。</div>
          )}

          {Object.entries(props).map(([k, schema]) => {
            const label = (
              <label style={{ fontSize: 12, color: "var(--text-muted)" }}>
                {k}
                {required.includes(k) && <span style={{ color: "var(--fail)" }}> *</span>}
                {schema.description && <div className="hint">{schema.description}</div>}
              </label>
            );
            const control =
              schema.type === "boolean" ? (
                <input
                  type="checkbox"
                  checked={Boolean(values[k])}
                  onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.checked }))}
                  style={{ accentColor: "var(--accent)" }}
                />
              ) : schema.enum ? (
                <select
                  value={String(values[k] ?? "")}
                  onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))}
                >
                  {schema.enum.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type={schema.type === "integer" || schema.type === "number" ? "number" : "text"}
                  value={String(values[k] ?? "")}
                  placeholder={schema.default != null ? String(schema.default) : ""}
                  onChange={(e) => setValues((v) => ({ ...v, [k]: e.target.value }))}
                />
              );
            return (
              <div key={k} className={schema.type === "boolean" ? "switch" : "field"}>
                {schema.type === "boolean" ? (
                  <>
                    {control}
                    {label}
                  </>
                ) : (
                  <>
                    {label}
                    {control}
                  </>
                )}
              </div>
            );
          })}
        </div>

        <div className="modal-foot">
          <span className="hint" style={{ marginRight: "auto" }}>
            手动执行(不经过 Agent)
          </span>
          <button className="btn-primary" onClick={run} disabled={running || !canRun}>
            {running ? "执行中…" : "执行工具"}
          </button>
        </div>

        {error && (
          <div style={{ padding: "0 18px 12px" }}>
            <div className="error-banner">⚠ {error}</div>
          </div>
        )}
        {result && (
          <div style={{ padding: "0 18px 18px" }}>
            <ToolCard name={tool.name} args={coerce(values, props)} result={result} />
          </div>
        )}
      </div>
    </div>
  );
}
