import React, { useEffect, useState } from "react";

interface SeedanceSchema {
  resolutions?: string[];
  durations?: string[];
  audio?: string[];
  modes?: string[];
  supports_audio?: boolean;
  default_audio?: string;
  ratio_default?: string;
  supports?: Record<string, boolean>;
}

interface Option {
  value: string;
  label: string;
}

interface Props {
  config: Record<string, any>;
  mode: string;
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

const MODE_TO_SHORT: Record<string, string> = {
  txt2video: "t2v",
  img2video: "i2v",
  flf2video: "flf",
  autovideo: "v2v",
};

const RATIO_OPTIONS: Option[] = [
  { value: "16:9", label: "16:9" },
  { value: "9:16", label: "9:16" },
  { value: "1:1", label: "1:1" },
  { value: "4:3", label: "4:3" },
  { value: "3:4", label: "3:4" },
  { value: "21:9", label: "21:9" },
  { value: "adaptive", label: "自适应(按首帧)" },
];

// 当后端 schema 未返回 supports 能力矩阵时，按模型家族做前端兜底显隐
const SEEDANCE_FAMILY_CAPS: Record<string, Record<string, boolean>> = {
  "doubao-seedance-2-5": {
    seed: true,
    camera_fixed: true,
    return_last_frame: true,
    draft: true,
    tools_web_search: true,
    priority: true,
    output_format_mov: true,
    service_tier_flex: false,
  },
  "doubao-seedance-2-0": {
    seed: true,
    camera_fixed: false,
    return_last_frame: true,
    draft: true,
    tools_web_search: true,
    priority: true,
    output_format_mov: false,
    service_tier_flex: false,
  },
  "doubao-seedance-1-5": {
    seed: true,
    camera_fixed: true,
    return_last_frame: true,
    draft: true,
    tools_web_search: false,
    priority: false,
    output_format_mov: false,
    service_tier_flex: true,
  },
  "doubao-seedance-1-0": {
    seed: true,
    camera_fixed: true,
    return_last_frame: false,
    draft: false,
    tools_web_search: false,
    priority: false,
    output_format_mov: false,
    service_tier_flex: false,
  },
};

function getFamilyCaps(model: string): Record<string, boolean> {
  for (const prefix of Object.keys(SEEDANCE_FAMILY_CAPS).sort((a, b) => b.length - a.length)) {
    if (model.startsWith(prefix)) return SEEDANCE_FAMILY_CAPS[prefix];
  }
  return SEEDANCE_FAMILY_CAPS["doubao-seedance-2-5"];
}

export function SeedanceVideoNode({ config, mode, onChange }: Props) {
  const [models, setModels] = useState<Option[]>([]);
  const [schema, setSchema] = useState<SeedanceSchema | null>(null);
  const [loadingModels, setLoadingModels] = useState(false);
  const [loadingSchema, setLoadingSchema] = useState(false);

  const model = config.model || "";

  // 加载模型列表（按能力 mode 过滤）
  useEffect(() => {
    const short = MODE_TO_SHORT[mode] || mode;
    setLoadingModels(true);
    apiGet(`/api/videogen-interfaces/sdk/backend.videogen.sdk.seedance_wrapper/models-for-node?mode=${encodeURIComponent(short)}`)
      .then((d) => {
        const arr = Array.isArray(d) ? d : d?.models || [];
        setModels(arr.map((m: any) => (typeof m === "string" ? { value: m, label: m } : { value: m.id || m.name, label: m.name || m.id })));
      })
      .catch(() => setModels([]))
      .finally(() => setLoadingModels(false));
  }, [mode]);

  // 模型变化 → 重新加载该模型的能力 schema
  useEffect(() => {
    if (!model) {
      setSchema(null);
      return;
    }
    setLoadingSchema(true);
    apiGet(`/api/videogen-interfaces/sdk/backend.videogen.sdk.seedance_wrapper/schema?model=${encodeURIComponent(model)}&mode=${encodeURIComponent(mode)}`)
      .then((d) => setSchema(d || {}))
      .catch(() => setSchema(null))
      .finally(() => setLoadingSchema(false));
  }, [model, mode]);

  // schema 加载后，若当前值不在可选项内则回落到默认值
  useEffect(() => {
    if (!schema) return;
    const res = schema.resolutions || [];
    if (res.length && !res.includes(config.resolution)) {
      onChange("resolution", res[0]);
    }
    const durs = schema.durations || [];
    if (durs.length && !durs.includes(String(config.duration))) {
      onChange("duration", Number(durs[0]));
    }
    if (schema.supports_audio && !config.audio && schema.default_audio) {
      onChange("audio", schema.default_audio);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [schema]);

  const familyCaps = getFamilyCaps(model);
  const schemaCaps = schema?.supports || {};
  const hasSchemaCaps = Object.values(schemaCaps).some(Boolean);
  // 后端 schema 有有效能力矩阵时优先使用；否则按模型家族兜底显隐
  const caps = hasSchemaCaps ? { ...familyCaps, ...schemaCaps } : familyCaps;
  const resolutions = schema?.resolutions || ["720P"];
  const durations = schema?.durations || ["5"];

  return (
    <div className="space-y-2">
      {/* 模型 */}
      <div>
        <label className={labelCls}>模型</label>
        <select
          className={fieldCls}
          value={model}
          disabled={loadingModels}
          onChange={(e) => onChange("model", e.target.value)}
        >
          <option value="">{loadingModels ? "加载中…" : "请选择模型…"}</option>
          {models.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      {loadingSchema && <div className="text-[11px] text-muted-foreground">正在加载模型参数…</div>}

      {schema && (
        <div className="space-y-2">
          {/* 第一行：分辨率 / 时长 */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={labelCls}>分辨率</label>
              <select className={fieldCls} value={config.resolution || ""} onChange={(e) => onChange("resolution", e.target.value)}>
                {resolutions.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls}>时长(秒)</label>
              <select className={fieldCls} value={String(config.duration || "")} onChange={(e) => onChange("duration", Number(e.target.value))}>
                {durations.map((d) => (
                  <option key={d} value={d}>{d === "-1" ? "智能" : d}</option>
                ))}
              </select>
            </div>
          </div>

          {/* 第二行：生成数量 / 声音（如果支持） */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={labelCls}>生成数量</label>
              <input
                type="number" min={1} max={10} className={fieldCls}
                value={Number(config.num_videos || 1)}
                onChange={(e) => onChange("num_videos", Number(e.target.value))}
              />
            </div>
            {schema.supports_audio && (
              <div>
                <label className={labelCls}>声音</label>
                <select className={fieldCls} value={config.audio || "on"} onChange={(e) => onChange("audio", e.target.value)}>
                  {(schema.audio && schema.audio.length ? schema.audio : ["on", "off", "keep_original", "model_default"]).map((a) => (
                    <option key={a} value={a}>{a}</option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {/* 第三行：宽高比 / 输出格式 */}
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={labelCls}>宽高比</label>
              <select className={fieldCls} value={config.ratio || schema.ratio_default || "16:9"} onChange={(e) => onChange("ratio", e.target.value)}>
                {RATIO_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
            <div>
              <label className={labelCls}>输出格式</label>
              <select className={fieldCls} value={config.output_format || "mp4"} onChange={(e) => onChange("output_format", e.target.value)}>
                <option value="mp4">MP4</option>
                {caps.output_format_mov && <option value="mov">MOV</option>}
              </select>
            </div>
          </div>

          {/* 开关行：两列紧凑排列 */}
          <div className="grid grid-cols-2 gap-x-2 gap-y-1">
            <label className={checkboxCls}>
              <input type="checkbox" checked={Boolean(config.watermark)} onChange={(e) => onChange("watermark", e.target.checked)} />
              添加水印
            </label>
            {caps.camera_fixed && (
              <label className={checkboxCls}>
                <input type="checkbox" checked={Boolean(config.camera_fixed)} onChange={(e) => onChange("camera_fixed", e.target.checked)} />
                固定摄像头
              </label>
            )}
            {caps.return_last_frame && (
              <label className={checkboxCls}>
                <input type="checkbox" checked={Boolean(config.return_last_frame)} onChange={(e) => onChange("return_last_frame", e.target.checked)} />
                返回尾帧
              </label>
            )}
            {caps.draft && (
              <label className={checkboxCls}>
                <input type="checkbox" checked={Boolean(config.draft)} onChange={(e) => onChange("draft", e.target.checked)} />
                样片模式
              </label>
            )}
            {caps.tools_web_search && (
              <label className={checkboxCls}>
                <input type="checkbox" checked={Boolean(config.web_search)} onChange={(e) => onChange("web_search", e.target.checked)} />
                联网搜索
              </label>
            )}
          </div>

          {/* 专有数字/下拉参数 */}
          <div className="grid grid-cols-2 gap-2">
            {caps.seed && (
              <div>
                <label className={labelCls}>随机种子</label>
                <input
                  type="number" className={fieldCls} placeholder="可选"
                  value={config.seed === undefined || config.seed === null ? "" : Number(config.seed)}
                  onChange={(e) => onChange("seed", e.target.value === "" ? "" : Number(e.target.value))}
                />
              </div>
            )}
            <div>
              <label className={labelCls}>服务等级</label>
              <select className={fieldCls} value={config.service_tier || "default"} onChange={(e) => onChange("service_tier", e.target.value)}>
                <option value="default">默认</option>
                {caps.service_tier_flex && <option value="flex">Flex 离线</option>}
              </select>
            </div>
            {caps.priority && (
              <div>
                <label className={labelCls}>优先级</label>
                <input
                  type="number" min={0} max={9} className={fieldCls} placeholder="0~9"
                  value={config.priority === undefined || config.priority === null ? "" : Number(config.priority)}
                  onChange={(e) => onChange("priority", e.target.value === "" ? "" : Number(e.target.value))}
                />
              </div>
            )}
            <div>
              <label className={labelCls}>轮询超时(秒)</label>
              <input
                type="number" min={60} step={60} className={fieldCls}
                value={Number(config.poll_timeout || 1800)}
                onChange={(e) => onChange("poll_timeout", Number(e.target.value))}
              />
            </div>
          </div>

          {!schema.supports_audio && (
            <p className="text-[10px] text-muted-foreground/70">该模型不支持声音。</p>
          )}

          {/* 即梦专属选项 */}
          <div className="grid grid-cols-2 gap-x-2 gap-y-1 pt-1 border-t border-border/40">
            <label className={checkboxCls}>
              <input type="checkbox" checked={Boolean(config.prefer_history)} onChange={(e) => onChange("prefer_history", e.target.checked)} />
              优先历史记录
            </label>
            <label className={checkboxCls}>
              <input type="checkbox" checked={Boolean(config.custom_prompt_enabled)} onChange={(e) => onChange("custom_prompt_enabled", e.target.checked)} />
              自定义提示词
            </label>
            <label className={checkboxCls}>
              <input type="checkbox" checked={Boolean(config.extract_last_frame)} onChange={(e) => onChange("extract_last_frame", e.target.checked)} />
              输出尾帧(ffmpeg)
            </label>
          </div>
          {config.custom_prompt_enabled && (
            <div>
              <label className={labelCls}>自定义提示词</label>
              <textarea
                className={fieldCls + " min-h-[44px] resize-y"}
                placeholder="输入视频生成提示词"
                value={config.custom_prompt || ""}
                onChange={(e) => onChange("custom_prompt", e.target.value)}
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
