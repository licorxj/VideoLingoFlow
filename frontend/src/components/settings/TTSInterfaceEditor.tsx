import { useState, useEffect } from "react";
import { ttsInterfacesApi, TTSInterface, TTSInterfaceConfig } from "@/api/ttsInterfaces";
import { cn } from "@/lib/utils";
import { X, Settings2 } from "lucide-react";
import client from "@/api/client";
import VoiceManagePanel from "./VoiceManagePanel";

const EMPTY_LOCAL: TTSInterfaceConfig = {
  api_url: "",
  text_param: "text",
  ref_audio_param: "reference_audio",
  modes: { clone: { enabled: false, endpoint: "" }, voice_design: { enabled: false, endpoint: "" }, controllable_clone: { enabled: false, endpoint: "" }, preset_voice: { enabled: false, endpoint: "" } },
  voice_design_param: null,
  controllable_clone_param: null,
  speed_param: null,
  max_concurrent: 1,
  timeout: 120,
  custom_params: [],
  model_options: [],
  voice_options: [],
};

const EMPTY_ONLINE: TTSInterfaceConfig = {
  api_url: "",
  api_key: "",
  text_param: "input",
  model: "tts-1",
  voice: "alloy",
  response_format: "wav",
  speed_param: "speed",
  modes: { clone: { enabled: false, endpoint: "" }, voice_design: { enabled: false, endpoint: "" }, controllable_clone: { enabled: false, endpoint: "" }, preset_voice: { enabled: false, endpoint: "" } },
  model_list_url: "",
  voice_list_url: "",
  model_list_key: "",
  voice_list_key: "",
  max_concurrent: 1,
  timeout: 120,
  custom_params: [],
  model_options: [],
  voice_options: [],
};

const EMPTY_SDK: TTSInterfaceConfig = {
  sdk_package: "",
  sdk_function: "synthesize",
  sdk_module: "",
  sdk_voice_list_function: "",
  sdk_api_key: "",
  text_param: "text",
  ref_audio_param: null,
  speed_param: null,
  modes: { clone: { enabled: false, endpoint: "" }, voice_design: { enabled: false, endpoint: "" }, controllable_clone: { enabled: false, endpoint: "" }, preset_voice: { enabled: false, endpoint: "" } },
  model: "",
  voice: "",
  model_list_url: "",
  voice_list_url: "",
  model_list_key: "",
  voice_list_key: "",
  sdk_extra_args: {},
  max_concurrent: 1,
  timeout: 120,
  custom_params: [],
  model_options: [],
  voice_options: [],
};

interface ParamRow {
  label: string;
  key: string;
  description: string;
  required: boolean;
  default?: string;
}

interface Props {
  iface?: TTSInterface | null;
  onSaved: () => void;
  onCancel: () => void;
}

export default function TTSInterfaceEditor({ iface, onSaved, onCancel }: Props) {
  const [name, setName] = useState("");
  const [type, setType] = useState<"local" | "online" | "sdk">("local");
  const [desc, setDesc] = useState("");
  const [apiSourceUrl, setApiSourceUrl] = useState("");
  const [config, setConfig] = useState<TTSInterfaceConfig>({ ...EMPTY_LOCAL });
  const [saving, setSaving] = useState(false);
  const [modelList, setModelList] = useState<string[]>([]);
  const [voiceList, setVoiceList] = useState<string[]>([]);
  const [showKeyPicker, setShowKeyPicker] = useState<null | "model" | "voice">(null);
  const [selectedKey, setSelectedKey] = useState("");
  const [manualModel, setManualModel] = useState("");
  const [manualVoice, setManualVoice] = useState("");
  const [showVoiceManage, setShowVoiceManage] = useState(false);
  const [voiceListVoices, setVoiceListVoices] = useState<{ voice_id: string; voice_name: string }[]>([]);

  useEffect(() => {
    if (iface) {
      setName(iface.name);
      setType(iface.type);
      setDesc(iface.description || "");
      setApiSourceUrl(iface.api_source_url || "");
      const cfg = iface.config || { ...EMPTY_LOCAL };
      setConfig(cfg);
      setModelList(cfg.model_options || []);
      setVoiceList(cfg.voice_options || []);
    }
  }, [iface]);

  useEffect(() => {
    if (iface?.id) {
      client
        .get(`/api/tts-voices/${iface.id}`)
        .then((res) => setVoiceListVoices(res.data.voices || []))
        .catch(() => setVoiceListVoices([]));
    } else {
      setVoiceListVoices([]);
    }
  }, [iface?.id]);

  const handleTypeChange = (t: "local" | "online" | "sdk") => {
    setType(t);
    setConfig(t === "local" ? { ...EMPTY_LOCAL } : t === "online" ? { ...EMPTY_ONLINE } : { ...EMPTY_SDK });
  };

  const uc = (key: string, val: any) => setConfig((p) => ({ ...p, [key]: val }));

  const updateMode = (mode: string, field: string, val: any) => {
    setConfig((p) => ({
      ...p,
      modes: { ...p.modes, [mode]: { ...(p.modes?.[mode as keyof typeof p.modes] || {}), [field]: val } },
    }));
  };

  const addCustomParam = () => {
    setConfig((p) => ({ ...p, custom_params: [...(p.custom_params || []), { key: "", default: "", description: "" }] }));
  };
  const updateCP = (idx: number, field: string, val: string) => {
    setConfig((p) => {
      const cp = [...(p.custom_params || [])];
      cp[idx] = { ...cp[idx], [field]: val };
      return { ...p, custom_params: cp };
    });
  };
  const removeCP = (idx: number) => {
    setConfig((p) => ({ ...p, custom_params: (p.custom_params || []).filter((_, i) => i !== idx) }));
  };

  const getParamRows = (): ParamRow[] => {
    const rows: ParamRow[] = [];
    if (type === "online") {
      rows.push(
        { label: "API URL *", key: "api_url", description: "OpenAI TTS API 端点地址", required: true },
        { label: "API 密钥 *", key: "api_key", description: "认证密钥", required: true },
        { label: "模型", key: "model", description: "TTS 模型名称", required: false, default: "tts-1" },
        { label: "语音", key: "voice", description: "语音名称", required: false, default: "alloy" },
        { label: "输出格式", key: "response_format", description: "wav, mp3, opus", required: false, default: "wav" },
      );
    } else if (type === "local") {
      rows.push(
        { label: "API URL *", key: "api_url", description: "请求的本地 API 端口地址", required: true },
        { label: "启动脚本", key: "startup_script", description: "启动脚本路径（接口未启动时自动执行）", required: false },
        { label: "文本参数", key: "text_param", description: "需要传递朗读文本的参数名", required: false, default: "text" },
        { label: "参考音频参数", key: "ref_audio_param", description: "传入克隆的参考音频路径，默认填入 null", required: false, default: "null" },
        { label: "声音设计参数", key: "voice_design_param", description: "语音设计指令参数名", required: false, default: "null" },
        { label: "可控克隆参数", key: "controllable_clone_param", description: "可控克隆指令参数名", required: false, default: "null" },
      );
    } else {
      rows.push(
        { label: "SDK 包名 *", key: "sdk_package", description: "pip 包名", required: true },
        { label: "SDK 模块", key: "sdk_module", description: "Python 模块路径", required: false },
        { label: "SDK 函数", key: "sdk_function", description: "用于合成的函数名", required: false, default: "synthesize" },
        { label: "音色列表函数", key: "sdk_voice_list_function", description: "获取音色列表的函数名，留空则不支持自动获取", required: false },
        { label: "API 密钥", key: "sdk_api_key", description: "API 密钥（如接口需要认证）", required: false },
        { label: "文本参数", key: "text_param", description: "需要传递朗读文本的参数名", required: false, default: "text" },
        { label: "参考音频参数", key: "ref_audio_param", description: "传入克隆的参考音频路径，默认填入 null", required: false, default: "null" },
      );
    }
    rows.push(
      { label: "最大并发", key: "max_concurrent", description: "最大并发数", required: false, default: "1" },
      { label: "超时时间", key: "timeout", description: "超时时间（秒）", required: false, default: "120" },
    );
    rows.push({ label: "语速参数", key: "speed_param", description: "语速控制参数名，null=禁用", required: false, default: "null" });
    return rows;
  };

  const fetchListData = async (url: string, listType: "model" | "voice") => {
    try {
      const headers: any = {};
      if (config.api_key) headers["Authorization"] = "Bearer " + config.api_key;
      const resp = await fetch(url, { headers });
      const data = await resp.json();
      const key = listType === "model" ? config.model_list_key : config.voice_list_key;
      let items: string[] = [];
      if (key) {
        const nested = key.split(".").reduce((obj: any, k: string) => obj?.[k], data);
        if (Array.isArray(nested)) items = nested.map((item: any) => typeof item === "string" ? item : JSON.stringify(item));
      } else if (Array.isArray(data)) {
        items = data.map((item: any) => typeof item === "string" ? item : JSON.stringify(item));
      }
      if (items.length === 0) {
        alert("未找到项目，请检查 URL 和 Key 路径");
        return;
      }
      if (listType === "model") { setModelList(items); uc("model_options", items); }
      else { setVoiceList(items); uc("voice_options", items); }
      setShowKeyPicker(listType);
    } catch (e: any) {
      alert("请求失败: " + e.message);
    }
  };

  const handleKeyConfirm = () => {
    if (showKeyPicker === "model") {
      uc("model_list_key", selectedKey);
    } else {
      uc("voice_list_key", selectedKey);
    }
    setShowKeyPicker(null);
  };

  const ucModel = (val: string) => uc("model", val);
  const ucVoice = (val: string) => uc("voice", val);

  const handleSave = async () => {
    if (!name.trim()) { alert("请填写接口名称"); return; }
    setSaving(true);
    try {
      const payload: any = {
        name: name.trim(),
        type,
        description: desc,
        api_source_url: apiSourceUrl.trim(),
        config: { ...config, model_options: modelList, voice_options: voiceList },
      };
      if (iface) { await ttsInterfacesApi.update(iface.id, payload); }
      else { await ttsInterfacesApi.create(payload); }
      onSaved();
    } catch (e: any) {
      alert("保存失败: " + (e.response?.data?.detail || e.message));
    } finally {
      setSaving(false);
    }
  };

  const labelCls = "text-xs font-medium text-muted-foreground mb-1.5 block";
  const inputCls = "px-3 py-2 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none w-full";
  const hasCustomParams = (config.custom_params || []).length > 0;

  return (
    <div className="max-h-[85vh] overflow-y-auto">
      <div className="p-6 space-y-5">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-extrabold tracking-tight">{iface ? "编辑接口" : "添加新接口"}</h3>
            <p className="text-xs text-muted-foreground mt-1">配置 TTS 接口的连接参数和功能模式</p>
          </div>
          <button onClick={onCancel} className="p-1.5 rounded-lg hover:bg-secondary transition-colors"><X className="w-4 h-4" /></button>
        </div>

        {/* Basic Info */}
        <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className={labelCls}>名称 *</label>
              <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} placeholder="例如 Edge TTS" />
            </div>
            <div>
              <label className={labelCls}>描述</label>
              <input className={inputCls} value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="简要描述" />
            </div>
          </div>
          <div>
            <label className={labelCls}>API 获取地址</label>
            <input className={inputCls} value={apiSourceUrl} onChange={(e) => setApiSourceUrl(e.target.value)} placeholder="https://example.com/api-docs" />
          </div>
          <div>
            <label className={labelCls}>类型 *</label>
            <div className="flex gap-1.5 mt-2 p-1 rounded-xl bg-muted/50">
              {(["local", "online", "sdk"] as const).map((t) => (
                <button key={t} onClick={() => handleTypeChange(t)}
                  className={"flex-1 px-3 py-2 rounded-lg text-xs font-semibold transition-all duration-200 " + (type === t ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
                  {t === "local" ? "本地 API" : t === "online" ? "OpenAI 格式" : "SDK"}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Supported Modes */}
        {(type === "local" || type === "online" || type === "sdk") && (
          <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-3">
            <h4 className="text-sm font-semibold">支持的模式</h4>
            <div className="grid grid-cols-2 gap-3">
              {(["clone", "voice_design", "controllable_clone", "preset_voice"] as const).map((m) => (
                <label key={m} className="flex items-center gap-2.5 p-3 rounded-xl border border-border/40 hover:border-border/60 cursor-pointer transition-all">
                  <input type="checkbox" checked={config.modes?.[m]?.enabled || false} onChange={(e) => updateMode(m, "enabled", e.target.checked)} className="rounded" />
                  <span className="text-sm">{m === "clone" ? "声音克隆" : m === "voice_design" ? "声音设计" : m === "controllable_clone" ? "可控克隆" : "预置音色"}</span>
                </label>
              ))}
            </div>
            {(["clone", "voice_design", "controllable_clone", "preset_voice"] as const).map((m) => (
              config.modes?.[m]?.enabled && (
                <div key={m + "_ep"} className="ml-6">
                  <label className="text-[11px] text-muted-foreground">{m === "clone" ? "声音克隆" : m === "voice_design" ? "声音设计" : m === "controllable_clone" ? "可控克隆" : "预置音色"} 端点</label>
                  <input className={inputCls + " mt-1"} value={config.modes?.[m]?.endpoint || ""} onChange={(e) => updateMode(m, "endpoint", e.target.value)} placeholder="请求端点，如 /tts/clone" />
                </div>
              )
            ))}
          </div>
        )}

        {/* Parameters */}
        <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-3">
          <h4 className="text-sm font-semibold">参数设置</h4>
          <div className="space-y-3">
            {getParamRows().map((row) => (
              <div key={row.key}>
                <div className="flex items-center gap-2 mb-1.5">
                  <div className="text-sm font-medium">{row.label}</div>
                  <code className="text-[11px] text-muted-foreground font-mono">{row.key}</code>
                </div>
                <input className={inputCls} value={(config as any)[row.key] ?? ""} onChange={(e) => uc(row.key, e.target.value)} placeholder={row.description} />
              </div>
            ))}
          </div>
        </div>

        {/* Model & Voice Selection (Online) */}
        {type === "online" && (
          <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
            <h4 className="text-sm font-semibold">模型与音色</h4>
            <p className="text-[11px] text-muted-foreground">通过 API 请求获取可用模型和音色列表</p>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <div className="flex gap-2">
                  <input className={inputCls + " flex-1"} value={config.model_list_url || ""} onChange={(e) => uc("model_list_url", e.target.value)} placeholder="模型列表 URL" />
                  <button onClick={() => fetchListData(config.model_list_url || "", "model")} className="px-3 py-2 text-xs font-medium border border-border/60 rounded-lg hover:bg-accent/60 transition-colors whitespace-nowrap">获取模型</button>
                </div>
                <select className={inputCls} value={config.model || ""} onChange={(e) => ucModel(e.target.value)}>
                  <option value="">选择模型</option>
                  {modelList.map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
                <input className={inputCls} value={manualModel} onChange={(e) => setManualModel(e.target.value)} placeholder="手动输入模型名" onKeyDown={(e) => { if (e.key === "Enter" && manualModel.trim()) { setModelList([...modelList, manualModel.trim()]); uc("model_options", [...modelList, manualModel.trim()]); setManualModel(""); } }} />
              </div>
              <div className="space-y-2">
                {iface?.id && (
                  <button onClick={() => setShowVoiceManage(true)} className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium border border-border/60 rounded-lg hover:bg-accent/60 transition-colors w-full">
                    <Settings2 className="w-3.5 h-3.5" /> 音色管理面板
                  </button>
                )}
                <select className={inputCls} value={config.voice || ""} onChange={(e) => ucVoice(e.target.value)}>
                  <option value="">选择音色</option>
                  {voiceListVoices.map((v) => <option key={v.voice_id} value={v.voice_id}>{v.voice_name || v.voice_id}</option>)}
                  {voiceList.filter((v) => !voiceListVoices.some((vl) => vl.voice_id === v)).map((v) => <option key={v} value={v}>{v}</option>)}
                </select>
              </div>
            </div>
          </div>
        )}

        {/* Voice Selection (SDK) */}
        {type === "sdk" && (
          <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
            <h4 className="text-sm font-semibold">音色选择</h4>
            <p className="text-[11px] text-muted-foreground">管理 SDK 支持的预置音色</p>
            {iface?.id && (
              <button onClick={() => setShowVoiceManage(true)} className="flex items-center gap-1.5 px-3 py-2 text-xs font-medium border border-border/60 rounded-lg hover:bg-accent/60 transition-colors">
                <Settings2 className="w-3.5 h-3.5" /> 音色管理面板
              </button>
            )}
            <select className={inputCls} value={config.voice || ""} onChange={(e) => ucVoice(e.target.value)}>
              <option value="">选择音色</option>
              {voiceListVoices.map((v) => <option key={v.voice_id} value={v.voice_id}>{v.voice_name || v.voice_id}</option>)}
              {voiceList.filter((v) => !voiceListVoices.some((vl) => vl.voice_id === v)).map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
            {voiceList.length > 0 && (
              <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto">
                {voiceList.map((v) => (
                  <span key={v} className={cn("text-xs px-2.5 py-1 rounded-lg border cursor-pointer transition-colors", config.voice === v ? "border-primary bg-primary/10 text-primary font-medium" : "border-border/40 bg-muted/30 text-muted-foreground")}>
                    <span onClick={() => ucVoice(v)} className="cursor-pointer">{v}</span>
                    <button onClick={() => { setVoiceList(voiceList.filter(x => x !== v)); setConfig(p => ({ ...p, voice_options: (p.voice_options || []).filter(x => x !== v) })); }} className="ml-0.5 text-red-400/60 hover:text-red-400">&times;</button>
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Custom Params */}
        <div className="rounded-2xl border border-border/50 bg-card/70 overflow-hidden">
          <div className="px-5 py-3 border-b border-border/40 flex items-center justify-between">
            <div>
              <h4 className="text-sm font-semibold">自定义参数</h4>
              <p className="text-[11px] text-muted-foreground mt-0.5">非标准接口的扩展键值对</p>
            </div>
            <button onClick={addCustomParam} className="px-3 py-1.5 text-xs font-semibold border border-border/60 rounded-lg hover:bg-accent/60 transition-colors">+ 添加</button>
          </div>
          {!hasCustomParams ? (
            <div className="px-5 py-6 text-center text-xs text-muted-foreground">暂无自定义参数</div>
          ) : (
            <div>
              <div className="flex items-center gap-3 px-5 py-2 border-b border-border/30 bg-muted/30">
                <div className="flex-1 text-xs font-medium text-muted-foreground">键名</div>
                <div className="flex-1 text-xs font-medium text-muted-foreground">默认值</div>
                <div className="flex-[3] text-xs font-medium text-muted-foreground">参数说明</div>
                <div className="w-8"></div>
              </div>
              <div className="divide-y divide-border/30">
                {(config.custom_params || []).map((cp, idx) => (
                  <div key={idx} className="flex items-center gap-3 px-5 py-2.5">
                    <input className={"flex-1 " + inputCls} value={cp.key} onChange={(e) => updateCP(idx, "key", e.target.value)} placeholder="key" />
                    <input className={"flex-1 " + inputCls} value={cp.default} onChange={(e) => updateCP(idx, "default", e.target.value)} placeholder="default" />
                    <input className={"flex-[3] " + inputCls} value={cp.description} onChange={(e) => updateCP(idx, "description", e.target.value)} placeholder="描述" />
                    <button onClick={() => removeCP(idx)} className="p-1.5 rounded-lg text-red-500/60 hover:text-red-500 hover:bg-red-500/10 transition-colors" title="删除">
                      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex gap-3 justify-end pt-2">
          <button onClick={onCancel} className="px-5 py-2.5 text-sm font-medium border border-border/60 rounded-xl hover:bg-secondary/70 transition-all duration-200 active:scale-[0.97]">取消</button>
          <button onClick={handleSave} disabled={saving || !name.trim()}
            className="px-5 py-2.5 text-sm font-semibold bg-primary text-primary-foreground rounded-xl transition-all duration-200 hover:shadow-lg hover:shadow-primary/25 active:scale-[0.97] disabled:opacity-40 btn-glow">
            {saving ? "保存中..." : "保存"}
          </button>
        </div>
      </div>

      {/* Key Picker Modal */}
      {showKeyPicker && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in">
          <div className="bg-background border border-border/60 rounded-2xl shadow-2xl p-6 w-96 animate-scale-in">
            <h4 className="text-sm font-semibold mb-3">选择 {showKeyPicker === "model" ? "模型" : "音色"} 列表的 Key</h4>
            <input className={inputCls} value={selectedKey} onChange={(e) => setSelectedKey(e.target.value)} placeholder="如 data.models 或 results" />
            <div className="flex gap-2 justify-end mt-4">
              <button onClick={() => setShowKeyPicker(null)} className="px-4 py-2 text-sm border border-border/60 rounded-xl hover:bg-secondary/70 transition-colors">取消</button>
              <button onClick={handleKeyConfirm} className="px-4 py-2 text-sm font-semibold bg-primary text-primary-foreground rounded-xl hover:shadow-lg hover:shadow-primary/25 transition-all">确认</button>
            </div>
          </div>
        </div>
      )}

      {showVoiceManage && iface?.id && (
        <VoiceManagePanel
          interfaceId={iface.id}
          interfaceName={name || iface.name}
          open={showVoiceManage}
          onClose={() => setShowVoiceManage(false)}
        />
      )}
    </div>
  );
}
