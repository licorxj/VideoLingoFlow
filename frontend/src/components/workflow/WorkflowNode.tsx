import { memo, useState, useCallback, useEffect, useRef, useMemo } from "react";
import { createPortal } from "react-dom";
import SubtitleParser from "srt-parser-2";
import { nativeFileDialog } from "@/api/files";
import { LANGUAGE_OPTIONS } from "@/lib/languages";
import { Handle, Position, useReactFlow } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";
import { cn } from "@/lib/utils";
import client from "@/api/client";
import { useWorkflowStore } from "@/stores/workflowStore";
import {
  getNodeTypeDef, PORT_COLORS, getVisibleOutputs, getNodeInputs, isConfigFieldVisible,
  PI_AGENT_OUTPUT_TYPES,
  type WorkflowNode as WFNode, type ConfigField, type PortType,
} from "@/lib/workflowTypes";
import VoiceSelectPanel from "../VoiceSelectPanel";
import AudioSelectorDialog from "@/components/AudioSelectorDialog";
import {
  Film, Music, Subtitles, Mic, Mic2, Scissors, Brain, Languages,
  FileText, Volume2, Merge, Clapperboard, Image, Stamp, Download,
  Upload, Wrench, CheckCircle2, Loader2, XCircle, Clock, AlertTriangle, Play,
  ChevronDown, ChevronRight, Eye, ArrowRight, Sparkles, Maximize2, HelpCircle,
  CheckSquare, Square, Users, FolderOpen, ExternalLink, FileJson,
} from "lucide-react";
import JsonEditorDialog from "./JsonEditorDialog";
import TextEditorDialog from "./TextEditorDialog";
import SubtitleEditorDialog from "./SubtitleEditorDialog";
import { LcwrWatermarkEditor } from "./LcwrWatermarkEditor";

const ICON_MAP: Record<string, any> = {
  Film, Music, Subtitles, Mic, Mic2, Scissors, Brain, Languages,
  FileText, Volume2, Merge, Clapperboard, Image, Stamp, Download,
  Upload, Wrench, Play, Eye, Sparkles, FolderOpen,
};

/** 解析 SRT/VTT/JSON 字幕内容为 [{start, end, text}]（时间为秒），支持双语（原文/译文两行） */
function parseSubtitleEntries(content: string): { start: number; end: number; text: string }[] {
  const trimmed = content.trim();
  if (!trimmed) return [];
  // JSON（项目双语字幕格式）
  try {
    const data = JSON.parse(trimmed);
    let list: any[] = [];
    if (Array.isArray(data)) list = data;
    else if (data && typeof data === "object") {
      for (const key of ["segments", "items", "subtitles", "entries"]) {
        if (Array.isArray(data[key])) { list = data[key]; break; }
      }
    }
    if (list.length > 0) {
      return list
        .filter((item) => item && typeof item === "object" && item.start !== undefined && item.end !== undefined)
        .map((item) => {
          const original = item.text ?? item.origin ?? item.original ?? item.src ?? item.content ?? "";
          const translated = item.translation ?? item.translate ?? item.translated ?? item.tr ?? item.direct ?? item.reflect ?? "";
          const parts = [String(original).trim(), String(translated).trim()].filter(Boolean);
          return {
            start: Number(item.start) || 0,
            end: Number(item.end) || 0,
            text: parts.join("\n"),
          };
        });
    }
  } catch { /* 非 JSON，走成熟库解析 SRT */ }
  try {
    const lines = new SubtitleParser().fromSrt(trimmed);
    return lines.map((l) => ({
      start: Number(l.startSeconds) || 0,
      end: Number(l.endSeconds) || 0,
      text: String(l.text || ""),
    }));
  } catch {
    return [];
  }
}

const STATUS_CONFIG: Record<string, { icon: any; color: string; bg: string; border: string; glow: string; label: string; badgeBg: string; badgeText: string }> = {
  pending: {
    icon: Clock, color: "text-muted-foreground", bg: "bg-muted/30",
    border: "", glow: "",
    label: "等待中",
    badgeBg: "bg-muted/60", badgeText: "text-muted-foreground",
  },
  running: {
    icon: Loader2, color: "text-blue-500", bg: "bg-blue-500/5",
    border: "border-blue-400 shadow-[0_0_12px_rgba(59,130,246,0.25)]",
    glow: "ring-2 ring-blue-400/30",
    label: "执行中",
    badgeBg: "bg-blue-500/15", badgeText: "text-blue-600",
  },
  waiting: {
    icon: Clock, color: "text-amber-600", bg: "bg-amber-500/5",
    border: "border-amber-400 shadow-[0_0_12px_rgba(245,158,11,0.2)]",
    glow: "",
    label: "等待剪辑",
    badgeBg: "bg-amber-500/15", badgeText: "text-amber-700",
  },
  completed: {
    icon: CheckCircle2, color: "text-emerald-500", bg: "bg-emerald-500/5",
    border: "!border-[4px] border-emerald-400 shadow-[0_0_14px_rgba(16,185,129,0.3)]",
    glow: "",
    label: "已完成",
    badgeBg: "bg-emerald-500/15", badgeText: "text-emerald-600",
  },
  failed: {
    icon: XCircle, color: "text-red-500", bg: "bg-red-500/5",
    border: "border-red-400 shadow-[0_0_12px_rgba(239,68,68,0.25)]",
    glow: "",
    label: "失败",
    badgeBg: "bg-red-500/15", badgeText: "text-red-600",
  },
  skipped: {
    icon: Clock, color: "text-yellow-500", bg: "bg-yellow-500/5",
    border: "border-yellow-400",
    glow: "",
    label: "已跳过",
    badgeBg: "bg-yellow-500/15", badgeText: "text-yellow-600",
  },
  cancelled: {
    icon: AlertTriangle, color: "text-orange-500", bg: "bg-orange-500/5",
    border: "border-orange-400 shadow-[0_0_10px_rgba(249,115,22,0.2)]",
    glow: "",
    label: "已取消",
    badgeBg: "bg-orange-500/15", badgeText: "text-orange-600",
  },
};

const CHIP_COLORS: Record<string, string> = {
  video: "#3b82f6",
  audio: "#10b981",
  subtitle: "#f59e0b",
  url: "#06b6d4",
};

/** 生成稳定的文件流 URL，仅在 path 或 refreshKey 变化时添加新的 cache-bust 时间戳；
 *  相对产物路径需带上 task_id，让后端相对任务工作区解析（见 /api/files/stream）。 */
function useStableFileUrl(path?: string, taskId?: string, refreshKey?: string): string {
  const cacheRef = useRef<{ key: string; url: string }>({ key: "", url: "" });
  return useMemo(() => {
    if (!path) return "";
    const compositeKey = `${path}|${taskId || ""}|${refreshKey || ""}`;
    if (cacheRef.current.key === compositeKey) return cacheRef.current.url;
    const params = new URLSearchParams({ path });
    if (taskId) params.set("task_id", taskId);
    params.set("t", String(Date.now()));
    const url = `/api/files/stream?${params.toString()}`;
    cacheRef.current = { key: compositeKey, url };
    return url;
  }, [path, taskId, refreshKey]);
}

function VideoPreview({ config, videoPath, subtitlePath, taskId, onConfigChange, refreshKey }: { config: Record<string, any>; videoPath?: string; subtitlePath?: string; taskId?: string; onConfigChange?: (key: string, value: any) => void; refreshKey?: string }) {
  const [fontSize, setFontSize] = useState(config.fontSize || 24);
  const [subtitles, setSubtitles] = useState<{ start: number; end: number; text: string }[]>([]);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const videoSrc = useStableFileUrl(videoPath, taskId, refreshKey);

  // 阻止节点内输入元素的拖拽和滚轮事件冒泡到 React Flow（原生捕获阶段）
  const previewRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) return;
    const stop = (e: Event) => e.stopPropagation();
    const opts: AddEventListenerOptions = { capture: true };
    for (const el of node.querySelectorAll("input, textarea, select")) {
      el.addEventListener("pointerdown", stop, opts);
      el.addEventListener("wheel", stop, opts);
    }
  }, []);

  useEffect(() => {
    setFontSize(config.fontSize || 24);
  }, [config.fontSize]);

  useEffect(() => {
    if (!subtitlePath) {
      setSubtitles([]);
      return;
    }
    client.get("/api/files/read", { params: { path: subtitlePath, task_id: taskId || undefined } }).then((res) => {
      const content = res.data?.content || "";
      const parsed = parseSRT(content);
      setSubtitles(parsed);
    }).catch(() => setSubtitles([]));
  }, [subtitlePath, taskId]);

  const parseSRT = (srt: string) => {
    const blocks = srt.trim().split(/\n\s*\n/);
    return blocks.map((block) => {
      const lines = block.trim().split("\n");
      if (lines.length < 3) return null;
      const timeMatch = lines[1].match(/(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})/);
      if (!timeMatch) return null;
      const start = parseInt(timeMatch[1]) * 3600 + parseInt(timeMatch[2]) * 60 + parseInt(timeMatch[3]) + parseInt(timeMatch[4]) / 1000;
      const end = parseInt(timeMatch[5]) * 3600 + parseInt(timeMatch[6]) * 60 + parseInt(timeMatch[7]) + parseInt(timeMatch[8]) / 1000;
      const text = lines.slice(2).join("\n");
      return { start, end, text };
    }).filter(Boolean) as { start: number; end: number; text: string }[];
  };

  const currentSub = subtitles.find((s) => currentTime >= s.start && currentTime <= s.end);

  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  };

  const togglePlay = () => {
    if (!videoRef.current) return;
    if (isPlaying) {
      videoRef.current.pause();
    } else {
      videoRef.current.play();
    }
    setIsPlaying(!isPlaying);
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!videoRef.current) return;
    const time = parseFloat(e.target.value);
    videoRef.current.currentTime = time;
    setCurrentTime(time);
  };

  const toggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen().then(() => setIsFullscreen(true)).catch(() => {});
    } else {
      document.exitFullscreen().then(() => setIsFullscreen(false)).catch(() => {});
    }
  };

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  if (!videoPath) {
    return (
      <div className="px-3 pb-3 border-t border-border/50 pt-2">
        <div className="text-[11px] text-muted-foreground/70 text-center py-4">请连接视频输入</div>
      </div>
    );
  }

  return (
    <div ref={previewRef} className="px-3 pb-3 border-t border-border/50 pt-2 space-y-2">
      {/* 标题输入框 */}
      <div className="flex items-center gap-2">
        <label className="text-[11px] font-medium text-muted-foreground whitespace-nowrap">标题</label>
        <input
          type="text"
          value={config.title || ""}
          onChange={(e) => onConfigChange?.("title", e.target.value)}
          placeholder="输入视频标题..."
          onPointerDown={(e) => e.stopPropagation()}
          onWheel={(e) => e.stopPropagation()}
          className="flex-1 h-6 text-[11px] px-2 rounded border border-border/50 bg-background focus:border-primary/50 focus:outline-none"
        />
      </div>
      {/* 字幕设置并排显示 */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2">
          <label className="text-[11px] font-medium text-muted-foreground">字幕字号</label>
          <button
            onClick={() => setFontSize((s: number) => Math.max(12, s - 2))}
            className="px-1.5 py-0.5 text-[10px] rounded bg-secondary/50 hover:bg-secondary transition-colors"
          >A-</button>
          <span className="text-[11px] font-mono w-6 text-center">{fontSize}</span>
          <button
            onClick={() => setFontSize((s: number) => Math.min(72, s + 2))}
            className="px-1.5 py-0.5 text-[10px] rounded bg-secondary/50 hover:bg-secondary transition-colors"
          >A+</button>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-[11px] font-medium text-muted-foreground">字幕位置</label>
          <select
            value={config.subtitlePosition || "bottom"}
            onChange={(e) => onConfigChange?.("subtitlePosition", e.target.value)}
            onPointerDown={(e) => e.stopPropagation()}
            onWheel={(e) => e.stopPropagation()}
            className="h-6 text-[11px] px-1.5 rounded border border-border/50 bg-background focus:border-primary/50 focus:outline-none"
          >
            <option value="top">顶部</option>
            <option value="middle">中间</option>
            <option value="bottom">底部</option>
          </select>
        </div>
      </div>
      <div ref={containerRef} className={`relative rounded-lg overflow-hidden bg-black group ${isFullscreen ? "w-full h-full flex items-center justify-center" : ""}`}>
        <video
          ref={videoRef}
          src={videoSrc}
          className={`w-full object-contain ${isFullscreen ? "max-h-full" : "max-h-[200px]"}`}
          onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
          onPlay={() => setIsPlaying(true)}
          onPause={() => setIsPlaying(false)}
        />
        {currentSub && (
          <div
            className="absolute left-0 right-0 text-center px-2 pointer-events-none"
            style={{
              [config.subtitlePosition === "top" ? "top" : config.subtitlePosition === "middle" ? "top" : "bottom"]: config.subtitlePosition === "middle" ? "50%" : "8px",
              transform: config.subtitlePosition === "middle" ? "translateY(-50%)" : undefined,
              fontSize: `${fontSize}px`,
              color: config.fontColor || "#ffffff",
              fontFamily: config.fontFamily || "sans-serif",
              textShadow: "1px 1px 2px rgba(0,0,0,0.8)",
            }}
          >
            <span className="bg-black/60 px-2 py-0.5 rounded" style={{ whiteSpace: "pre-line" }}>{currentSub.text}</span>
          </div>
        )}
        {/* 全屏按钮 */}
        <button
          onClick={toggleFullscreen}
          className="absolute bottom-2 right-2 w-7 h-7 rounded-md flex items-center justify-center bg-black/50 text-white/80 hover:bg-black/70 hover:text-white transition-all opacity-0 group-hover:opacity-100"
          title="全屏播放"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4" />
          </svg>
        </button>
      </div>
      {/* Custom Controls */}
      <div className="flex items-center gap-2 px-1">
        <button
          onClick={togglePlay}
          className="w-6 h-6 rounded-full flex items-center justify-center bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
        >
          {isPlaying ? (
            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
              <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
            </svg>
          ) : (
            <svg className="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
              <path d="M8 5v14l11-7z" />
            </svg>
          )}
        </button>
        <span className="text-[10px] font-mono text-muted-foreground/70 w-10">{formatTime(currentTime)}</span>
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.1}
          value={currentTime}
          onChange={handleSeek}
          onPointerDown={(e) => e.stopPropagation()}
          onWheel={(e) => e.stopPropagation()}
          className="flex-1 h-1 rounded-full appearance-none cursor-pointer accent-primary bg-secondary"
        />
        <span className="text-[10px] font-mono text-muted-foreground/70 w-10">{formatTime(duration)}</span>
      </div>
      {!subtitlePath && (
        <div className="text-[10px] text-muted-foreground/70 text-center">连接字幕输入以显示字幕</div>
      )}
    </div>
  );
}

function ImagePreview({ config, imagePath, taskId, refreshKey }: { config: Record<string, any>; imagePath?: string; taskId?: string; refreshKey?: string }) {
  const imageSrc = useStableFileUrl(imagePath, taskId, refreshKey);
  const [broken, setBroken] = useState(false);
  useEffect(() => { setBroken(false); }, [imageSrc]);
  if (!imagePath) {
    return (
      <div className="px-3 pb-3 border-t border-border/50 pt-2">
        <div className="text-[11px] text-muted-foreground/70 text-center py-4">请连接图片输入</div>
      </div>
    );
  }

  return (
    <div className="px-3 pb-3 border-t border-border/50 pt-2">
      <div className="rounded-lg overflow-hidden bg-black/5">
        {broken ? (
          <div className="grid h-[120px] place-items-center text-[11px] text-muted-foreground/70">预览文件不存在或已删除</div>
        ) : (
          <img
            src={imageSrc}
            alt="Preview"
            className="w-full max-h-[200px]"
            style={{ objectFit: config.fit || "contain" }}
            onError={() => setBroken(true)}
          />
        )}
      </div>
    </div>
  );
}

function ApiSelectField({ field, value, config, onConfigChange }: { field: ConfigField; value: string; config: Record<string, any>; onConfigChange: (key: string, value: any) => void }) {
  const [apiOptions, setApiOptions] = useState<{value: string; label: string; description?: string}[]>([]);
  const [apiLoading, setApiLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [hoveredOption, setHoveredOption] = useState<string | null>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  // Resolve dynamic API endpoint with parameter substitution
  const resolveEndpoint = (endpoint: string): string => {
    if (!endpoint) return "";
    return endpoint.replace(/\{(\w+)\}/g, (_, key) => {
      const val = config[key];
      // Handle array values (e.g., tts_mode is ["preset_voice"])
      if (Array.isArray(val)) {
        return val[0] || "";
      }
      return val || "";
    });
  };

  const rawEndpoint = field.apiEndpoint || field.apiUrl || "";
  const fetchKey = resolveEndpoint(rawEndpoint);
  const dependsValue = config[field.dependsOn || ""];

  useEffect(() => {
    if (fetchKey && !fetchKey.includes("{")) {
      setApiLoading(true);
      client.get(fetchKey).then((res) => {
        const resData = res.data || {};
        let allItems: {value: string; label: string; description?: string}[] = [];
        const optionLabel = field.optionLabel || "label";
        const optionValue = field.optionValue || "value";

        const mapOptionList = (items: any[]) => items.map((item) => {
          if (typeof item === "string") {
            return { value: item, label: item, description: "" };
          }
          const mappedValue = item?.[optionValue] ?? item?.value ?? item?.id ?? item?.name;
          const mappedLabel = item?.[optionLabel] ?? item?.label ?? item?.name ?? mappedValue;
          const mappedDesc = item?.description ?? "";
          return { value: String(mappedValue ?? ""), label: String(mappedLabel ?? ""), description: String(mappedDesc) };
        }).filter((item) => item.value);

        if (Array.isArray(resData)) {
          allItems = mapOptionList(resData);
        } else if (Array.isArray(resData.options)) {
          allItems = mapOptionList(resData.options);
        } else if (Array.isArray(resData.items)) {
          allItems = mapOptionList(resData.items);
        } else if (Array.isArray(resData.presets)) {
          allItems = mapOptionList(resData.presets);
        } else if (Array.isArray(resData.voices)) {
          allItems = mapOptionList(resData.voices);
        }

        // Handle { interfaces: [...] } shape (from /enabled or /asr-interfaces)
        if (!allItems.length && resData.interfaces && Array.isArray(resData.interfaces)) {
          for (const iface of resData.interfaces) {
            allItems.push({ value: iface.id, label: iface.name, description: iface.description || "" });
          }
        } else if (!allItems.length) {
          // Handle { models_by_engine: {...} } or { models: {...} } shape
          const engineKey = config[field.dependsOn || ""] || "";
          
          // Check for model_details_by_engine first (for separation models with descriptions)
          if (resData.model_details_by_engine && resData.model_details_by_engine[engineKey]) {
            allItems = resData.model_details_by_engine[engineKey];
          } else {
            let optionsMap = resData.models_by_engine || resData.models || resData.options || {};
            if (field.key === "compute_type" && resData.compute_types_by_engine) {
              optionsMap = resData.compute_types_by_engine;
            }
            const items: string[] = optionsMap[engineKey] || [];
            allItems = items.map((m: string) => ({ value: m, label: m, description: "" }));
            if (!engineKey) {
              const merged: Record<string, boolean> = {};
              for (const arr of Object.values(optionsMap) as string[][]) {
                for (const m of arr) { if (!merged[m]) { merged[m] = true; allItems.push({ value: m, label: m, description: "" }); } }
              }
            }
          }
        }
        setApiOptions(allItems);
        
        // If current value is not in the new options, clear it
        if (value && !allItems.some((opt) => opt.value === value)) {
          onConfigChange(field.key, "");
        }
      }).catch(() => {}).finally(() => setApiLoading(false));
    }
  }, [fetchKey, dependsValue, config.tts_engine]);

  const selectedLabel = apiOptions.find(opt => opt.value === value)?.label || (apiLoading ? "加载中..." : field.placeholder || "请选择");
  const hasDescriptions = apiOptions.some(opt => opt.description);

  // If no descriptions, use native select for better UX
  if (!hasDescriptions) {
    return (
      <div>
        <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
        <select
          value={value}
          onChange={(e) => onConfigChange(field.key, e.target.value)}
          onPointerDown={(e) => e.stopPropagation()}
          onWheel={(e) => e.stopPropagation()}
          className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 outline-none transition-all"
        >
          <option value="">{apiLoading ? "加载中..." : field.placeholder || "请选择"}</option>
          {apiOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>
    );
  }

  // Custom dropdown with tooltip support
  return (
    <div className="relative" ref={dropdownRef}>
      <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        onPointerDown={(e) => e.stopPropagation()}
        className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 outline-none transition-all text-left flex items-center justify-between"
      >
        <span className={!value ? "text-muted-foreground/70" : ""}>{selectedLabel}</span>
        <ChevronDown className={`w-3 h-3 text-muted-foreground/70 transition-transform ${isOpen ? "rotate-180" : ""}`} />
      </button>
      {isOpen && (
        <div className="absolute z-50 w-full mt-1 bg-background border border-border/50 rounded-md shadow-lg max-h-[200px] overflow-y-auto">
          {apiOptions.map((opt) => (
            <div
              key={opt.value}
              onMouseEnter={() => setHoveredOption(opt.value)}
              onMouseLeave={() => setHoveredOption(null)}
              onClick={() => {
                onConfigChange(field.key, opt.value);
                setIsOpen(false);
              }}
              className={`px-2.5 py-1.5 text-xs cursor-pointer hover:bg-primary/10 ${opt.value === value ? "bg-primary/10 text-primary" : ""}`}
            >
              <div>{opt.label}</div>
              {hoveredOption === opt.value && opt.description && (
                <div className="text-[10px] text-muted-foreground/80 mt-1 border-t border-border/50 pt-1">{opt.description}</div>
              )}
            </div>
          ))}
          {apiOptions.length === 0 && !apiLoading && (
            <div className="px-2.5 py-1.5 text-xs text-muted-foreground/70">无可用选项</div>
          )}
        </div>
      )}
    </div>
  );
}

/** 账号选择弹窗组件 - 按平台分组，支持全选/取消全选/清空 */
function AccountSelectField({ field, value, onConfigChange }: { field: ConfigField; value: string[]; onConfigChange: (key: string, value: any) => void }) {
  const [open, setOpen] = useState(false);
  const [accounts, setAccounts] = useState<{ value: string; label: string; platform: string; name: string; type: number }[]>([]);
  const [loading, setLoading] = useState(false);
  const selected: string[] = Array.isArray(value) ? value : [];

  const fetchAccounts = () => {
    setLoading(true);
    const endpoint = field.apiEndpoint || "/api/publish/accounts/all";
    client.get(endpoint).then((res) => {
      const data = res.data || {};
      const items = data.options || data.items || data || [];
      setAccounts(Array.isArray(items) ? items : []);
    }).catch(() => setAccounts([])).finally(() => setLoading(false));
  };

  const handleOpen = () => {
    setOpen(true);
    fetchAccounts();
  };

  // 按平台分组
  const grouped = accounts.reduce<Record<string, typeof accounts>>((acc, item) => {
    const key = item.platform || "未知平台";
    (acc[key] ??= []).push(item);
    return acc;
  }, {});

  const toggleAccount = (val: string) => {
    const next = selected.includes(val) ? selected.filter((v) => v !== val) : [...selected, val];
    onConfigChange(field.key, next);
  };

  const selectAll = () => onConfigChange(field.key, accounts.map((a) => a.value));
  const deselectAll = () => onConfigChange(field.key, []);
  const togglePlatform = (platform: string) => {
    const platformVals = (grouped[platform] || []).map((a) => a.value);
    const allSelected = platformVals.every((v) => selected.includes(v));
    if (allSelected) {
      onConfigChange(field.key, selected.filter((v) => !platformVals.includes(v)));
    } else {
      const newSet = new Set([...selected, ...platformVals]);
      onConfigChange(field.key, [...newSet]);
    }
  };

  const btnLabel = selected.length > 0
    ? `已选 ${selected.length} 个账号`
    : field.placeholder || "点击选择发布账号";

  return (
    <>
      <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
      <button
        type="button"
        onClick={handleOpen}
        onPointerDown={(e) => e.stopPropagation()}
        className={cn(
          "w-full text-xs px-2.5 py-1.5 rounded-md border text-left transition-all flex items-center gap-2",
          selected.length > 0
            ? "border-primary/50 bg-primary/5 text-foreground"
            : "border-border/50 bg-background text-muted-foreground"
        )}
      >
        <Users className="w-3.5 h-3.5 flex-shrink-0" />
        <span className="truncate">{btnLabel}</span>
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onPointerDown={(e) => e.stopPropagation()}>
          <div className="bg-card border border-border/50 rounded-xl shadow-2xl w-[480px] max-h-[70vh] flex flex-col" onPointerDown={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-border/50">
              <span className="text-sm font-semibold">选择发布账号</span>
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-muted-foreground">已选 {selected.length}/{accounts.length}</span>
                <button onClick={() => setOpen(false)} className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/60 transition-colors">
                  <XCircle className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Action buttons */}
            <div className="flex items-center gap-2 px-4 py-2 border-b border-border/50">
              <button onClick={selectAll} className="px-2 py-1 text-[11px] rounded-md bg-primary/10 text-primary hover:bg-primary/20 transition-colors">全选</button>
              <button onClick={deselectAll} className="px-2 py-1 text-[11px] rounded-md bg-secondary/60 text-muted-foreground hover:bg-secondary transition-colors">取消全选</button>
              <button onClick={() => onConfigChange(field.key, [])} className="px-2 py-1 text-[11px] rounded-md bg-red-500/10 text-red-500 hover:bg-red-500/20 transition-colors">清空</button>
            </div>

            {/* Account list */}
            <div className="flex-1 overflow-y-auto px-4 py-2 space-y-3">
              {loading && (
                <div className="text-center py-6 text-[11px] text-muted-foreground">加载中...</div>
              )}
              {!loading && accounts.length === 0 && (
                <div className="text-center py-6 text-[11px] text-muted-foreground">请到发布标签页添加账号</div>
              )}
              {!loading && Object.entries(grouped).map(([platform, items]) => {
                const platformVals = items.map((a) => a.value);
                const allChecked = platformVals.every((v) => selected.includes(v));
                const someChecked = platformVals.some((v) => selected.includes(v));
                return (
                  <div key={platform}>
                    <div
                      className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-secondary/30 cursor-pointer hover:bg-secondary/50 transition-colors select-none"
                      onClick={() => togglePlatform(platform)}
                    >
                      {allChecked ? (
                        <CheckSquare className="w-3.5 h-3.5 text-primary" />
                      ) : someChecked ? (
                        <div className="w-3.5 h-3.5 rounded-sm border-2 border-primary bg-primary/30" />
                      ) : (
                        <Square className="w-3.5 h-3.5 text-muted-foreground/50" />
                      )}
                      <span className="text-[11px] font-semibold text-foreground">{platform}</span>
                      <span className="text-[10px] text-muted-foreground ml-auto">
                        {items.filter((a) => selected.includes(a.value)).length}/{items.length}
                      </span>
                    </div>
                    <div className="ml-4 space-y-0.5 mt-1">
                      {items.map((acc) => {
                        const checked = selected.includes(acc.value);
                        return (
                          <div
                            key={acc.value}
                            className="flex items-center gap-2 px-2 py-1 rounded-md cursor-pointer hover:bg-secondary/30 transition-colors select-none"
                            onClick={() => toggleAccount(acc.value)}
                          >
                            {checked ? (
                              <CheckSquare className="w-3.5 h-3.5 text-primary" />
                            ) : (
                              <Square className="w-3.5 h-3.5 text-muted-foreground/50" />
                            )}
                            <span className="text-[11px] text-foreground">{acc.name}</span>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Footer */}
            <div className="flex justify-end px-4 py-3 border-t border-border/50">
              <button
                onClick={() => setOpen(false)}
                className="px-3 py-1.5 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
              >
                确定
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function ConfigForm({ nodeType, config, onConfigChange, onVoiceSelect, onButtonAction }: {
  nodeType: any;
  config: Record<string, any>;
  onConfigChange: (key: string, value: any) => void;
  onVoiceSelect?: (field: ConfigField) => void;
  onButtonAction?: (field: ConfigField) => void;
}) {
  const [dynamicFields, setDynamicFields] = useState<ConfigField[]>([]);
  const [dynamicLoading, setDynamicLoading] = useState(false);
  const [expandField, setExpandField] = useState<{ key: string; label: string; value: string } | null>(null);
  const [audioSelectorOpen, setAudioSelectorOpen] = useState(false);
  const [audioSelectorField, setAudioSelectorField] = useState<{ key: string; label: string } | null>(null);
  const [actionState, setActionState] = useState<Record<string, { busy: boolean; ok?: boolean; message?: string }>>({});
  const modalTextareaRef = useRef<HTMLTextAreaElement>(null);
  const textareaRefs = useRef<Record<string, HTMLTextAreaElement | null>>({});
  const [piSkillOptions, setPiSkillOptions] = useState<{ value: string; label: string }[]>([]);
  const [piMcpOptions, setPiMcpOptions] = useState<{ value: string; label: string }[]>([]);

  // pi_agent：从 Pi Agent 设置拉取已授权 Skill/MCP 选项
  useEffect(() => {
    if (nodeType.id !== "pi_agent") return;
    client.get("/api/pi/settings").then((res) => {
      const data = (res.data || {}) as { skills?: { name: string }[]; mcps?: { name: string }[] };
      setPiSkillOptions((data.skills || []).map((item) => ({ value: item.name, label: item.name })));
      setPiMcpOptions((data.mcps || []).map((item) => ({ value: item.name, label: item.name })));
    }).catch(() => undefined);
  }, [nodeType.id]);

  // chips 动作按钮：调用后端接口（如安装即梦插件）
  const handleChipAction = useCallback(async (field: ConfigField) => {
    const act = field.action;
    if (!act) return;
    setActionState((s) => ({ ...s, [field.key]: { busy: true } }));
    try {
      const res = (act.method || "POST").toLowerCase() === "get"
        ? await client.get(act.url)
        : await client.post(act.url);
      const data = (res.data as any) || {};
      const ok = !!data.installed;
      setActionState((s) => ({
        ...s,
        [field.key]: { busy: false, ok, message: data.message || data.detail || (ok ? "已完成" : "未完成") },
      }));
    } catch (err: any) {
      const msg = err?.response?.data?.detail || err?.message || "请求失败";
      setActionState((s) => ({ ...s, [field.key]: { busy: false, ok: false, message: msg } }));
    }
  }, []);

  // 弹窗 textarea 原生事件拦截（阻止 React Flow 全局拖拽）
  useEffect(() => {
    const el = modalTextareaRef.current;
    if (!el) return;
    const stop = (e: Event) => e.stopPropagation();
    const opts: AddEventListenerOptions = { capture: true };
    el.addEventListener("pointerdown", stop, opts);
    el.addEventListener("mousedown", stop, opts);
    el.addEventListener("wheel", stop, opts);
    return () => {
      el.removeEventListener("pointerdown", stop, opts);
      el.removeEventListener("mousedown", stop, opts);
      el.removeEventListener("wheel", stop, opts);
    };
  }, [expandField]);

  // 阻止节点内输入元素的拖拽和滚轮事件冒泡到 React Flow（原生捕获阶段）
  const formRef = useCallback((node: HTMLDivElement | null) => {
    if (!node) return;
    const stop = (e: Event) => e.stopPropagation();
    const opts: AddEventListenerOptions = { capture: true };
    for (const el of node.querySelectorAll("input, textarea, select")) {
      el.addEventListener("pointerdown", stop, opts);
      el.addEventListener("wheel", stop, opts);
    }
  }, []);

  // Fetch dynamic config fields from API if nodeType has dynamicConfigEndpoint
  useEffect(() => {
    const endpoint = nodeType.dynamicConfigEndpoint;
    if (endpoint) {
      setDynamicLoading(true);
      client.get(endpoint).then((res) => {
        const data = res.data;
        // Build config fields from API response
        const fields: ConfigField[] = [];
        if (data.engine_options) {
          fields.push({ key: "engine", label: "ASR 引擎", type: "select", placeholder: "跟随全局配置", options: data.engine_options });
        }
        if (data.models_by_engine) {
          fields.push({ key: "model", label: "模型", type: "api-select", apiEndpoint: endpoint, dependsOn: "engine", placeholder: "跟随引擎默认" });
        }
        if (data.compute_types_by_engine) {
          fields.push({ key: "compute_type", label: "计算精度", type: "api-select", apiEndpoint: endpoint, dependsOn: "engine", placeholder: "跟随全局配置" });
        }
        // Common ASR fields
        fields.push({ key: "language", label: "识别语言", type: "select", placeholder: "跟随输入节点", options: [
          { value: "from_input", label: "来自输入节点" },
          { value: "auto", label: "自动检测(auto)" },
          { value: "zh", label: "中文 (zh)" },
          { value: "en", label: "英语 (en)" },
          { value: "ja", label: "日语 (ja)" },
          { value: "ko", label: "韩语 (ko)" },
          { value: "fr", label: "法语 (fr)" },
          { value: "de", label: "德语 (de)" },
          { value: "es", label: "西班牙语 (es)" },
          { value: "pt", label: "葡萄牙语 (pt)" },
          { value: "ru", label: "俄语 (ru)" },
        ] });
        fields.push({ key: "batch_size", label: "批处理大小", type: "text", placeholder: "0=自动检测GPU显存" });
        fields.push({ key: "word_timestamps", label: "启用词级时间戳对齐", type: "checkbox" });
        fields.push({ key: "vad_onset", label: "VAD 起始阈值", type: "text", placeholder: "0.500" });
        fields.push({ key: "vad_offset", label: "VAD 结束阈值", type: "text", placeholder: "0.363" });
        setDynamicFields(fields);
      }).catch(() => {}).finally(() => setDynamicLoading(false));
    }
  }, []);

  const configFields = (() => {
    const base = (dynamicFields.length > 0 ? dynamicFields : nodeType.configFields) || [];
    if (nodeType.id !== "pi_agent") return base;
    return base
       .filter((field: ConfigField) => field.key !== "inputCount" && field.key !== "outputCount")
       .map((field: ConfigField) => {
         if (field.key === "skills" && piSkillOptions.length) return { ...field, options: piSkillOptions };
         if (field.key === "mcps" && piMcpOptions.length) return { ...field, options: piMcpOptions };
         return field;
       });
  })();
  // LCWR 去水印节点使用自定义编辑器（LcwrWatermarkEditor），跳过通用表单渲染
  if (nodeType.id === "lcwr_watermark_removal") return null;
  if (configFields.length === 0 && !dynamicLoading) return null;

  const fieldSpanClass = (field: ConfigField) => {
    if (field.colSpan === "half") return "col-span-3";
    if (field.colSpan === "third") return "col-span-2";
    return "col-span-6";
  };

  return (
    <>
    <div ref={formRef} className="px-3 pb-3 grid grid-cols-6 gap-x-3 gap-y-2 border-t border-border/50 pt-2">
      {dynamicLoading && (
        <div className="col-span-2 text-[11px] text-muted-foreground/70 py-1">加载配置中...</div>
      )}
      {configFields.map((field: ConfigField) => {
        if (!isConfigFieldVisible(field, config)) return null;

        // Chips / toggle group
        if (field.type === "chips") {
          const selected: string[] = config[field.key] || [];
          const isSingle = field.singleSelect;
          return (
            <div key={field.key} className={fieldSpanClass(field)}>
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
              <div className="flex flex-wrap gap-1.5">
                {field.options?.map((opt) => {
                  const isSelected = selected.includes(opt.value);
                  const chipColor = CHIP_COLORS[opt.value] || field.chipColor || "#6b7280";
                  return (
                    <button
                      key={opt.value}
                      type="button"
                      onClick={() => {
                        let next: string[];
                        if (isSingle) {
                          // 单选模式：直接选择当前
                        next = [opt.value];
                        } else {
                          // 多选模式
                          if (isSelected) {
                            next = selected.filter((v) => v !== opt.value);
                            if (next.length === 0) next = [opt.value]; // at least one
                          } else {
                            next = [...selected, opt.value];
                          }
                        }
                        onConfigChange(field.key, next);
                      }}
                      className={cn(
                        "px-3 py-1.5 rounded-lg text-xs font-medium border transition-all duration-150",
                        isSelected
                          ? "text-white shadow-sm"
                          : "text-muted-foreground border-border/50 bg-background hover:border-primary/25"
                      )}
                      style={isSelected ? {
                        backgroundColor: chipColor,
                        borderColor: chipColor,
                        boxShadow: `0 1px 4px ${chipColor}33`,
                      } : undefined}
                    >
                      {opt.label}
                    </button>
                  );
                })}
                {field.action && (() => {
                  const st = actionState[field.key];
                  return (
                    <button
                      key="__chips_action__"
                      type="button"
                      disabled={st?.busy}
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={(e) => { e.stopPropagation(); handleChipAction(field); }}
                      className={cn(
                        "inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all",
                        st?.busy
                          ? "opacity-60 cursor-wait text-purple-500 border-purple-500/40 bg-purple-500/5"
                          : st?.ok
                            ? "text-emerald-600 dark:text-emerald-400 border-emerald-500/40 bg-emerald-500/5 hover:bg-emerald-500/10"
                            : "text-purple-600 dark:text-purple-400 border-purple-500/40 bg-purple-500/5 hover:bg-purple-500/10"
                      )}
                      title={st?.message}
                    >
                      {st?.busy ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : st?.ok ? (
                        <CheckCircle2 className="w-3 h-3" />
                      ) : (
                        <Download className="w-3 h-3" />
                      )}
                      {st?.busy ? (field.action.busyLabel || "执行中...") : field.action.label}
                    </button>
                  );
                })()}
                {field.link && (
                  <a
                    key="__chips_link__"
                    href={field.link.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    title={field.link.url}
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={(e) => e.stopPropagation()}
                    className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-medium text-sky-600 dark:text-sky-400 border border-sky-500/40 bg-sky-500/5 hover:bg-sky-500/10 transition-all"
                  >
                    <ExternalLink className="w-3 h-3" />
                    {field.link.label || "访问"}
                  </a>
                )}
              </div>
            </div>
          );
        }

        if (field.type === "button") {
          return (
            <div key={field.key} className={fieldSpanClass(field)}>
              {field.description && (
                <p className="text-[11px] text-muted-foreground mb-1.5 leading-snug">{field.description}</p>
              )}
              <button
                type="button"
                onClick={(e) => { e.stopPropagation(); onButtonAction?.(field); }}
                onPointerDown={(e) => e.stopPropagation()}
                className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-medium rounded-md border border-primary/40 bg-primary/10 text-primary hover:bg-primary/20 transition-colors"
              >
                <FileJson className="w-3.5 h-3.5" />
                {field.label}
              </button>
            </div>
          );
        }

        const value = config[field.key] ?? "";

        if (field.type === "language-select") {
          return (
            <div key={field.key} className={fieldSpanClass(field)}>
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
              <select
                value={value || "auto"}
                onChange={(e) => onConfigChange(field.key, e.target.value)}
                onPointerDown={(e) => e.stopPropagation()}
                onWheel={(e) => e.stopPropagation()}
                className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 outline-none transition-all"
              >
                {LANGUAGE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          );
        }

        if (field.type === "file") {
          return (
            <div key={field.key} className={fieldSpanClass(field)}>
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
              <div className="flex gap-1">
                <input
                  type="text"
                  value={value}
                  onChange={(e) => onConfigChange(field.key, e.target.value)}
                  placeholder={field.placeholder}
                  onPointerDown={(e) => e.stopPropagation()}
                  onWheel={(e) => e.stopPropagation()}
                  className="flex-1 text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all"
                />
                <button
                  onClick={async () => {
                    // Determine if this is a folder selector (outputDir, cookie_file, etc.)
                    const isFolder = field.key === "outputDir" || (field.fileFilter && field.fileFilter.length === 0);
                    const filterArr: [string, string][] = (field.fileFilter || []).map((f: string) => [f, f] as [string, string]);
                    const path = await nativeFileDialog(
                      isFolder ? "folder" : "file",
                      field.label || "Select",
                      filterArr
                    );
                    if (path) onConfigChange(field.key, path);
                  }}
                  className="px-2 py-1 text-[10px] rounded-md bg-primary/10 text-primary hover:bg-primary/20 border border-primary/30 transition-colors flex-shrink-0"
                >
                  Browse
                </button>
              </div>
            </div>
          );
        }

        if (field.type === "hotwords") {
          return (
            <div key={field.key} className="col-span-2">
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
              <div className="flex gap-1">
                <textarea
                  value={value}
                  onChange={(e) => onConfigChange(field.key, e.target.value)}
                  placeholder={field.placeholder}
                  onPointerDown={(e) => e.stopPropagation()}
                  onWheel={(e) => e.stopPropagation()}
                  rows={2}
                  className="flex-1 text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all resize-none"
                />
                <button
                  onClick={async () => {
                    const path = await nativeFileDialog("file", "选择热词文件", [["Text", "*.txt"]]);
                    if (typeof path === "string" && path) {
                      try {
                        const res = await client.get("/api/files/read", { params: { path } });
                        const content: string = res.data?.content || "";
                        // Convert newline-separated words to semicolon-separated
                        const hotwords = content.split(/\r?\n/).map(w => w.trim()).filter(Boolean).join(";");
                        onConfigChange(field.key, hotwords);
                      } catch (e) {
                        console.error("Failed to read hotwords file:", e);
                      }
                    }
                  }}
                  className="px-2 py-1 text-[10px] rounded-md bg-primary/10 text-primary hover:bg-primary/20 border border-primary/30 transition-colors flex-shrink-0 self-start mt-0.5"
                >
                  加载文件
                </button>
              </div>
            </div>
          );
        }

        if (field.type === "text") {
          // Special handling for path_to_title node's template field
          const isPathTemplate = nodeType.id === "path_to_title" && field.key === "template";
          const pathPlaceholders = [
            { key: "filename", label: "文件名", placeholder: "{filename}" },
            { key: "parent", label: "父文件夹", placeholder: "{parent}" },
            { key: "grandparent", label: "父父文件夹", placeholder: "{grandparent}" },
          ];

          return (
            <div key={field.key} className={fieldSpanClass(field)}>
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
              <div className="relative group">
                <input
                  type="text"
                  value={value}
                  onChange={(e) => onConfigChange(field.key, e.target.value)}
                  placeholder={field.placeholder}
                  onPointerDown={(e) => e.stopPropagation()}
                  onWheel={(e) => e.stopPropagation()}
                  className="w-full text-xs px-2.5 py-1.5 pr-7 rounded-md border border-border/50 bg-background focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all"
                />
                <button
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={() => setExpandField({ key: field.key, label: field.label, value: value || "" })}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 p-1 rounded text-muted-foreground/70 hover:text-primary opacity-0 group-hover:opacity-100 transition-opacity"
                  title="放大编辑"
                >
                  <Maximize2 className="w-3 h-3" />
                </button>
              </div>
              {isPathTemplate && (
                <div className="flex flex-wrap gap-1 mt-1.5">
                  {pathPlaceholders.map((p) => (
                    <button
                      key={p.key}
                      type="button"
                      onPointerDown={(e) => e.stopPropagation()}
                      onClick={() => {
                        const newValue = (value || "") + p.placeholder;
                        onConfigChange(field.key, newValue);
                      }}
                      className="px-2 py-0.5 rounded-md text-[10px] font-medium bg-purple-500/10 text-purple-600 hover:bg-purple-500/20 border border-purple-500/30 transition-colors"
                      title={`插入 ${p.placeholder} 到模板`}
                    >
                      {p.label}
                    </button>
                  ))}
                </div>
              )}
              {field.description && (
                <p className="text-[10px] text-muted-foreground/70 mt-1">{field.description}</p>
              )}
            </div>
          );
        }

        if (field.type === "datetime-local") {
          return (
            <div key={field.key} className={fieldSpanClass(field)}>
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
              <input
                type="datetime-local"
                value={value}
                onChange={(e) => onConfigChange(field.key, e.target.value)}
                onPointerDown={(e) => e.stopPropagation()}
                onWheel={(e) => e.stopPropagation()}
                className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all"
              />
            </div>
          );
        }

        if (field.type === "date") {
          return (
            <div key={field.key} className={fieldSpanClass(field)}>
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
              <input
                type="date"
                value={value}
                onChange={(e) => onConfigChange(field.key, e.target.value)}
                onPointerDown={(e) => e.stopPropagation()}
                onWheel={(e) => e.stopPropagation()}
                className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all"
              />
            </div>
          );
        }

        if (field.type === "time") {
          return (
            <div key={field.key} className={fieldSpanClass(field)}>
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
              <input
                type="time"
                value={value}
                onChange={(e) => onConfigChange(field.key, e.target.value)}
                onPointerDown={(e) => e.stopPropagation()}
                onWheel={(e) => e.stopPropagation()}
                className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all"
              />
            </div>
          );
        }

        if (field.type === "textarea") {
          return (
            <div key={field.key} className={fieldSpanClass(field)}>
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
              {field.chips && field.chips.length > 0 && (
                <div className="flex flex-wrap gap-1 mb-1.5">
                  {field.chips.map((chip) => (
                    <button
                      key={chip.value}
                      type="button"
                      onClick={() => {
                        const textarea = textareaRefs.current[field.key];
                        const cur = typeof value === "string" ? value : "";
                        const start = textarea?.selectionStart ?? cur.length;
                        const end = textarea?.selectionEnd ?? cur.length;
                        onConfigChange(field.key, cur.slice(0, start) + chip.value + cur.slice(end));
                        requestAnimationFrame(() => {
                          textarea?.focus();
                          textarea?.setSelectionRange(start + chip.value.length, start + chip.value.length);
                        });
                      }}
                      className="px-2 py-0.5 text-[10px] rounded-full border border-primary/30 bg-primary/10 text-primary hover:bg-primary/20 transition-colors cursor-pointer"
                      title={`插入 ${chip.value}`}
                    >
                      {chip.label}
                    </button>
                  ))}
                </div>
              )}
              <div className="relative group">
                <textarea
                  ref={(element) => { textareaRefs.current[field.key] = element; }}
                  value={value}
                  onChange={(e) => onConfigChange(field.key, e.target.value)}
                  placeholder={field.placeholder}
                  rows={3}
                  onPointerDown={(e) => e.stopPropagation()}
                  onWheel={(e) => e.stopPropagation()}
                  className="w-full text-xs px-2.5 py-1.5 pr-7 rounded-md border border-border/50 bg-background focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all resize-none"
                />
                <button
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={() => setExpandField({ key: field.key, label: field.label, value: value || "" })}
                  className="absolute right-1.5 bottom-1.5 p-1 rounded text-muted-foreground/70 hover:text-primary opacity-0 group-hover:opacity-100 transition-opacity"
                  title="放大编辑"
                >
                  <Maximize2 className="w-3 h-3" />
                </button>
              </div>
            </div>
          );
        }

        if (field.type === "select") {
          return (
            <div key={field.key} className={fieldSpanClass(field)}>
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
              <select
                value={value}
                onChange={(e) => onConfigChange(field.key, e.target.value)}
                onPointerDown={(e) => e.stopPropagation()}
                onWheel={(e) => e.stopPropagation()}
                className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 outline-none transition-all"
              >
                {field.options?.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          );
        }

        if (field.type === "api-select") {
          return <div key={field.key} className={fieldSpanClass(field)}><ApiSelectField field={field} value={value} config={config} onConfigChange={onConfigChange} /></div>;
        }

        if (field.type === "multiselect") {
          const selectedValues: string[] = Array.isArray(value) ? value : (value ? [String(value)] : []);
          const options = field.options || [];
          return (
            <div key={field.key} className={fieldSpanClass(field)}>
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
              <div className="rounded-md border border-border/50 bg-background">
                <div className="flex flex-wrap gap-1 px-2 py-1.5 min-h-[30px]">
                  {selectedValues.length === 0 && (
                    <span className="text-[11px] text-muted-foreground/70">{field.placeholder || "自行选择"}</span>
                  )}
                  {selectedValues.map((sv) => (
                    <span key={sv} className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-md bg-primary/10 text-primary">
                      {options.find((o) => o.value === sv)?.label || sv}
                      <button
                        type="button"
                        onPointerDown={(e) => e.stopPropagation()}
                        onClick={(e) => { e.stopPropagation(); onConfigChange(field.key, selectedValues.filter((v) => v !== sv)); }}
                        className="hover:text-destructive"
                      >×</button>
                    </span>
                  ))}
                </div>
                <select
                  multiple
                  value={selectedValues}
                  onChange={(e) => {
                    const next = Array.from(e.target.selectedOptions).map((o) => o.value);
                    onConfigChange(field.key, next);
                  }}
                  onPointerDown={(e) => e.stopPropagation()}
                  onWheel={(e) => e.stopPropagation()}
                  className="w-full text-[11px] px-2 py-1 border-t border-border/40 bg-background outline-none"
                >
                  {options.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
              {field.description && <p className="text-[10px] text-muted-foreground mt-1">{field.description}</p>}
            </div>
          );
        }

        if (field.type === "account-select") {
          return <div key={field.key} className={fieldSpanClass(field)}><AccountSelectField field={field} value={value} onConfigChange={onConfigChange} /></div>;
        }

        if (field.type === "voice-select") {
          const selectedVoice = value || "";
          return (
            <div key={field.key} className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">{field.label}</label>
              <button
                type="button"
                onClick={() => onVoiceSelect?.(field)}
                className="w-full px-3 py-2 border border-border/50 bg-background rounded-xl text-sm text-left hover:border-primary/50 transition-colors"
              >
                {selectedVoice || "点击选择音色..."}
              </button>
              {field.description && (
                <p className="text-[10px] text-muted-foreground">{field.description}</p>
              )}
            </div>
          );
        }

        if (field.type === "checkbox" || field.type === "toggle") {
          const nextField = configFields[configFields.indexOf(field) + 1];
          const hasInlineNext = nextField?.inline;
          return (
            <div key={field.key} className={`${fieldSpanClass(field)} flex items-center gap-2`}>
              <input
                type="checkbox"
                checked={!!value}
                onChange={(e) => onConfigChange(field.key, e.target.checked)}
                className="w-3 h-3 rounded border-border/50 bg-background accent-primary"
              />
              <label className="text-[11px] font-medium text-muted-foreground">{field.label}</label>
              {hasInlineNext && (
                <div className="flex items-center gap-1 ml-auto">
                  <span className="text-[11px] text-muted-foreground">{nextField.label}</span>
                  <input
                    type="number"
                    min={nextField.min}
                    max={nextField.max}
                    step={nextField.step}
                    value={config[nextField.key] ?? ""}
                    onChange={(e) => onConfigChange(nextField.key, parseInt(e.target.value) || 0)}
                    className="w-16 text-xs px-1.5 py-0.5 rounded-md border border-border/50 bg-background focus:border-primary/50 outline-none transition-all"
                  />
                </div>
              )}
            </div>
          );
        }

        if (field.type === "slider") {
          const min = field.min ?? 0;
          const max = field.max ?? 100;
          const step = field.step ?? 1;
          return (
            <div key={field.key} className={fieldSpanClass(field)}>
              <div className="flex items-center justify-between mb-1">
                <label className="text-[11px] font-medium text-muted-foreground">{field.label}</label>
                <span className="text-[11px] font-mono text-muted-foreground">{value ?? min}</span>
              </div>
              <input
                type="range"
                min={min}
                max={max}
                step={step}
                value={value ?? min}
                onChange={(e) => onConfigChange(field.key, parseFloat(e.target.value))}
                onPointerDown={(e) => e.stopPropagation()}
                onWheel={(e) => e.stopPropagation()}
                className="w-full h-1.5 rounded-full appearance-none cursor-pointer accent-primary bg-secondary"
              />
            </div>
          );
        }

        if (field.type === "number") {
          // Skip rendering if this field is marked as inline (already rendered with previous toggle)
          if (field.inline) return null;
          return (
            <div key={field.key} className={fieldSpanClass(field)}>
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
              <input
                type="number"
                min={field.min}
                max={field.max}
                step={field.step}
                value={value ?? ""}
                onChange={(e) => onConfigChange(field.key, parseFloat(e.target.value) || 0)}
                placeholder={field.placeholder}
                onPointerDown={(e) => e.stopPropagation()}
                onWheel={(e) => e.stopPropagation()}
                className="w-full text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background focus:border-primary/50 focus:ring-1 focus:ring-primary/20 outline-none transition-all"
              />
            </div>
          );
        }

        if (field.type === "audio-selector") {
          return (
            <div key={field.key} className={fieldSpanClass(field)}>
              <label className="text-[11px] font-medium text-muted-foreground block mb-1">{field.label}</label>
              <div className="flex items-center gap-1.5">
                <input
                  type="text"
                  value={value ? String(value) : ""}
                  readOnly
                  placeholder="未选择音频"
                  title={value ? String(value) : ""}
                  className="flex-1 text-xs px-2.5 py-1.5 rounded-md border border-border/50 bg-background text-muted-foreground cursor-not-allowed truncate"
                />
                <button
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={() => setAudioSelectorField({ key: field.key, label: field.label })}
                  className="px-2.5 py-1.5 text-[11px] font-medium rounded-md border border-border/50 bg-background hover:bg-primary/10 hover:border-primary/30 text-primary transition-all flex-shrink-0"
                >
                  <Music className="w-3 h-3 inline mr-1" />
                  选择
                </button>
              </div>
            </div>
          );
        }

        return null;
      })}

    </div>

    {expandField && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onPointerDown={(e) => e.stopPropagation()}>
        <div className="bg-card border border-border/50 rounded-xl shadow-2xl w-[600px] max-h-[80vh] flex flex-col" onPointerDown={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-between px-4 py-3 border-b border-border/50">
            <span className="text-sm font-semibold">{expandField.label}</span>
            <button onClick={() => setExpandField(null)} className="p-1 rounded-md text-muted-foreground hover:text-foreground hover:bg-secondary/60 transition-colors">
              <XCircle className="w-4 h-4" />
            </button>
          </div>
          <div className="flex-1 p-4 overflow-auto">
            <textarea
              ref={modalTextareaRef}
              value={expandField.value}
              onChange={(e) => {
                onConfigChange(expandField.key, e.target.value);
                setExpandField((f) => f ? { ...f, value: e.target.value } : null);
              }}
              className="w-full h-full min-h-[300px] text-sm p-3 rounded-lg border border-border/50 bg-background resize-none outline-none focus:border-primary/50 focus:ring-1 focus:ring-primary/20"
              autoFocus
            />
          </div>
          <div className="flex justify-end px-4 py-3 border-t border-border/50">
            <button
              onClick={() => setExpandField(null)}
              className="px-3 py-1.5 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
            >
              完成
            </button>
          </div>
        </div>
      </div>
    )}

    {audioSelectorField && createPortal(
      <AudioSelectorDialog
        open={true}
        onClose={() => setAudioSelectorField(null)}
        onSelect={(path) => {
          onConfigChange(audioSelectorField.key, path);
          setAudioSelectorField(null);
        }}
      />
      , document.body
    )}
    </>
  );
}

function WorkflowNodeComponent({ data, id, selected }: NodeProps) {
  const nd = data as any;
  const nodeType = getNodeTypeDef(nd.nodeType);
  const { updateNodeData, getNodes, getEdges } = useReactFlow();
  const [expanded, setExpanded] = useState(true);
  const [jsonPreviewOpen, setJsonPreviewOpen] = useState(false);
  const [voiceSelectField, setVoiceSelectField] = useState<any>(null);
  const [showDesc, setShowDesc] = useState(false);
  const [editingNote, setEditingNote] = useState(false);
  const [noteText, setNoteText] = useState(nd.note || "");
  const [jsonEditorOpen, setJsonEditorOpen] = useState(false);
  const [editorInitialJson, setEditorInitialJson] = useState<any>({});
  const [textEditorOpen, setTextEditorOpen] = useState(false);
  const [textEditorInitialText, setTextEditorInitialText] = useState("");
  const [subtitleEditorOpen, setSubtitleEditorOpen] = useState(false);
  const [subtitleEditorEntries, setSubtitleEditorEntries] = useState<any[]>([]);
  const [subtitleEditorVideo, setSubtitleEditorVideo] = useState("");

  if (!nodeType) return null;

  // Get upstream node outputs for preview nodes
  const getUpstreamOutputs = useCallback(() => {
    const edges = getEdges();
    const nodes = getNodes();
    const incomingEdges = edges.filter((e) => e.target === id);
    const outputs: Record<string, any> = {};
    const configs: Record<string, any> = {};
    const statuses: string[] = [];

    // File extension heuristics for matching output ports to actual files
    const VIDEO_EXTS = [".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv"];
    const SUBTITLE_EXTS = [".srt", ".ass", ".ssa", ".vtt", ".sub"];
    const IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"];
    const isVideoFile = (p: string) => VIDEO_EXTS.some((ext) => p.toLowerCase().endsWith(ext));
    const isSubtitleFile = (p: string) => SUBTITLE_EXTS.some((ext) => p.toLowerCase().endsWith(ext));
    const isImageFile = (p: string) => IMAGE_EXTS.some((ext) => p.toLowerCase().endsWith(ext));

    for (const edge of incomingEdges) {
      const sourceNode = nodes.find((n) => n.id === edge.source);
      const targetHandle = edge.targetHandle || "";
      if (!sourceNode?.data?.outputs) continue;
      const srcOutputs = sourceNode.data.outputs as Record<string, any>;
      const srcStatus = (sourceNode.data as any)?.status;
      if (srcStatus) statuses.push(srcStatus);

      // 1. Exact key match (sourceHandle -> outputs key)
      const srcHandle = edge.sourceHandle || "";
      const srcKey = srcHandle.replace(/^out-/, "");
      const tgtKey = targetHandle.replace(/^(in|out)-/, "");
      if (srcKey && srcOutputs[srcKey] !== undefined) {
        outputs[tgtKey || targetHandle || srcHandle] = srcOutputs[srcKey];
        continue;
      }
      // Also try raw sourceHandle
      if (srcHandle && srcOutputs[srcHandle] !== undefined) {
        outputs[tgtKey || targetHandle || srcHandle] = srcOutputs[srcHandle];
        continue;
      }

      // 2. Type-based matching: find first output file matching the target port type
      const allPaths = Object.values(srcOutputs).filter(
        (v): v is string => typeof v === "string"
      );
      let matched = false;
      // Normalize targetHandle: strip in-/out- prefix for type matching and output key
      const targetType = targetHandle.replace(/^(in|out)-/, "");
      if (targetType === "video") {
        const found = allPaths.find(isVideoFile);
        if (found) { outputs[targetType] = found; matched = true; }
      } else if (["subtitle", "original", "bilingual"].includes(targetType)) {
        const found = allPaths.find(isSubtitleFile);
        if (found) { outputs[targetType] = found; matched = true; }
      } else if (targetType === "image") {
        const found = allPaths.find(isImageFile);
        if (found) { outputs[targetType] = found; matched = true; }
      }

      // 3. Last resort: take the first file path output
      if (!matched && allPaths.length > 0) {
        outputs[targetType || "first"] = allPaths[0];
      }

      // Also check config for input nodes
      if (sourceNode?.data?.config) {
        Object.assign(configs, sourceNode.data.config);
      }
    }
    return { outputs, configs, refreshKey: statuses.join("|") };
  }, [id, getNodes, getEdges]);

  // For preview nodes, get paths from upstream outputs or configs
  const { outputs: upstreamOutputs, configs: upstreamConfigs, refreshKey: upstreamRefreshKey } = 
    (nodeType.id === "video_preview" || nodeType.id === "image_preview" || nodeType.id === "json_visual_editor" || nodeType.id === "text_editor" || nodeType.id === "subtitle_editor" || nodeType.id === "lcwr_watermark_removal") ? getUpstreamOutputs() : { outputs: {}, configs: {}, refreshKey: "" };

  // 当前任务 id（调试任务 activeTaskId 或一般/批量任务 taskModeId），用于相对产物路径解析
  const storeActiveTaskId = useWorkflowStore((s) => s.activeTaskId);
  const taskModeId = useWorkflowStore((s) => s.taskModeId);
  const previewTaskId = storeActiveTaskId || taskModeId;

  const IconComp = ICON_MAP[nodeType.icon] || Wrench;
  const status = nd.status || "pending";
  const config = nd.config || {};
  const statusCfg = STATUS_CONFIG[status] || STATUS_CONFIG.pending;
  const StatusIcon = statusCfg.icon;

  const visibleOutputs = getVisibleOutputs(nodeType, config);
  const visibleInputs = getNodeInputs(nodeType, config);
  const isPiAgent = nodeType.id === "pi_agent";
  const dedupedOutputEntries = (() => {
    const seen = new Set<string>();
    const rawOutputs = nd.outputs;
    // Only process plain object with string values
    if (!rawOutputs || typeof rawOutputs !== "object" || Array.isArray(rawOutputs)) return [];
    return Object.entries(rawOutputs).filter(([key, filePath]) => {
      if (typeof key !== "string") return false;
      // Only include string or number values, skip objects/functions
      if (filePath !== null && filePath !== undefined && typeof filePath !== "string" && typeof filePath !== "number") return false;
      const dedupeKey = String(filePath);
      if (!dedupeKey || seen.has(dedupeKey)) return false;
      seen.add(dedupeKey);
      return true;
    });
  })();

  const configRef = useRef(config);
  configRef.current = config;

  const handleConfigChange = useCallback((key: string, value: any) => {
    const newConfig = { ...configRef.current, [key]: value };
    updateNodeData(id, { config: newConfig });
  }, [id, updateNodeData]);

  // JSON 可视化编辑：打开弹窗并载入输入（优先已编辑结果，其次上游 JSON 输入/配置）
  const openJsonEditor = useCallback(async () => {
    let initial: any;
    const saved = configRef.current.edited_json;
    if (saved && String(saved).trim()) {
      try { initial = JSON.parse(saved); } catch { initial = {}; }
    } else {
      initial = upstreamOutputs.json !== undefined ? upstreamOutputs.json : upstreamConfigs.json;
    }
    // 若上游值是文件路径，尝试从后端读取内容
    if (typeof initial === "string" && initial.trim() && !initial.trim().startsWith("{") && !initial.trim().startsWith("[")) {
      try {
        const params = new URLSearchParams({ path: initial.trim() });
        if (previewTaskId) params.set("task_id", previewTaskId);
        const res = await client.get(`/api/files/stream?${params.toString()}`, { responseType: "text" });
        const text = typeof res.data === "string" ? res.data : JSON.stringify(res.data);
        try { initial = JSON.parse(text); } catch { initial = text; }
      } catch { /* 读取失败时保留原值 */ }
    }
    setEditorInitialJson(initial);
    setJsonEditorOpen(true);
  }, [upstreamOutputs.json, upstreamConfigs.json, previewTaskId]);

  // 文本编辑：打开弹窗并载入输入（优先已编辑结果，其次上游文本输入/配置）
  const openTextEditor = useCallback(async () => {
    let initial = "";
    const saved = configRef.current.edited_text;
    if (saved && String(saved).trim() !== "") {
      initial = String(saved);
    } else {
      const upstream = upstreamOutputs.text !== undefined ? upstreamOutputs.text : upstreamConfigs.text;
      if (upstream === undefined || upstream === null) initial = "";
      else if (typeof upstream === "string") initial = upstream;
      else initial = String(upstream);
    }
    // 若上游值是文件路径（单行无换行），尝试从后端读取内容
    if (initial.trim() && !initial.includes("\n")) {
      try {
        const params = new URLSearchParams({ path: initial.trim() });
        if (previewTaskId) params.set("task_id", previewTaskId);
        const res = await client.get(`/api/files/stream?${params.toString()}`, { responseType: "text" });
        initial = typeof res.data === "string" ? res.data : JSON.stringify(res.data);
      } catch { /* 读取失败时保留原值 */ }
    }
    setTextEditorInitialText(initial);
    setTextEditorOpen(true);
  }, [upstreamOutputs.text, upstreamConfigs.text, previewTaskId]);

  // 字幕编辑：打开弹窗并载入输入字幕（优先已编辑结果，其次上游字幕）与输入视频
  const openSubtitleEditor = useCallback(async () => {
    let entries: any[] = [];
    let video = "";
    const saved = configRef.current.edited_subtitles;
    if (saved && String(saved).trim()) {
      try {
        const parsed = JSON.parse(saved);
        entries = Array.isArray(parsed) ? parsed : [];
      } catch { entries = []; }
    } else {
      const sub = upstreamOutputs.subtitle !== undefined ? upstreamOutputs.subtitle : upstreamConfigs.subtitlePath;
      if (typeof sub === "string" && sub.trim()) {
        try {
          const params = new URLSearchParams({ path: sub.trim() });
          if (previewTaskId) params.set("task_id", previewTaskId);
          const res = await client.get(`/api/files/stream?${params.toString()}`, { responseType: "text" });
          const content = typeof res.data === "string" ? res.data : JSON.stringify(res.data);
          entries = parseSubtitleEntries(content);
        } catch { entries = []; }
      } else if (sub && typeof sub === "object") {
        entries = Array.isArray(sub) ? sub : [];
      }
    }
    // 视频：优先上游 video 输出，其次输入节点的 videoPath
    if (upstreamOutputs.video !== undefined) video = String(upstreamOutputs.video);
    else if (upstreamConfigs.videoPath) video = String(upstreamConfigs.videoPath);
    if (!video) {
      const nodes = getNodes();
      const inputNode = nodes.find((n) => (n.data as any)?.nodeType === "input");
      const inputConfig = (inputNode?.data as any)?.config || {};
      if (inputConfig.videoPath) video = String(inputConfig.videoPath);
    }
    setSubtitleEditorEntries(entries);
    setSubtitleEditorVideo(video);
    setSubtitleEditorOpen(true);
  }, [upstreamOutputs.subtitle, upstreamOutputs.video, upstreamConfigs.subtitlePath, upstreamConfigs.videoPath, previewTaskId, getNodes]);

  const handleStyle = (portType: string, idx: number, total: number, portColor?: string) => ({
    top: ((idx + 1) / (total + 1)) * 100 + "%",
    background: portColor || PORT_COLORS[portType as PortType] || "#6b7280",
    width: 12, height: 12, border: "2px solid white",
  });

  const hasConfig = nodeType.configFields && nodeType.configFields.length > 0;
  const nodeColor = nodeType.color || "#6b7280";

  const saveNote = (text: string) => {
    setNoteText(text);
    setEditingNote(false);
    updateNodeData(id, { note: text || undefined });
  };

  return (
    <div className={cn(
      "rounded-2xl border-[3px] bg-card text-card-foreground w-[420px] max-w-[420px] transition-all duration-300",
      selected
        ? "border-primary shadow-primary/20 shadow-lg scale-[1.02]"
        : status === "completed"
          ? "!border-[5px] border-emerald-400 shadow-[0_0_20px_6px_rgba(16,185,129,0.4),0_0_40px_12px_rgba(16,185,129,0.2)]"
          : "",
      status === "running" && "animate-node-glow",
      statusCfg.glow,
      (status === "pending" || status === "failed") && "shadow-md",
    )} style={{ borderColor: selected ? undefined : status === "completed" ? "#34d399" : nodeColor }} >
      {/* Input Handles */}
      {getNodeInputs(nodeType, config).map((port: any, i: number) => (
        <Handle
          key={"in-" + port.id}
          type="target"
          position={Position.Left}
          id={"in-" + port.id}
          style={handleStyle(port.type, i, getNodeInputs(nodeType, config).length, port.color)}
        />
      ))}

      {/* Header */}
      <div
        className={cn(
          "flex items-center gap-2 px-4 py-2.5",
          hasConfig ? "cursor-pointer rounded-t-xl" : "rounded-t-xl"
        )}
        style={{ backgroundColor: nodeType.color + "30" }}
        onClick={hasConfig ? () => setExpanded(!expanded) : undefined}
      >
        <div
          className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
          style={{ backgroundColor: nodeType.color + "40" }}
        >
          <IconComp className="w-5 h-5" style={{ color: nodeType.color }} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-bold truncate">{nd.label || nodeType.name}</div>
          <div className="text-xs text-muted-foreground truncate">{(nodeType.description || "").slice(0, 25)}</div>
        </div>
        {nodeType.id !== "input" && (
          <div className="relative">
            <button
              onClick={(e) => { e.stopPropagation(); setShowDesc((p) => !p); }}
              onMouseEnter={() => setShowDesc(true)}
              onMouseLeave={() => setShowDesc(false)}
              className="w-6 h-6 rounded-md flex items-center justify-center text-muted-foreground/70 hover:text-foreground/70 hover:bg-foreground/10 transition-colors"
            >
              <HelpCircle className="w-3 h-3" />
            </button>
            {showDesc && (
              <div
                className="absolute top-full right-0 mt-1 z-50 w-64 p-3 text-xs text-muted-foreground bg-popover border border-border/50 rounded-lg shadow-lg"
                onMouseEnter={() => setShowDesc(true)}
                onMouseLeave={() => setShowDesc(false)}
              >
                {nodeType.description}
              </div>
            )}
          </div>
        )}
        {nd.onExecuteNode && (
          <div className="flex items-center gap-1">
            <button
              onClick={(e) => {
                e.stopPropagation();
                nd.onExecuteNode(id);
              }}
              disabled={nd.disableExecute || status === "running"}
              className="w-6 h-6 rounded-md flex items-center justify-center bg-primary/10 text-primary hover:bg-primary/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
              title="仅执行此节点"
            >
              <Play className="w-3 h-3" />
            </button>
            {nd.onExecuteFromNode && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  nd.onExecuteFromNode(id);
                }}
                disabled={nd.disableExecute || status === "running"}
                className="w-6 h-6 rounded-md flex items-center justify-center bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                title="从此节点继续执行下游"
              >
                <ArrowRight className="w-3 h-3" />
              </button>
            )}
          </div>
)}
        {nodeType.id === "cutia" && status === "waiting" && nd.workbench_url && (
          <button
            onClick={(e) => { e.stopPropagation(); window.location.href = nd.workbench_url; }}
            className="w-6 h-6 rounded-md flex items-center justify-center bg-amber-500/10 text-amber-700 hover:bg-amber-500/20 transition-colors"
            title="打开剪辑工作台"
          >
            <Clapperboard className="w-3 h-3" />
          </button>
        )}
        <div className="flex items-center gap-1.5">
          {hasConfig && (
            expanded
              ? <ChevronDown className="w-3 h-3 text-muted-foreground/70" />
              : <ChevronRight className="w-3 h-3 text-muted-foreground/70" />
          )}
          <div className={cn("flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium", statusCfg.badgeBg, statusCfg.badgeText)}>
            <StatusIcon className={cn("w-2.5 h-2.5", status === "running" && "animate-spin")} />
            <span>{statusCfg.label}</span>
          </div>
        </div>
      </div>

      {/* Port Labels */}
      <div className="px-3 py-2 space-y-1">
        {isPiAgent && (
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-semibold text-muted-foreground">输入</span>
            <button
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); const n = Math.min(Number(config.inputCount) || 2, 8); handleConfigChange("inputCount", n + 1); }}
              className="w-5 h-5 rounded flex items-center justify-center text-[11px] font-bold text-primary border border-primary/30 hover:bg-primary/10"
              title="增加输入端口"
            >+</button>
            <button
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); const n = Math.max(Number(config.inputCount) || 2, 1); handleConfigChange("inputCount", n - 1); }}
              className="w-5 h-5 rounded flex items-center justify-center text-[11px] font-bold text-muted-foreground border border-border/50 hover:bg-muted"
              title="减少输入端口"
            >−</button>
            <span className="text-[10px] text-muted-foreground">{visibleInputs.length}</span>
            <span className="text-[10px] font-semibold text-muted-foreground ml-3">输出</span>
            <button
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); const n = Math.min(Number(config.outputCount) || 2, 8); handleConfigChange("outputCount", n + 1); }}
              className="w-5 h-5 rounded flex items-center justify-center text-[11px] font-bold text-primary border border-primary/30 hover:bg-primary/10"
              title="增加输出端口"
            >+</button>
            <button
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); const n = Math.max(Number(config.outputCount) || 2, 1); handleConfigChange("outputCount", n - 1); }}
              className="w-5 h-5 rounded flex items-center justify-center text-[11px] font-bold text-muted-foreground border border-border/50 hover:bg-muted"
              title="减少输出端口"
            >−</button>
            <span className="text-[10px] text-muted-foreground">{visibleOutputs.length}</span>
          </div>
        )}
        {visibleInputs.length > 0 && (
          <div className="flex items-center justify-between gap-2">
            <div className="flex flex-wrap gap-1">
              {visibleInputs.map((p: any) => (
                <span
                  key={p.id}
                  className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded-md"
                  style={{ backgroundColor: (p.color || PORT_COLORS[p.type as PortType]) + "20", color: p.color || PORT_COLORS[p.type as PortType] }}
                >
                  <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: p.color || PORT_COLORS[p.type as PortType] }} />
                  {p.label}
                </span>
              ))}
            </div>
            {/* Note */}
            {editingNote ? (
              <input
                autoFocus
                value={noteText}
                onChange={(e) => setNoteText(e.target.value)}
                onBlur={() => saveNote(noteText)}
                onKeyDown={(e) => { if (e.key === "Enter") saveNote(noteText); if (e.key === "Escape") { setNoteText(nd.note || ""); setEditingNote(false); } }}
                onClick={(e) => e.stopPropagation()}
                className="flex-shrink-0 w-28 text-[11px] px-2 py-0.5 rounded-md border border-border/50 bg-background outline-none"
                placeholder="输入备注..."
              />
            ) : (
              <div
                onDoubleClick={(e) => { e.stopPropagation(); setEditingNote(true); }}
                className={cn(
                  "flex-shrink-0 w-28 text-[11px] text-right px-2 py-0.5 rounded-md cursor-default select-none truncate",
                  noteText ? "bg-secondary text-muted-foreground" : "bg-secondary/60 text-muted-foreground/70"
                )}
                title={noteText || "双击添加备注"}
              >
                {noteText || "无备注"}
              </div>
            )}
          </div>
        )}
        {visibleOutputs.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {visibleOutputs.map((p) => (
              <span
                key={p.id}
                className="inline-flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded-md"
                style={{ backgroundColor: (p.color || PORT_COLORS[p.type as PortType]) + "20", color: p.color || PORT_COLORS[p.type as PortType] }}
              >
                {p.label}
                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: p.color || PORT_COLORS[p.type as PortType] }} />
              </span>
            ))}
          </div>
        )}
      </div>
      {/* Running Progress */}
      {status === "running" && (
        <div className="px-3 pb-2">
          <div className="w-full h-1.5 bg-pink-100 dark:bg-pink-900/30 rounded-full overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-pink-400 to-pink-500 rounded-full transition-all duration-700 ease-out"
              style={{ width: (nd.progress || 0) + "%" }}
            />
          </div>
          {nd.message && (
            <div className="text-[11px] text-pink-600 dark:text-pink-400 mt-1 truncate flex items-center gap-1">
              <span className="inline-block w-1 h-1 rounded-full bg-pink-500 animate-pulse" />
              {nd.message}
            </div>
          )}
        </div>
      )}

      {/* Config Form (when expanded) */}
      {hasConfig && expanded && (
        <ConfigForm
          nodeType={nodeType}
          config={config}
          onConfigChange={handleConfigChange}
          onVoiceSelect={setVoiceSelectField}
          onButtonAction={() => {
            if (nodeType.id === "text_editor") openTextEditor();
            else if (nodeType.id === "subtitle_editor") openSubtitleEditor();
            else openJsonEditor();
          }}
        />
      )}

      {/* LCWR 去水印：自定义编辑器（视频/黑帧预览、区域框选、片头片尾时间轴、模型选择） */}
      {nodeType.id === "lcwr_watermark_removal" && expanded && (
        <LcwrWatermarkEditor
          config={config}
          onConfigChange={handleConfigChange}
          videoPath={upstreamOutputs.video}
          imagePath={upstreamOutputs.image}
          taskId={previewTaskId}
        />
      )}

      {/* pi_agent: 输出产物设置板块 */}
      {isPiAgent && expanded && (
        <div className="px-3 pb-3 border-t border-border/50 pt-2 space-y-2">
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] font-semibold text-foreground">输出产物设置</span>
            <span className="text-[10px] text-muted-foreground">按输出端口逐条配置类型与描述</span>
          </div>
          {(() => {
            const count = Math.min(Math.max(Number(config.outputCount) || 2, 1), 8);
            const items: { port: string; type: string; desc: string }[] = Array.isArray(config.output_items)
              ? config.output_items.map((item: any, i: number) => ({
                  port: String(item?.port || `输出${i + 1}`),
                  type: String(item?.type || "text"),
                  desc: String(item?.desc || ""),
                }))
              : [];
            const rows = Array.from({ length: count }, (_, i) => items[i] || { port: `输出${i + 1}`, type: "text", desc: "" });
            const updateItem = (index: number, patch: Partial<{ port: string; type: string; desc: string }>) => {
              const next = rows.map((row, i) => (i === index ? { ...row, ...patch } : row));
              handleConfigChange("output_items", next);
            };
            return (
              <div className="space-y-1.5">
                {rows.map((row, index) => (
                  <div key={index} className="flex items-center gap-1.5">
                    <input
                      value={row.port}
                      onChange={(e) => updateItem(index, { port: e.target.value })}
                      onPointerDown={(e) => e.stopPropagation()}
                      className="w-20 text-[11px] px-2 py-1 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
                      placeholder={`输出${index + 1}`}
                    />
                    <select
                      value={row.type}
                      onChange={(e) => updateItem(index, { type: e.target.value })}
                      onPointerDown={(e) => e.stopPropagation()}
                      onWheel={(e) => e.stopPropagation()}
                      className="w-24 text-[11px] px-1.5 py-1 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
                    >
                      {PI_AGENT_OUTPUT_TYPES.map((opt) => (
                        <option key={opt.value} value={opt.value}>{opt.label}</option>
                      ))}
                    </select>
                    <input
                      value={row.desc}
                      onChange={(e) => updateItem(index, { desc: e.target.value })}
                      onPointerDown={(e) => e.stopPropagation()}
                      className="min-w-0 flex-1 text-[11px] px-2 py-1 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
                      placeholder={`输出${index + 1} 描述`}
                    />
                  </div>
                ))}
              </div>
            );
          })()}
        </div>
      )}

      {/* Preview Nodes */}
      {nodeType.id === "video_preview" && (
        <VideoPreview
          config={config}
          videoPath={nd.videoPath || upstreamOutputs.video || upstreamConfigs.videoPath}
          subtitlePath={nd.subtitlePath || upstreamOutputs.subtitle || upstreamOutputs.original || upstreamOutputs.bilingual || upstreamConfigs.subtitlePath}
          taskId={previewTaskId}
          onConfigChange={handleConfigChange}
          refreshKey={upstreamRefreshKey}
        />
      )}
      {nodeType.id === "image_preview" && (
        <ImagePreview config={config} imagePath={nd.imagePath || upstreamOutputs.image || upstreamConfigs.imagePath} taskId={previewTaskId} refreshKey={upstreamRefreshKey} />
      )}

      {/* Output Display Panel - shows results/errors after execution */}
      {status === "completed" && dedupedOutputEntries.length > 0 && (() => {
        // Separate file-based outputs from text/JSON outputs
        const fileEntries: [string, string | number][] = [];
        const jsonEntries: [string, string][] = [];
        for (const [key, val] of dedupedOutputEntries) {
          const s = String(val);
          if (key === "text" && s.trimStart().startsWith("{")) {
            jsonEntries.push([key, s]);
          } else {
            fileEntries.push([key, val as string | number]);
          }
        }
        if (fileEntries.length === 0 && jsonEntries.length === 0) return null;
        return (
          <div className="px-3 pb-3 border-t border-border/50 pt-2">
            <div className="flex items-center gap-1.5 mb-1.5">
              <FileText className="w-3 h-3 text-emerald-500" />
              <span className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400">{"输出产物"}</span>
            </div>
            <div className="space-y-1">
              {/* File-based outputs */}
              {fileEntries.map(([key, filePath]) => {
                const raw = String(filePath).replace(/\\/g, "/");
                const full = raw.split("/").pop() || String(filePath);
                const ext = full.includes(".") ? full.substring(full.lastIndexOf(".")) : "";
                const base = full.includes(".") ? full.substring(0, full.lastIndexOf(".")) : full;
                const displayName = base.length > 15 ? base.substring(0, 8) + "..." + base.substring(base.length - 5) + ext : full;
                return (
                  <button
                    key={key}
                    onClick={(e) => {
                      e.stopPropagation();
                      client.post("/api/tasks/open-file", { file_path: String(filePath) }).catch(() => {});
                    }}
                    className="flex items-center gap-2 text-[10px] px-2 py-1 rounded-md bg-emerald-500/5 border border-emerald-500/20 w-full text-left hover:bg-emerald-500/15 transition-colors cursor-pointer group"
                    title={full}
                  >
                    <span className="font-medium text-emerald-600 dark:text-emerald-400 flex-shrink-0">{key}</span>
                    <span className="text-muted-foreground truncate group-hover:text-foreground transition-colors">{displayName}</span>
                  </button>
                );
              })}
              {/* JSON preview outputs */}
              {jsonEntries.map(([key, jsonStr]) => {
                let parsed: any = null;
                try { parsed = JSON.parse(jsonStr); } catch { /* not valid JSON */ }
                const summary = parsed
                  ? (parsed.success !== undefined ? `${parsed.success}成功 / ${parsed.failed ?? 0}失败` : "")
                  : "";
                return (
                  <div key={key} className="rounded-md bg-emerald-500/5 border border-emerald-500/20">
                    <div className="flex items-center gap-1 text-[10px] px-2 py-1">
                      <button
                        onClick={(e) => { e.stopPropagation(); setJsonPreviewOpen(!jsonPreviewOpen); }}
                        className="flex items-center gap-1 flex-1 text-left hover:bg-emerald-500/15 transition-colors cursor-pointer rounded-sm -ml-0.5 px-0.5"
                      >
                        {jsonPreviewOpen
                          ? <ChevronDown className="w-3 h-3 text-emerald-500 flex-shrink-0" />
                          : <ChevronRight className="w-3 h-3 text-emerald-500 flex-shrink-0" />
                        }
                        <span className="font-medium text-emerald-600 dark:text-emerald-400">发布结果</span>
                        {summary && <span className="text-muted-foreground">{summary}</span>}
                      </button>
                      {parsed?.publish_params?.video_path && (
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            // Try to open the result JSON file from the task output directory
                            const vp = parsed.publish_params.video_path as string;
                            const taskDir = vp.substring(0, vp.lastIndexOf("/output/")) || vp.substring(0, vp.lastIndexOf("\\output\\"));
                            if (taskDir) {
                              client.post("/api/tasks/open-file", { file_path: taskDir + "/output" }).catch(() => {});
                            }
                          }}
                          className="text-emerald-600/60 hover:text-emerald-600 transition-colors cursor-pointer flex-shrink-0"
                          title="打开输出目录"
                        >
                          <Eye className="w-3 h-3" />
                        </button>
                      )}
                    </div>
                    {jsonPreviewOpen && parsed && (
                      <div className="px-2 pb-2 max-h-48 overflow-y-auto">
                        {/* Summary section */}
                        {parsed.publish_params && (
                          <div className="mb-1.5 space-y-0.5">
                            <div className="text-[10px] text-emerald-600/80 font-semibold">发布参数</div>
                            {Object.entries(parsed.publish_params).map(([pk, pv]) => (
                              pv ? <div key={pk} className="flex gap-1.5 text-[9px]">
                                <span className="text-muted-foreground/70 flex-shrink-0 w-24 text-right">{pk}:</span>
                                <span className="text-foreground/80 break-all">{typeof pv === "object" ? JSON.stringify(pv) : String(pv)}</span>
                              </div> : null
                            ))}
                          </div>
                        )}
                        {/* Raw JSON */}
                        <details className="mt-1">
                          <summary className="text-[9px] text-muted-foreground/70 cursor-pointer hover:text-foreground">原始 JSON</summary>
                          <pre className="text-[9px] text-foreground/70 whitespace-pre-wrap break-all mt-1 p-1.5 rounded bg-muted/30 max-h-32 overflow-y-auto">
                            {JSON.stringify(parsed, null, 2)}
                          </pre>
                        </details>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })()}

      {/* Error Display Panel - shows errors after failure */}
      {status === "failed" && nd.error && (
        <div className="px-3 pb-3 border-t border-border/50 pt-2">
          <div className="flex items-center gap-1.5 mb-1.5">
            <AlertTriangle className="w-3 h-3 text-red-500" />
            <span className="text-[11px] font-semibold text-red-600 dark:text-red-400">{"执行错误"}</span>
          </div>
          <div className="text-[10px] text-red-600/80 dark:text-red-400/80 px-2 py-1.5 rounded-md bg-red-500/5 border border-red-500/20 break-all max-h-20 overflow-y-auto">
            {nd.error}
          </div>
        </div>
      )}

      {/* Output Handles (dynamic for input node) */}
      {visibleOutputs.map((port: any, i: number) => (
        <Handle
          key={"out-" + port.id}
          type="source"
          position={Position.Right}
          id={"out-" + port.id}
          style={handleStyle(port.type, i, visibleOutputs.length, port.color)}
        />
      ))}

      {/* Voice Select Panel */}
      {voiceSelectField && (
        <VoiceSelectPanel
          interfaceId={config[voiceSelectField.interfaceIdKey] || ""}
          selected={config[voiceSelectField.key] || ""}
          onSelect={(voiceId) => {
            handleConfigChange(voiceSelectField.key, voiceId);
            setVoiceSelectField(null);
          }}
          open={!!voiceSelectField}
          onClose={() => setVoiceSelectField(null)}
        />
      )}

      {/* JSON 可视化编辑弹窗 */}
      {nodeType.id === "json_visual_editor" && (
        <JsonEditorDialog
          open={jsonEditorOpen}
          initialJson={editorInitialJson}
          onClose={() => setJsonEditorOpen(false)}
          onSave={(data) => handleConfigChange("edited_json", JSON.stringify(data, null, 2))}
        />
      )}

      {/* 文本编辑弹窗 */}
      {nodeType.id === "text_editor" && (
        <TextEditorDialog
          open={textEditorOpen}
          initialText={textEditorInitialText}
          onClose={() => setTextEditorOpen(false)}
          onSave={(text) => handleConfigChange("edited_text", text)}
        />
      )}

      {/* 字幕编辑弹窗 */}
      {nodeType.id === "subtitle_editor" && (
        <SubtitleEditorDialog
          open={subtitleEditorOpen}
          initialEntries={subtitleEditorEntries}
          initialVideo={subtitleEditorVideo}
          taskId={previewTaskId}
          onClose={() => setSubtitleEditorOpen(false)}
          onSave={(entries) => handleConfigChange("edited_subtitles", JSON.stringify(entries))}
        />
      )}
    </div>
  );
}

export default memo(WorkflowNodeComponent);
;
