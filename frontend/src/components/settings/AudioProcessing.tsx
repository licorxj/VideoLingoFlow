import { useState, useEffect } from "react";
import { settingsApi } from "@/api/settings";
import { SlidersVertical, Scissors, Headphones } from "lucide-react";
import SeparationSettings from "./SeparationSettings";

export default function AudioProcessingSettings() {
  const [cutExtendTime, setCutExtendTime] = useState(0.1);
  const [peakCutEnabled, setPeakCutEnabled] = useState(true);
  const [peakCutWindow, setPeakCutWindow] = useState(1.0);
  const [denoiseEnabled, setDenoiseEnabled] = useState(true);

  // Output audio quality settings
  const [outputFormat, setOutputFormat] = useState("wav");
  const [bitrate, setBitrate] = useState(320);
  const [sampleRate, setSampleRate] = useState(48000);
  const [bitDepth, setBitDepth] = useState(16);

  useEffect(() => {
    Promise.all([
      settingsApi.get("audio.cut_extend_time"),
      settingsApi.get("audio.peak_cut_enabled"),
      settingsApi.get("audio.peak_cut_window"),
      settingsApi.get("audio.denoise_enabled"),
      settingsApi.get("audio.output_format"),
      settingsApi.get("audio.bitrate"),
      settingsApi.get("audio.sample_rate"),
      settingsApi.get("audio.bit_depth"),
    ]).then(([ext, peak, windowRes, denoise, fmt, br, sr, bd]) => {
      setCutExtendTime(ext.data.value ?? 0.1);
      setPeakCutEnabled(peak.data.value ?? true);
      setPeakCutWindow(windowRes.data.value ?? 1.0);
      setDenoiseEnabled(denoise.data.value ?? true);
      setOutputFormat(fmt.data.value || "wav");
      setBitrate(br.data.value ?? 320);
      setSampleRate(sr.data.value ?? 48000);
      setBitDepth(bd.data.value ?? 16);
    });
  }, []);

  const save = (k: string, v: any) => settingsApi.update(k, v);

  return (
    <div className="space-y-5 stagger-children">
      {/* Audio Cutting Section */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Scissors className="w-4 h-4 text-primary" />
          音频切割
        </h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              切割点延展（秒）
            </label>
            <p className="text-[10px] text-muted-foreground/60 mt-1">在切割点前后延展的时间，避免切断对话</p>
            <input
              type="number"
              step="0.01"
              min="0"
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
              value={cutExtendTime}
              onChange={(e) => setCutExtendTime(parseFloat(e.target.value) || 0)}
              onBlur={() => save("audio.cut_extend_time", cutExtendTime)}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              波谷寻找窗口（秒）
            </label>
            <p className="text-[10px] text-muted-foreground/60 mt-1">在切割点附近搜索波形能量最低点的窗口大小</p>
            <input
              type="number"
              step="0.1"
              min="0.1"
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none"
              value={peakCutWindow}
              onChange={(e) => setPeakCutWindow(parseFloat(e.target.value) || 1.0)}
              onBlur={() => save("audio.peak_cut_window", peakCutWindow)}
            />
          </div>
          <div className="flex items-end">
            <label className="flex items-center gap-3 cursor-pointer group w-full">
              <div className="relative flex-shrink-0">
                <input
                  type="checkbox"
                  checked={peakCutEnabled}
                  onChange={(e) => {
                    setPeakCutEnabled(e.target.checked);
                    save("audio.peak_cut_enabled", e.target.checked);
                  }}
                  className="peer sr-only"
                />
                <div className="w-9 h-5 bg-muted rounded-full peer-checked:bg-primary transition-colors duration-200" />
                <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-background rounded-full shadow-sm peer-checked:translate-x-4 transition-transform duration-200" />
              </div>
              <div className="flex flex-col">
                <span className="text-sm group-hover:text-foreground transition-colors">
                  波谷切割
                </span>
                <span className="text-[10px] text-muted-foreground/60">在静音点切割，避免切断对话</span>
              </div>
            </label>
          </div>
          <div className="flex items-end">
            <label className="flex items-center gap-3 cursor-pointer group w-full">
              <div className="relative flex-shrink-0">
                <input
                  type="checkbox"
                  checked={denoiseEnabled}
                  onChange={(e) => {
                    setDenoiseEnabled(e.target.checked);
                    save("audio.denoise_enabled", e.target.checked);
                  }}
                  className="peer sr-only"
                />
                <div className="w-9 h-5 bg-muted rounded-full peer-checked:bg-primary transition-colors duration-200" />
                <div className="absolute left-0.5 top-0.5 w-4 h-4 bg-background rounded-full shadow-sm peer-checked:translate-x-4 transition-transform duration-200" />
              </div>
              <div className="flex flex-col">
                <span className="text-sm group-hover:text-foreground transition-colors">
                  切割后音频去噪
                </span>
                <span className="text-[10px] text-muted-foreground/60">使用频谱减法去除背景噪声</span>
              </div>
            </label>
          </div>
        </div>
      </div>

      {/* Output Audio Quality Section */}
      <div className="rounded-2xl border border-border/50 bg-card/70 p-5 space-y-4">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Headphones className="w-4 h-4 text-primary" />
          输出音频质量
        </h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              输出格式
            </label>
            <p className="text-[10px] text-muted-foreground/60 mt-1">音频导出格式</p>
            <select
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none appearance-none"
              value={outputFormat}
              onChange={(e) => {
                setOutputFormat(e.target.value);
                save("audio.output_format", e.target.value);
              }}
            >
              <option value="wav">WAV (无损)</option>
              <option value="mp3">MP3 (有损)</option>
              <option value="flac">FLAC (无损压缩)</option>
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              比特率 (kbps)
            </label>
            <p className="text-[10px] text-muted-foreground/60 mt-1">音频编码比特率（MP3/FLAC）</p>
            <select
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none appearance-none"
              value={bitrate}
              onChange={(e) => {
                setBitrate(parseInt(e.target.value));
                save("audio.bitrate", parseInt(e.target.value));
              }}
            >
              <option value={128}>128 kbps</option>
              <option value={192}>192 kbps ★推荐</option>
              <option value={256}>256 kbps</option>
              <option value={320}>320 kbps</option>
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              采样率 (Hz)
            </label>
            <p className="text-[10px] text-muted-foreground/60 mt-1">音频采样率</p>
            <select
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none appearance-none"
              value={sampleRate}
              onChange={(e) => {
                setSampleRate(parseInt(e.target.value));
                save("audio.sample_rate", parseInt(e.target.value));
              }}
            >
              <option value={44100}>44100 Hz</option>
              <option value={48000}>48000 Hz</option>
              <option value={96000}>96000 Hz</option>
            </select>
          </div>
          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider">
              位深度 (bit)
            </label>
            <p className="text-[10px] text-muted-foreground/60 mt-1">音频量化位深</p>
            <select
              className="w-full mt-2 px-3.5 py-2.5 border border-border/60 rounded-xl bg-background/50 text-sm focus:border-primary/50 focus:ring-2 focus:ring-primary/10 transition-all duration-200 outline-none appearance-none"
              value={bitDepth}
              onChange={(e) => {
                setBitDepth(parseInt(e.target.value));
                save("audio.bit_depth", parseInt(e.target.value));
              }}
            >
              <option value={16}>16 bit ★推荐</option>
              <option value={24}>24 bit</option>
              <option value={32}>32 bit</option>
            </select>
          </div>
        </div>
      </div>

      {/* Vocal Separation Interfaces Section */}
      <SeparationSettings />
    </div>
  );
}
