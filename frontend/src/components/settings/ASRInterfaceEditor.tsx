import { useState, useEffect, useRef } from "react";
import { asrInterfacesApi, ASRInterface, ASRInterfaceConfig } from "@/api/asrInterfaces";
import { cn } from "@/lib/utils";
import { Upload, X, FileAudio, Settings2, Languages } from "lucide-react";
import VoiceLanguagePicker from "@/components/shared/VoiceLanguagePicker";

const EMPTY_LOCAL: ASRInterfaceConfig = {
  api_url: "",
  audio_param: "file",
  language_param: "language",
  endpoint: "/v1/audio/transcriptions",
  body_type: "form",
  auth_header: "Authorization",
  auth_scheme: "Bearer",
  response_format: "verbose_json",
  api_key: "",
  max_duration: 0,
  word_timestamps: false,
  diarize: false,
  hotwords_enabled: false,
  hotwords: "",
  max_concurrent: 1,
  timeout: 300,
  custom_params: [],
  model_options: [],
  voice_options: [],
};

const EMPTY_SDK: ASRInterfaceConfig = {
  sdk_package: "",
  sdk_module: "",
  sdk_function: "transcribe",
  sdk_language_list_function: "",
  sdk_api_key: "",
  model: "",
  text_param: "input_path",
  max_duration: 0,
  word_timestamps: false,
  diarize: false,
  hotwords_enabled: false,
  hotwords: "",
  max_concurrent: 1,
  timeout: 300,
  custom_params: [],
  model_options: [],
  voice_options: [],
  sdk_extra_args: {},
};

interface Props {
  iface?: ASRInterface | null;
  onSaved: () => void;
  onCancel: () => void;
}

export default function ASRInterfaceEditor({ iface, onSaved, onCancel }: Props) {
  const [name, setName] = useState("");
  const [type, setType] = useState<"local" | "sdk" | "openai">("local");
  const [desc, setDesc] = useState("");
  const [config, setConfig] = useState<ASRInterfaceConfig>({ ...EMPTY_LOCAL });
  const [saving, setSaving] = useState(false);
  const [modelList, setModelList] = useState<string[]>([]);
  const [voiceList, setVoiceList] = useState<string[]>([]);
  const [manualModel, setManualModel] = useState("");
  const [showLangPicker, setShowLangPicker] = useState(false);
  const [testAudioPath, setTestAudioPath] = useState("");
  const [testResult, setTestResult] = useState<any>(null);
  const [testLoading, setTestLoading] = useState(false);
  const [testError, setTestError] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (iface) {
      setName(iface.name);
      setType(iface.type);
      setDesc(iface.description || "");
      const cfg = iface.config || { ...EMPTY_LOCAL };
      setConfig(cfg);
      setModelList(cfg.model_options || []);
      setVoiceList(cfg.voice_options || []);
    }
  }, [iface]);

  const handleTypeChange = (t: "local" | "sdk" | "openai") => {
    setType(t);
    setConfig(t === "sdk" ? { ...EMPTY_SDK } : { ...EMPTY_LOCAL });
    setModelList([]);
    setVoiceList([]);
  };

  const uc = (key: string, val: any) => setConfig((p) => ({ ...p, [key]: val }));

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

  const addModel = () => {
    if (!manualModel.trim()) return;
    const newModels = [...modelList, manualModel.trim()];
    setModelList(newModels);
    uc("model_options", newModels);
    setManualModel("");
  };

  const removeModel = (m: string) => {
    const newModels = modelList.filter((x) => x !== m);
    setModelList(newModels);
    uc("model_options", newModels);
    if (config.model === m) uc("model", "");
  };

  const handleLangConfirm = (selected: string[]) => {
    setVoiceList(selected);
    uc("voice_options", selected);
    setShowLangPicker(false);
  };

  const handleSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const payload: any = {
        name: name.trim(),
        type,
        description: desc,
        config: {
          ...config,
          model_options: modelList,
          voice_options: voiceList,
        },
      };
      if (iface) {
        await asrInterfacesApi.update(iface.id, payload);
      } else {
        await asrInterfacesApi.create(payload);
      }
      onSaved();
    } catch (e: any) {
      console.error("Save failed:", e);
    } finally {
      setSaving(false);
    }
  };

  const handleTestUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setTestLoading(true);
    setTestError("");
    setTestResult(null);
    try {
      const resp = await asrInterfacesApi.uploadAudio(file);
      setTestAudioPath(resp.data.path);
    } catch (err: any) {
      setTestError(`上传失败: ${err.message}`);
    } finally {
      setTestLoading(false);
    }
  };

  const handleRunTest = async () => {
    if (!iface || !testAudioPath) return;
    setTestLoading(true);
    setTestError("");
    setTestResult(null);
    try {
      const resp = await asrInterfacesApi.test(iface.id, {
        audio_path: testAudioPath,
        model: config.model,
      });
      setTestResult(resp.data);
    } catch (err: any) {
      setTestError(err.response?.data?.detail || err.message);
    } finally {
      setTestLoading(false);
    }
  };

  const inputCls = "px-3 py-2 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none";

  const isSDK = type === "sdk";
  const hasCustomParams = (config.custom_params || []).length > 0;

  return (
    <div className="max-h-[85vh] overflow-y-auto">
      <div className="p-6 space-y-5">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-bold">{iface ? "编辑 ASR 接口" : "添加 ASR 接口"}</h3>
          <button onClick={onCancel} className="p-1.5 rounded-lg hover:bg-secondary transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Basic Info */}
        <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
          <h4 className="text-sm font-semibold">基本信息</h4>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">名称 *</label>
              <input className={cn(inputCls, "w-full")} value={name} onChange={(e) => setName(e.target.value)} placeholder="例如 WhisperX 本地" />
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">类型 *</label>
              <select
                className={cn(inputCls, "w-full appearance-none")}
                value={type}
                onChange={(e) => handleTypeChange(e.target.value as any)}
                disabled={!!iface?.builtin}
              >
                <option value="local">本地 API (HTTP)</option>
                <option value="sdk">SDK (Python 模块)</option>
                <option value="openai">OpenAI 兼容 (HTTP)</option>
              </select>
            </div>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground mb-1.5 block">描述</label>
            <input className={cn(inputCls, "w-full")} value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="简要描述" />
          </div>
        </div>

        {/* Connection / SDK Config */}
        <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
          <h4 className="text-sm font-semibold">{isSDK ? "SDK 配置" : "连接配置"}</h4>

          {isSDK ? (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">模块路径 (sdk_module) *</label>
                <input className={cn(inputCls, "w-full")} value={config.sdk_module || ""} onChange={(e) => uc("sdk_module", e.target.value)} placeholder="例如 backend.asr.asr_whisperx" />
                <p className="text-[11px] text-muted-foreground mt-1">Python 模块导入路径</p>
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">执行函数名 (sdk_function) *</label>
                <input className={cn(inputCls, "w-full")} value={config.sdk_function || ""} onChange={(e) => uc("sdk_function", e.target.value)} placeholder="transcribe" />
                <p className="text-[11px] text-muted-foreground mt-1">入口函数名称</p>
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">包名 (sdk_package)</label>
                <input className={cn(inputCls, "w-full")} value={config.sdk_package || ""} onChange={(e) => uc("sdk_package", e.target.value)} placeholder="可选 pip 包名" />
                <p className="text-[11px] text-muted-foreground mt-1">可选，当模块路径为空时使用</p>
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">API 密钥</label>
                <input className={cn(inputCls, "w-full")} value={config.sdk_api_key || ""} onChange={(e) => uc("sdk_api_key", e.target.value)} placeholder="可选" type="password" />
              </div>
              <div className="col-span-2">
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">语言列表获取函数 (sdk_language_list_function)</label>
                <input className={cn(inputCls, "w-full")} value={config.sdk_language_list_function || ""} onChange={(e) => uc("sdk_language_list_function", e.target.value)} placeholder="可选：获取支持语言列表的函数名" />
                <p className="text-[11px] text-muted-foreground mt-1">可选：返回支持语言列表的 SDK 函数名称</p>
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">API 地址 *</label>
                <input className={cn(inputCls, "w-full")} value={config.api_url || ""} onChange={(e) => uc("api_url", e.target.value)} placeholder="http://localhost:8800" />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">API 密钥</label>
                <input className={cn(inputCls, "w-full")} value={config.api_key || ""} onChange={(e) => uc("api_key", e.target.value)} placeholder="可选" type="password" />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">接口端点</label>
                <input className={cn(inputCls, "w-full")} value={config.endpoint || ""} onChange={(e) => uc("endpoint", e.target.value)} placeholder="/v1/audio/transcriptions" />
              </div>
              {type === "openai" ? (
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">响应格式</label>
                  <select className={cn(inputCls, "w-full appearance-none")} value={config.response_format || "verbose_json"} onChange={(e) => uc("response_format", e.target.value)}>
                    <option value="verbose_json">verbose_json（含时间戳）</option>
                    <option value="json">json</option>
                    <option value="text">text</option>
                    <option value="srt">srt</option>
                    <option value="vtt">vtt</option>
                  </select>
                </div>
              ) : (
                <div>
                  <label className="text-xs font-medium text-muted-foreground mb-1.5 block">请求格式</label>
                  <select className={cn(inputCls, "w-full appearance-none")} value={config.body_type || "form"} onChange={(e) => uc("body_type", e.target.value)}>
                    <option value="form">multipart/form-data</option>
                    <option value="json">application/json</option>
                  </select>
                </div>
              )}
              {type === "openai" && (
                <>
                  <div>
                    <label className="text-xs font-medium text-muted-foreground mb-1.5 block">鉴权头名称</label>
                    <input className={cn(inputCls, "w-full")} value={config.auth_header || "Authorization"} onChange={(e) => uc("auth_header", e.target.value)} placeholder="Authorization" />
                  </div>
                  <div>
                    <label className="text-xs font-medium text-muted-foreground mb-1.5 block">鉴权头前缀</label>
                    <input className={cn(inputCls, "w-full")} value={config.auth_scheme || "Bearer"} onChange={(e) => uc("auth_scheme", e.target.value)} placeholder="Bearer（留空则不加前缀）" />
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {/* Audio / Language Params */}
        <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
          <h4 className="text-sm font-semibold">请求参数</h4>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">输入音频参数名</label>
              <input className={cn(inputCls, "w-full")} value={config.audio_param || "file"} onChange={(e) => uc("audio_param", e.target.value)} placeholder="file" />
              <p className="text-[11px] text-muted-foreground mt-1">请求中音频文件对应的字段名</p>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">语言参数名</label>
              <input className={cn(inputCls, "w-full")} value={config.language_param || "language"} onChange={(e) => uc("language_param", e.target.value)} placeholder="language" />
              <p className="text-[11px] text-muted-foreground mt-1">请求中语言代码对应的字段名</p>
            </div>
          </div>
        </div>

        {/* ASR Capability Settings */}
        <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
          <div className="flex items-center gap-2">
            <Settings2 className="w-4 h-4 text-primary" />
            <h4 className="text-sm font-semibold">能力设置</h4>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">最大时长（秒）</label>
              <input
                className={cn(inputCls, "w-full")}
                type="number"
                min={0}
                value={config.max_duration ?? 0}
                onChange={(e) => uc("max_duration", parseInt(e.target.value) || 0)}
                placeholder="0 = 不限"
              />
              <p className="text-[11px] text-muted-foreground mt-1">支持的最大音频时长（秒），0 表示不限制</p>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">词级时间戳</label>
              <div className="flex items-center gap-3 h-[38px]">
                <label className="relative cursor-pointer flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={config.word_timestamps ?? false}
                    onChange={(e) => uc("word_timestamps", e.target.checked)}
                    className="peer sr-only"
                  />
                  <div className="w-9 h-5 bg-muted rounded-full peer-checked:bg-primary transition-colors duration-200" />
                  <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-background rounded-full shadow-sm peer-checked:translate-x-[16px] transition-transform duration-200" />
                  <span className="text-xs text-muted-foreground ml-1">{config.word_timestamps ? "支持" : "不支持"}</span>
                </label>
              </div>
              <p className="text-[11px] text-muted-foreground mt-1">该引擎是否支持词级别的时间戳定位</p>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">说话人识别</label>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  role="switch"
                  aria-checked={config.diarize ?? false}
                  onClick={() => uc("diarize", !config.diarize)}
                  className="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors duration-200 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background bg-muted"
                >
                  <span className={cn(
                    "pointer-events-none block h-4 w-4 rounded-full shadow-lg ring-0 transition-transform duration-200",
                    (config.diarize ?? false) ? "translate-x-[18px] bg-primary" : "translate-x-0.5 bg-background"
                  )} />
                </button>
                <label className="text-xs font-medium cursor-pointer" onClick={() => uc("diarize", !config.diarize)}>
                  <span className="text-xs text-muted-foreground ml-1">{config.diarize ? "支持" : "不支持"}</span>
                </label>
              </div>
              <p className="text-[11px] text-muted-foreground mt-1">该引擎是否支持说话人分离识别</p>
            </div>
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">热词</label>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  role="switch"
                  aria-checked={config.hotwords_enabled ?? false}
                  onClick={() => {
                    const next = !(config.hotwords_enabled ?? false);
                    uc("hotwords_enabled", next);
                    if (!next) uc("hotwords", "");
                  }}
                  className="relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full transition-colors duration-200 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background bg-muted"
                >
                  <span className={cn(
                    "pointer-events-none block h-4 w-4 rounded-full shadow-lg ring-0 transition-transform duration-200",
                    (config.hotwords_enabled ?? false) ? "translate-x-[18px] bg-primary" : "translate-x-0.5 bg-background"
                  )} />
                </button>
                <label className="text-xs font-medium cursor-pointer" onClick={() => {
                  const next = !(config.hotwords_enabled ?? false);
                  uc("hotwords_enabled", next);
                  if (!next) uc("hotwords", "");
                }}>
                  <span className="text-xs text-muted-foreground ml-1">{(config.hotwords_enabled ?? false) ? "开启" : "关闭"}</span>
                </label>
              </div>
              <p className="text-[11px] text-muted-foreground mt-1">是否支持热词增强识别</p>
            </div>
          </div>
          {(config.hotwords_enabled ?? false) && (
            <div className="col-span-2">
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">热词配置</label>
              <input
                className={cn(inputCls, "w-full text-[11px]")}
                value={config.hotwords || ""}
                onChange={(e) => uc("hotwords", e.target.value)}
                placeholder="热词文件路径 (.txt) 或逗号分隔的热词"
              />
              <p className="text-[11px] text-muted-foreground mt-1">支持 .txt 文件路径（每行一个热词）或逗号分隔的热词列表</p>
            </div>
          )}
        </div>

        {/* Model Selection */}
        <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
          <div>
            <h4 className="text-sm font-semibold">模型</h4>
            <p className="text-[11px] text-muted-foreground mt-0.5">选择或手动添加 ASR 模型名称</p>
          </div>
          {isSDK && (
            <div>
              <label className="text-xs font-medium text-muted-foreground mb-1.5 block">当前模型</label>
              <input className={cn(inputCls, "w-full")} value={config.model || ""} onChange={(e) => uc("model", e.target.value)} placeholder="例如 large-v2" />
            </div>
          )}
          {modelList.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {modelList.map((m) => (
                <span key={m} className={cn(
                  "text-xs px-2.5 py-1 rounded-lg border cursor-pointer transition-colors",
                  config.model === m ? "border-primary bg-primary/10 text-primary font-medium" : "border-border/40 bg-muted/30 text-muted-foreground hover:border-primary/40"
                )} onClick={() => uc("model", m)}>
                  {m}
                </span>
              ))}
            </div>
          )}
          <div className="flex gap-2">
            <input className={cn(inputCls, "flex-1")} value={manualModel} onChange={(e) => setManualModel(e.target.value)} placeholder="手动添加模型名称" onKeyDown={(e) => e.key === "Enter" && addModel()} />
            <button onClick={addModel} className="px-3 py-1.5 text-xs font-medium border border-border/60 rounded-lg hover:bg-accent/60 transition-colors whitespace-nowrap">+ 添加</button>
          </div>
          {modelList.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {modelList.map((m) => (
                <span key={m} className="text-xs px-2 py-1 rounded-md bg-muted/40 text-muted-foreground flex items-center gap-1">
                  {m}
                  <button onClick={() => removeModel(m)} className="text-red-400/60 hover:text-red-400">&times;</button>
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Supported Languages */}
        <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h4 className="text-sm font-semibold">支持语言</h4>
              <p className="text-[11px] text-muted-foreground mt-0.5">该 ASR 引擎支持的语言列表</p>
            </div>
          </div>
          {!isSDK && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">语言列表 URL</label>
                <input className={cn(inputCls, "w-full")} value={config.language_list_url || ""} onChange={(e) => uc("language_list_url", e.target.value)} placeholder="https://..." />
              </div>
              <div>
                <label className="text-xs font-medium text-muted-foreground mb-1.5 block">Key 路径</label>
                <input className={cn(inputCls, "w-full")} value={config.language_list_key || ""} onChange={(e) => uc("language_list_key", e.target.value)} placeholder="例如 data.languages" />
              </div>
            </div>
          )}
          {isSDK && config.sdk_language_list_function && (
            <p className="text-[11px] text-muted-foreground">将使用 SDK 函数 <code className="text-primary">{config.sdk_language_list_function}</code> 获取语言列表</p>
          )}

          <button
            onClick={() => setShowLangPicker(true)}
            className="w-full flex items-center justify-center gap-2 px-4 py-3 border-2 border-dashed border-border/50 rounded-xl hover:border-primary/40 hover:bg-primary/5 transition-all duration-200 text-sm text-muted-foreground hover:text-primary"
          >
            <Languages className="w-4 h-4" />
            打开语言选择器
            {voiceList.length > 0 && (
              <span className="ml-1 px-2 py-0.5 text-xs bg-primary/10 text-primary rounded-full font-medium">
                已选 {voiceList.length} 项
              </span>
            )}
          </button>

          {voiceList.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {voiceList.slice(0, 20).map((v) => (
                <span key={v} className="text-xs px-2.5 py-1 rounded-lg border border-primary/40 bg-primary/10 text-primary font-medium">
                  {v}
                </span>
              ))}
              {voiceList.length > 20 && (
                <span className="text-xs text-muted-foreground">还有 {voiceList.length - 20} 项</span>
              )}
            </div>
          )}
        </div>

        {/* Custom Params */}
        <div className="rounded-2xl border border-border/50 bg-card/70 overflow-hidden">
          <div className="px-5 py-3 border-b border-border/40 flex items-center justify-between">
            <div>
              <h4 className="text-sm font-semibold">自定义参数</h4>
              <p className="text-[11px] text-muted-foreground mt-0.5">可扩展的键值对参数及默认值</p>
            </div>
            <button onClick={addCustomParam} className="px-3 py-1.5 text-xs font-semibold border border-border/60 rounded-lg hover:bg-accent/60 transition-colors">+ 添加</button>
          </div>
          {!hasCustomParams ? (
            <div className="px-5 py-6 text-center text-xs text-muted-foreground">暂无自定义参数</div>
          ) : (
            <div>
              <div className="flex items-center gap-3 px-5 py-2 border-b border-border/30 bg-muted/30">
                <div className="w-[15%] text-xs font-medium text-muted-foreground">键名</div>
                <div className="w-[15%] text-xs font-medium text-muted-foreground">默认值</div>
                <div className="flex-1 text-xs font-medium text-muted-foreground">参数说明</div>
                <div className="w-8"></div>
              </div>
              <div className="divide-y divide-border/30">
                {(config.custom_params || []).map((cp, idx) => (
                  <div key={idx} className="flex items-center gap-3 px-5 py-2.5">
                    <input className={cn("w-[15%]", inputCls)} value={cp.key} onChange={(e) => updateCP(idx, "key", e.target.value)} placeholder="key" />
                    <input className={cn("w-[15%]", inputCls)} value={cp.default} onChange={(e) => updateCP(idx, "default", e.target.value)} placeholder="default" />
                    <input className={cn("flex-1", inputCls)} value={cp.description} onChange={(e) => updateCP(idx, "description", e.target.value)} placeholder="描述" />
                    <button onClick={() => removeCP(idx)} className="p-1.5 rounded-lg text-red-500/60 hover:text-red-500 hover:bg-red-500/10 transition-colors" title="删除">
                      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Test Section */}
        <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
          <h4 className="text-sm font-semibold">测试接口</h4>
          <div className="flex items-center gap-3">
            <input ref={fileInputRef} type="file" accept="audio/*" className="hidden" onChange={handleTestUpload} />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={testLoading}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium border border-border/60 rounded-xl hover:bg-accent/60 transition-all duration-200 disabled:opacity-40"
            >
              <Upload className="w-4 h-4" />
              {testAudioPath ? "替换音频" : "上传音频"}
            </button>
            {testAudioPath && (
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <FileAudio className="w-3.5 h-3.5" />
                {testAudioPath.split(/[/\\]/).pop()}
              </span>
            )}
          </div>
          {testAudioPath && (
            <button
              onClick={handleRunTest}
              disabled={testLoading}
              className="px-4 py-2 text-sm font-semibold bg-emerald-500 text-white rounded-xl transition-all duration-200 hover:shadow-lg hover:shadow-emerald-500/25 active:scale-[0.97] disabled:opacity-40"
            >
              {testLoading ? "运行中..." : "运行 ASR 测试"}
            </button>
          )}
          {testError && <p className="text-xs text-red-500">{testError}</p>}
          {testResult && (
            <div className="rounded-xl border border-border/40 bg-muted/20 p-4 space-y-2">
              <div className="flex items-center gap-2 text-xs font-medium text-emerald-500">
                <span>测试完成 - 共 {testResult.segment_count || 0} 个片段</span>
              </div>
              {testResult.result?.segments && (
                <div className="max-h-40 overflow-y-auto space-y-1">
                  {testResult.result.segments.slice(0, 20).map((seg: any, i: number) => (
                    <div key={i} className="text-xs text-muted-foreground">
                      <span className="text-foreground/70">[{seg.start?.toFixed(1)}s - {seg.end?.toFixed(1)}s]</span>{" "}
                      {seg.text}
                    </div>
                  ))}
                  {testResult.result.segments.length > 20 && (
                    <p className="text-xs text-muted-foreground">... 还有 {testResult.result.segments.length - 20} 个片段</p>
                  )}
                </div>
              )}
              {(!testResult.result?.segments || testResult.result.segments.length === 0) && testResult.result?.text && (
                <div className="text-xs text-foreground/80 whitespace-pre-wrap break-words leading-relaxed">
                  {testResult.result.text}
                </div>
              )}
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

      {/* Language Picker Modal */}
      {showLangPicker && (
        <VoiceLanguagePicker
          title="选择支持语言"
          items={voiceList}
          selected={voiceList}
          onConfirm={handleLangConfirm}
          onCancel={() => setShowLangPicker(false)}
          fetchUrl={
            isSDK
              ? undefined
              : config.language_list_url || undefined
          }
          fetchKeyPath={isSDK ? undefined : config.language_list_key}
        />
      )}
    </div>
  );
}
