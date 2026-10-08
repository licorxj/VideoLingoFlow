import React, { useEffect, useState, useRef } from "react";

interface VGParams {
  modes?: string[];
  resolutions?: string[];
  durations?: (number | string)[];
  audio?: string[];
  max_ref_images?: number;
  max_ref_videos?: number;
  supports_audio?: boolean;
  default_audio?: string;
  supports_ratio?: boolean;
  ratios?: string[];
  ratio_default?: string;
}

interface Option {
  value: string;
  label: string;
}

interface Props {
  config: Record<string, any>;
  onChange: (key: string, value: any) => void;
}

async function apiGet(url: string): Promise<any> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`请求失败 ${r.status}`);
  return r.json();
}

const fieldCls =
  "w-full rounded-md border border-border bg-background px-2 py-1 text-xs text-foreground focus:outline-none focus:ring-1 focus:ring-primary";
const labelCls = "block text-[11px] text-muted-foreground mb-0.5";
const checkboxCls = "flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-pointer";

// 视频比例可选项：后端未返回 ratios 时用此列表兜底（与「即梦」节点保持一致）
const DEFAULT_RATIOS = ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9"];

// 时长下拉中的「手动输入」哨兵值（不可能与真实秒数冲突）
const MANUAL_DURATION = "__manual__";

export function VideoGenNode({ config, onChange }: Props) {
  const [interfaces, setInterfaces] = useState<Option[]>([]);
  const [models, setModels] = useState<Option[]>([]);
  const [params, setParams] = useState<VGParams | null>(null);
  const [loadingModels, setLoadingModels] = useState(false);
  const [loadingParams, setLoadingParams] = useState(false);

  const ifaceMap = useRef<Record<string, any>>({});
  const iface = config.interface || "";
  const model = config.model || "";

  // 加载已启用接口
  useEffect(() => {
    apiGet("/api/videogen-interfaces/enabled")
      .then((d) => {
        const arr = Array.isArray(d) ? d : d?.interfaces || [];
        const map: Record<string, any> = {};
        arr.forEach((m: any) => { if (m && m.id) map[m.id] = m; });
        ifaceMap.current = map;
        setInterfaces(
          arr.map((m: any) => (typeof m === "string" ? { value: m, label: m } : { value: m.id, label: m.name || m.id }))
        );
      })
      .catch(() => setInterfaces([]));
  }, []);

  // 接口变化 → 重新加载模型
  useEffect(() => {
    if (!iface) {
      setModels([]);
      setParams(null);
      return;
    }
    setLoadingModels(true);
    apiGet(`/api/videogen-interfaces/${encodeURIComponent(iface)}/models`)
      .then((d) => {
        const arr = Array.isArray(d) ? d : d?.models || [];
        setModels(arr.map((m: any) => (typeof m === "string" ? { value: m, label: m } : { value: m.id || m.name, label: m.name || m.id })));
      })
      .catch(() => setModels([]))
      .finally(() => setLoadingModels(false));
  }, [iface]);

  // 模型变化 → 重新加载参数结构（传递完整接口配置，由后端按模型匹配设置项与可选项）
  useEffect(() => {
    if (!iface || !model) {
      setParams(null);
      return;
    }
    const ifaceConfig = ifaceMap.current[iface]?.config;
    if (!ifaceConfig) {
      setParams(null);
      return;
    }
    setLoadingParams(true);
    fetch("/api/videogen-interfaces/schema", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ config: ifaceConfig, model, mode: config.mode || "" }),
    })
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => setParams(d || {}))
      .catch(() => setParams(null))
      .finally(() => setLoadingParams(false));
  }, [iface, model, config.mode]);

  // 模型参数加载后，补齐默认值
  useEffect(() => {
    if (!params) return;
    if (params.resolutions?.length && !params.resolutions.includes(config.resolution)) {
      onChange("resolution", params.resolutions[0]);
    }
    // 时长：非手动模式下，当前值不在模型可选时长内才对齐到首个合法值；
    // 手动模式（duration_manual）保留用户输入，不强制改写
    if (params.durations?.length && !config.duration_manual
        && !params.durations.map(String).includes(String(config.duration))) {
      onChange("duration", params.durations[0]);
    }
    if (!config.sound && params.default_audio) {
      onChange("sound", params.default_audio);
    }
    // 视频比例：未配置时按模型默认值落盘，保证「界面显示」与「实际执行」一致
    if (!config.ratio && params.supports_ratio !== false) {
      const opts = params.ratios?.length ? params.ratios : DEFAULT_RATIOS;
      const def =
        params.ratio_default && opts.includes(params.ratio_default)
          ? params.ratio_default
          : opts[0] || "16:9";
      onChange("ratio", def);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  const onInterfaceChange = (v: string) => {
    onChange("interface", v);
    onChange("model", "");
    setParams(null);
  };

  const resolutions = params?.resolutions || ["720P"];
  const durations = (params?.durations || [5]).map(String);
  const modes = params?.modes || [];
  const supportsAudio = params?.supports_audio ?? false;
  // 时长：下拉首选「手动输入」，选中后改为直接输入秒数（可超出模型预设区间）
  const manualDuration = config.duration_manual === true;
  const durationValue = String(config.duration ?? "");
  // 后端未声明 supports_ratio 时按支持处理（兼容旧后端）；ratios 为空则用通用比例列表
  const supportsRatio = params?.supports_ratio !== false;
  const ratioOptions = params?.ratios?.length ? params.ratios : DEFAULT_RATIOS;
  const ratioDefault =
    params?.ratio_default && ratioOptions.includes(params.ratio_default)
      ? params.ratio_default
      : ratioOptions[0] || "16:9";
  const ratio = config.ratio || ratioDefault;
  // 图生视频场景下画幅通常由首帧图/模型策略决定（Seedance 强制 adaptive）
  const ratioHint =
    config.mode === "img2video" || config.mode === "flf2video"
      ? "图生视频的画幅通常由首帧图决定，部分模型固定为自适应，此项可能不生效。"
      : "";

  return (
    <div className="space-y-2">
      {/* 提示词前缀 */}
      <div>
        <label className={labelCls}>提示词前缀</label>
        <textarea
          className={fieldCls + " min-h-[40px] resize-y"}
          placeholder="可选；执行时拼接到连线输入的提示词之前"
          value={config.prompt_prefix || ""}
          onChange={(e) => onChange("prompt_prefix", e.target.value)}
          onPointerDown={(e) => e.stopPropagation()}
        />
      </div>

      {/* 生成接口 + 模型 两列 */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className={labelCls}>生成接口</label>
          <select
            className={fieldCls}
            value={iface}
            onChange={(e) => onInterfaceChange(e.target.value)}
            onPointerDown={(e) => e.stopPropagation()}
          >
            <option value="">请选择接口…</option>
            {interfaces.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelCls}>模型</label>
          <select
            className={fieldCls}
            value={model}
            disabled={!iface || loadingModels}
            onChange={(e) => onChange("model", e.target.value)}
            onPointerDown={(e) => e.stopPropagation()}
          >
            <option value="">{loadingModels ? "加载中…" : "请选择模型…"}</option>
            {models.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {loadingParams && <div className="text-[11px] text-muted-foreground">正在加载模型参数…</div>}

      {/* 模型支持的参数设置 */}
      {params && (
        <div className="space-y-2 border-t border-border/60 pt-2">
          {/* 生成类型 */}
          {modes.length > 0 && (
            <div>
              <label className={labelCls}>生成类型</label>
              <div className="flex flex-wrap gap-1">
                {modes.map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => onChange("mode", m)}
                    className={
                      "px-2 py-0.5 rounded-md text-[11px] border transition-colors " +
                      (config.mode === m
                        ? "bg-primary text-primary-foreground border-primary"
                        : "bg-background text-muted-foreground border-border hover:border-primary/50")
                    }
                  >
                    {m}
                  </button>
                ))}
              </div>
              <p className="text-[10px] text-muted-foreground/70 mt-0.5">未选择时后端按已连接输入自动推断</p>
            </div>
          )}

          {/* 分辨率 / 时长 / 数量 / 声音 */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={labelCls}>分辨率</label>
              <select className={fieldCls} value={config.resolution || ""} onChange={(e) => onChange("resolution", e.target.value)}>
                {resolutions.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls}>
                时长(秒)
                {manualDuration && <span className="ml-1 text-primary">· 手动</span>}
              </label>
              {manualDuration ? (
                <div className="flex items-center gap-1">
                  <input
                    type="number"
                    min={1}
                    step={1}
                    className={fieldCls}
                    title="手动输入视频时长（秒）"
                    value={durationValue}
                    onChange={(e) => {
                      const n = Math.max(1, Math.floor(Number(e.target.value) || 1));
                      onChange("duration", n);
                    }}
                  />
                  <button
                    type="button"
                    title="改回从预设时长中选择"
                    className="shrink-0 rounded-md border border-border bg-background px-1.5 py-1 text-[11px] text-muted-foreground hover:border-primary/50 hover:text-foreground"
                    onClick={() => {
                      onChange("duration_manual", false);
                      if (!durations.includes(durationValue)) {
                        onChange("duration", Number(durations[0]) || 5);
                      }
                    }}
                  >
                    ▾
                  </button>
                </div>
              ) : (
                <select
                  className={fieldCls}
                  value={durations.includes(durationValue) ? durationValue : MANUAL_DURATION}
                  onChange={(e) => {
                    const v = e.target.value;
                    if (v === MANUAL_DURATION) {
                      // 切到手动输入：沿用当前时长作为起点（不合法则取预设首项）
                      onChange("duration_manual", true);
                      if (!durations.includes(durationValue)) {
                        onChange("duration", Number(durations[0]) || 5);
                      }
                    } else {
                      onChange("duration_manual", false);
                      onChange("duration", Number(v));
                    }
                  }}
                >
                  <option value={MANUAL_DURATION}>手动输入</option>
                  {durations.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              )}
            </div>
            {supportsRatio && (
              <div>
                <label className={labelCls}>视频比例</label>
                <select
                  className={fieldCls}
                  value={ratio}
                  title="视频宽高比，如 16:9 横屏 / 9:16 竖屏"
                  onChange={(e) => onChange("ratio", e.target.value)}
                >
                  {ratioOptions.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div>
              <label className={labelCls}>视频数量</label>
              <input
                type="number"
                min={1}
                max={8}
                className={fieldCls}
                value={Number(config.num_videos || 1)}
                onChange={(e) => onChange("num_videos", Number(e.target.value))}
              />
            </div>
            {supportsAudio && (
              <div>
                <label className={labelCls}>声音</label>
                <select className={fieldCls} value={config.sound || "on"} onChange={(e) => onChange("sound", e.target.value)}>
                  {(params?.audio && params.audio.length ? params.audio : ["on", "off", "keep_original"]).map((a) => (
                    <option key={a} value={a}>
                      {a}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {!supportsAudio && (
            <p className="text-[10px] text-muted-foreground/70">该接口/模型不支持声音。</p>
          )}
          {supportsRatio && ratioHint && (
            <p className="text-[10px] text-muted-foreground/70">{ratioHint}</p>
          )}

          {/* 负向提示词 */}
          <div>
            <label className={labelCls}>负向提示词</label>
            <textarea
              className={fieldCls + " min-h-[36px] resize-y"}
              placeholder="可选"
              value={config.negative_prompt || ""}
              onChange={(e) => onChange("negative_prompt", e.target.value)}
            />
          </div>

          {/* 输出前缀 + 轮询超时 */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={labelCls}>输出命名前缀</label>
              <input
                className={fieldCls}
                placeholder="video"
                value={config.output_prefix || ""}
                onChange={(e) => onChange("output_prefix", e.target.value)}
              />
            </div>
            <div>
              <label className={labelCls}>轮询超时(秒)</label>
              <input
                type="number"
                min={60}
                step={60}
                className={fieldCls}
                value={Number(config.poll_timeout || 1800)}
                onChange={(e) => onChange("poll_timeout", Number(e.target.value))}
              />
            </div>
          </div>
        </div>
      )}

      {/* 通用开关：优化提示词 / 输出尾帧 */}
      <div className="grid grid-cols-2 gap-x-2 gap-y-1">
        <label className={checkboxCls}>
          <input
            type="checkbox"
            checked={Boolean(config.optimize_prompt)}
            onChange={(e) => onChange("optimize_prompt", e.target.checked)}
          />
          优化提示词
        </label>
        <label className={checkboxCls}>
          <input
            type="checkbox"
            checked={Boolean(config.extract_last_frame)}
            onChange={(e) => onChange("extract_last_frame", e.target.checked)}
          />
          输出尾帧(ffmpeg)
        </label>
      </div>
    </div>
  );
}
