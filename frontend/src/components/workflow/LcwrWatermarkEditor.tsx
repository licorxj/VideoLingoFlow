import { memo, useState, useCallback, useEffect, useRef, useMemo } from "react";
import client from "@/api/client";
import { cn } from "@/lib/utils";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { RefreshCw, ExternalLink, Trash2, Loader2, Info, Eraser, ChevronLeft, ChevronRight } from "lucide-react";

const LCWR_DOWNLOAD_URL = "https://qinmuzhifang.feishu.cn/wiki/IkBVwfe72iEVLTkhVQ0cW0mvnBc";

const STATIC_MODELS = [
  { id: "lama", name: "LaMa（快速）", type: "local" },
  { id: "sttn", name: "STTN（时空张量）", type: "local" },
  { id: "propainter", name: "ProPainter（高质量）", type: "local" },
  { id: "diffueraser", name: "DiffuEraser（扩散模型）", type: "local" },
  { id: "bernini", name: "Bernini（旗舰）", type: "local" },
  { id: "online", name: "LCWR在线模型", type: "online" },
];

const ASPECT_PRESETS = ["16:9", "9:16", "4:3", "3:4", "1:1", "21:9"];

type Region = { start: [number, number]; end: [number, number]; frame_range: number[] };
type VideoMeta = { duration: number; fps: number; width: number; height: number };

export function LcwrRegionSummary({ config }: { config: Record<string, any> }) {
  const regions = Array.isArray(config.regions) ? config.regions as Region[] : [];
  if (!regions.length) {
    return <div className="px-3 pb-2 text-[10px] text-muted-foreground/70">尚未设置去除区域</div>;
  }

  return (
    <div className="px-3 pb-2 space-y-1">
      <div className="text-[10px] font-medium text-muted-foreground">去除区域（{regions.length}）</div>
      <div className="max-h-24 overflow-y-auto space-y-1 pr-0.5">
        {regions.map((region, index) => {
          const x1 = clamp01(Number(region.start?.[0]) || 0);
          const y1 = clamp01(Number(region.start?.[1]) || 0);
          const x2 = clamp01(Number(region.end?.[0]) || 0);
          const y2 = clamp01(Number(region.end?.[1]) || 0);
          const frameRange = Array.isArray(region.frame_range) ? region.frame_range : [];
          const timeRange = frameRange.length >= 2
            ? `${frameRange[0]}-${frameRange[1]} 帧`
            : "全程生效";
          return (
            <div key={index} className="flex items-center gap-1.5 rounded bg-sky-500/5 border border-sky-500/15 px-1.5 py-1 text-[10px]">
              <span className="flex-shrink-0 inline-flex items-center justify-center w-4 h-4 rounded bg-sky-500 text-white text-[9px]">{index + 1}</span>
              <span className="min-w-0 flex-1 truncate text-muted-foreground" title={`x ${x1.toFixed(3)}-${x2.toFixed(3)}, y ${y1.toFixed(3)}-${y2.toFixed(3)}`}>
                x {Math.min(x1, x2).toFixed(3)}-{Math.max(x1, x2).toFixed(3)} · y {Math.min(y1, y2).toFixed(3)}-{Math.max(y1, y2).toFixed(3)}
              </span>
              <span className="flex-shrink-0 text-muted-foreground/70">{timeRange}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function LcwrNodeControls({ config, onConfigChange }: {
  config: Record<string, any>;
  onConfigChange: (key: string, value: any) => void;
}) {
  const baseUrl = String(config.lcwr_base_url || "http://localhost:1120").trim();
  const [models, setModels] = useState<{ id: string; name: string }[]>(STATIC_MODELS);
  const [connected, setConnected] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(() => {
    setLoading(true);
    const params = { base_url: baseUrl };
    Promise.all([
      client.get("/api/lcwr/health", { params }),
      client.get("/api/lcwr/models", { params }),
    ]).then(([health, modelResponse]) => {
      setConnected(!!health.data?.connected);
      const list = modelResponse.data?.models;
      if (Array.isArray(list) && list.length) {
        setModels(list.map((x: any) => ({
          id: String(x.id ?? x.value ?? ""),
          name: String(x.name ?? x.label ?? x.id ?? ""),
        })));
      }
    }).catch(() => setConnected(false)).finally(() => setLoading(false));
  }, [baseUrl]);

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <div className="px-3 pb-3 pt-1 space-y-1.5">
      <div className="flex items-center justify-between gap-2">
        <a
          href={LCWR_DOWNLOAD_URL}
          target="_blank"
          rel="noopener noreferrer"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
          className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-md text-sky-600 dark:text-sky-400 border border-sky-500/40 bg-sky-500/5 hover:bg-sky-500/10 transition-all"
        >
          <ExternalLink className="w-3 h-3" />
          软件下载
        </a>
        <span className={cn(
          "inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full",
          connected === null ? "text-muted-foreground bg-muted/50" : connected ? "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10" : "text-red-600 dark:text-red-400 bg-red-500/10"
        )} title={connected ? "LCWR 服务在线" : "LCWR 服务不可用"}>
          <span className={cn("w-1.5 h-1.5 rounded-full", connected === null ? "bg-muted-foreground/50" : connected ? "bg-emerald-500" : "bg-red-500")} />
          {connected === null ? "检测中" : connected ? "服务在线" : "服务离线"}
        </span>
      </div>
      <div className="flex items-center gap-1.5">
        <label className="text-[11px] font-medium text-muted-foreground flex-shrink-0">执行模型</label>
        <select
          value={config.model || "bernini"}
          onChange={(e) => onConfigChange("model", e.target.value)}
          onPointerDown={(e) => e.stopPropagation()}
          onWheel={(e) => e.stopPropagation()}
          className="min-w-0 flex-1 text-[11px] px-2 py-1 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
        >
          {models.map((model) => <option key={model.id} value={model.id}>{model.name || model.id}</option>)}
        </select>
        <button type="button" onPointerDown={(e) => e.stopPropagation()} onClick={(e) => { e.stopPropagation(); refresh(); }} className="flex-shrink-0 inline-flex items-center gap-1 text-[10px] px-1.5 py-1 rounded-md border border-border/50 hover:bg-muted transition-colors" title="刷新模型与连接状态">
          {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
        </button>
      </div>
    </div>
  );
}

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

function toCssAspectRatio(value: string): string {
  const match = value.trim().match(/^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/);
  return match ? `${match[1]} / ${match[2]}` : "16 / 9";
}

/** 稳定文件流 URL（带 cache-bust，仅在 path/taskId 变化时更新） */
function useStableFileUrl(path?: string, taskId?: string): string {
  const cacheRef = useRef<{ key: string; url: string }>({ key: "", url: "" });
  return useMemo(() => {
    if (!path) return "";
    const compositeKey = `${path}|${taskId || ""}`;
    if (cacheRef.current.key === compositeKey) return cacheRef.current.url;
    const params = new URLSearchParams({ path });
    if (taskId) params.set("task_id", taskId);
    params.set("t", String(Date.now()));
    const url = `/api/files/stream?${params.toString()}`;
    cacheRef.current = { key: compositeKey, url };
    return url;
  }, [path, taskId]);
}

function fmtTime(sec: number): string {
  if (!isFinite(sec) || sec < 0) return "00:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function LcwrWatermarkEditorInner({ config, onConfigChange, videoPath, imagePath, taskId, open, onOpenChange }: {
  config: Record<string, any>;
  onConfigChange: (key: string, value: any) => void;
  videoPath?: string;
  imagePath?: string;
  taskId?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const regions: Region[] = Array.isArray(config.regions) ? config.regions : [];
  const aspectPreset = String(config.aspect_ratio || "16:9");
  const durationSec = Number(config.duration_sec) || 10;
  const fps = Number(config.fps) || 25;

  // 视频元信息与帧浏览
  const [meta, setMeta] = useState<VideoMeta | null>(null);
  const [metaError, setMetaError] = useState("");
  const [frameStep, setFrameStep] = useState(0); // 每格 = 10 帧
  const videoRef = useRef<HTMLVideoElement>(null);
  const mediaUrl = useStableFileUrl(videoPath || imagePath, taskId);

  // 框选状态
  const overlayRef = useRef<HTMLDivElement>(null);
  const [drawing, setDrawing] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null);

  // 时间轴拖拽（ref 保证 pointermove 期间状态即时可用）
  const timelineRef = useRef<HTMLDivElement>(null);
  const timelineDragRef = useRef<"head" | "tail" | null>(null);

  // 图片自然比例（用于对齐框选坐标）
  const [imgRatio, setImgRatio] = useState<string>("");

  const hasVideo = !!videoPath;
  const hasImage = !hasVideo && !!imagePath;
  // 有效时长：视频用元信息，无视频时用黑帧预设时长
  const duration = hasVideo ? (meta?.duration || 0) : durationSec;

  // 加载视频元信息
  useEffect(() => {
    setMeta(null);
    setMetaError("");
    setFrameStep(0);
    if (!hasVideo || !videoPath) return;
    let cancelled = false;
    client.get("/api/files/video-info", { params: { path: videoPath, task_id: taskId || undefined } })
      .then((res) => {
        if (cancelled) return;
        const d = res.data || {};
        setMeta({ duration: Number(d.duration) || 0, fps: Number(d.fps) || 25, width: Number(d.width) || 0, height: Number(d.height) || 0 });
      })
      .catch((err) => {
        if (!cancelled) setMetaError(err?.response?.data?.detail || err?.message || "视频信息读取失败");
      });
    return () => { cancelled = true; };
  }, [hasVideo, videoPath, taskId]);

  // 帧浏览参数
  const totalFrames = meta ? Math.max(1, Math.floor(meta.duration * meta.fps)) : Math.max(1, Math.floor(durationSec * fps));
  const frameStepSize = 10; // 每 10 帧读一帧展示
  const sliderMax = Math.max(1, Math.floor(totalFrames / frameStepSize));
  const currentFrame = Math.min(frameStep * frameStepSize, totalFrames);
  const currentTime = hasVideo ? currentFrame / (meta?.fps || fps) : 0;

  const goFrame = (frame: number) => {
    const clamped = clamp01(frame / totalFrames);
    setFrameStep(Math.round(clamped * sliderMax));
  };

  const seekTime = useCallback((time: number) => {
    if (!videoRef.current) return;
    try { videoRef.current.currentTime = Math.max(0, Math.min(time, Math.max(0, duration) - 0.05)); } catch { /* ignore */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasVideo, meta]);

  // 滑块变化：换算到时间并 seek
  const onFrameSlider = (val: number) => {
    setFrameStep(val);
    if (hasVideo) seekTime(val * frameStepSize / (meta?.fps || fps));
  };

  // ---------- 区域框选 ----------
  const getPos = (e: React.PointerEvent) => {
    const el = overlayRef.current;
    if (!el) return { x: 0, y: 0 };
    const rect = el.getBoundingClientRect();
    return { x: clamp01((e.clientX - rect.left) / rect.width), y: clamp01((e.clientY - rect.top) / rect.height) };
  };

  const commitRegion = (region: Region) => {
    const next = [...regions, region];
    onConfigChange("regions", next);
  };

  const removeRegion = (idx: number) => {
    const next = regions.filter((_, i) => i !== idx);
    onConfigChange("regions", next);
  };

  const clearRegions = () => onConfigChange("regions", []);

  // ---------- 时间轴（片头/片尾跳过） ----------
  const headSec = Math.min(Number(config.skip_head_sec) || 0, Math.max(0, duration - (Number(config.skip_tail_sec) || 0)));
  const tailSec = Math.min(Number(config.skip_tail_sec) || 0, Math.max(0, duration - headSec));

  const timelineToSec = (e: React.PointerEvent): number => {
    const el = timelineRef.current;
    if (!el) return 0;
    const rect = el.getBoundingClientRect();
    return clamp01((e.clientX - rect.left) / rect.width) * duration;
  };

  const updateSkip = (type: "head" | "tail", sec: number) => {
    const clamped = Math.max(0, Math.min(duration, sec));
    if (type === "head") {
      onConfigChange("skip_head_sec", Math.min(clamped, Math.max(0, duration - tailSec)));
    } else {
      onConfigChange("skip_tail_sec", Math.min(clamped, Math.max(0, duration - headSec)));
    }
  };

  // 容器宽高比：视频用真实比例，图片用自然比例，黑帧用预设比例
  const mediaRatio = hasVideo
    ? (meta?.width && meta?.height ? `${meta.width}:${meta.height}` : aspectPreset)
    : hasImage
      ? (imgRatio || aspectPreset)
      : aspectPreset;
  const cssMediaRatio = toCssAspectRatio(mediaRatio);

  const regionColor = "#0ea5e9";
  const skipColor = "rgba(239,68,68,0.22)";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Eraser className="w-4 h-4 text-sky-500" />LCWR 预览设置</DialogTitle>
          <DialogDescription>在预览画面中框选需要去除的水印或字幕区域，坐标将按媒体比例保存。</DialogDescription>
        </DialogHeader>
        <div className="space-y-2.5 select-none">
      {/* 预览说明 */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground min-w-0">
          <Eraser className="w-3.5 h-3.5 text-sky-500 flex-shrink-0" />
          <span className="truncate">在画面上鼠标拖拽框选水印/字幕区域（可多选），坐标按视频尺寸比例保存</span>
        </div>
      </div>

      {/* 媒体预览 + 框选层 */}
      <div
        className="relative isolate w-full mx-auto overflow-hidden rounded-lg border border-border/50 bg-neutral-500"
        style={{ aspectRatio: cssMediaRatio, width: "100%", height: "auto" }}
        onPointerDown={(e) => e.stopPropagation()}
        onWheel={(e) => e.stopPropagation()}
      >
        {hasVideo ? (
          <video
            ref={videoRef}
            src={mediaUrl}
            muted
            playsInline
            preload="auto"
            onLoadedMetadata={(e) => {
              const el = e.currentTarget;
              if (el.videoWidth && el.videoHeight && (!meta?.width || !meta?.height)) {
                setMeta((current) => ({
                  duration: current?.duration || el.duration || durationSec,
                  fps: current?.fps || fps,
                  width: el.videoWidth,
                  height: el.videoHeight,
                }));
              }
            }}
            className="absolute inset-0 w-full h-full object-contain"
          />
        ) : hasImage ? (
          <img
            src={mediaUrl}
            alt="输入图片"
            className="absolute inset-0 w-full h-full object-contain"
            onLoad={(e) => {
              const el = e.currentTarget;
              if (el.naturalWidth && el.naturalHeight) setImgRatio(`${el.naturalWidth}:${el.naturalHeight}`);
            }}
          />
        ) : (
          <div className="absolute inset-0 bg-neutral-500 flex items-center justify-center">
            <span className="text-[10px] text-white/40 px-3 text-center leading-snug">
              未接入视频，使用黑帧（{aspectPreset}）框选区域<br />
              实际执行时需连接视频/图片输入
            </span>
          </div>
        )}

        {/* 已选区域 */}
        {regions.map((r, idx) => {
          const x1 = clamp01(r.start[0]), y1 = clamp01(r.start[1]);
          const x2 = clamp01(r.end[0]), y2 = clamp01(r.end[1]);
          const left = Math.min(x1, x2) * 100, top = Math.min(y1, y2) * 100;
          const w = Math.abs(x2 - x1) * 100, h = Math.abs(y2 - y1) * 100;
          return (
            <div
              key={idx}
              className="absolute border-2 pointer-events-none"
              style={{ left: `${left}%`, top: `${top}%`, width: `${w}%`, height: `${h}%`, borderColor: regionColor, boxShadow: `0 0 0 1px rgba(0,0,0,0.5) inset` }}
            >
              <span
                className="absolute -top-4 left-0 text-[9px] px-1 rounded text-white leading-4"
                style={{ backgroundColor: regionColor }}
              >
                {idx + 1}
              </span>
            </div>
          );
        })}

        {/* 正在绘制的框 */}
        {drawing && (
          <div
            className="absolute border-2 border-dashed pointer-events-none"
            style={{
              left: `${Math.min(drawing.x1, drawing.x2) * 100}%`,
              top: `${Math.min(drawing.y1, drawing.y2) * 100}%`,
              width: `${Math.abs(drawing.x2 - drawing.x1) * 100}%`,
              height: `${Math.abs(drawing.y2 - drawing.y1) * 100}%`,
              borderColor: regionColor,
              backgroundColor: "rgba(14,165,233,0.12)",
            }}
          />
        )}

        {/* 框选交互层 */}
        <div
          ref={overlayRef}
          className="absolute inset-0 cursor-crosshair"
          onPointerDown={(e) => {
            e.stopPropagation();
            (e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId);
            const p = getPos(e);
            setDrawing({ x1: p.x, y1: p.y, x2: p.x, y2: p.y });
          }}
          onPointerMove={(e) => {
            if (!drawing) return;
            e.stopPropagation();
            const p = getPos(e);
            setDrawing((d) => d ? { ...d, x2: p.x, y2: p.y } : d);
          }}
          onPointerUp={(e) => {
            e.stopPropagation();
            if (!drawing) return;
            const p = getPos(e);
            const final = { ...drawing, x2: p.x, y2: p.y };
            setDrawing(null);
            const x1 = Math.min(final.x1, final.x2), x2 = Math.max(final.x1, final.x2);
            const y1 = Math.min(final.y1, final.y2), y2 = Math.max(final.y1, final.y2);
            if (x2 - x1 > 0.005 && y2 - y1 > 0.005) {
              commitRegion({ start: [x1, y1], end: [x2, y2], frame_range: [] });
            }
          }}
        />
      </div>

      {/* 帧浏览工具栏（仅视频模式） */}
      {hasVideo && (
        <div className="space-y-1">
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); goFrame(currentFrame - frameStepSize); }}
              className="flex-shrink-0 inline-flex items-center gap-0.5 text-[10px] px-1.5 py-1 rounded-md border border-border/50 hover:bg-muted transition-colors"
              title="向前 10 帧"
            >
              <ChevronLeft className="w-3 h-3" />
            </button>
            <input
              type="range"
              min={0}
              max={sliderMax}
              step={1}
              value={Math.min(frameStep, sliderMax)}
              onChange={(e) => onFrameSlider(Number(e.target.value))}
              onPointerDown={(e) => e.stopPropagation()}
              onWheel={(e) => e.stopPropagation()}
              className="min-w-0 flex-1 accent-sky-500"
              title="拖动切换帧（每格 10 帧）"
            />
            <button
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); goFrame(currentFrame + frameStepSize); }}
              className="flex-shrink-0 inline-flex items-center gap-0.5 text-[10px] px-1.5 py-1 rounded-md border border-border/50 hover:bg-muted transition-colors"
              title="向后 10 帧"
            >
              <ChevronRight className="w-3 h-3" />
            </button>
          </div>
          <div className="flex items-center justify-between text-[10px] text-muted-foreground">
            <span>第 {currentFrame} 帧 / 共 {totalFrames} 帧</span>
            <span>{fmtTime(currentTime)} / {fmtTime(duration)}</span>
          </div>
          {metaError && (
            <div className="flex items-center gap-1 text-[10px] text-amber-600 dark:text-amber-400">
              <Info className="w-3 h-3 flex-shrink-0" />
              <span className="truncate">{metaError}</span>
            </div>
          )}
        </div>
      )}

      {/* 片头/片尾时间轴 */}
      <div className="space-y-1">
        <div className="flex items-center justify-between text-[10px] text-muted-foreground">
          <span className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-sm bg-red-400/80 inline-block" />
            片头跳过 {headSec.toFixed(1)}s
          </span>
          <span className="flex items-center gap-1">
            片尾跳过 {tailSec.toFixed(1)}s
            <span className="w-2 h-2 rounded-sm bg-red-400/80 inline-block" />
          </span>
        </div>
        <div
          ref={timelineRef}
          className="relative h-6 rounded-md bg-muted/60 border border-border/50 overflow-hidden cursor-pointer"
          onPointerDown={(e) => e.stopPropagation()}
        >
          {/* 片头跳过区 */}
          {headSec > 0 && (
            <div className="absolute inset-y-0 left-0 z-0" style={{ width: `${(headSec / duration) * 100}%`, backgroundColor: skipColor, borderRight: "1px dashed rgba(239,68,68,0.7)" }} />
          )}
          {/* 片尾跳过区 */}
          {tailSec > 0 && (
            <div className="absolute inset-y-0 right-0 z-0" style={{ width: `${(tailSec / duration) * 100}%`, backgroundColor: skipColor, borderLeft: "1px dashed rgba(239,68,68,0.7)" }} />
          )}
          {/* 片头拖拽柄 */}
          <div
            className="absolute top-0 bottom-0 z-10 w-2 cursor-ew-resize"
            style={{ left: `${(headSec / duration) * 100}%` }}
            onPointerDown={(e) => {
              e.stopPropagation();
              (e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId);
              timelineDragRef.current = "head";
            }}
            onPointerMove={(e) => { if (timelineDragRef.current === "head") updateSkip("head", timelineToSec(e)); }}
            onPointerUp={() => { timelineDragRef.current = null; }}
            title="拖动设置片头跳过时间"
          >
            <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-1.5 h-4 rounded-sm bg-red-400 shadow" />
          </div>
          {/* 片尾拖拽柄 */}
          <div
            className="absolute top-0 bottom-0 z-10 w-2 cursor-ew-resize"
            style={{ left: `${((duration - tailSec) / duration) * 100}%` }}
            onPointerDown={(e) => {
              e.stopPropagation();
              (e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId);
              timelineDragRef.current = "tail";
            }}
            onPointerMove={(e) => { if (timelineDragRef.current === "tail") updateSkip("tail", duration - timelineToSec(e)); }}
            onPointerUp={() => { timelineDragRef.current = null; }}
            title="拖动设置片尾跳过时间"
          >
            <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 w-1.5 h-4 rounded-sm bg-red-400 shadow" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <input
            type="number"
            min={0}
            step={0.5}
            value={headSec}
            onChange={(e) => updateSkip("head", Number(e.target.value))}
            onPointerDown={(e) => e.stopPropagation()}
            onWheel={(e) => e.stopPropagation()}
            className="text-[11px] px-2 py-1 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
            placeholder="片头跳过(秒)"
          />
          <input
            type="number"
            min={0}
            step={0.5}
            value={tailSec}
            onChange={(e) => updateSkip("tail", Number(e.target.value))}
            onPointerDown={(e) => e.stopPropagation()}
            onWheel={(e) => e.stopPropagation()}
            className="text-[11px] px-2 py-1 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
            placeholder="片尾跳过(秒)"
          />
        </div>
        {!hasVideo && (
          <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
            <span>视频比例</span>
            <div className="flex flex-wrap gap-1">
              {ASPECT_PRESETS.map((r) => (
                <button
                  key={r}
                  type="button"
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={(e) => { e.stopPropagation(); onConfigChange("aspect_ratio", r); }}
                  className={cn(
                    "px-1.5 py-0.5 rounded text-[10px] border transition-colors",
                    aspectPreset === r ? "bg-sky-500/15 border-sky-500/50 text-sky-600 dark:text-sky-400" : "border-border/50 hover:bg-muted"
                  )}
                >
                  {r}
                </button>
              ))}
            </div>
            <span className="ml-auto flex items-center gap-1">
              时长
              <input
                type="number"
                min={1}
                value={durationSec}
                onChange={(e) => onConfigChange("duration_sec", Number(e.target.value) || 10)}
                onPointerDown={(e) => e.stopPropagation()}
                className="w-14 text-[11px] px-1.5 py-0.5 rounded-md border border-border/50 bg-background outline-none focus:border-primary/50"
              />s
            </span>
          </div>
        )}
      </div>

      {/* 区域列表 */}
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-medium text-muted-foreground">去除区域（{regions.length}）</span>
          {regions.length > 0 && (
            <button
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); clearRegions(); }}
              className="flex items-center gap-0.5 text-[10px] text-red-500 hover:text-red-600 transition-colors"
            >
              <Trash2 className="w-3 h-3" /> 清空
            </button>
          )}
        </div>
        {regions.length === 0 ? (
          <p className="text-[10px] text-muted-foreground/70">尚未框选区域，请在预览画面上按住鼠标左键拖拽框选水印/字幕位置</p>
        ) : (
          <div className="space-y-1">
            {regions.map((r, idx) => {
              const x1 = clamp01(r.start[0]), y1 = clamp01(r.start[1]);
              const x2 = clamp01(r.end[0]), y2 = clamp01(r.end[1]);
              return (
                <div key={idx} className="flex items-center gap-1.5 text-[10px] px-2 py-1 rounded-md bg-sky-500/5 border border-sky-500/20">
                  <span className="flex-shrink-0 inline-flex items-center justify-center w-4 h-4 rounded text-[9px] text-white" style={{ backgroundColor: regionColor }}>
                    {idx + 1}
                  </span>
                  <span className="text-muted-foreground truncate flex-1">
                    x: {Math.min(x1, x2).toFixed(3)}~{Math.max(x1, x2).toFixed(3)} · y: {Math.min(y1, y2).toFixed(3)}~{Math.max(y1, y2).toFixed(3)}
                  </span>
                  <span className="text-muted-foreground/60 flex-shrink-0">全程生效</span>
                  <button
                    type="button"
                    onPointerDown={(e) => e.stopPropagation()}
                    onClick={(e) => { e.stopPropagation(); removeRegion(idx); }}
                    className="flex-shrink-0 text-muted-foreground hover:text-red-500 transition-colors"
                    title="删除该区域"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              );
            })}
          </div>
        )}</div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export const LcwrWatermarkEditor = memo(LcwrWatermarkEditorInner);
