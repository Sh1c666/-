// API client: REST helpers + a streaming reader for the SSE diagnose endpoint.
//
// EventSource only does GET, but /api/diagnose is POST. We read the SSE stream
// manually from a fetch Response body and yield one parsed JSON event at a time.

import type { AgentEvent, Profile, SettingsView, ToolMeta } from "./types";

async function* parseSSE(resp: Response): AsyncGenerator<AgentEvent> {
  if (!resp.ok || !resp.body) {
    throw new Error(`诊断请求失败 (HTTP ${resp.status})`);
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line.
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const data = frame
        .split("\n")
        .filter((l) => l.startsWith("data:"))
        .map((l) => l.slice(5).replace(/^ /, ""))
        .join("\n");
      if (!data) continue;
      try {
        yield JSON.parse(data) as AgentEvent;
      } catch {
        // ignore malformed frames (e.g. keep-alive comments)
      }
    }
  }
}

export async function* streamDiagnose(
  symptom: string,
  context: Record<string, unknown>
): AsyncGenerator<AgentEvent> {
  const resp = await fetch("/api/diagnose", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ symptom, context }),
  });
  yield* parseSSE(resp);
}

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} → HTTP ${r.status}`);
  return (await r.json()) as T;
}

export const fetchHealth = () => getJson<{ status: string; version: string; has_api_key: boolean; model: string }>("/api/health");
export const fetchTools = () => getJson<{ tools: ToolMeta[] }>("/api/tools").then((r) => r.tools);
export const fetchSettings = () => getJson<SettingsView>("/api/settings");
export const fetchProfiles = () => getJson<{ profiles: Profile[] }>("/api/profiles").then((r) => r.profiles);

export async function saveSettings(payload: {
  llm?: Record<string, unknown>;
  privacy?: Record<string, unknown>;
}): Promise<SettingsView> {
  const r = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`保存设置失败 (HTTP ${r.status})`);
  return (await r.json()) as SettingsView;
}

export async function createProfile(body: Partial<Profile>): Promise<Profile> {
  const r = await fetch("/api/profiles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`创建失败 (HTTP ${r.status})`);
  return (await r.json()) as Profile;
}

export async function deleteProfile(id: string): Promise<void> {
  const r = await fetch(`/api/profiles/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`删除失败 (HTTP ${r.status})`);
}

export async function runTool(name: string, arguments_: Record<string, unknown>): Promise<import("./types").ToolRunResult> {
  const r = await fetch("/api/tools/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, arguments: arguments_ }),
  });
  if (!r.ok) throw new Error(`工具执行失败 (HTTP ${r.status})`);
  return (await r.json()) as import("./types").ToolRunResult;
}
