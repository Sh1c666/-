import { useState } from "react";
import type { Profile, ToolMeta } from "../types";

interface Props {
  profiles: Profile[];
  tools: ToolMeta[];
  model?: string;
  masked: boolean;
  onOpenSettings: () => void;
  onPickProfile: (p: Profile) => void;
  onNewProfile: (name: string, target: string) => Promise<Profile>;
  onDeleteProfile: (id: string) => void;
  onRunTool: (t: ToolMeta) => void;
}

export default function Sidebar({
  profiles,
  tools,
  model,
  masked,
  onOpenSettings,
  onPickProfile,
  onNewProfile,
  onDeleteProfile,
  onRunTool,
}: Props) {
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [target, setTarget] = useState("");

  const submit = async () => {
    if (!name.trim() || !target.trim()) return;
    await onNewProfile(name.trim(), target.trim());
    setName("");
    setTarget("");
    setAdding(false);
  };

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-logo" />
        <div>
          <div className="brand-title">NetPilot</div>
          <div className="brand-sub">网络诊断工作台</div>
        </div>
      </div>

      <div className="side-section">
        <div className="side-label">常用目标 (Profile)</div>
        {profiles.map((p) => (
          <div key={p.id} className="profile-row">
            <button className="profile-item profile-item-fill" onClick={() => onPickProfile(p)}>
              <span className="pn">{p.name}</span>
              <span className="pt">{p.target}</span>
            </button>
            <button
              className="profile-del"
              title="删除"
              onClick={() => onDeleteProfile(p.id)}
            >
              ×
            </button>
          </div>
        ))}
        {adding ? (
          <div className="profile-form">
            <input
              className="input-shell input-compact"
              placeholder="名称"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <input
              className="input-shell input-compact"
              placeholder="host:port / url"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
            />
            <div className="profile-form-actions">
              <button className="btn-ghost btn-compact" onClick={submit}>
                保存
              </button>
              <button className="btn-ghost btn-compact" onClick={() => setAdding(false)}>
                取消
              </button>
            </div>
          </div>
        ) : (
          <button className="side-link" onClick={() => setAdding(true)}>
            <span className="dot" /> 新增目标
          </button>
        )}
      </div>

      <div className="side-section">
        <div className="side-label">诊断工具</div>
        {tools.map((t) => (
          <button
            key={t.name}
            className="side-link"
            title={t.description}
            onClick={() => onRunTool(t)}
          >
            <span className="dot" style={{ background: "var(--info)" }} />
            <span className="mono-text">{t.name}</span>
          </button>
        ))}
      </div>

      <div className="sidebar-foot">
        <div>模型: {model ?? "—"}</div>
        <div>隐私脱敏: {masked ? "已开启" : "关闭"}</div>
        <button className="btn-ghost btn-full sidebar-settings" onClick={onOpenSettings}>
          打开设置
        </button>
      </div>
    </aside>
  );
}
