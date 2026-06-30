// Wire types — mirror backend/netpilot/agent/events.py + api/schemas.py.

export type Severity = "ok" | "warn" | "fail" | "info";

export type AgentEvent =
  | { type: "meta"; session_id: string; symptom: string; context: Record<string, unknown>; masked: boolean }
  | { type: "message"; role: string; text: string }
  | { type: "tool_call"; id: string; name: string; arguments: Record<string, unknown> }
  | {
      type: "tool_result";
      id: string;
      tool: string;
      severity: Severity;
      ok: boolean;
      summary_zh: string;
      data: Record<string, unknown>;
      duration_ms: number;
      error: string | null;
    }
  | {
      type: "final";
      is_network_issue: boolean | null;
      layer: string;
      root_cause: string;
      evidence: string[];
      recommendation: string;
      confidence: "high" | "medium" | "low" | null;
      text: string;
    }
  | { type: "error"; message: string }
  | { type: "done"; session_id: string; steps: number; total_ms: number };

export interface Profile {
  id: string;
  name: string;
  target: string;
  kind: string;
  notes: string;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface ToolMeta {
  name: string;
  description: string;
  parameters?: Record<string, unknown>;
}

export interface ToolRunResult {
  tool: string;
  severity: Severity;
  ok: boolean;
  summary_zh: string;
  data: Record<string, unknown>;
  duration_ms: number;
  error: string | null;
}

export interface SettingsView {
  llm: {
    base_url: string;
    model: string;
    temperature: number;
    max_tokens: number;
    max_steps: number;
    has_api_key: boolean;
    api_key_preview: string;
  };
  privacy: { mask_internal_ips: boolean };
}
