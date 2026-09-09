import { useState, useEffect } from "react";
import { musicgenInterfacesApi, MusicGenInterface, MusicGenInterfaceConfig } from "@/api/musicgenInterfaces";
import { cn } from "@/lib/utils";
import { X, Plus, Trash2, Save, Loader2 } from "lucide-react";
import { SecretField } from "@/components/shared/SecretPicker";

const inputCls = "w-full px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none";
const labelCls = "text-xs font-medium text-muted-foreground uppercase tracking-wider";
const sectionCls = "rounded-xl border border-border/40 p-4 space-y-3";

const DURATION_OPTIONS = [15, 30, 60, 120, 240];

const MUSIC_MODE_LABELS: Record<string, string> = {
  txt2music: "文生音乐 (txt2music)",
  instrumental: "纯音乐 (instrumental)",
  lyrics: "歌词生成 (lyrics)",
  extend: "音乐扩展 (extend)",
  cover: "翻唱/风格迁移 (cover)",
  add_instrumental: "添加伴奏 (add_instrumental)",
  add_vocals: "添加人声 (add_vocals)",
  separate: "人声分离 (separate)",
  to_wav: "转 WAV (to_wav)",
  upload_extend: "上传并扩展 (upload_extend)",
};

const DEFAULT_CONFIG: MusicGenInterfaceConfig = {
  api_url: "",
  api_key: "",
  sdk_package: "",
  sdk_module: "backend.musicgen.sdk.kieai_music_wrapper",
  sdk_function: "generate",
  sdk_api_key: "",
  default_model: "V5_5",
  model_options: [],
  model_metadata: {},
  modes: {
    txt2music: { enabled: true, endpoint: "" },
    instrumental: { enabled: true, endpoint: "" },
    lyrics: { enabled: true, endpoint: "" },
    extend: { enabled: true, endpoint: "" },
    cover: { enabled: true, endpoint: "" },
    add_instrumental: { enabled: true, endpoint: "" },
    add_vocals: { enabled: true, endpoint: "" },
    separate: { enabled: true, endpoint: "" },
    to_wav: { enabled: true, endpoint: "" },
    upload_extend: { enabled: true, endpoint: "" },
  },
  sdk_extra_args: { poll_timeout: 600 },
  max_concurrent: 1,
  timeout: 600,
  poll_timeout: 600,
};

interface Props {
  iface: MusicGenInterface | null;
  onSaved: () => void;
  onCancel: () => void;
}

export default function MusicGenInterfaceEditor({ iface, onSaved, onCancel }: Props) {
  const [name, setName] = useState("");
  const [type, setType] = useState<"sdk" | "openai_compatible">("sdk");
  const [description, setDescription] = useState("");
  const [apiSourceUrl, setApiSourceUrl] = useState("");
  const [modelDocsUrl, setModelDocsUrl] = useState("");
  const [config, setConfig] = useState<MusicGenInterfaceConfig>(DEFAULT_CONFIG);
  const [saving, setSaving] = useState(false);
  const [fetchingModels, setFetchingModels] = useState(false);

  const [newModel, setNewModel] = useState("");
  const [newModelModes, setNewModelModes] = useState<string[]>(["txt2music"]);
  const [newModelPrice, setNewModelPrice] = useState("");
  const [newModelDurations, setNewModelDurations] = useState<number[]>([60]);

  useEffect(() => {
    if (iface) {
      setName(iface.name);
      setType(iface.type);
      setDescription(iface.description || "");
      setApiSourceUrl(iface.api_source_url || "");
      setModelDocsUrl(iface.model_docs_url || "");
      setConfig({ ...DEFAULT_CONFIG, ...iface.config });
    }
  }, [iface]);

  const updateConfig = (patch: Partial<MusicGenInterfaceConfig>) => {
    setConfig((prev) => ({ ...prev, ...patch }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const data = {
        name,
        type,
        description,
        api_source_url: apiSourceUrl.trim(),
        model_docs_url: modelDocsUrl.trim(),
        config,
      };
      if (iface) {
        await musicgenInterfacesApi.update(iface.id, data);
      } else {
        const id = name.trim().toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]/g, "_");
        await musicgenInterfacesApi.create({ id, ...data });
      }
      onSaved();
    } catch (e: any) {
      alert("保存失败: " + (e.response?.data?.detail || e.message));
    } finally {
      setSaving(false);
    }
  };

  const handleAddModel = () => {
    if (!newModel.trim()) return;
    const modelName = newModel.trim();
    const models = [...(config.model_options || []), modelName];
    const metadata = { ...(config.model_metadata || {}) };
    metadata[modelName] = {
      modes: newModelModes,
      price: newModelPrice,
      durations: newModelDurations,
      max_ref_audios: 1,
      supports_lyrics: true,
    };
    updateConfig({ model_options: models, model_metadata: metadata });
    setNewModel("");
    setNewModelModes(["txt2music"]);
    setNewModelPrice("");
    setNewModelDurations([60]);
  };

  const handleRemoveModel = (m: string) => {
    const models = (config.model_options || []).filter((x) => x !== m);
    const metadata = { ...(config.model_metadata || {}) };
    delete metadata[m];
    updateConfig({ model_options: models, model_metadata: metadata });
  };

  const updateModelMeta = (modelName: string, field: string, value: any) => {
    const metadata = { ...(config.model_metadata || {}) };
    const meta = metadata[modelName] || {};
    metadata[modelName] = { ...meta, [field]: value };
    updateConfig({ model_metadata: metadata });
  };

  const toggleNewModelMode = (mode: string) => {
    setNewModelModes((prev) =>
      prev.includes(mode) ? prev.filter((m) => m !== mode) : [...prev, mode]
    );
  };

  const toggleModelMode = (modelName: string, mode: string) => {
    const meta = config.model_metadata?.[modelName] || {};
    const modes = meta.modes || [];
    const newModes = modes.includes(mode) ? modes.filter((m) => m !== mode) : [...modes, mode];
    updateModelMeta(modelName, "modes", newModes);
  };

  const toggleModelDuration = (modelName: string, d: number) => {
    const meta = config.model_metadata?.[modelName] || {};
    const current = meta.durations || [];
    const next = current.includes(d) ? current.filter((v) => v !== d) : [...current, d];
    updateModelMeta(modelName, "durations", next);
  };

  const handleFetchModels = async () => {
    if (!iface) return;
    setFetchingModels(true);
    try {
      const res = await musicgenInterfacesApi.fetchModels(iface.id);
      const patch: any = {};
      if (res.data.models) patch.model_options = res.data.models;
      if (res.data.model_metadata) patch.model_metadata = res.data.model_metadata;
      if (Object.keys(patch).length > 0) updateConfig(patch);
    } catch (e: any) {
      alert("拉取模型失败: " + (e.response?.data?.detail || e.message));
    } finally {
      setFetchingModels(false);
    }
  };

  return (
    <div className="flex flex-col max-h-[85vh]">
      <div className="flex items-center justify-between px-6 py-4 border-b border-border/50 shrink-0">
        <h2 className="text-lg font-semibold">{iface ? "编辑接口" : "新建接口"}</h2>
        <button onClick={onCancel} className="p-1.5 rounded-lg hover:bg-accent/60 transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-6 space-y-5">
        <div className={sectionCls}>
          <h4 className="text-xs font-semibold text-foreground">基础信息</h4>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>名称</label>
              <input className={cn(inputCls, "mt-1.5")} value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <label className={labelCls}>类型</label>
              <select className={cn(inputCls, "mt-1.5")} value={type} onChange={(e) => setType(e.target.value as any)}>
                <option value="sdk">SDK</option>
                <option value="openai_compatible">OpenAI Compatible</option>
              </select>
            </div>
          </div>
          <div>
            <label className={labelCls}>描述</label>
            <input className={cn(inputCls, "mt-1.5")} value={description} onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div>
            <label className={labelCls}>API 获取地址</label>
            <input className={cn(inputCls, "mt-1.5")} value={apiSourceUrl} onChange={(e) => setApiSourceUrl(e.target.value)} placeholder="https://kieai.erweima.ai" />
          </div>
          <div>
            <label className={labelCls}>支持模型查看链接</label>
            <input className={cn(inputCls, "mt-1.5")} value={modelDocsUrl} onChange={(e) => setModelDocsUrl(e.target.value)} placeholder="https://example.com/models" />
          </div>
        </div>

        {type === "sdk" && (
          <div className={sectionCls}>
            <h4 className="text-xs font-semibold text-foreground">SDK 配置</h4>
            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className={labelCls}>Package</label>
                <input className={cn(inputCls, "mt-1.5")} value={config.sdk_package || ""} onChange={(e) => updateConfig({ sdk_package: e.target.value })} />
              </div>
              <div>
                <label className={labelCls}>Module</label>
                <input className={cn(inputCls, "mt-1.5")} value={config.sdk_module || ""} onChange={(e) => updateConfig({ sdk_module: e.target.value })} />
              </div>
              <div>
                <label className={labelCls}>Function</label>
                <input className={cn(inputCls, "mt-1.5")} value={config.sdk_function || "generate"} onChange={(e) => updateConfig({ sdk_function: e.target.value })} />
              </div>
            </div>
            <SecretField label="SDK API Key" value={config.sdk_api_key || ""} onChange={(v) => updateConfig({ sdk_api_key: v })} />
          </div>
        )}

        {type === "openai_compatible" && (
          <div className={sectionCls}>
            <h4 className="text-xs font-semibold text-foreground">API 配置</h4>
            <div>
              <label className={labelCls}>API URL</label>
              <input className={cn(inputCls, "mt-1.5")} value={config.api_url || ""} onChange={(e) => updateConfig({ api_url: e.target.value })} />
            </div>
            <SecretField label="API Key" value={config.api_key || ""} onChange={(v) => updateConfig({ api_key: v })} />
          </div>
        )}

        <div className={sectionCls}>
          <h4 className="text-xs font-semibold text-foreground">模式配置</h4>
          <div className="grid grid-cols-2 gap-3">
            {Object.keys(config.modes || {}).map((mode) => (
              <div key={mode} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={config.modes?.[mode]?.enabled ?? true}
                  onChange={(e) =>
                    updateConfig({
                      modes: {
                        ...config.modes,
                        [mode]: { ...(config.modes?.[mode] || { enabled: true, endpoint: "" }), enabled: e.target.checked },
                      },
                    })
                  }
                />
                <label className="text-sm">{MUSIC_MODE_LABELS[mode] || mode}</label>
              </div>
            ))}
          </div>
        </div>

        <div className={sectionCls}>
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-semibold text-foreground">模型管理</h4>
            {iface && (
              <button
                onClick={handleFetchModels}
                disabled={fetchingModels}
                className="flex items-center gap-1 px-2 py-1 text-[11px] border border-border/40 rounded-lg hover:bg-accent/60 disabled:opacity-50 transition-colors"
              >
                {fetchingModels ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                从 SDK 拉取
              </button>
            )}
          </div>
          <div>
            <label className={labelCls}>默认模型</label>
            <select className={cn(inputCls, "mt-1.5")} value={config.default_model || ""} onChange={(e) => updateConfig({ default_model: e.target.value })}>
              <option value="">未选择</option>
              {(config.model_options || []).map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
          </div>

          <div className="space-y-2">
            {(config.model_options || []).map((m) => {
              const meta = config.model_metadata?.[m] || { modes: [], price: "", durations: [], max_ref_audios: 1, supports_lyrics: true };
              return (
                <div key={m} className="px-3 py-2 rounded-lg bg-muted/30 text-sm space-y-2">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="flex-1 truncate font-medium" title={m}>{m}</span>
                    <div className="flex items-center gap-1 flex-wrap max-w-[60%]">
                      {Object.keys(MUSIC_MODE_LABELS).map((mode) => (
                        <label key={mode} className="flex items-center gap-0.5 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={(meta.modes || []).includes(mode)}
                            onChange={() => toggleModelMode(m, mode)}
                            className="w-3 h-3 accent-primary"
                          />
                          <span className="text-[10px]">{mode}</span>
                        </label>
                      ))}
                    </div>
                    <input
                      className="w-24 px-2 py-0.5 border border-border/40 rounded bg-background/50 text-xs outline-none focus:border-primary/50"
                      placeholder="¥0.06/首"
                      value={meta.price || ""}
                      onChange={(e) => updateModelMeta(m, "price", e.target.value)}
                    />
                    <button onClick={() => handleRemoveModel(m)} className="text-muted-foreground hover:text-red-500 transition-colors">
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>
                  <div className="flex items-start gap-4 pl-1">
                    <div className="flex-1">
                      <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">时长(秒)</span>
                      <div className="flex flex-wrap gap-1.5 mt-1">
                        {DURATION_OPTIONS.map((d) => (
                          <label key={d} className="flex items-center gap-0.5 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={(meta.durations || []).includes(d)}
                              onChange={() => toggleModelDuration(m, d)}
                              className="w-3 h-3 accent-primary"
                            />
                            <span className="text-[11px]">{d}</span>
                          </label>
                        ))}
                      </div>
                    </div>
                    <div className="flex items-center gap-2">
                      <label className="flex items-center gap-1 cursor-pointer text-[11px]">
                        <input
                          type="checkbox"
                          checked={meta.supports_lyrics ?? true}
                          onChange={(e) => updateModelMeta(m, "supports_lyrics", e.target.checked)}
                          className="w-3 h-3 accent-primary"
                        />
                        支持歌词
                      </label>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          <div className="space-y-2 pt-2">
            <div className="grid grid-cols-[1fr_140px_100px_60px] gap-2 items-end">
              <div>
                <input className={inputCls} placeholder="输入模型名称..." value={newModel} onChange={(e) => setNewModel(e.target.value)} onKeyDown={(e) => e.key === "Enter" && handleAddModel()} />
              </div>
              <div className="flex items-center gap-1.5 flex-wrap pb-2.5">
                {["txt2music", "instrumental", "lyrics"].map((mode) => (
                  <label key={mode} className="flex items-center gap-0.5 cursor-pointer">
                    <input type="checkbox" checked={newModelModes.includes(mode)} onChange={() => toggleNewModelMode(mode)} className="w-3 h-3 accent-primary" />
                    <span className="text-[10px]">{mode}</span>
                  </label>
                ))}
              </div>
              <input className={inputCls} placeholder="价格" value={newModelPrice} onChange={(e) => setNewModelPrice(e.target.value)} />
              <button onClick={handleAddModel} className="flex items-center justify-center gap-1 px-3 py-2.5 text-xs border border-border/40 rounded-xl hover:bg-accent/60 transition-colors">
                <Plus className="w-3.5 h-3.5" /> 添加
              </button>
            </div>
            <div className="flex items-start gap-4 pl-1">
              <div className="flex-1">
                <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">时长(秒)</span>
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {DURATION_OPTIONS.map((d) => (
                    <label key={d} className="flex items-center gap-0.5 cursor-pointer">
                      <input type="checkbox" checked={newModelDurations.includes(d)} onChange={() => setNewModelDurations((prev) => prev.includes(d) ? prev.filter((v) => v !== d) : [...prev, d])} className="w-3 h-3 accent-primary" />
                      <span className="text-[11px]">{d}</span>
                    </label>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className={sectionCls}>
          <h4 className="text-xs font-semibold text-foreground">高级设置</h4>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>最大并发</label>
              <input type="number" className={cn(inputCls, "mt-1.5")} value={config.max_concurrent || 1} onChange={(e) => updateConfig({ max_concurrent: +e.target.value })} />
            </div>
            <div>
              <label className={labelCls}>轮询超时 (秒)</label>
              <input type="number" className={cn(inputCls, "mt-1.5")} value={config.poll_timeout || config.timeout || 600} onChange={(e) => updateConfig({ poll_timeout: +e.target.value, timeout: +e.target.value })} />
            </div>
          </div>
          <div>
            <label className={labelCls}>SDK 额外参数 (JSON)</label>
            <textarea
              className={cn(inputCls, "mt-1.5 font-mono text-xs")}
              rows={3}
              value={JSON.stringify(config.sdk_extra_args || {}, null, 2)}
              onChange={(e) => {
                try {
                  updateConfig({ sdk_extra_args: JSON.parse(e.target.value) });
                } catch {}
              }}
            />
          </div>
        </div>
      </div>

      <div className="flex justify-end gap-3 px-6 py-4 border-t border-border/50 shrink-0">
        <button onClick={onCancel} className="px-4 py-2 text-sm border border-border/60 rounded-xl hover:bg-accent/60 transition-colors">
          取消
        </button>
        <button onClick={handleSave} disabled={saving} className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-xl hover:shadow-lg hover:shadow-primary/25 disabled:opacity-50 transition-all">
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          保存
        </button>
      </div>
    </div>
  );
}
