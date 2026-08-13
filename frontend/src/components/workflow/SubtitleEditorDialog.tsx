import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Combine, FolderOpen, Maximize2, Minimize2, Pause, Play, Scissors, X } from "lucide-react";
import { nativeFileDialog } from "@/api/files";
import { cn } from "@/lib/utils";

interface SubtitleEntry {
  start: number;
  end: number;
  text: string;
}

interface Props {
  open: boolean;
  initialEntries?: SubtitleEntry[];
  initialVideo?: string;
  taskId?: string;
  onClose: () => void;
  onSave: (entries: SubtitleEntry[]) => void;
}

function stableFileUrl(path?: string, taskId?: string): string {
  if (!path) return "";
  const params = new URLSearchParams({ path });
  if (taskId) params.set("task_id", taskId);
  params.set("t", String(Date.now()));
  return `/api/files/stream?${params.toString()}`;
}

function formatTime(sec: number): string {
  if (!isFinite(sec)) return "00:00";
  const s = Math.max(0, Math.floor(sec));
  const m = Math.floor(s / 60);
  const h = Math.floor(m / 60);
  return h > 0 ? `${h}:${String(m % 60).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}` : `${m}:${String(s % 60).padStart(2, "0")}`;
}

export default function SubtitleEditorDialog({ open, initialEntries, initialVideo, taskId, onClose, onSave }: Props) {
  const [entries, setEntries] = useState<SubtitleEntry[]>([]);
  const [videoUrl, setVideoUrl] = useState("");
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [maximized, setMaximized] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const rowRefs = useRef<(HTMLDivElement | null)[]>([]);
  const cursorPos = useRef<{ i: number; pos: number }>({ i: -1, pos: 0 });

  // 打开时初始化：载入字幕与视频
  useEffect(() => {
    if (!open) return;
    setEntries((initialEntries || []).map((e) => ({ start: Number(e.start) || 0, end: Number(e.end) || 0, text: e.text || "" })));
    const vid = initialVideo || "";
    setVideoUrl(stableFileUrl(vid, taskId));
    setCurrentTime(0);
    setDuration(0);
    setPlaying(false);
  }, [open, initialEntries, initialVideo, taskId]);

  // 当前播放时间命中的字幕索引
  const activeIndex = useMemo(() => {
    for (let i = 0; i < entries.length; i++) {
      if (currentTime >= entries[i].start && currentTime < entries[i].end) return i;
    }
    return -1;
  }, [entries, currentTime]);

  // 播放时自动滚动到当前字幕
  useEffect(() => {
    if (activeIndex >= 0 && playing) {
      rowRefs.current[activeIndex]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [activeIndex, playing]);

  const updateEntry = useCallback((i: number, patch: Partial<SubtitleEntry>) => {
    setEntries((prev) => prev.map((e, j) => (j === i ? { ...e, ...patch } : e)));
  }, []);

  // 合并到上一条：文本拼接到上一条，时间区间取上条起点到本条终点
  const mergeUp = useCallback((i: number) => {
    if (i <= 0) return;
    setEntries((prev) => {
      const next = prev.map((e, j) => {
        if (j === i - 1) return { ...e, end: prev[i].end, text: (e.text + "\n" + prev[i].text).trim() };
        return e;
      });
      next.splice(i, 1);
      return next;
    });
  }, []);

  // 在光标处拆分：文本按光标位置分为两段，时间按中点均分
  const splitAtCursor = useCallback((i: number, cursor: number) => {
    setEntries((prev) => {
      const e = prev[i];
      if (!e) return prev;
      const text = e.text || "";
      const pos = Math.max(0, Math.min(cursor, text.length));
      if (pos === 0 || pos >= text.length) return prev;
      const left = text.slice(0, pos).trim();
      const right = text.slice(pos).trim();
      if (!right) return prev;
      const mid = (e.start + e.end) / 2;
      const next = prev.map((x, j) => (j === i ? { ...x, text: left, end: mid } : x));
      next.splice(i + 1, 0, { start: mid, end: e.end, text: right });
      return next;
    });
  }, []);

  const jumpTo = useCallback((t: number) => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = t;
    setCurrentTime(t);
  }, []);

  const togglePlay = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      v.play().catch(() => {});
      setPlaying(true);
    } else {
      v.pause();
      setPlaying(false);
    }
  }, []);

  const loadVideo = useCallback(async () => {
    const path = await nativeFileDialog("file", "选择视频", [["Video", "mp4,avi,mkv,mov,webm,flv"]]);
    if (path) {
      const p = Array.isArray(path) ? path[0] : path;
      setVideoUrl(stableFileUrl(p, taskId));
    }
  }, [taskId]);

  if (!open) return null;

  const numCls = "w-16 text-xs px-1.5 py-1 rounded border border-border/50 bg-background focus:border-primary/50 outline-none";

  return createPortal(
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 backdrop-blur-sm" onPointerDown={(e) => e.stopPropagation()}>
      <div className={cn(
        "w-[1320px] max-w-[94vw] h-[816px] max-h-[88vh] flex flex-col rounded-2xl border border-border/60 bg-card text-card-foreground shadow-2xl",
        maximized && "w-[96vw] max-w-[96vw] h-[94vh] max-h-[94vh]"
      )}>
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-border/50">
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold">字幕编辑</span>
            <span className="text-[11px] text-muted-foreground">共 {entries.length} 条</span>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => setMaximized((p) => !p)}
              className="p-1.5 rounded-md text-muted-foreground/70 hover:text-foreground hover:bg-foreground/10"
              title={maximized ? "还原窗口" : "最大化"}
            >
              {maximized ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-md text-muted-foreground/70 hover:text-foreground hover:bg-foreground/10"
              title="关闭"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Body：左侧字幕列表（可滚动），右侧视频预览（固定） */}
        <div className="flex-1 min-h-0 flex gap-3 px-4 py-3">
          {/* 左侧字幕列表 */}
          <div ref={listRef} className="flex-1 min-w-0 overflow-y-auto space-y-2 pr-1">
            {entries.length === 0 && (
              <div className="text-xs text-muted-foreground text-center py-8">暂无字幕数据</div>
            )}
            {entries.map((e, i) => (
              <div
                key={i}
                ref={(el) => { rowRefs.current[i] = el; }}
                className={cn(
                  "rounded-lg border p-2 transition-colors",
                  activeIndex === i ? "border-primary/60 bg-primary/10" : "border-border/50 bg-background"
                )}
              >
                <div className="flex items-center gap-1.5 mb-1">
                  <span className="text-[10px] text-muted-foreground w-6 flex-shrink-0">{i + 1}</span>
                  <input
                    type="number" step="0.1" min={0}
                    value={Number.isFinite(e.start) ? e.start : 0}
                    onChange={(ev) => updateEntry(i, { start: Number(ev.target.value) || 0 })}
                    className={numCls}
                    title="起始时间（秒）"
                    onPointerDown={(ev) => ev.stopPropagation()}
                  />
                  <span className="text-muted-foreground text-xs">-</span>
                  <input
                    type="number" step="0.1" min={0}
                    value={Number.isFinite(e.end) ? e.end : 0}
                    onChange={(ev) => updateEntry(i, { end: Number(ev.target.value) || 0 })}
                    className={numCls}
                    title="结束时间（秒）"
                    onPointerDown={(ev) => ev.stopPropagation()}
                  />
                  <span className="text-[10px] text-muted-foreground ml-auto flex-shrink-0 tabular-nums">
                    {formatTime(e.start)} ~ {formatTime(e.end)}
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <input
                    value={e.text}
                    onChange={(ev) => updateEntry(i, { text: ev.target.value })}
                    onSelect={(ev) => { cursorPos.current = { i, pos: ev.currentTarget.selectionStart ?? 0 }; }}
                    placeholder="字幕文本"
                    className="flex-1 min-w-0 text-xs px-2 py-1 rounded border border-border/50 bg-background focus:border-primary/50 outline-none"
                    onPointerDown={(ev) => ev.stopPropagation()}
                  />
                  <button
                    type="button"
                    onClick={() => mergeUp(i)}
                    disabled={i === 0}
                    title="合并到上一条"
                    className="p-1.5 rounded-md text-muted-foreground/70 hover:text-amber-600 hover:bg-amber-500/10 disabled:opacity-30 disabled:cursor-not-allowed"
                    onPointerDown={(ev) => ev.stopPropagation()}
                  >
                    <Combine className="w-3.5 h-3.5" />
                  </button>
                  <button
                    type="button"
                    onClick={() => splitAtCursor(i, cursorPos.current.i === i ? cursorPos.current.pos : 0)}
                    title="在光标处拆分"
                    className="p-1.5 rounded-md text-muted-foreground/70 hover:text-sky-600 hover:bg-sky-500/10"
                    onPointerDown={(ev) => ev.stopPropagation()}
                  >
                    <Scissors className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* 右侧视频预览（固定） */}
          <div className="w-[430px] flex-shrink-0 flex flex-col gap-2 border-l border-border/50 pl-3">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-medium text-muted-foreground">视频预览</span>
              <button
                type="button"
                onClick={loadVideo}
                className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border border-border/50 text-muted-foreground hover:text-primary hover:border-primary/40"
              >
                <FolderOpen className="w-3 h-3" />
                加载视频
              </button>
            </div>
            <div className="relative rounded-lg overflow-hidden bg-black aspect-video flex-shrink-0">
              <video
                ref={videoRef}
                src={videoUrl}
                className="w-full h-full"
                onTimeUpdate={(ev) => setCurrentTime(ev.currentTarget.currentTime)}
                onLoadedMetadata={(ev) => setDuration(ev.currentTarget.duration)}
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
                onEnded={() => setPlaying(false)}
              />
              {!videoUrl && (
                <div className="absolute inset-0 flex items-center justify-center text-muted-foreground text-xs">
                  未加载视频
                </div>
              )}
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={togglePlay}
                disabled={!videoUrl}
                title={playing ? "暂停" : "播放"}
                className="p-1.5 rounded-md bg-primary/10 text-primary border border-primary/30 hover:bg-primary/20 disabled:opacity-30 disabled:cursor-not-allowed"
              >
                {playing ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5" />}
              </button>
              <input
                type="range"
                min={0}
                max={duration || 0}
                step={0.1}
                value={currentTime}
                onChange={(ev) => jumpTo(Number(ev.target.value))}
                className="flex-1 accent-primary"
                onPointerDown={(ev) => ev.stopPropagation()}
              />
              <span className="text-[10px] text-muted-foreground flex-shrink-0 tabular-nums">
                {formatTime(currentTime)} / {formatTime(duration)}
              </span>
            </div>
            {/* 当前字幕预览 */}
            {activeIndex >= 0 ? (
              <div className="text-[11px] p-2 rounded-md bg-primary/10 border border-primary/30 break-words">
                <span className="font-medium text-primary">{entries[activeIndex].text || "（空文本）"}</span>
              </div>
            ) : (
              <div className="text-[11px] text-muted-foreground p-2 rounded-md border border-border/40">当前无命中字幕</div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between px-4 py-3 border-t border-border/50">
          <span className="text-[11px] text-muted-foreground pr-3 leading-snug">
            左侧逐条编辑字幕（文本/时间/合并到上一条/光标处拆分），右侧视频预览固定；播放时高亮并自动滚动到当前字幕，时间轴同步。默认不修改输入，保存后输出编辑结果；勾选「另存副本」输出带随机后缀的副本，否则覆盖原文件。需人工编辑，可与「运行等待」节点配合。
          </span>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="px-3 py-1.5 text-xs rounded-md border border-border/50 text-muted-foreground hover:text-foreground"
            >
              取消
            </button>
            <button
              onClick={() => { onSave(entries); onClose(); }}
              className="px-3 py-1.5 text-xs rounded-md bg-primary text-primary-foreground hover:opacity-90"
            >
              保存到节点
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
}
