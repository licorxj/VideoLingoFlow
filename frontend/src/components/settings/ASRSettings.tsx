import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { asrInterfacesApi, ASRInterface } from "@/api/asrInterfaces";
import { settingsApi } from "@/api/settings";
import ASRInterfaceEditor from "./ASRInterfaceEditor";
import { cn } from "@/lib/utils";
import {
  Mic,
  Plus,
  Pencil,
  Trash2,
  Shield,
  Zap,
  CheckCircle2,
  Clock,
  Users,
  AudioLines,
  RefreshCw,
  Settings,
  Volume2,
  AlignLeft,
  UserCircle,
} from "lucide-react";

interface PostProcessConfig {
  vad: { enabled: boolean; engine: string };
  alignment: { enabled: boolean; engine: string };
  diarization: { enabled: boolean; engine: string };
}

const TYPE_LABELS: Record<string, string> = {
  local: "本地 API",
  sdk: "SDK",
};

function getCapabilityBadges(config: Record<string, any>): { label: string; color: string; icon?: string }[] {
  const badges: { label: string; color: string; icon?: string }[] = [];

  if (config.word_timestamps) {
    badges.push({ label: "词级时间戳", color: "bg-violet-500/10 text-violet-500" });
  }
  if (config.diarize) {
    badges.push({ label: "说话人识别", color: "bg-cyan-500/10 text-cyan-500" });
  }
  if (config.max_duration && config.max_duration > 0) {
    const mins = Math.floor(config.max_duration / 60);
    const secs = config.max_duration % 60;
    const label = mins > 0 ? (secs > 0 ? `${mins}m${secs}s` : `${mins}m`) : `${secs}s`;
    badges.push({ label: `最长${label}`, color: "bg-amber-500/10 text-amber-600" });
  }
  if (config.hotwords !== undefined) {
    badges.push({ label: "热词", color: "bg-emerald-500/10 text-emerald-600" });
  }
  if (config.use_itn) {
    badges.push({ label: "ITN", color: "bg-blue-500/10 text-blue-500" });
  }
  if (config.vad_model || config.vad_onset !== undefined) {
    badges.push({ label: "VAD", color: "bg-orange-500/10 text-orange-600" });
  }

  return badges;
}

export default function ASRSettings() {
  const [interfaces, setInterfaces] = useState<ASRInterface[]>([]);
  const [activeEngine, setActiveEngine] = useState("whisperx_local");
  const [editing, setEditing] = useState<ASRInterface | null>(null);
  const [showEditor, setShowEditor] = useState(false);
  const [postProcessConfig, setPostProcessConfig] = useState<PostProcessConfig>({
    vad: { enabled: false, engine: "fsmn" },
    alignment: { enabled: false, engine: "whisperx" },
    diarization: { enabled: false, engine: "pyannote" },
  });

  const load = async () => {
    const [ifaceRes, engineRes, vadEnabled, vadEngine, alignEnabled, alignEngine, diarizeEnabled, diarizeEngine] = await Promise.all([
      asrInterfacesApi.list(),
      settingsApi.get("asr.engine"),
      settingsApi.get("asr.post_process.vad.enabled"),
      settingsApi.get("asr.post_process.vad.engine"),
      settingsApi.get("asr.post_process.alignment.enabled"),
      settingsApi.get("asr.post_process.alignment.engine"),
      settingsApi.get("asr.post_process.diarization.enabled"),
      settingsApi.get("asr.post_process.diarization.engine"),
    ]);
    setInterfaces(ifaceRes.data.interfaces || []);
    setActiveEngine(engineRes.data.value || "whisperx_local");
    setPostProcessConfig({
      vad: { 
        enabled: vadEnabled.data.value === true || vadEnabled.data.value === "true", 
        engine: vadEngine.data.value || "silero" 
      },
      alignment: { 
        enabled: alignEnabled.data.value === true || alignEnabled.data.value === "true", 
        engine: alignEngine.data.value || "whisperx" 
      },
      diarization: { 
        enabled: diarizeEnabled.data.value === true || diarizeEnabled.data.value === "true", 
        engine: diarizeEngine.data.value || "pyannote" 
      },
    });
  };

  useEffect(() => {
    load();
  }, []);

  const handleSelect = async (id: string) => {
    setActiveEngine(id);
    await settingsApi.update("asr.engine", id);
  };

  const handleToggle = async (id: string, enabled: boolean) => {
    await asrInterfacesApi.toggle(id, enabled);
    load();
  };

  const handleDelete = async (id: string) => {
    if (!confirm("确定要删除此接口吗？")) return;
    await asrInterfacesApi.delete(id);
    load();
  };

  const handleEdit = (iface: ASRInterface) => {
    setEditing(iface);
    setShowEditor(true);
  };

  const handleAdd = () => {
    setEditing(null);
    setShowEditor(true);
  };

  const handleRefresh = async () => {
    await asrInterfacesApi.reload();
    load();
  };

  const handleSaved = () => {
    setShowEditor(false);
    setEditing(null);
    load();
  };

  const handlePostProcessChange = async (type: "vad" | "alignment" | "diarization", field: "enabled" | "engine", value: boolean | string) => {
    const newConfig = { ...postProcessConfig };
    newConfig[type] = { ...newConfig[type], [field]: value };
    setPostProcessConfig(newConfig);
    
    // Save to settings
    await settingsApi.update(`asr.post_process.${type}.${field}`, value);
  };

  return (
    <div className="space-y-5 stagger-children">
      {/* Active Engine Selector */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-3">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Zap className="w-4 h-4 text-primary" />
          当前 ASR 引擎
        </h3>
        <select
          className="w-full px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none appearance-none"
          value={activeEngine}
          onChange={(e) => handleSelect(e.target.value)}
        >
          {interfaces
            .filter((i) => i.enabled)
            .map((i) => (
              <option key={i.id} value={i.id}>
                {i.name}
              </option>
            ))}
        </select>
      </div>

      {/* Post-Processing Settings */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Settings className="w-4 h-4 text-primary" />
          后处理补全设置
        </h3>
        <p className="text-xs text-muted-foreground">
          当当前 ASR 引擎不支持某项能力时，自动使用备用模型进行补全
        </p>

        {/* VAD Fallback */}
        <div className="flex items-center justify-between p-3 rounded-xl border border-border/40 hover:border-border/60 transition-all duration-200">
          <div className="flex items-center gap-3">
            <Volume2 className="w-4 h-4 text-orange-500" />
            <div>
              <label className="text-sm font-medium">备用 VAD 模型</label>
              <p className="text-xs text-muted-foreground">语音活动检测</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <select
              className="px-3 py-1.5 border border-border/60 rounded-lg bg-background/50 text-xs focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none appearance-none"
              value={postProcessConfig.vad.engine}
              onChange={(e) => handlePostProcessChange("vad", "engine", e.target.value)}
            >
              <option value="silero">Silero VAD</option>
              <option value="fsmn">FSMN VAD</option>
              <option value="webrtc">WebRTC VAD</option>
            </select>
            <label className="relative cursor-pointer flex items-center">
              <input
                type="checkbox"
                checked={postProcessConfig.vad.enabled}
                onChange={(e) => handlePostProcessChange("vad", "enabled", e.target.checked)}
                className="peer sr-only"
              />
              <div className="w-9 h-5 bg-muted rounded-full peer-checked:bg-primary transition-colors duration-200" />
              <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-background rounded-full shadow-sm peer-checked:translate-x-4 transition-transform duration-200" />
            </label>
          </div>
        </div>

        {/* Alignment Fallback */}
        <div className="flex items-center justify-between p-3 rounded-xl border border-border/40 hover:border-border/60 transition-all duration-200">
          <div className="flex items-center gap-3">
            <AlignLeft className="w-4 h-4 text-violet-500" />
            <div>
              <label className="text-sm font-medium">备用词级对齐模型</label>
              <p className="text-xs text-muted-foreground">词级时间戳生成</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <select
              className="px-3 py-1.5 border border-border/60 rounded-lg bg-background/50 text-xs focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none appearance-none"
              value={postProcessConfig.alignment.engine}
              onChange={(e) => handlePostProcessChange("alignment", "engine", e.target.value)}
            >
              <option value="whisperx">WhisperX Alignment</option>
              <option value="qwen3">Qwen3 ForcedAligner</option>
              <option value="funasr">FunASR CT-Aligner</option>
            </select>
            <label className="relative cursor-pointer flex items-center">
              <input
                type="checkbox"
                checked={postProcessConfig.alignment.enabled}
                onChange={(e) => handlePostProcessChange("alignment", "enabled", e.target.checked)}
                className="peer sr-only"
              />
              <div className="w-9 h-5 bg-muted rounded-full peer-checked:bg-primary transition-colors duration-200" />
              <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-background rounded-full shadow-sm peer-checked:translate-x-4 transition-transform duration-200" />
            </label>
          </div>
        </div>

        {/* Diarization Fallback */}
        <div className="flex items-center justify-between p-3 rounded-xl border border-border/40 hover:border-border/60 transition-all duration-200">
          <div className="flex items-center gap-3">
            <UserCircle className="w-4 h-4 text-cyan-500" />
            <div>
              <label className="text-sm font-medium">备用说话人识别模型</label>
              <p className="text-xs text-muted-foreground">说话人分离</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <select
              className="px-3 py-1.5 border border-border/60 rounded-lg bg-background/50 text-xs focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none appearance-none"
              value={postProcessConfig.diarization.engine}
              onChange={(e) => handlePostProcessChange("diarization", "engine", e.target.value)}
            >
              <option value="pyannote">Pyannote</option>
              <option value="cam++">Cam++</option>
            </select>
            <label className="relative cursor-pointer flex items-center">
              <input
                type="checkbox"
                checked={postProcessConfig.diarization.enabled}
                onChange={(e) => handlePostProcessChange("diarization", "enabled", e.target.checked)}
                className="peer sr-only"
              />
              <div className="w-9 h-5 bg-muted rounded-full peer-checked:bg-primary transition-colors duration-200" />
              <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-background rounded-full shadow-sm peer-checked:translate-x-4 transition-transform duration-200" />
            </label>
          </div>
        </div>
      </div>

      {/* Interface List */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Mic className="w-4 h-4 text-primary" />
            接口列表
          </h3>
          <div className="flex items-center gap-2">
            <button
              onClick={handleRefresh}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium border border-border/60 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent/60 transition-all duration-200 active:scale-[0.97]"
              title="刷新接口数据"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              刷新
            </button>
            <button
              onClick={handleAdd}
              className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold bg-primary text-primary-foreground rounded-lg transition-all duration-200 hover:shadow-lg hover:shadow-primary/25 active:scale-[0.97]"
            >
              <Plus className="w-3.5 h-3.5" />
              添加接口
            </button>
          </div>
        </div>

        <div className="space-y-2">
          {interfaces.map((iface) => {
            const isActive = activeEngine === iface.id;
            return (
              <div
                key={iface.id}
                className={cn(
                  "flex items-center gap-3 p-4 rounded-xl border transition-all duration-200",
                  isActive
                    ? "border-primary/40 bg-primary/5"
                    : "border-border/40 hover:border-border/60"
                )}
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-sm">{iface.name}</span>
                    <span className="text-[11px] px-2 py-0.5 rounded-md bg-muted text-muted-foreground font-medium">
                      {TYPE_LABELS[iface.type] || iface.type}
                    </span>
                    {iface.builtin && (
                      <span className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-blue-500/10 text-blue-500 font-medium">
                        <Shield className="w-3 h-3" />
                        内置
                      </span>
                    )}
                    {isActive && (
                      <span className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-md bg-emerald-500/10 text-emerald-500 font-medium">
                        <CheckCircle2 className="w-3 h-3" />
                        当前
                      </span>
                    )}
                    {getCapabilityBadges(iface.config || {}).map((badge, i) => (
                      <span
                        key={i}
                        className={cn(
                          "text-[11px] px-2 py-0.5 rounded-md font-medium",
                          badge.color
                        )}
                      >
                        {badge.label}
                      </span>
                    ))}
                  </div>
                  <p className="text-xs text-muted-foreground mt-1">
                    {iface.description || "暂无描述"}
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <label className="relative cursor-pointer flex items-center gap-1.5">
                    <input
                      type="checkbox"
                      checked={iface.enabled}
                      onChange={(e) => handleToggle(iface.id, e.target.checked)}
                      className="peer sr-only"
                    />
                    <div className="w-8 h-[18px] bg-muted rounded-full peer-checked:bg-primary transition-colors duration-200" />
                    <div className="absolute left-0.5 top-0.5 w-3.5 h-3.5 bg-background rounded-full shadow-sm peer-checked:translate-x-[14px] transition-transform duration-200" />
                  </label>
                  <button
                    onClick={() => handleEdit(iface)}
                    className="p-1.5 rounded-lg border border-border/40 hover:bg-accent/60 text-muted-foreground hover:text-foreground transition-all duration-200"
                    title="编辑"
                  >
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  {!iface.builtin && (
                    <button
                      onClick={() => handleDelete(iface.id)}
                      className="p-1.5 rounded-lg border border-border/40 hover:bg-red-500/10 text-muted-foreground hover:text-red-500 transition-all duration-200"
                      title="删除"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Editor Modal */}
      {showEditor &&
        createPortal(
          <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 backdrop-blur-sm animate-fade-in overflow-y-auto py-10 px-4">
            <div className="bg-background border border-border/60 rounded-2xl shadow-2xl w-[min(880px,92vw)] animate-scale-in">
              <ASRInterfaceEditor
                iface={editing}
                onSaved={handleSaved}
                onCancel={() => setShowEditor(false)}
              />
            </div>
          </div>,
          document.body
        )}
    </div>
  );
}
