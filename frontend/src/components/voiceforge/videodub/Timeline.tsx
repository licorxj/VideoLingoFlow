import { useEffect, useMemo, useRef, useState } from "react";
import { Plus, Scan, Volume2, VolumeX, X, ZoomIn, ZoomOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { timelineDuration, useVideoDubStore } from "./store";
import { formatTimecode, mediaDuration } from "./media";
import { clamp, isAudioTrack, TRACK_COLORS, TRACK_NAMES, TRACK_ORDER, TrackKind } from "./types";

const HEADER_W = 140;
const RULER_H = 26;
const TRACK_H = 46;
const TAIL_SECONDS = 8;

const TICK_STEPS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 1200, 1800, 3600];

type ScrubHandlers = {
  onPointerDown: (event: React.PointerEvent) => void;
  onPointerMove: (event: React.PointerEvent) => void;
  onPointerUp: () => void;
  onPointerCancel: () => void;
};

/** 把指针横向拖动换算成时间并驱动时间指针（标尺 / 轨道空白区 / 指针手柄共用）。 */
function useScrub(contentRef: React.RefObject<HTMLDivElement | null>): ScrubHandlers {
  const seek = useVideoDubStore((state) => state.seek);
  const activeRef = useRef(false);

  const timeAt = (clientX: number) => {
    const rect = contentRef.current?.getBoundingClientRect();
    if (!rect) return null;
    return Math.max(0, (clientX - rect.left - HEADER_W) / useVideoDubStore.getState().pxPerSec);
  };

  return {
    onPointerDown: (event) => {
      if (event.button !== 0) return;
      const time = timeAt(event.clientX);
      if (time == null) return;
      activeRef.current = true;
      event.currentTarget.setPointerCapture(event.pointerId);
      seek(time);
    },
    onPointerMove: (event) => {
      if (!activeRef.current) return;
      const time = timeAt(event.clientX);
      if (time != null) seek(time);
    },
    onPointerUp: () => {
      activeRef.current = false;
    },
    onPointerCancel: () => {
      activeRef.current = false;
    },
  };
}

/** 可拖动的时间指针，纵贯标尺与全部轨道。 */
function Playhead({ contentRef }: { contentRef: React.RefObject<HTMLDivElement | null> }) {
  const currentTime = useVideoDubStore((state) => state.currentTime);
  const pxPerSec = useVideoDubStore((state) => state.pxPerSec);
  const scrub = useScrub(contentRef);
  return (
    <div
      className="absolute bottom-0 top-0 z-[25] w-3 -translate-x-1/2 cursor-ew-resize touch-none select-none"
      style={{ left: HEADER_W + currentTime * pxPerSec }}
      title="时间指针（拖动定位，与视频播放同步）"
      onPointerDown={scrub.onPointerDown}
      onPointerMove={scrub.onPointerMove}
      onPointerUp={scrub.onPointerUp}
      onPointerCancel={scrub.onPointerCancel}
    >
      <div className="absolute inset-y-0 left-1/2 w-[2px] -translate-x-1/2 bg-red-500/90" />
      <div className="absolute left-1/2 top-0 h-3.5 w-3.5 -translate-x-1/2 rounded-full border-2 border-white bg-red-500 shadow-sm" />
    </div>
  );
}

/** 时间刻度尺：自适应刻度密度，点击 / 拖动可定位。 */
function Ruler({ contentSec, contentRef }: { contentSec: number; contentRef: React.RefObject<HTMLDivElement | null> }) {
  const pxPerSec = useVideoDubStore((state) => state.pxPerSec);
  const scrub = useScrub(contentRef);

  const major = TICK_STEPS.find((step) => step * pxPerSec >= 64) ?? 3600;
  const minor = major / 5;
  const ticks = useMemo(() => {
    const items: Array<{ time: number; major: boolean }> = [];
    const count = Math.min(2000, Math.ceil(contentSec / minor) + 1);
    for (let index = 0; index <= count; index += 1) {
      const time = index * minor;
      items.push({ time, major: index % 5 === 0 });
    }
    return items;
  }, [contentSec, minor]);

  return (
    <div className="sticky top-0 z-20 flex border-b border-border/60 bg-card" style={{ height: RULER_H }}>
      <div
        className="sticky left-0 z-30 flex-none border-r border-border/60 bg-card text-[10px] text-muted-foreground"
        style={{ width: HEADER_W }}
      >
        <span className="flex h-full items-center px-2">时间</span>
      </div>
      <div
        className="relative flex-none cursor-ew-resize touch-none select-none"
        style={{ width: `${contentSec * pxPerSec}px` }}
        onPointerDown={scrub.onPointerDown}
        onPointerMove={scrub.onPointerMove}
        onPointerUp={scrub.onPointerUp}
        onPointerCancel={scrub.onPointerCancel}
      >
        {ticks.map(({ time, major: isMajor }) => (
          <div key={time} className={cn("absolute bottom-0", isMajor ? "w-px bg-border" : "w-px bg-border/50")} style={{ left: time * pxPerSec }}>
            {isMajor ? (
              <>
                <span className="absolute bottom-[13px] left-1 -translate-x-0 whitespace-nowrap font-mono text-[9px] tabular-nums text-muted-foreground">
                  {formatTimecode(time, major < 1 ? 1 : 0)}
                </span>
                <span className="absolute bottom-0 h-2.5 w-px bg-border" />
              </>
            ) : (
              <span className="absolute bottom-0 h-1.5 w-px bg-border/50" />
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/** 音轨喇叭开关：静音 / 取消静音该轨道的声音输出。 */
function TrackMuteButton({ kind }: { kind: TrackKind }) {
  const muted = useVideoDubStore((state) => state.mutedTracks[kind]);
  const toggleTrackMute = useVideoDubStore((state) => state.toggleTrackMute);
  return (
    <button
      type="button"
      title={muted ? "开启该轨道声音" : "静音该轨道"}
      aria-label={muted ? "开启该轨道声音" : "静音该轨道"}
      aria-pressed={!muted}
      onClick={(event) => {
        event.stopPropagation();
        toggleTrackMute(kind);
      }}
      className={cn(
        "flex-none rounded p-0.5 transition-colors",
        muted ? "text-muted-foreground/45 hover:text-foreground" : "text-primary hover:text-primary/70",
      )}
    >
      {muted ? <VolumeX className="h-3.5 w-3.5" /> : <Volume2 className="h-3.5 w-3.5" />}
    </button>
  );
}

/** 音轨「+」：选择本地音频文件，从播放头之后顺序铺到轨道上。 */
function TrackAddAudioButton({ kind }: { kind: TrackKind }) {
  const inputRef = useRef<HTMLInputElement>(null);
  const handleFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    const state = useVideoDubStore.getState();
    let cursor = Math.max(
      state.clips[kind].reduce((end, clip) => Math.max(end, clip.start + clip.duration), 0),
      state.currentTime,
    );
    for (const file of Array.from(files)) {
      const url = URL.createObjectURL(file);
      const detected = await mediaDuration(url);
      const duration = detected > 0 ? detected : 3;
      state.addClip(kind, { name: file.name, start: cursor, duration, url, file });
      cursor += duration;
    }
  };
  return (
    <>
      <button
        type="button"
        title="添加本地音频文件到该轨道（从播放头之后顺序排列）"
        onClick={() => inputRef.current?.click()}
        className="flex-none rounded p-0.5 text-muted-foreground/70 transition-colors hover:bg-muted hover:text-foreground"
      >
        <Plus className="h-3.5 w-3.5" />
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="audio/*"
        multiple
        className="hidden"
        onChange={(event) => {
          void handleFiles(event.target.files);
          event.target.value = "";
        }}
      />
    </>
  );
}

function TrackHeaderCell({ kind }: { kind: TrackKind }) {
  const removeTrack = useVideoDubStore((state) => state.removeTrack);
  const color = TRACK_COLORS[kind];
  return (
    <div
      className="group sticky left-0 z-30 flex flex-none items-center gap-1 border-r border-border/60 bg-card px-2"
      style={{ width: HEADER_W, height: TRACK_H }}
    >
      <span className={cn("h-2 w-2 flex-none rounded-full", color.dot)} />
      <span className="min-w-0 flex-1 truncate text-xs font-medium">{TRACK_NAMES[kind]}</span>
      {isAudioTrack(kind) ? <TrackAddAudioButton kind={kind} /> : null}
      {isAudioTrack(kind) ? <TrackMuteButton kind={kind} /> : null}
      <button
        type="button"
        title="删除轨道（可通过「添加轨道」恢复）"
        onClick={() => removeTrack(kind)}
        className="flex-none rounded p-0.5 text-muted-foreground/70 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function ClipBlock({
  id,
  start,
  end,
  label,
  color,
  active,
  onSeek,
  onMove,
  onDelete,
}: {
  id: string;
  start: number;
  end: number;
  label: string;
  color: { clip: string };
  active: boolean;
  onSeek: (id: string) => void;
  /** 水平拖动片段时回调新的起始时间（未拖动则触发 onSeek）。 */
  onMove?: (id: string, newStart: number) => void;
  onDelete?: (id: string) => void;
}) {
  const pxPerSec = useVideoDubStore((state) => state.pxPerSec);
  const dragRef = useRef<{ startX: number; origStart: number; moved: boolean } | null>(null);

  return (
    <div
      data-clip
      title={`${formatTimecode(start)} - ${formatTimecode(end)}\n${label}${onMove ? "\n拖动可调整位置" : ""}`}
      className={cn(
        "group/clip absolute top-1 flex h-[calc(100%-8px)] cursor-grab touch-none select-none items-center overflow-hidden rounded border pl-1.5 pr-1 text-left text-[11px] leading-4 transition-shadow active:cursor-grabbing",
        color.clip,
        active && "ring-2 ring-primary/70",
      )}
      style={{ left: start * pxPerSec, width: Math.max(4, (end - start) * pxPerSec - 1) }}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.stopPropagation();
        dragRef.current = { startX: event.clientX, origStart: start, moved: false };
        event.currentTarget.setPointerCapture(event.pointerId);
      }}
      onPointerMove={(event) => {
        const drag = dragRef.current;
        if (!drag || !onMove) return;
        if (Math.abs(event.clientX - drag.startX) > 4) drag.moved = true;
        if (drag.moved) onMove(id, Math.max(0, drag.origStart + (event.clientX - drag.startX) / pxPerSec));
      }}
      onPointerUp={(event) => {
        const drag = dragRef.current;
        dragRef.current = null;
        if (drag && !drag.moved) onSeek(id);
        else event.stopPropagation();
      }}
      onPointerCancel={() => {
        dragRef.current = null;
      }}
    >
      <span className="pointer-events-none truncate">{label}</span>
      {onDelete ? (
        <button
          type="button"
          title="删除该片段"
          onClick={(event) => {
            event.stopPropagation();
            onDelete(id);
          }}
          onPointerDown={(event) => event.stopPropagation()}
          className="absolute right-0.5 top-0.5 hidden rounded bg-black/35 p-0.5 text-white/90 hover:bg-black/60 group-hover/clip:block"
        >
          <X className="h-2.5 w-2.5" />
        </button>
      ) : null}
    </div>
  );
}

function TrackLane({ kind }: { kind: TrackKind }) {
  const pairs = useVideoDubStore((state) => state.pairs);
  const clips = useVideoDubStore((state) => state.clips[kind]);
  const selectedPairId = useVideoDubStore((state) => state.selectedPairId);
  const currentTime = useVideoDubStore((state) => state.currentTime);
  const muted = useVideoDubStore((state) => state.mutedTracks[kind]);
  const seek = useVideoDubStore((state) => state.seek);
  const selectPair = useVideoDubStore((state) => state.selectPair);
  const updatePair = useVideoDubStore((state) => state.updatePair);
  const moveClip = useVideoDubStore((state) => state.moveClip);
  const removeClip = useVideoDubStore((state) => state.removeClip);
  const laneRef = useRef<HTMLDivElement>(null);

  const locateAt = (clientX: number) => {
    const rect = laneRef.current?.getBoundingClientRect();
    if (!rect) return;
    seek(Math.max(0, (clientX - rect.left) / useVideoDubStore.getState().pxPerSec));
  };

  // 拖动吸附：片段起始/结束边缘对齐到字幕边界、其他片段边缘、播放头或 0 点
  const snap = (clipId: string, rawStart: number, duration: number) => {
    const state = useVideoDubStore.getState();
    const targets = new Set<number>([0, state.currentTime]);
    for (const pair of state.pairs) {
      targets.add(pair.start);
      targets.add(pair.end);
    }
    for (const trackKind of TRACK_ORDER) {
      for (const clip of state.clips[trackKind]) {
        if (trackKind === kind && clip.id === clipId) continue;
        targets.add(clip.start);
        targets.add(clip.start + clip.duration);
      }
    }
    const threshold = 8 / state.pxPerSec;
    let best = rawStart;
    let bestDelta = threshold;
    for (const target of targets) {
      const startDelta = Math.abs(rawStart - target);
      if (startDelta < bestDelta) {
        bestDelta = startDelta;
        best = target;
      }
      const endDelta = Math.abs(rawStart + duration - target);
      if (endDelta < bestDelta) {
        bestDelta = endDelta;
        best = target - duration;
      }
    }
    return Math.max(0, best);
  };

  // 字幕片段拖动 = 整句平移（保持时长，配音片段自动跟随）；音频片段拖动 = 移动起点
  const movePair = (id: string, newStart: number) => {
    const pair = useVideoDubStore.getState().pairs.find((item) => item.id === id);
    if (!pair) return;
    const duration = Math.max(0.1, pair.end - pair.start);
    const snapped = snap(id, newStart, duration);
    updatePair(id, { start: snapped, end: snapped + duration });
  };

  const items =
    kind === "subtitle"
      ? pairs.map((pair) => ({ id: pair.id, start: pair.start, end: Math.max(pair.end, pair.start + 0.1), label: pair.text || "（空）", duration: Math.max(0.1, pair.end - pair.start), move: movePair, onDelete: undefined }))
      : kind === "subtitle_translation"
        ? pairs
            .filter((pair) => pair.translation)
            .map((pair) => ({ id: pair.id, start: pair.start, end: Math.max(pair.end, pair.start + 0.1), label: pair.translation, duration: Math.max(0.1, pair.end - pair.start), move: movePair, onDelete: undefined }))
        : clips.map((clip) => ({
            id: clip.id,
            start: clip.start,
            end: clip.start + clip.duration,
            label: clip.name,
            duration: clip.duration,
            move: (id: string, newStart: number) => moveClip(kind, id, snap(id, newStart, clip.duration)),
            onDelete: (id: string) => removeClip(kind, id),
          }));

  const color = TRACK_COLORS[kind];

  return (
    <div
      ref={laneRef}
      className={cn("relative flex-1 touch-none transition-opacity", muted && "opacity-45")}
      style={{ height: TRACK_H }}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        locateAt(event.clientX);
      }}
    >
      {items.map((item) => (
        <ClipBlock
          key={item.id}
          id={item.id}
          start={item.start}
          end={item.end}
          label={item.label}
          color={color}
          active={item.id === selectedPairId || (isAudioTrack(kind) && currentTime >= item.start && currentTime <= item.end)}
          onSeek={(id) => {
            seek(item.start + 0.01);
            if (kind === "subtitle" || kind === "subtitle_translation") selectPair(id);
          }}
          onMove={item.move}
          onDelete={item.onDelete}
        />
      ))}
    </div>
  );
}

function AddTrackControl({ missing }: { missing: TrackKind[] }) {
  const addTrack = useVideoDubStore((state) => state.addTrack);
  const trackCount = useVideoDubStore((state) => state.tracks.length);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  return (
    <div ref={rootRef} className="relative flex h-9 items-center border-t border-border/40 px-2" style={{ width: HEADER_W }}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        disabled={!missing.length}
        className="flex w-full items-center gap-1 rounded px-1 py-1 text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-50"
        title={missing.length ? "恢复被删除的轨道" : "已显示全部轨道"}
      >
        <Plus className="h-3.5 w-3.5" />
        添加轨道
        <span className="ml-auto font-mono">{trackCount}/6</span>
      </button>
      {open && missing.length ? (
        <div className="absolute bottom-full left-0 z-50 mb-1 w-40 rounded-lg border border-border bg-popover p-1 shadow-lg">
          {missing.map((kind) => {
            const color = TRACK_COLORS[kind];
            return (
              <button
                key={kind}
                type="button"
                onClick={() => {
                  addTrack(kind);
                  setOpen(false);
                }}
                className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-muted"
              >
                <span className={cn("h-2 w-2 rounded-full", color.dot)} />
                {TRACK_NAMES[kind]}
              </button>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}

export function Timeline() {
  const tracks = useVideoDubStore((state) => state.tracks);
  const pxPerSec = useVideoDubStore((state) => state.pxPerSec);
  const setPxPerSec = useVideoDubStore((state) => state.setPxPerSec);
  const playing = useVideoDubStore((state) => state.playing);
  const currentTime = useVideoDubStore((state) => state.currentTime);
  const hasContent = useVideoDubStore((state) => Boolean(state.video || state.pairs.length));

  const duration = useVideoDubStore(timelineDuration);
  const contentSec = duration + TAIL_SECONDS;
  const scrollerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);

  // 鼠标在轨道区滚动滚轮 → 横向滚动
  useEffect(() => {
    const element = scrollerRef.current;
    if (!element) return;
    const onWheel = (event: WheelEvent) => {
      if (Math.abs(event.deltaY) > Math.abs(event.deltaX)) {
        element.scrollLeft += event.deltaY;
        event.preventDefault();
      }
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, []);

  // 播放时时间指针靠近边缘则自动跟随
  useEffect(() => {
    if (!playing) return;
    const element = scrollerRef.current;
    if (!element) return;
    const position = currentTime * pxPerSec;
    if (position < element.scrollLeft + 32 || position > element.scrollLeft + element.clientWidth - 96) {
      element.scrollLeft = Math.max(0, position - element.clientWidth * 0.3);
    }
  }, [currentTime, playing, pxPerSec]);

  const fit = () => {
    const element = scrollerRef.current;
    if (!element) return;
    const available = element.clientWidth - HEADER_W - 16;
    setPxPerSec(available / Math.max(duration, 1));
  };

  const missing = TRACK_ORDER.filter((kind) => !tracks.includes(kind));

  return (
    <section className="flex h-[380px] flex-none flex-col overflow-hidden rounded-xl border border-border/60 bg-card">
      <header className="flex h-9 flex-none items-center gap-2 border-b border-border/60 px-3">
        <span className="text-sm font-semibold">时间轴</span>
        <span className="text-[11px] text-muted-foreground">总时长 {formatTimecode(duration, 1)}</span>
        <div className="ml-auto flex items-center gap-1">
          <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => setPxPerSec(pxPerSec / 1.4)} title="缩小">
            <ZoomOut className="h-3.5 w-3.5" />
          </Button>
          <span className="w-14 text-center font-mono text-[11px] tabular-nums text-muted-foreground">{Math.round(pxPerSec)} px/s</span>
          <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => setPxPerSec(pxPerSec * 1.4)} title="放大">
            <ZoomIn className="h-3.5 w-3.5" />
          </Button>
          <Button size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={fit}>
            <Scan className="mr-1 h-3 w-3" />
            适应
          </Button>
        </div>
      </header>

      <div ref={scrollerRef} className="min-h-0 flex-1 overflow-auto">
        <div ref={contentRef} className="relative select-none" style={{ width: HEADER_W + contentSec * pxPerSec, minHeight: "100%" }}>
          <Ruler contentSec={contentSec} contentRef={contentRef} />

          {tracks.map((kind) => (
            <div key={kind} className="flex border-b border-border/40" style={{ height: TRACK_H }}>
              <TrackHeaderCell kind={kind} />
              <TrackLane kind={kind} />
            </div>
          ))}

          <div className="flex h-9 items-center border-t border-border/40" style={{ minHeight: 36 }}>
            <AddTrackControl missing={missing} />
            <div className="flex-1 px-3 text-[11px] text-muted-foreground">
              {hasContent
                ? "滚轮在轨道区左右滚动 · 点击标尺或轨道定位 · 拖动红色时间指针微调"
                : "添加视频与字幕后，字幕、原音等片段会显示在对应轨道上"}
            </div>
          </div>

          <Playhead contentRef={contentRef} />
        </div>
      </div>
    </section>
  );
}
