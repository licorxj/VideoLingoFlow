import { useState, useRef } from "react";
import { ttsInterfacesApi, TTSInterface } from "@/api/ttsInterfaces";
import { cn } from "@/lib/utils";
import { X, Play, Upload, FileAudio } from "lucide-react";

const MODE_LABELS: Record<string, string> = {
  clone: "声音克隆",
  voice_design: "声音设计",
  controllable_clone: "可控克隆",
  preset_voice: "预置音色",
};

interface Props {
  iface: TTSInterface;
  onClose: () => void;
}

export default function TTSInterfaceTestModal({ iface, onClose }: Props) {
  const [text, setText] = useState("这是一段测试语音，请听效果。This is a test voice.");
  const [mode, setMode] = useState("");
  const [speed, setSpeed] = useState<number | "">("");
  const [voice, setVoice] = useState("");
  const [refAudio, setRefAudio] = useState("");
  const [voiceDesign, setVoiceDesign] = useState("");
  const [controllableClone, setControllableClone] = useState("");
  const [playing, setPlaying] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [audioUrl, setAudioUrl] = useState("");
  const audioRef = useRef<HTMLAudioElement>(null);
  const refInputRef = useRef<HTMLInputElement>(null);

  const cfg = iface.config || {}; const voiceList = cfg.voice_options || [];
  const modes = cfg.modes || {};
  const enabledModes = Object.entries(modes).filter(([, v]) => v.enabled).map(([k]) => k);
  const needsRefAudio = mode === "clone" || mode === "controllable_clone";
  const needsVoiceDesign = mode === "voice_design";
  const needsControllableClone = mode === "controllable_clone";

  const getAudioUrl = (path: string) => {
    if (!path) return "";
    if (path.startsWith("http")) return path;
    const base = window.location.origin;
    return base + (path.startsWith("/") ? path : "/" + path);
  };

  const handleTest = async () => {
    if (!text.trim()) return;
    setLoading(true);
    setError("");
    setAudioUrl("");
    try {
      const resp = await ttsInterfacesApi.test(iface.id, {
        text,
        mode: mode || undefined,
        speed: speed !== "" ? speed : undefined,
        voice: voice || undefined,
        ref_audio: refAudio || undefined,
        voice_design: voiceDesign || undefined,
        controllable_clone: controllableClone || undefined,
      });
      if (resp.data.success && resp.data.audio_url) {
        setAudioUrl(getAudioUrl(resp.data.audio_url));
      } else {
        setError("测试失败：未返回音频");
      }
    } catch (e: any) {
      setError(e.response?.data?.detail || e.message || "测试失败");
    } finally {
      setLoading(false);
    }
  };

  const handleUploadRef = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const resp = await ttsInterfacesApi.uploadAudio(file);
      setRefAudio(resp.data.path);
    } catch (err: any) {
      setError("上传失败: " + err.message);
    }
  };

  const handlePlay = () => {
    if (audioRef.current) {
      if (playing) { audioRef.current.pause(); setPlaying(false); }
      else { audioRef.current.play(); setPlaying(true); }
    }
  };

  const inputCls = "px-3 py-2 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none w-full";
  const labelCls = "text-xs font-medium text-muted-foreground uppercase tracking-wider";

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm animate-fade-in">
      <div className="bg-background border border-border/60 rounded-2xl shadow-2xl w-[min(640px,92vw)] animate-scale-in">
        <div className="p-6 space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-lg font-bold">测试接口</h3>
              <p className="text-xs text-muted-foreground mt-1">
                {iface.name} ({iface.type === "local" ? "本地 API" : iface.type === "online" ? "OpenAI 格式" : "SDK"})
              </p>
            </div>
            <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-secondary transition-colors">
              <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
            </button>
          </div>

          {/* Mode Selection */}
          {enabledModes.length > 0 && (
            <div>
              <label className={labelCls}>模式</label>
              <div className="flex gap-1.5 mt-2 p-1 rounded-xl bg-muted/50 flex-wrap">
                <button onClick={() => setMode("")}
                  className={cn("px-3 py-1.5 rounded-lg text-xs font-semibold transition-all duration-200", mode === "" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
                  默认
                </button>
                {enabledModes.map((m) => (
                  <button key={m} onClick={() => setMode(m)}
                    className={cn("px-3 py-1.5 rounded-lg text-xs font-semibold transition-all duration-200", mode === m ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground")}>
                    {MODE_LABELS[m] || m}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Voice */}
          {voiceList.length > 0 && (mode === "" || mode === "preset_voice") && (
            <div>
              <label className={labelCls}>音色</label>
              <select className={inputCls + " mt-2"} value={voice} onChange={(e) => setVoice(e.target.value)}>
                <option value="">默认音色</option>
                {voiceList.map((v) => <option key={v} value={v}>{v}</option>)}
              </select>
            </div>
          )}

          {/* Reference Audio */}
          {needsRefAudio && (
            <div>
              <label className={labelCls}>参考音频</label>
              <div className="flex gap-2 mt-2">
                <input ref={refInputRef} type="file" accept="audio/*" className="hidden" onChange={handleUploadRef} />
                <button onClick={() => refInputRef.current?.click()} className="flex items-center gap-2 px-4 py-2 text-sm font-medium border border-border/60 rounded-xl hover:bg-accent/60 transition-all">
                  <Upload className="w-4 h-4" />
                  {refAudio ? "替换音频" : "上传参考音频"}
                </button>
                {refAudio && <span className="flex items-center gap-1.5 text-xs text-muted-foreground"><FileAudio className="w-3.5 h-3.5" />{refAudio.split(/[/\\]/).pop()}</span>}
              </div>
            </div>
          )}

          {/* Voice Design */}
          {needsVoiceDesign && (
            <div>
              <label className={labelCls}>声音设计指令</label>
              <textarea className={inputCls + " mt-2 min-h-[60px] resize-y"} value={voiceDesign} onChange={(e) => setVoiceDesign(e.target.value)} placeholder="描述期望的声音特征" />
            </div>
          )}

          {/* Controllable Clone */}
          {needsControllableClone && (
            <div>
              <label className={labelCls}>可控克隆指令</label>
              <textarea className={inputCls + " mt-2 min-h-[60px] resize-y"} value={controllableClone} onChange={(e) => setControllableClone(e.target.value)} placeholder="描述克隆控制参数" />
            </div>
          )}

          {/* Text Input */}
          <div>
            <label className={labelCls}>合成文本</label>
            <textarea className={inputCls + " mt-2 min-h-[80px] resize-y"} value={text} onChange={(e) => setText(e.target.value)} placeholder="输入要合成的文本" />
          </div>

          {/* Speed */}
          <div>
            <label className={labelCls}>语速</label>
            <input className={inputCls + " mt-2"} type="number" step="0.1" min="0.5" max="2.0" value={speed} onChange={(e) => setSpeed(e.target.value ? parseFloat(e.target.value) : "")} placeholder="1.0（默认）" />
          </div>

          {/* Error */}
          {error && <p className="text-xs text-red-500 bg-red-500/5 rounded-lg p-2">{error}</p>}

          {/* Audio Player */}
          {audioUrl && (
            <div className="rounded-xl border border-border/40 bg-muted/20 p-4 space-y-2">
              <audio ref={audioRef} src={audioUrl} onEnded={() => setPlaying(false)} className="w-full" controls />
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3 justify-end pt-2">
            <button onClick={onClose} className="px-5 py-2.5 text-sm font-medium border border-border/60 rounded-xl hover:bg-secondary/70 transition-all active:scale-[0.97]">关闭</button>
            <button onClick={handleTest} disabled={loading || !text.trim()}
              className="flex items-center gap-2 px-5 py-2.5 text-sm font-semibold bg-primary text-primary-foreground rounded-xl transition-all hover:shadow-lg hover:shadow-primary/25 active:scale-[0.97] disabled:opacity-40">
              <Play className="w-4 h-4" />
              {loading ? "测试中..." : "开始测试"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
