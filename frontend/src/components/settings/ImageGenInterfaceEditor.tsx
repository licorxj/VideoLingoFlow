import { useState, useEffect } from "react";
import { imagegenInterfacesApi, ImageGenInterface, ImageGenInterfaceConfig } from "@/api/imagegenInterfaces";
import { cn } from "@/lib/utils";
import { X, Plus, Trash2, Save, Loader2 } from "lucide-react";

const inputCls = "w-full px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none";
const labelCls = "text-xs font-medium text-muted-foreground uppercase tracking-wider";
const sectionCls = "rounded-xl border border-border/40 p-4 space-y-3";

interface Props {
  iface: ImageGenInterface | null;
  onSaved: () => void;
  onCancel: () => void;
}

const RESOLUTION_OPTIONS = ["1K", "2K", "4K"];
const ASPECT_RATIO_OPTIONS = ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3"];

const DEFAULT_CONFIG: ImageGenInterfaceConfig = {
  api_url: "",
  api_key: "",
  sdk_package: "",
  sdk_module: "",
  sdk_function: "generate",
  sdk_api_key: "",
  default_model: "",
  model_options: [],
  model_metadata: {},
  model_list_url: "",
  model_list_key: "",
  response_format: "url",
  output_format: "",
  balance_endpoint: "",
  modes: {
    txt2img: { enabled: true, endpoint: "" },
    img2img: { enabled: true, endpoint: "" },
  },
  custom_params: [],
  max_concurrent: 1,
  timeout: 120,
};

export default function ImageGenInterfaceEditor({ iface, onSaved, onCancel }: Props) {
  const [name, setName] = useState("");
  const [type, setType] = useState<"sdk" | "openai_compatible">("sdk");
  const [description, setDescription] = useState("");
  const [apiSourceUrl, setApiSourceUrl] = useState("");
  const [modelDocsUrl, setModelDocsUrl] = useState("");
  const [config, setConfig] = useState<ImageGenInterfaceConfig>(DEFAULT_CONFIG);
  const [saving, setSaving] = useState(false);

  // Model management
  const [newModel, setNewModel] = useState("");
  const [newModelModes, setNewModelModes] = useState<string[]>(["t2i", "i2i"]);
  const [newModelPrice, setNewModelPrice] = useState("");
  const [newModelResolutions, setNewModelResolutions] = useState<string[]>([]);
  const [newModelAspectRatios, setNewModelAspectRatios] = useState<string[]>([]);
  const [fetchingModels, setFetchingModels] = useState(false);

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

  const updateConfig = (patch: Partial<ImageGenInterfaceConfig>) => {
    setConfig((prev) => ({ ...prev, ...patch }));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const data = { name, type, description, api_source_url: apiSourceUrl.trim(), model_docs_url: modelDocsUrl.trim(), config };
      if (iface) {
        await imagegenInterfacesApi.update(iface.id, data);
      } else {
        await imagegenInterfacesApi.create(data);
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
    const name = newModel.trim();
    const models = [...(config.model_options || []), name];
    const metadata = { ...(config.model_metadata || {}) };
    metadata[name] = { modes: newModelModes, price: newModelPrice, resolutions: newModelResolutions, aspect_ratios: newModelAspectRatios };
    updateConfig({ model_options: models, model_metadata: metadata });
    setNewModel("");
    setNewModelModes(["t2i", "i2i"]);
    setNewModelPrice("");
    setNewModelResolutions([]);
    setNewModelAspectRatios([]);
  };

  const handleRemoveModel = (m: string) => {
    const models = (config.model_options || []).filter((x) => x !== m);
    const metadata = { ...(config.model_metadata || {}) };
    delete metadata[m];
    updateConfig({ model_options: models, model_metadata: metadata });
  };

  const updateModelMeta = (modelName: string, field: string, value: any) => {
    const metadata = { ...(config.model_metadata || {}) };
    const meta = metadata[modelName] || { modes: [], price: "" };
    metadata[modelName] = { ...meta, [field]: value };
    updateConfig({ model_metadata: metadata });
  };

  const toggleNewModelMode = (mode: string) => {
    setNewModelModes((prev) =>
      prev.includes(mode) ? prev.filter((m) => m !== mode) : [...prev, mode]
    );
  };

  const toggleModelMode = (modelName: string, mode: string) => {
    const meta = config.model_metadata?.[modelName] || { modes: [], price: "" };
    const modes = meta.modes || [];
    const newModes = modes.includes(mode) ? modes.filter((m) => m !== mode) : [...modes, mode];
    updateModelMeta(modelName, "modes", newModes);
  };

  const toggleModelResolution = (modelName: string, res: string) => {
    const meta = config.model_metadata?.[modelName] || {};
    const current = meta.resolutions || [];
    const next = current.includes(res) ? current.filter((r) => r !== res) : [...current, res];
    updateModelMeta(modelName, "resolutions", next);
  };

  const toggleModelAspectRatio = (modelName: string, ratio: string) => {
    const meta = config.model_metadata?.[modelName] || {};
    const current = meta.aspect_ratios || [];
    const next = current.includes(ratio) ? current.filter((r) => r !== ratio) : [...current, ratio];
    updateModelMeta(modelName, "aspect_ratios", next);
  };

  const handleFetchModels = async () => {
    if (!iface) return;
    setFetchingModels(true);
    try {
      const res = await imagegenInterfacesApi.fetchModels(iface.id);
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

  const addCustomParam = () => {
    updateConfig({
      custom_params: [...(config.custom_params || []), { key: "", default: "", description: "" }],
    });
  };

  const updateCustomParam = (idx: number, field: string, value: string) => {
    const params = [...(config.custom_params || [])];
    params[idx] = { ...params[idx], [field]: value };
    updateConfig({ custom_params: params });
  };

  const removeCustomParam = (idx: number) => {
    const params = (config.custom_params || []).filter((_, i) => i !== idx);
    updateConfig({ custom_params: params });
  };

  return (
    <div className="p-6 space-y-5 max-h-[80vh] overflow-y-auto">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{iface ? "编辑接口" : "新建接口"}</h2>
        <button onClick={onCancel} className="p-1.5 rounded-lg hover:bg-accent/60 transition-colors">
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Basic Info */}
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
          <input className={cn(inputCls, "mt-1.5")} value={apiSourceUrl} onChange={(e) => setApiSourceUrl(e.target.value)} placeholder="https://example.com/api-docs" />
        </div>
        <div>
          <label className={labelCls}>支持模型查看链接</label>
          <input className={cn(inputCls, "mt-1.5")} value={modelDocsUrl} onChange={(e) => setModelDocsUrl(e.target.value)} placeholder="https://example.com/models" />
        </div>
      </div>

      {/* SDK Config */}
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
          <div>
            <label className={labelCls}>SDK API Key</label>
            <input className={cn(inputCls, "mt-1.5")} type="password" value={config.sdk_api_key || ""} onChange={(e) => updateConfig({ sdk_api_key: e.target.value })} />
          </div>
        </div>
      )}

      {/* API Config (openai_compatible) */}
      {type === "openai_compatible" && (
        <div className={sectionCls}>
          <h4 className="text-xs font-semibold text-foreground">API 配置</h4>
          <div>
            <label className={labelCls}>API URL</label>
            <input className={cn(inputCls, "mt-1.5")} value={config.api_url || ""} onChange={(e) => updateConfig({ api_url: e.target.value })} />
          </div>
          <div>
            <label className={labelCls}>API Key</label>
            <input className={cn(inputCls, "mt-1.5")} type="password" value={config.api_key || ""} onChange={(e) => updateConfig({ api_key: e.target.value })} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className={labelCls}>Response Format</label>
              <select className={cn(inputCls, "mt-1.5")} value={config.response_format || "url"} onChange={(e) => updateConfig({ response_format: e.target.value })}>
                <option value="url">url</option>
                <option value="b64_json">b64_json</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>Output Format</label>
              <input className={cn(inputCls, "mt-1.5")} value={config.output_format || ""} onChange={(e) => updateConfig({ output_format: e.target.value })} placeholder="png / jpg / webp" />
            </div>
          </div>
        </div>
      )}

      {/* Mode Config */}
      <div className={sectionCls}>
        <h4 className="text-xs font-semibold text-foreground">模式配置</h4>
        <div className="grid grid-cols-2 gap-3">
          {(["txt2img", "img2img"] as const).map((mode) => (
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
              <label className="text-sm">{mode === "txt2img" ? "文生图 (txt2img)" : "图生图 (img2img)"}</label>
            </div>
          ))}
        </div>
      </div>

      {/* Model Management */}
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
          <select
            className={cn(inputCls, "mt-1.5")}
            value={config.default_model || ""}
            onChange={(e) => updateConfig({ default_model: e.target.value })}
          >
            <option value="">未选择</option>
            {(config.model_options || []).map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </div>
        <div className="space-y-2">
          {(config.model_options || []).map((m) => {
            const meta = config.model_metadata?.[m] || { modes: [], price: "", resolutions: [], aspect_ratios: [] };
            return (
              <div key={m} className="px-3 py-2 rounded-lg bg-muted/30 text-sm space-y-2">
                <div className="flex items-center gap-2">
                  <span className="flex-1 truncate font-medium" title={m}>{m}</span>
                  <div className="flex items-center gap-1">
                    {(["t2i", "i2i"] as const).map((mode) => (
                      <label key={mode} className="flex items-center gap-0.5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={(meta.modes || []).includes(mode)}
                          onChange={() => toggleModelMode(m, mode)}
                          className="w-3 h-3 accent-primary"
                        />
                        <span className="text-[11px]">{mode}</span>
                      </label>
                    ))}
                  </div>
                  <input
                    className="w-24 px-2 py-0.5 border border-border/40 rounded bg-background/50 text-xs outline-none focus:border-primary/50"
                    placeholder="¥0.04/张"
                    value={meta.price || ""}
                    onChange={(e) => updateModelMeta(m, "price", e.target.value)}
                  />
                  <button onClick={() => handleRemoveModel(m)} className="text-muted-foreground hover:text-red-500 transition-colors">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
                <div className="flex items-start gap-4 pl-1">
                  <div className="flex-1">
                    <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">分辨率</span>
                    <div className="flex flex-wrap gap-1.5 mt-1">
                      {RESOLUTION_OPTIONS.map((res) => (
                        <label key={res} className="flex items-center gap-0.5 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={(meta.resolutions || []).includes(res)}
                            onChange={() => toggleModelResolution(m, res)}
                            className="w-3 h-3 accent-primary"
                          />
                          <span className="text-[11px]">{res}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                  <div className="flex-1">
                    <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">出图比例</span>
                    <div className="flex flex-wrap gap-1.5 mt-1">
                      {ASPECT_RATIO_OPTIONS.map((ratio) => (
                        <label key={ratio} className="flex items-center gap-0.5 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={(meta.aspect_ratios || []).includes(ratio)}
                            onChange={() => toggleModelAspectRatio(m, ratio)}
                            className="w-3 h-3 accent-primary"
                          />
                          <span className="text-[11px]">{ratio}</span>
                        </label>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
        <div className="space-y-2 pt-2">
          <div className="grid grid-cols-[1fr_120px_100px_60px] gap-2 items-end">
            <div>
              <input
                className={inputCls}
                placeholder="输入模型名称..."
                value={newModel}
                onChange={(e) => setNewModel(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleAddModel()}
              />
            </div>
            <div className="flex items-center gap-1.5 pb-2.5">
              {(["t2i", "i2i"] as const).map((mode) => (
                <label key={mode} className="flex items-center gap-0.5 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={newModelModes.includes(mode)}
                    onChange={() => toggleNewModelMode(mode)}
                    className="w-3 h-3 accent-primary"
                  />
                  <span className="text-[11px]">{mode}</span>
                </label>
              ))}
            </div>
            <input
              className={inputCls}
              placeholder="价格"
              value={newModelPrice}
              onChange={(e) => setNewModelPrice(e.target.value)}
            />
            <button onClick={handleAddModel} className="flex items-center justify-center gap-1 px-3 py-2.5 text-xs border border-border/40 rounded-xl hover:bg-accent/60 transition-colors">
              <Plus className="w-3.5 h-3.5" />
              添加
            </button>
          </div>
          <div className="flex items-start gap-4 pl-1">
            <div className="flex-1">
              <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">分辨率</span>
              <div className="flex flex-wrap gap-1.5 mt-1">
                {RESOLUTION_OPTIONS.map((res) => (
                  <label key={res} className="flex items-center gap-0.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={newModelResolutions.includes(res)}
                      onChange={() => setNewModelResolutions((prev) => prev.includes(res) ? prev.filter((r) => r !== res) : [...prev, res])}
                      className="w-3 h-3 accent-primary"
                    />
                    <span className="text-[11px]">{res}</span>
                  </label>
                ))}
              </div>
            </div>
            <div className="flex-1">
              <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">出图比例</span>
              <div className="flex flex-wrap gap-1.5 mt-1">
                {ASPECT_RATIO_OPTIONS.map((ratio) => (
                  <label key={ratio} className="flex items-center gap-0.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={newModelAspectRatios.includes(ratio)}
                      onChange={() => setNewModelAspectRatios((prev) => prev.includes(ratio) ? prev.filter((r) => r !== ratio) : [...prev, ratio])}
                      className="w-3 h-3 accent-primary"
                    />
                    <span className="text-[11px]">{ratio}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Advanced */}
      <div className={sectionCls}>
        <h4 className="text-xs font-semibold text-foreground">高级设置</h4>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className={labelCls}>最大并发</label>
            <input type="number" className={cn(inputCls, "mt-1.5")} value={config.max_concurrent || 1} onChange={(e) => updateConfig({ max_concurrent: +e.target.value })} />
          </div>
          <div>
            <label className={labelCls}>超时 (秒)</label>
            <input type="number" className={cn(inputCls, "mt-1.5")} value={config.timeout || 120} onChange={(e) => updateConfig({ timeout: +e.target.value })} />
          </div>
        </div>
        <div>
          <label className={labelCls}>余额获取端点</label>
          <input className={cn(inputCls, "mt-1.5")} value={config.balance_endpoint || ""} onChange={(e) => updateConfig({ balance_endpoint: e.target.value })} placeholder="/v1/dashboard/billing/balance 或完整URL" />
        </div>
      </div>

      {/* Custom Params */}
      <div className={sectionCls}>
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-semibold text-foreground">自定义参数</h4>
          <button onClick={addCustomParam} className="flex items-center gap-1 px-2 py-1 text-[11px] border border-border/40 rounded-lg hover:bg-accent/60 transition-colors">
            <Plus className="w-3 h-3" /> 添加
          </button>
        </div>
        {(config.custom_params || []).map((p, idx) => (
          <div key={idx} className="grid grid-cols-[1fr_1fr_2fr_auto] gap-2 items-end">
            <div>
              {idx === 0 && <label className={labelCls}>Key</label>}
              <input className={cn(inputCls, idx === 0 ? "mt-1.5" : "")} value={p.key} onChange={(e) => updateCustomParam(idx, "key", e.target.value)} />
            </div>
            <div>
              {idx === 0 && <label className={labelCls}>Default</label>}
              <input className={cn(inputCls, idx === 0 ? "mt-1.5" : "")} value={p.default} onChange={(e) => updateCustomParam(idx, "default", e.target.value)} />
            </div>
            <div>
              {idx === 0 && <label className={labelCls}>Description</label>}
              <input className={cn(inputCls, idx === 0 ? "mt-1.5" : "")} value={p.description} onChange={(e) => updateCustomParam(idx, "description", e.target.value)} />
            </div>
            <button onClick={() => removeCustomParam(idx)} className="p-2 text-muted-foreground hover:text-red-500 transition-colors">
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>

      {/* Actions */}
      <div className="flex justify-end gap-3 pt-2">
        <button onClick={onCancel} className="px-4 py-2 text-sm border border-border/60 rounded-xl hover:bg-accent/60 transition-colors">
          取消
        </button>
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-2 px-4 py-2 text-sm bg-primary text-primary-foreground rounded-xl hover:shadow-lg hover:shadow-primary/25 disabled:opacity-50 transition-all"
        >
          {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
          保存
        </button>
      </div>
    </div>
  );
}
