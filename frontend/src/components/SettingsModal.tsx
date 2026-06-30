import { useState } from "react";
import type { SettingsView } from "../types";

interface Props {
  settings: SettingsView;
  onClose: () => void;
  onSave: (payload: { llm?: Record<string, unknown>; privacy?: Record<string, unknown> }) => void;
}

// Provider presets — NetPilot works with any OpenAI-compatible endpoint.
// Picking one just fills in base_url + model; both stay editable afterwards.
interface Preset {
  key: string;
  label: string;
  base_url: string;
  model: string;
  protocol?: string; // "openai" (default) | "anthropic"
  hint: string;
}

const PROVIDER_PRESETS: Preset[] = [
  { key: "deepseek", label: "DeepSeek", base_url: "https://api.deepseek.com", model: "deepseek-chat", hint: "platform.deepseek.com" },
  { key: "openai", label: "OpenAI", base_url: "https://api.openai.com/v1", model: "gpt-4o-mini", hint: "platform.openai.com" },
  { key: "glm", label: "GLM 智谱 (v4 端点)", base_url: "https://open.bigmodel.cn/api/paas/v4/", model: "glm-4-flash", hint: "免费 flash；高端模型此端点 1113" },
  { key: "glm-claude", label: "GLM 智谱 (Claude 兼容)", base_url: "https://open.bigmodel.cn/api/anthropic", model: "glm-5.2", protocol: "anthropic", hint: "季度套餐走此端点；glm-4.6 / 5.2" },
  { key: "ollama", label: "Ollama (本地)", base_url: "http://localhost:11434/v1", model: "qwen2.5", hint: "零数据外发，key 随便填" },
];

export default function SettingsModal({ settings, onClose, onSave }: Props) {
  const [baseUrl, setBaseUrl] = useState(settings.llm.base_url);
  const [model, setModel] = useState(settings.llm.model);
  const [temperature, setTemperature] = useState(String(settings.llm.temperature));
  const [maxTokens, setMaxTokens] = useState(String(settings.llm.max_tokens));
  const [maxSteps, setMaxSteps] = useState(String(settings.llm.max_steps));
  const [protocol, setProtocol] = useState(settings.llm.protocol || "openai");
  const [apiKey, setApiKey] = useState("");
  const [masked, setMasked] = useState(settings.privacy.mask_internal_ips);
  const [preset, setPreset] = useState("");

  const applyPreset = (key: string) => {
    const p = PROVIDER_PRESETS.find((x) => x.key === key);
    if (p) {
      setBaseUrl(p.base_url);
      setModel(p.model);
      setProtocol(p.protocol ?? "openai");
    }
    setPreset(key);
  };

  const save = () => {
    onSave({
      llm: {
        base_url: baseUrl,
        model,
        protocol,
        temperature: Number(temperature) || 0.2,
        max_tokens: Number(maxTokens) || 2048,
        max_steps: Number(maxSteps) || 12,
        ...(apiKey ? { api_key: apiKey } : {}),
      },
      privacy: { mask_internal_ips: masked },
    });
  };

  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>设置</h3>
        </div>
        <div className="modal-body">
          <div className="field">
            <label>Provider 预设</label>
            <select value={preset} onChange={(e) => applyPreset(e.target.value)}>
              <option value="">— 选择以自动填充下方端点 / 模型 —</option>
              {PROVIDER_PRESETS.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label} · {p.hint}
                </option>
              ))}
            </select>
            <span className="hint">
              NetPilot 兼容任何 OpenAI 兼容端点。选预设只是自动填表，下面两项仍可手改。
            </span>
          </div>

          <div className="field">
            <label>API Key</label>
            <input
              type="password"
              placeholder={settings.llm.has_api_key ? `已保存(${settings.llm.api_key_preview || "••••"})` : "粘贴你的 API Key"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            <span className="hint">
              从所选 provider 的开放平台获取。留空则保持现有 Key 不变。仅保存在本地 data/settings.json。
            </span>
          </div>

          <div className="field">
            <label>API 协议</label>
            <select value={protocol} onChange={(e) => setProtocol(e.target.value)}>
              <option value="openai">OpenAI 兼容 (/chat/completions) — DeepSeek / OpenAI / GLM v4 / Ollama</option>
              <option value="anthropic">Anthropic 兼容 (/v1/messages) — GLM Claude 兼容端点</option>
            </select>
            <span className="hint">
              智谱季度套餐的高端模型（glm-4.6 / 5.2）只在 Anthropic 端点有额度；v4 端点会返回 1113。
            </span>
          </div>

          <div className="row2">
            <div className="field">
              <label>Base URL</label>
              <input value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
            </div>
            <div className="field">
              <label>模型</label>
              <input value={model} onChange={(e) => setModel(e.target.value)} placeholder="deepseek-chat / gpt-4o-mini / glm-4-flash / glm-5.2" />
            </div>
          </div>

          <div className="row2">
            <div className="field">
              <label>Temperature</label>
              <input value={temperature} onChange={(e) => setTemperature(e.target.value)} />
            </div>
            <div className="field">
              <label>Max Tokens</label>
              <input value={maxTokens} onChange={(e) => setMaxTokens(e.target.value)} />
            </div>
          </div>

          <div className="field">
            <label>Agent 最大工具调用次数</label>
            <input value={maxSteps} onChange={(e) => setMaxSteps(e.target.value)} />
            <span className="hint">单次排查的工具调用上限，防止失控循环。</span>
          </div>

          <label className="switch">
            <input type="checkbox" checked={masked} onChange={(e) => setMasked(e.target.checked)} />
            <span>
              <b>隐私脱敏</b>：发送给云端模型前，把内网 IP 替换为 [内网IP-1] 占位符（强烈建议开启）
            </span>
          </label>
        </div>
        <div className="modal-foot">
          <button className="btn-ghost" onClick={onClose}>
            取消
          </button>
          <button className="btn-primary" onClick={save}>
            保存
          </button>
        </div>
      </div>
    </div>
  );
}
