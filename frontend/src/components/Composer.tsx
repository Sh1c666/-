interface Props {
  symptom: string;
  setSymptom: (v: string) => void;
  target: string;
  setTarget: (v: string) => void;
  recentlyChanged: boolean;
  setRecentlyChanged: (v: boolean) => void;
  running: boolean;
  onRun: () => void;
}

export default function Composer({
  symptom,
  setSymptom,
  target,
  setTarget,
  recentlyChanged,
  setRecentlyChanged,
  running,
  onRun,
}: Props) {
  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      onRun();
    }
  };

  return (
    <div className="composer">
      <div className="composer-head">
        <div>
          <span className="eyebrow">输入区</span>
          <h3>描述这次故障现象</h3>
        </div>
        <span className="composer-shortcut">
          <span className="kbd">Ctrl</span>
          <span className="composer-plus">+</span>
          <span className="kbd">Enter</span>
        </span>
      </div>

      <div className="composer-grid">
        <div className="field field-grow">
          <label>故障现象</label>
          <textarea
            placeholder="例如：公司 OA 打不开、pay.example.com 证书报错、接口偶发卡顿"
            value={symptom}
            onChange={(e) => setSymptom(e.target.value)}
            onKeyDown={handleKey}
            disabled={running}
          />
        </div>

        <div className="composer-side">
          <div className="field">
            <label>目标</label>
            <input
              className="input-shell"
              placeholder="host:port / 域名（可选）"
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              disabled={running}
            />
          </div>

          <label className="switch switch-card">
            <span className="switch-copy">
              <strong>近期有变更</strong>
              <span className="hint">用于提醒排查时优先关注上线、配置和策略改动。</span>
            </span>
            <input
              type="checkbox"
              checked={recentlyChanged}
              onChange={(e) => setRecentlyChanged(e.target.checked)}
              disabled={running}
            />
          </label>

          <button className="btn-primary btn-block" onClick={onRun} disabled={running || !symptom.trim()}>
            {running ? "排查中…" : "开始排查"}
          </button>
        </div>
      </div>

      <div className="composer-meta">
        <span className="composer-tip">建议先填目标地址，再输入现象，结论会更聚焦。</span>
      </div>
    </div>
  );
}
