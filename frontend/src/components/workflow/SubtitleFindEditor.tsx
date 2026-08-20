import { memo, useState, useCallback, useEffect, useRef, useMemo } from "react";
import client from "@/api/client";
import { nativeFileDialog } from "@/api/files";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Captions, Trash2, ChevronLeft, ChevronRight, Info, Upload, FolderOpen } from "lucide-react";

/**
 * 手动定位弹窗：预览视频并框选字幕区域（相对比例坐标）+ 设置片头/片尾跳过时间。
 *
 * 配置字段（config）：
 * - manual_box: {x1, y1, x2, y2}（相对比例 0~1）
 * - skip_head_sec / skip_tail_sec：片头/片尾跳过秒数（默认 0）
 *
 * 复用 LCWR 去水印弹窗的交互模式（预览 + 框选 + 时间轴拖拽）。
 */

type VideoMeta = { duration: number; fps: number; width: number; height: number };
type ManualBox = { x1: number; y1: number; x2: number; y2: number };

function clamp01(v: number): number {
  return Math.max(0, Math.min(1, v));
}

function toCssAspectRatio(value: string): string {
  const match = value.trim().match(/^(\d+(?:\.\d+)?):(\d+(?:\.\d+)?)$/);
  return match ? `${match[1]} / ${match[2]}` : "16 / 9";
}

function fmtTime(sec: number): string {
  if (!isFinite(sec) || sec < 0) return "00:00";
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
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

function SubtitleFindEditorInner({ config, onConfigChange, videoPath, taskId, open, onOpenChange }: {
  config: Record<string, any>;
  onConfigChange: (key: string, value: any) => void;
  videoPath?: string;
  taskId?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const box: ManualBox | null = config.manual_box && typeof config.manual_box === "object" && "x1" in config.manual_box
    ? config.manual_box as ManualBox
    : null;
  const durationSec = Number(config.duration_sec) || 10;
  const fps = Number(config.fps) || 25;

  // 手动导入的参考视频（优先级高于上游连线视频），用于无连线或需本地参考时框选
  const [importedPath, setImportedPath] = useState<string>("");
  const effectiveVideoPath = importedPath || videoPath;

  const [meta, setMeta] = useState<VideoMeta | null>(null);
  const [metaError, setMetaError] = useState("");
  const [frameStep, setFrameStep] = useState(0);
  const videoRef = useRef<HTMLVideoElement>(null);
  const mediaUrl = useStableFileUrl(effectiveVideoPath, taskId);

  const [drawing, setDrawing] = useState<{ x1: number; y1: number; x2: number; y2: number } | null>(null);
  const overlayRef = useRef<HTMLDivElement>(null);
  const timelineRef = useRef<HTMLDivElement>(null);
  const timelineDragRef = useRef<"head" | "tail" | null>(null);

  const hasVideo = !!effectiveVideoPath;
  const duration = hasVideo ? (meta?.duration || 0) : durationSec;

  // 导入参考视频：打开系统文件选择框
  const handleImportVideo = useCallback(async () => {
    const path = await nativeFileDialog("file", "选择参考视频", [["视频", "*.mp4;*.mkv;*.avi;*.mov;*.webm;*.flv;*.wmv;*.m4v"]]);
    if (typeof path === "string" && path) {
      setImportedPath(path);
      setFrameStep(0);
    }
  }, []);

  useEffect(() => {
    setMeta(null);
    setMetaError("");
    setFrameStep(0);
    if (!hasVideo || !effectiveVideoPath) return;
    let cancelled = false;
    client.get("/api/files/video-info", { params: { path: effectiveVideoPath, task_id: taskId || undefined } })
      .then((res) => {
        if (cancelled) return;
        const d = res.data || {};
        setMeta({ duration: Number(d.duration) || 0, fps: Number(d.fps) || 25, width: Number(d.width) || 0, height: Number(d.height) || 0 });
      })
      .catch((err) => {
        if (!cancelled) setMetaError(err?.response?.data?.detail || err?.message || "视频信息读取失败");
      });
    return () => { cancelled = true; };
  }, [hasVideo, effectiveVideoPath, taskId]);

  const totalFrames = meta ? Math.max(1, Math.floor(meta.duration * meta.fps)) : Math.max(1, Math.floor(durationSec * fps));
  const frameStepSize = 10;
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

  const onFrameSlider = (val: number) => {
    setFrameStep(val);
    if (hasVideo) seekTime(val * frameStepSize / (meta?.fps || fps));
  };

  // ---------- 字幕区域框选（单区域，相对比例坐标） ----------
  /** 基于视频尺寸（meta.width/height）计算画面内容在预览容器中的实际显示矩形（object-contain letterbox）。 */
  const getVideoContentRect = useCallback(() => {
    const el = overlayRef.current;
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    // 无视频或尺寸未知时以预览区域为准
    if (!meta?.width || !meta?.height || rect.width <= 0 || rect.height <= 0) {
      return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
    }
    const ar = meta.width / meta.height;
    const boxAr = rect.width / rect.height;
    if (boxAr > ar) {
      // 容器更宽：上下留黑边，内容高度由视频比例决定
      const h = rect.width / ar;
      return { left: rect.left, top: rect.top + (rect.height - h) / 2, width: rect.width, height: h };
    }
    // 容器更高：左右留黑边
    const w = rect.height * ar;
    return { left: rect.left + (rect.width - w) / 2, top: rect.top, width: w, height: rect.height };
  }, [meta]);

  const getPos = (e: React.PointerEvent) => {
    const content = getVideoContentRect();
    if (!content || content.width <= 0 || content.height <= 0) return { x: 0, y: 0 };
    return {
      x: clamp01((e.clientX - content.left) / content.width),
      y: clamp01((e.clientY - content.top) / content.height),
    };
  };

  const setBox = (next: ManualBox | null) => onConfigChange("manual_box", next);

  const commitBox = (x1: number, y1: number, x2: number, y2: number) => {
    setBox({ x1, y1, x2, y2 });
  };

  // ---------- 片头/片尾跳过 ----------
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
      onConfigChange("skip_head_sec", Math.round(Math.min(clamped, Math.max(0, duration - tailSec)) * 10) / 10);
    } else {
      onConfigChange("skip_tail_sec", Math.round(Math.min(clamped, Math.max(0, duration - headSec)) * 10) / 10);
    }
  };

  const mediaRatio = hasVideo && meta?.width && meta?.height ? `${meta.width}:${meta.height}` : "16:9";
  const cssMediaRatio = toCssAspectRatio(mediaRatio);
  const regionColor = "#f59e0b";
  const skipColor = "rgba(239,68,68,0.22)";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2"><Captions className="w-4 h-4" style={{ color: regionColor }} />手动定位字幕区域</DialogTitle>
          <DialogDescription>在预览画面中拖拽框选字幕位置，坐标按视频比例（相对）保存，可适配不同分辨率视频。</DialogDescription>
        </DialogHeader>
        <div className="space-y-2.5 select-none">
          {/* 预览说明 */}
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground min-w-0">
              <Captions className="w-3.5 h-3.5 flex-shrink-0" style={{ color: regionColor }} />
              <span className="truncate">
                在画面上鼠标拖拽框选字幕区域，坐标为相对比例（0~1）
                {importedPath && <span className="ml-1 text-amber-600 dark:text-amber-400">· 参考：{importedPath.split(/[\\/]/).pop()}</span>}
              </span>
            </div>
            <div className="flex items-center gap-1 flex-shrink-0">
              {box && (
                <button
                  type="button"
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={(e) => { e.stopPropagation(); setBox(null); }}
                  className="flex items-center gap-0.5 text-[10px] text-red-500 hover:text-red-600 transition-colors"
                >
                  <Trash2 className="w-3 h-3" /> 清除框选
                </button>
              )}
              {importedPath ? (
                <button
                  type="button"
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={(e) => { e.stopPropagation(); setImportedPath(""); }}
                  className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-md border border-border/50 hover:bg-muted transition-colors"
                  title="恢复使用连线视频"
                >
                  <FolderOpen className="w-3 h-3" /> 恢复连线视频
                </button>
              ) : (
                <button
                  type="button"
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={(e) => { e.stopPropagation(); handleImportVideo(); }}
                  className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-md border border-border/50 hover:bg-muted transition-colors"
                  title="导入本地视频作为参考进行框选"
                >
                  <Upload className="w-3 h-3" /> 导入参考视频
                </button>
              )}
            </div>
          </div>

          {/* 视频预览 + 框选层 */}
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
            ) : (
              <div className="absolute inset-0 bg-neutral-500 flex items-center justify-center">
                <span className="text-[10px] text-white/40 px-3 text-center leading-snug">
                  未接入视频，无法预览<br />可点击「导入参考视频」选择本地视频，或先连接视频输入
                </span>
              </div>
            )}

            {/* 已框选的字幕区域 */}
            {box && (
              <div
                className="absolute border-2 pointer-events-none"
                style={{
                  left: `${Math.min(box.x1, box.x2) * 100}%`,
                  top: `${Math.min(box.y1, box.y2) * 100}%`,
                  width: `${Math.abs(box.x2 - box.x1) * 100}%`,
                  height: `${Math.abs(box.y2 - box.y1) * 100}%`,
                  borderColor: regionColor,
                  boxShadow: "0 0 0 1px rgba(0,0,0,0.5) inset",
                  backgroundColor: "rgba(245,158,11,0.12)",
                }}
              >
                <span className="absolute -top-4 left-0 text-[9px] px-1 rounded text-white leading-4" style={{ backgroundColor: regionColor }}>
                  字幕区域
                </span>
              </div>
            )}

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
                  backgroundColor: "rgba(245,158,11,0.12)",
                }}
              />
            )}

            {/* 框选交互层 */}
            {hasVideo && (
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
                    commitBox(x1, y1, x2, y2);
                  }
                }}
              />
            )}
          </div>

          {/* 帧浏览工具栏 */}
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
                  className="min-w-0 flex-1 accent-amber-500"
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
              {headSec > 0 && (
                <div className="absolute inset-y-0 left-0 z-0" style={{ width: `${(headSec / duration) * 100}%`, backgroundColor: skipColor, borderRight: "1px dashed rgba(239,68,68,0.7)" }} />
              )}
              {tailSec > 0 && (
                <div className="absolute inset-y-0 right-0 z-0" style={{ width: `${(tailSec / duration) * 100}%`, backgroundColor: skipColor, borderLeft: "1px dashed rgba(239,68,68,0.7)" }} />
              )}
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
            <p className="text-[10px] text-muted-foreground/70">
              设置后字幕查找与识别阶段都会跳过片头/片尾时间段，不参与 OCR。
            </p>
          </div>

          {/* 字幕框坐标显示 */}
          <div className="rounded-md border border-amber-500/20 bg-amber-500/5 px-2 py-1.5 text-[10px] text-muted-foreground">
            {box ? (
              <span>
                字幕框坐标（相对）：x {Math.min(box.x1, box.x2).toFixed(3)}~{Math.max(box.x1, box.x2).toFixed(3)} · y {Math.min(box.y1, box.y2).toFixed(3)}~{Math.max(box.y1, box.y2).toFixed(3)}
              </span>
            ) : (
              <span>尚未框选字幕区域，请在预览画面上按住鼠标左键拖拽框选</span>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export const SubtitleFindEditor = memo(SubtitleFindEditorInner);
