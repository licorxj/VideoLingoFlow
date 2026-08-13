import { useState } from "react";
import {
  separationInterfacesApi,
  SeparationInterface,
  SeparationInterfaceConfig,
} from "@/api/separationInterfaces";
import { X, Save, Plus, Trash2, Check } from "lucide-react";

interface Props {
  iface?: SeparationInterface | null;
  onSaved: () => void;
  onCancel: () => void;
}

const EMPTY_SDK: SeparationInterfaceConfig = {
  sdk_module: "",
  sdk_class: "",
  model: "",
  model_options: [],
  model_details: {},
  segment: 1200,
  two_stems: "vocals",
  format: "wav",
  format_options: ["wav", "mp3"],
  timeout: 600,
  max_concurrent: 1,
  custom_params: [],
};

const EMPTY_ONLINE: SeparationInterfaceConfig = {
  model: "",
  model_options: [],
  model_details: {},
  format: "wav",
  format_options: ["wav", "mp3"],
  api_url: "",
  api_key: "",
  endpoint: "/v1/separate",
  body_type: "form",
  audio_param: "file",
  timeout: 600,
  max_concurrent: 1,
  custom_params: [],
};

const EMPTY_LOCAL: SeparationInterfaceConfig = {
  model: "",
  model_options: [],
  model_details: {},
  format: "wav",
  format_options: ["wav", "mp3"],
  api_url: "",
  startup_script: "",
  endpoint: "/v1/separate",
  body_type: "form",
  audio_param: "file",
  timeout: 600,
  max_concurrent: 1,
  custom_params: [],
};

const TYPE_LABELS: Record<string, string> = {
  sdk: "SDK",
  online: "Online API",
  local: "Local API",
};

export default function SeparationInterfaceEditor({
  iface,
  onSaved,
  onCancel,
}: Props) {
  const [name, setName] = useState(iface?.name ?? "");
  const [desc, setDesc] = useState(iface?.description ?? "");
  const [type, setType] = useState<SeparationInterface["type"]>(iface?.type ?? "sdk");
  const [config, setConfig] = useState<SeparationInterfaceConfig>(
    iface?.config ?? EMPTY_SDK
  );
  const [modelOptionsText, setModelOptionsText] = useState(
    (iface?.config?.model_options ?? []).join(", ")
  );
  const [formatOptionsText, setFormatOptionsText] = useState(
    (iface?.config?.format_options ?? ["wav", "mp3"]).join(", ")
  );
  const [saving, setSaving] = useState(false);

  // Model details management
  const [modelDetailsEntries, setModelDetailsEntries] = useState<
    Array<{ name: string; description: string }>
  >(() => {
    const details = iface?.config?.model_details || {};
    return Object.entries(details).map(([key, val]) => ({
      name: key,
      description: val?.description ?? "",
    }));
  });
  const [newModelName, setNewModelName] = useState("");
  const [newModelDesc, setNewModelDesc] = useState("");

  const handleTypeChange = (newType: SeparationInterface["type"]) => {
    setType(newType);
    if (newType === "sdk") setConfig({ ...EMPTY_SDK });
    else if (newType === "online") setConfig({ ...EMPTY_ONLINE });
    else setConfig({ ...EMPTY_LOCAL });
    setModelOptionsText("");
    setFormatOptionsText("wav, mp3");
    setModelDetailsEntries([]);
    setNewModelName("");
    setNewModelDesc("");
  };

  const addModelDetail = () => {
    if (!newModelName.trim()) return;
    setModelDetailsEntries((prev) => [
      ...prev,
      { name: newModelName.trim(), description: newModelDesc.trim() },
    ]);
    setNewModelName("");
    setNewModelDesc("");
  };

  const removeModelDetail = (idx: number) => {
    setModelDetailsEntries((prev) => prev.filter((_, i) => i !== idx));
  };

  const uc = (key: string, val: any) => {
    setConfig((p) => ({ ...p, [key]: val }));
  };

  const addCustomParam = () => {
    setConfig((p) => ({
      ...p,
      custom_params: [...(p.custom_params || []), { key: "", default: "", description: "" }],
    }));
  };
  const updateCP = (idx: number, field: string, val: string) => {
    setConfig((p) => ({
      ...p,
      custom_params: (p.custom_params || []).map((cp, i) =>
        i === idx ? { ...cp, [field]: val } : cp
      ),
    }));
  };
  const removeCP = (idx: number) => {
    setConfig((p) => ({
      ...p,
      custom_params: (p.custom_params || []).filter((_, i) => i !== idx),
    }));
  };

  type ParamRow = {
    label: string;
    key: string;
    desc: string;
    type?: "text" | "number" | "select";
    options?: string[];
  };

  const getParamRows = (): ParamRow[] => {
    const rows: ParamRow[] = [];
    if (type === "sdk") {
      rows.push(
        { label: "SDK 模块", key: "sdk_module", desc: "Python 模块路径，如 backend.separation.sep_demucs" },
        { label: "SDK 类名", key: "sdk_class", desc: "类名，如 DemucsSeparation" },
        { label: "默认模型", key: "model", desc: "默认使用的模型名" },
        { label: "模型选项", key: "model_options", desc: "逗号分隔的模型列表" },
        { label: "输出格式", key: "format", desc: "默认输出格式", type: "select", options: ["wav", "mp3"] },
      );
      // Demucs-specific fields
      rows.push(
        { label: "分段时长 (秒)", key: "segment", desc: "Demucs 分段处理时长", type: "number" },
        { label: "分离目标", key: "two_stems", desc: "如 vocals" },
      );
    } else {
      rows.push(
        { label: "默认模型", key: "model", desc: "默认使用的模型名" },
        { label: "API URL", key: "api_url", desc: type === "online" ? "云端 API 地址" : "本地 API 地址，如 http://localhost:8800" },
        { label: "API Key", key: "api_key", desc: "API 密钥（可选）" },
        { label: "端点路径", key: "endpoint", desc: "如 /v1/separate" },
        { label: "请求类型", key: "body_type", desc: "form 或 json", type: "select", options: ["form", "json"] },
        { label: "音频参数名", key: "audio_param", desc: "如 file" },
        { label: "输出格式", key: "format", desc: "默认输出格式", type: "select", options: ["wav", "mp3"] },
      );
      if (type === "local") {
        rows.push({ label: "启动脚本", key: "startup_script", desc: "本地服务启动脚本路径（可选）" });
      }
    }
    rows.push(
      { label: "超时 (秒)", key: "timeout", desc: "分离超时时间", type: "number" },
      { label: "最大并发", key: "max_concurrent", desc: "最大并发数", type: "number" },
    );
    return rows;
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const modelOptions = modelOptionsText
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const formatOptions = formatOptionsText
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const payload = {
        name,
        type,
        description: desc,
        config: {
          ...config,
          model_options: modelOptions,
          format_options: formatOptions.length > 0 ? formatOptions : ["wav", "mp3"],
          model_details: Object.fromEntries(
            modelDetailsEntries.map((m) => [m.name, { name: m.name, description: m.description }])
          ),
        },
      };
      if (iface) {
        await separationInterfacesApi.update(iface.id, payload);
      } else {
        await separationInterfacesApi.create(payload);
      }
      onSaved();
    } catch (e: any) {
      alert("保存失败: " + (e?.response?.data?.detail || e?.message || String(e)));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-h-[85vh] overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between p-5 border-b border-border/50">
        <h2 className="text-base font-semibold">
          {iface ? "编辑接口" : "添加接口"}
        </h2>
        <button
          onClick={onCancel}
          className="p-1.5 rounded-lg hover:bg-accent/60 transition-all duration-200"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="p-5 space-y-5">
        {/* Basic Info */}
        <div className="space-y-3">
          <h3 className="text-sm font-semibold">基本信息</h3>
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1 block">
              接口名称
            </label>
            <input
              type="text"
              className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 outline-none transition-all duration-200"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1 block">
              描述
            </label>
            <input
              type="text"
              className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 outline-none transition-all duration-200"
              value={desc}
              onChange={(e) => setDesc(e.target.value)}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1 block">
              接口类型
            </label>
            <div className="flex gap-2">
              {(["sdk", "online", "local"] as const).map((t) => (
                <button
                  key={t}
                  onClick={() => handleTypeChange(t)}
                  className={`px-4 py-2 text-xs font-medium rounded-lg border transition-all duration-200 ${
                    type === t
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border/60 hover:bg-accent/60"
                  }`}
                >
                  {TYPE_LABELS[t]}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Parameters */}
        <div className="space-y-3">
          <h3 className="text-sm font-semibold">参数设置</h3>
          <div className="space-y-3">
            {getParamRows().map((row) => (
              <div key={row.key}>
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1 block">
                  {row.label}
                </label>
                <p className="text-[10px] text-muted-foreground/60 mb-1.5">{row.desc}</p>
                {row.type === "number" ? (
                  <input
                    type="number"
                    className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 outline-none transition-all duration-200"
                    value={(config as any)[row.key] ?? ""}
                    onChange={(e) => uc(row.key, parseInt(e.target.value) || 0)}
                  />
                ) : row.type === "select" ? (
                  <select
                    className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 outline-none transition-all duration-200 appearance-none"
                    value={(config as any)[row.key] ?? ""}
                    onChange={(e) => uc(row.key, e.target.value)}
                  >
                    {(row.options || []).map((opt) => (
                      <option key={opt} value={opt}>
                        {opt}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 outline-none transition-all duration-200"
                    value={
                      row.key === "model_options"
                        ? modelOptionsText
                        : row.key === "format_options"
                        ? formatOptionsText
                        : (config as any)[row.key] ?? ""
                    }
                    onChange={(e) => {
                      if (row.key === "model_options") {
                        setModelOptionsText(e.target.value);
                      } else if (row.key === "format_options") {
                        setFormatOptionsText(e.target.value);
                      } else {
                        uc(row.key, e.target.value);
                      }
                    }}
                  />
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Model Details */}
        <div className="space-y-3">
          <h3 className="text-sm font-semibold">模型详情</h3>
          <div className="space-y-2">
            {modelDetailsEntries.map((entry, idx) => (
              <div key={idx} className="flex gap-2 items-start">
                <span className="flex-shrink-0 px-3 py-2 border border-border/60 rounded-lg bg-muted/30 text-xs font-mono text-muted-foreground">
                  {entry.name}
                </span>
                <input
                  type="text"
                  placeholder="模型说明"
                  className="flex-1 px-3 py-2 border border-border/60 rounded-lg bg-background/50 text-xs outline-none focus:border-primary/50"
                  value={entry.description}
                  onChange={(e) => {
                    setModelDetailsEntries((prev) =>
                      prev.map((m, i) => i === idx ? { ...m, description: e.target.value } : m)
                    );
                  }}
                />
                <button
                  onClick={() => removeModelDetail(idx)}
                  className="p-2 rounded-lg border border-border/40 hover:bg-red-500/10 hover:text-red-500 transition-all duration-200 text-xs"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              </div>
            ))}
          </div>
          <div className="flex gap-2 items-start pt-2 border-t border-border/40">
            <input
              type="text"
              placeholder="模型名称"
              className="flex-1 px-3 py-2 border border-border/60 rounded-lg bg-background/50 text-xs outline-none focus:border-primary/50"
              value={newModelName}
              onChange={(e) => setNewModelName(e.target.value)}
            />
            <input
              type="text"
              placeholder="模型说明（可选）"
              className="flex-1 px-3 py-2 border border-border/60 rounded-lg bg-background/50 text-xs outline-none focus:border-primary/50"
              value={newModelDesc}
              onChange={(e) => setNewModelDesc(e.target.value)}
            />
            <button
              onClick={addModelDetail}
              disabled={!newModelName.trim()}
              className="px-3 py-2 text-xs font-medium bg-primary text-primary-foreground rounded-lg transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Plus className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Custom Params */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">自定义参数</h3>
            <button
              onClick={addCustomParam}
              className="text-xs px-3 py-1 rounded-lg border border-border/60 hover:bg-accent/60 transition-all duration-200"
            >
              + 添加
            </button>
          </div>
          {(config.custom_params || []).map((cp, idx) => (
            <div key={idx} className="flex gap-2 items-start">
              <input
                type="text"
                placeholder="key"
                className="flex-1 px-3 py-2 border border-border/60 rounded-lg bg-background/50 text-xs outline-none focus:border-primary/50"
                value={cp.key}
                onChange={(e) => updateCP(idx, "key", e.target.value)}
              />
              <input
                type="text"
                placeholder="default"
                className="flex-1 px-3 py-2 border border-border/60 rounded-lg bg-background/50 text-xs outline-none focus:border-primary/50"
                value={cp.default}
                onChange={(e) => updateCP(idx, "default", e.target.value)}
              />
              <input
                type="text"
                placeholder="description"
                className="flex-1 px-3 py-2 border border-border/60 rounded-lg bg-background/50 text-xs outline-none focus:border-primary/50"
                value={cp.description}
                onChange={(e) => updateCP(idx, "description", e.target.value)}
              />
              <button
                onClick={() => removeCP(idx)}
                className="p-2 rounded-lg border border-border/40 hover:bg-red-500/10 hover:text-red-500 transition-all duration-200 text-xs"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          ))}
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-end gap-3 p-5 border-t border-border/50">
        <button
          onClick={onCancel}
          className="px-4 py-2 text-sm font-medium border border-border/60 rounded-lg hover:bg-accent/60 transition-all duration-200"
        >
          取消
        </button>
        <button
          onClick={handleSave}
          disabled={saving || !name.trim()}
          className="flex items-center gap-2 px-4 py-2 text-sm font-semibold bg-primary text-primary-foreground rounded-lg transition-all duration-200 hover:shadow-lg hover:shadow-primary/25 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Save className="w-4 h-4" />
          {saving ? "保存中..." : "保存"}
        </button>
      </div>
    </div>
  );
}
