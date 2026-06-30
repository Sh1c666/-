import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Sidebar from "./components/Sidebar";
import Composer from "./components/Composer";
import Timeline from "./components/Timeline";
import SettingsModal from "./components/SettingsModal";
import ToolRunnerModal from "./components/ToolRunnerModal";
import type { AgentEvent, Profile, SettingsView, ToolMeta } from "./types";
import {
  createProfile,
  deleteProfile,
  fetchProfiles,
  fetchSettings,
  fetchTools,
  saveSettings,
  streamDiagnose,
} from "./api";

type ThemeMode = "dark" | "light";

const THEME_KEY = "netpilot-theme";

export default function App() {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [running, setRunning] = useState(false);
  const [symptom, setSymptom] = useState("");
  const [target, setTarget] = useState("");
  const [recentlyChanged, setRecentlyChanged] = useState(false);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [tools, setTools] = useState<ToolMeta[]>([]);
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const [runnerTool, setRunnerTool] = useState<ToolMeta | null>(null);
  const [theme, setTheme] = useState<ThemeMode>(() => {
    const saved = window.localStorage.getItem(THEME_KEY);
    return saved === "light" ? "light" : "dark";
  });
  const abortRef = useRef<AbortController | null>(null);
  const watchdogRef = useRef<number | null>(null);
  const stop = useCallback(() => {
    abortRef.current?.abort();
    if (watchdogRef.current) window.clearTimeout(watchdogRef.current);
    watchdogRef.current = null;
  }, []);

  const refreshProfiles = useCallback(async () => {
    try {
      setProfiles(await fetchProfiles());
    } catch {
      /* ignore — sidebar just stays empty */
    }
  }, []);

  useEffect(() => {
    fetchTools().then(setTools).catch(() => {});
    fetchSettings().then(setSettings).catch(() => {});
    refreshProfiles();
  }, [refreshProfiles]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem(THEME_KEY, theme);
  }, [theme]);

  useEffect(() => () => stop(), [stop]);

  const run = useCallback(
    async (text: string) => {
      if (!text.trim() || running) return;

      if (settings && !settings.llm.has_api_key) {
        setEvents([
          {
            type: "error",
            message:
              "尚未配置 LLM API Key，模型无法调用。请点击右上角「设置」填写 Key（例如 DeepSeek / GLM / OpenAI），或在 backend/.env 设置 NETPILOT_LLM_API_KEY 后重启后端。",
          },
        ]);
        return;
      }

      stop();
      const controller = new AbortController();
      abortRef.current = controller;
      setEvents([]);
      setRunning(true);

      const ctx: Record<string, unknown> = {};
      if (target.trim()) ctx.target = target.trim();
      if (recentlyChanged) ctx.recently_changed = true;

      const armWatchdog = () => {
        if (watchdogRef.current) window.clearTimeout(watchdogRef.current);
        watchdogRef.current = window.setTimeout(() => {
          controller.abort();
        }, 75_000);
      };
      armWatchdog();

      try {
        for await (const ev of streamDiagnose(text, ctx, controller.signal)) {
          armWatchdog();
          setEvents((prev) => [...prev, ev]);
        }
      } catch (e) {
        const aborted = controller.signal.aborted;
        const raw = e instanceof Error ? e.message : String(e);
        const message = aborted
          ? "等待模型响应超时或已被手动停止。请检查模型服务是否可达（Base URL / 网络 / API Key），或稍后重试。"
          : /Failed to fetch|NetworkError|load failed/i.test(raw)
            ? "无法连接到后端服务。请确认后端已启动（默认 http://127.0.0.1:8000），并检查浏览器控制台的网络请求。"
            : raw;
        setEvents((prev) => [...prev, { type: "error", message }]);
      } finally {
        if (watchdogRef.current) window.clearTimeout(watchdogRef.current);
        watchdogRef.current = null;
        abortRef.current = null;
        setRunning(false);
      }
    },
    [running, target, recentlyChanged, settings, stop]
  );

  const meta = useMemo(
    () => events.find((e) => e.type === "meta") as Extract<AgentEvent, { type: "meta" }> | undefined,
    [events]
  );
  const done = events.find((e) => e.type === "done") as Extract<AgentEvent, { type: "done" }> | undefined;

  const onSaveSettings = useCallback(async (payload: Parameters<typeof saveSettings>[0]) => {
    const s = await saveSettings(payload);
    setSettings(s);
    setShowSettings(false);
  }, []);

  return (
    <div className="app">
      <Sidebar
        profiles={profiles}
        tools={tools}
        model={settings?.llm.model}
        masked={settings?.privacy.mask_internal_ips ?? true}
        onOpenSettings={() => setShowSettings(true)}
        onPickProfile={(p) => {
          setTarget(p.target);
          setSymptom((s) => s || `${p.name}(${p.target})异常,请排查是否网络问题`);
        }}
        onNewProfile={async (name, t) => {
          const p = await createProfile({ name, target: t, kind: t.startsWith("http") ? "url" : "host" });
          setProfiles((prev) => [...prev, p]);
          return p;
        }}
        onDeleteProfile={async (id) => {
          await deleteProfile(id);
          setProfiles((prev) => prev.filter((p) => p.id !== id));
        }}
        onRunTool={(t) => setRunnerTool(t)}
      />

      <div className="main">
        <header className="topbar">
          <div className="topbar-copy">
            <span className="eyebrow">网络诊断工作台</span>
            <div className="topbar-heading">
              <h1>NetPilot</h1>
              {meta && <span className="session-chip">会话 {meta.session_id}</span>}
            </div>
          </div>
          <div className="spacer" />
          <div className="topbar-actions">
            <div className="theme-switch" aria-label="主题切换">
              <button
                type="button"
                className={`theme-switch-btn ${theme === "dark" ? "active" : ""}`}
                onClick={() => setTheme("dark")}
              >
                暗调
              </button>
              <button
                type="button"
                className={`theme-switch-btn ${theme === "light" ? "active" : ""}`}
                onClick={() => setTheme("light")}
              >
                白底
              </button>
            </div>
            <button className="icon-btn" onClick={() => setShowSettings(true)}>
              设置
            </button>
          </div>
        </header>

        <Composer
          symptom={symptom}
          setSymptom={setSymptom}
          target={target}
          setTarget={setTarget}
          recentlyChanged={recentlyChanged}
          setRecentlyChanged={setRecentlyChanged}
          running={running}
          onRun={() => run(symptom)}
          onStop={stop}
        />

        <Timeline events={events} running={running} done={done} />
      </div>

      {showSettings && settings && (
        <SettingsModal settings={settings} onClose={() => setShowSettings(false)} onSave={onSaveSettings} />
      )}

      {runnerTool && (
        <ToolRunnerModal tool={runnerTool} onClose={() => setRunnerTool(null)} />
      )}
    </div>
  );
}
