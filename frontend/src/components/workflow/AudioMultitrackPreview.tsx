/**
 * 音频多轨预览卡片：按接入的音频输入渲染音轨（最多 6 轨）。
 *
 * - 每轨：播放/暂停、进度拖动、时间显示、独立静音按钮；
 * - 静音只关掉该轨声音，播放位置继续跟随时间轴走位，取消静音后仍与其它轨对齐；
 * - 顶部「同步播放」开关：开启时所有已接入音轨对齐到同一时间轴播放，并周期性校正漂移；
 *   关闭时各轨完全独立，适合逐轨试听；
 * - 开关状态持久化在节点 config.sync_play（沿用 video_preview 用 config 承载预览设置的做法）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Headphones, Link2, Pause, Play, Square, Unlink2, Volume2, VolumeX } from "lucide-react";
import { cn } from "@/lib/utils";

export const AUDIO_TRACK_COUNT = 6;

const DRIFT_TOLERANCE = 0.12;      // 同步播放时允许的最大时间偏差（秒），超出即回拨到主轨
const DRIFT_CHECK_INTERVAL = 300;  // 漂移校正检查周期（毫秒）
const ALIGN_EPSILON = 0.02;        // 对齐播放前的最小回拨阈值（秒），避免无意义的 currentTime 写入

/** 生成稳定的文件流 URL（与 WorkflowNode 内同名工具一致：带 task_id 与 cache-bust）。 */
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

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds <= 0) return "0:00";
  const total = Math.floor(seconds);
  const mm = Math.floor(total / 60);
  const ss = total % 60;
  return `${mm}:${String(ss).padStart(2, "0")}`;
}

function fileName(path: string): string {
  const parts = String(path || "").split(/[\\/]/);
  return parts[parts.length - 1] || String(path || "");
}

interface TrackRowProps {
  index: number;
  path: string;
  taskId?: string;
  refreshKey?: string;
  sync: boolean;
  solo: boolean;
  muted: boolean;
  playing: boolean;
  time: number;
  duration: number;
  errored: boolean;
  onTogglePlay: () => void;
  onSeek: (seconds: number) => void;
  onToggleMute: () => void;
  registerAudio: (index: number, el: HTMLAudioElement | null) => void;
  onTimeUpdate: (index: number, seconds: number) => void;
  onDuration: (index: number, seconds: number) => void;
  onPlayingChange: (index: number, playing: boolean) => void;
  onError: (index: number, errored: boolean) => void;
}

function TrackRow({
  index, path, taskId, refreshKey, sync, solo, muted, playing, time, duration, errored,
  onTogglePlay, onSeek, onToggleMute, registerAudio, onTimeUpdate, onDuration, onPlayingChange, onError,
}: TrackRowProps) {
  const src = useStableFileUrl(path, taskId, refreshKey);
  const hasDuration = duration > 0;
  const seekable = hasDuration || time > 0;

  // ref 回调必须保持稳定身份：内联箭头每次渲染都是新函数，React 会在每次提交时
  // 先 detach(null) 再 attach，若在回调里 setState 就会与提交阶段相互触发成死循环。
  const setAudioRef = useCallback((el: HTMLAudioElement | null) => {
    registerAudio(index, el);
  }, [index, registerAudio]);

  return (
    <div className="min-w-0 space-y-1 rounded-md border border-border/50 bg-background/60 px-2 py-1.5">
      <div className="flex min-w-0 items-center gap-1.5">
        <span className="flex-shrink-0 rounded bg-emerald-500/10 px-1 py-0.5 text-[10px] font-medium text-emerald-600">
          音轨{index + 1}
        </span>
        <span className="min-w-0 flex-1 truncate text-[10px] text-foreground/80" title={path}>
          {fileName(path)}
        </span>
        <span className="flex-shrink-0 text-[10px] tabular-nums text-muted-foreground">
          {formatTime(time)}/{formatTime(duration)}
        </span>
        {errored && (
          <span
            className="flex-shrink-0 text-[10px] text-destructive"
            title="音频文件不存在或不可读（相对路径需要用产出它的任务打开，或该产物已被清理）"
          >
            文件不可读
          </span>
        )}
        <button
          type="button"
          disabled={errored}
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => { e.stopPropagation(); onTogglePlay(); }}
          title={sync ? "同步播放/暂停全部音轨" : "播放/暂停本轨"}
          className="flex-shrink-0 rounded p-0.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-40"
        >
          {playing ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
        </button>
        <button
          type="button"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => { e.stopPropagation(); onToggleMute(); }}
          title={
            solo
              ? (muted ? "独听本轨（自动关闭其它轨的喇叭）" : "静音本轨（独播模式下会全部静音）")
              : (muted ? "取消静音（播放位置一直保持同步）" : "静音本轨（仍同步走位）")
          }
          className={cn(
            "flex-shrink-0 rounded p-0.5 transition-colors hover:bg-accent",
            muted ? "text-destructive" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {muted ? <VolumeX className="h-3 w-3" /> : <Volume2 className="h-3 w-3" />}
        </button>
      </div>
      <input
        type="range"
        min={0}
        max={hasDuration ? duration : 0}
        step={0.01}
        value={hasDuration ? Math.min(time, duration) : 0}
        disabled={!seekable || errored}
        onChange={(e) => onSeek(Number(e.target.value))}
        onPointerDown={(e) => e.stopPropagation()}
        onWheel={(e) => e.stopPropagation()}
        className="h-1 w-full accent-primary disabled:opacity-40"
      />
      <audio
        key={src}
        ref={setAudioRef}
        src={src}
        muted={muted}
        preload="metadata"
        onTimeUpdate={(e) => onTimeUpdate(index, e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => { onError(index, false); onDuration(index, e.currentTarget.duration); }}
        onDurationChange={(e) => onDuration(index, e.currentTarget.duration)}
        onPlay={() => onPlayingChange(index, true)}
        onPause={() => onPlayingChange(index, false)}
        onEnded={() => onPlayingChange(index, false)}
        onError={() => onError(index, true)}
        className="hidden"
      />
    </div>
  );
}

export function AudioMultitrackPreview({ config, tracks, taskId, refreshKey, onConfigChange }: {
  config: Record<string, any>;
  tracks: string[];
  taskId?: string;
  refreshKey?: string;
  onConfigChange?: (key: string, value: any) => void;
}) {
  const sync = config.sync_play !== false;
  const solo = config.solo_mode === true;
  const audioEls = useRef<(HTMLAudioElement | null)[]>([]);
  // 独播开关可持久化：首帧就按「只放开第一路已接入音轨」初始化静音位
  const [muted, setMuted] = useState<boolean[]>(() => {
    const firstConnected = (tracks || []).findIndex((path) => !!path);
    return Array.from({ length: AUDIO_TRACK_COUNT }, (_, i) =>
      (config.solo_mode === true ? i !== firstConnected : false));
  });
  const [playing, setPlaying] = useState<boolean[]>(() => Array(AUDIO_TRACK_COUNT).fill(false));
  const [times, setTimes] = useState<number[]>(() => Array(AUDIO_TRACK_COUNT).fill(0));
  const [durations, setDurations] = useState<number[]>(() => Array(AUDIO_TRACK_COUNT).fill(0));
  const [errors, setErrors] = useState<boolean[]>(() => Array(AUDIO_TRACK_COUNT).fill(false));

  const paths = useMemo(
    () => Array.from({ length: AUDIO_TRACK_COUNT }, (_, i) => String(tracks?.[i] || "")),
    [tracks],
  );
  // 内容指纹：paths 每次渲染都是新数组，副作用依赖必须用它而非数组本身
  const pathsKey = paths.join("\u0000");
  const activeIndexes = useMemo(
    () => paths.map((path, i) => (path ? i : -1)).filter((i) => i >= 0),
    [paths],
  );
  // activeIndexes 每次渲染都是新数组，用拼接字符串做依赖/缓存键，避免依赖它的回调与副作用每帧重建
  const activeKey = activeIndexes.join(",");
  const leaderIndex = activeIndexes.length ? activeIndexes[0] : -1;
  const anyPlaying = playing.some(Boolean);

  const collectEls = useCallback(
    () => (activeKey ? activeKey.split(",").map(Number) : [])
      .map((i) => audioEls.current[i])
      .filter((el): el is HTMLAudioElement => !!el),
    [activeKey],
  );

  // 接入集合变化时修正状态，避免按钮停在“播放中”的假象
  useEffect(() => {
    const active = new Set(activeKey ? activeKey.split(",").map(Number) : []);
    setPlaying((prev) => {
      let changed = false;
      const next = prev.map((value, i) => {
        if (!active.has(i) && value) { changed = true; return false; }
        return value;
      });
      return changed ? next : prev;
    });
  }, [activeKey]);

  const registerAudio = useCallback((index: number, el: HTMLAudioElement | null) => {
    audioEls.current[index] = el;
  }, []);

  // 音频路径变化（换源/断连/重连）时重置该轨的播放/进度/时长：
  // 对应 <audio>（key=src）会重建并重新加载，旧进度与“播放中”标记都不再成立。
  // 这段逻辑放在父组件里、由 paths 驱动，不依赖子组件回调，避免组件间契约在热更新等场景错位。
  const prevPathsRef = useRef(pathsKey);
  useEffect(() => {
    const prevKey = prevPathsRef.current;
    prevPathsRef.current = pathsKey;
    if (prevKey === pathsKey) return;
    const prevList = prevKey.split("\u0000");
    const nextList = pathsKey.split("\u0000");
    const touched = new Set<number>();
    for (let i = 0; i < AUDIO_TRACK_COUNT; i += 1) {
      if ((prevList[i] || "") !== (nextList[i] || "")) touched.add(i);
    }
    if (!touched.size) return;
    setTimes((prev) => {
      let hit = false;
      const next = prev.map((value, i) => {
        if (touched.has(i) && value) { hit = true; return 0; }
        return value;
      });
      return hit ? next : prev;
    });
    setDurations((prev) => {
      let hit = false;
      const next = prev.map((value, i) => {
        if (touched.has(i) && value) { hit = true; return 0; }
        return value;
      });
      return hit ? next : prev;
    });
    setPlaying((prev) => {
      let hit = false;
      const next = prev.map((value, i) => {
        if (touched.has(i) && value) { hit = true; return false; }
        return value;
      });
      return hit ? next : prev;
    });
  }, [pathsKey]);

  /** 全部对齐播放：以主轨（第一路已接入音轨）当前时间为基准，或用 from 指定起点。 */
  const playAll = useCallback((from?: number) => {
    const els = collectEls();
    if (!els.length) return;
    const leader = leaderIndex >= 0 ? audioEls.current[leaderIndex] : null;
    const base = typeof from === "number" ? from : (leader?.currentTime ?? 0);
    els.forEach((el) => {
      if (Math.abs(el.currentTime - base) > ALIGN_EPSILON) {
        try { el.currentTime = base; } catch { /* 元数据未就绪，忽略 */ }
      }
    });
    els.forEach((el) => { void el.play().catch(() => undefined); });
  }, [collectEls, leaderIndex]);

  const pauseAll = useCallback(() => {
    collectEls().forEach((el) => el.pause());
  }, [collectEls]);

  const stopAll = useCallback(() => {
    collectEls().forEach((el) => { el.pause(); el.currentTime = 0; });
  }, [collectEls]);

  // 离开画布/节点卸载时停止播放，避免后台继续出声
  useEffect(() => () => {
    audioEls.current.forEach((el) => el?.pause());
  }, []);

  // 同步模式下的漂移校正：任一轨跑偏超过阈值就回拨到主轨
  useEffect(() => {
    if (!sync || !anyPlaying || leaderIndex < 0) return;
    const timer = window.setInterval(() => {
      const leader = audioEls.current[leaderIndex];
      if (!leader || leader.paused) return;
      audioEls.current.forEach((el, i) => {
        if (!el || i === leaderIndex || el.paused) return;
        if (Math.abs(el.currentTime - leader.currentTime) > DRIFT_TOLERANCE) {
          el.currentTime = leader.currentTime;
        }
      });
    }, DRIFT_CHECK_INTERVAL);
    return () => window.clearInterval(timer);
  }, [sync, anyPlaying, leaderIndex]);

  const toggleTrack = useCallback((index: number) => {
    if (sync) {
      if (anyPlaying) pauseAll(); else playAll();
      return;
    }
    const el = audioEls.current[index];
    if (!el) return;
    if (el.paused) void el.play().catch(() => undefined); else el.pause();
  }, [sync, anyPlaying, pauseAll, playAll]);

  /** 独播开关：打开只放开第一路已接入音轨（其余全部静音），关闭则所有轨恢复发声。 */
  const toggleSolo = useCallback(() => {
    const next = !solo;
    onConfigChange?.("solo_mode", next);
    const first = activeKey ? Number(activeKey.split(",")[0]) : -1;
    setMuted(Array.from({ length: AUDIO_TRACK_COUNT }, (_, i) => (next ? i !== first : false)));
  }, [solo, activeKey, onConfigChange]);

  /** 喇叭按钮：独播模式下「取消静音某轨」= 把它设为唯一可听轨，自动关闭其它轨的喇叭。 */
  const toggleMute = useCallback((index: number) => {
    setMuted((prev) => {
      if (!solo) return prev.map((v, i) => (i === index ? !v : v));
      const wasMuted = prev[index];
      // 取消静音 → 只留本轨；再点一次（静音本轨）→ 全部静音
      return prev.map((_, i) => (i === index ? !wasMuted : true));
    });
  }, [solo]);

  /** 拖动进度：同步模式下所有轨一起跳（保持对齐），独立模式下只动本轨。 */
  const seekTo = useCallback((index: number, seconds: number) => {
    const value = Math.max(0, Number(seconds) || 0);
    if (sync) {
      collectEls().forEach((el) => { el.currentTime = value; });
      setTimes((prev) => prev.map((t, i) => (activeIndexes.includes(i) ? value : t)));
      return;
    }
    const el = audioEls.current[index];
    if (el) el.currentTime = value;
    setTimes((prev) => {
      const next = [...prev];
      next[index] = value;
      return next;
    });
  }, [sync, collectEls, activeIndexes]);

  const toggleSync = useCallback(() => {
    const next = !sync;
    onConfigChange?.("sync_play", next);
    // 由独立切到同步且正在播放：立刻以主轨为基准对齐一次，避免带着偏差继续跑
    if (next && anyPlaying) playAll();
  }, [sync, anyPlaying, playAll, onConfigChange]);

  const handleTimeUpdate = useCallback((index: number, value: number) => {
    setTimes((prev) => {
      if (Math.abs((prev[index] ?? 0) - value) < 0.05) return prev;
      const next = [...prev];
      next[index] = value;
      return next;
    });
  }, []);

  const handleDuration = useCallback((index: number, value: number) => {
    setDurations((prev) => {
      const safe = isFinite(value) && value > 0 ? value : 0;
      if (prev[index] === safe) return prev;
      const next = [...prev];
      next[index] = safe;
      return next;
    });
  }, []);

  const handlePlayingChange = useCallback((index: number, value: boolean) => {
    setPlaying((prev) => (prev[index] === value ? prev : prev.map((v, i) => (i === index ? value : v))));
  }, []);

  // 音频流 404/解码失败时标记该轨不可读（相对路径依赖任务工作区，换任务打开或产物被清就会命中）
  const handleError = useCallback((index: number, value: boolean) => {
    setErrors((prev) => (prev[index] === value ? prev : prev.map((v, i) => (i === index ? value : v))));
  }, []);

  const masterTime = leaderIndex >= 0 ? (times[leaderIndex] ?? 0) : 0;
  const masterDuration = leaderIndex >= 0 ? (durations[leaderIndex] ?? 0) : 0;

  return (
    <div className="min-w-0 space-y-2 border-t border-border/50 px-3 pb-3 pt-2">
      {/* 顶部：同步开关 + 全局播放控制 */}
      <div className="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => { e.stopPropagation(); toggleSync(); }}
          title={sync ? "已开启：六轨对齐同一时间轴播放（点击改为各轨独立）" : "已关闭：各轨独立播放（点击改为同步对齐播放）"}
          className={cn(
            "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium transition-colors",
            sync
              ? "border-primary/40 bg-primary/10 text-primary"
              : "border-border/50 text-muted-foreground hover:text-foreground",
          )}
        >
          {sync ? <Link2 className="h-3 w-3" /> : <Unlink2 className="h-3 w-3" />}
          同步播放
          <span className={cn(
            "relative ml-0.5 inline-block h-3 w-6 rounded-full transition-colors",
            sync ? "bg-primary/60" : "bg-muted",
          )}>
            <span className={cn(
              "absolute top-0.5 h-2 w-2 rounded-full bg-background transition-all",
              sync ? "left-3.5" : "left-0.5",
            )} />
          </span>
        </button>
        {sync && activeIndexes.length > 0 && (
          <>
            <button
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); anyPlaying ? pauseAll() : playAll(); }}
              title={anyPlaying ? "暂停全部音轨" : "六轨对齐播放"}
              className="inline-flex items-center gap-1 rounded-md border border-border/50 px-1.5 py-0.5 text-[10px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              {anyPlaying ? <Pause className="h-3 w-3" /> : <Play className="h-3 w-3" />}
              {anyPlaying ? "暂停" : "对齐播放"}
            </button>
            <button
              type="button"
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => { e.stopPropagation(); stopAll(); }}
              title="停止并回到起点"
              className="inline-flex items-center gap-1 rounded-md border border-border/50 px-1.5 py-0.5 text-[10px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              <Square className="h-3 w-3" />
              重置
            </button>
          </>
        )}
        {/* 独播：一次只听一路（打开时默认放开第一路已接入音轨） */}
        <button
          type="button"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={(e) => { e.stopPropagation(); toggleSolo(); }}
          title={
            solo
              ? "独播已开：只放一路，点其它轨的喇叭即切到该轨；关闭后所有轨恢复发声"
              : "独播：打开后所有轨静音、只放开第一路已接入音轨，点其它轨的喇叭即独占该轨"
          }
          className={cn(
            "inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[10px] font-medium transition-colors",
            solo
              ? "border-primary/40 bg-primary/10 text-primary"
              : "border-border/50 text-muted-foreground hover:text-foreground",
          )}
        >
          <Headphones className="h-3 w-3" />
          独播
          <span className={cn(
            "relative ml-0.5 inline-block h-3 w-6 rounded-full transition-colors",
            solo ? "bg-primary/60" : "bg-muted",
          )}>
            <span className={cn(
              "absolute top-0.5 h-2 w-2 rounded-full bg-background transition-all",
              solo ? "left-3.5" : "left-0.5",
            )} />
          </span>
        </button>
        <span className="ml-auto flex-shrink-0 text-[10px] text-muted-foreground">
          {activeIndexes.length}/{AUDIO_TRACK_COUNT} 轨已接入
        </span>
      </div>

      {/* 同步模式：主时间轴（拖动即六轨一起跳） */}
      {sync && activeIndexes.length > 0 && (
        <div className="flex items-center gap-2">
          <span className="w-20 flex-shrink-0 text-[10px] tabular-nums text-muted-foreground">
            {formatTime(masterTime)} / {formatTime(masterDuration)}
          </span>
          <input
            type="range"
            min={0}
            max={masterDuration > 0 ? masterDuration : 0}
            step={0.01}
            value={masterDuration > 0 ? Math.min(masterTime, masterDuration) : 0}
            disabled={masterDuration <= 0}
            onChange={(e) => seekTo(leaderIndex, Number(e.target.value))}
            onPointerDown={(e) => e.stopPropagation()}
            onWheel={(e) => e.stopPropagation()}
            className="h-1 flex-1 min-w-0 accent-primary disabled:opacity-40"
            title="主时间轴：拖动后六轨一起跳转，保持对齐"
          />
        </div>
      )}

      {activeIndexes.length === 0 ? (
        <p className="text-[10px] leading-snug text-muted-foreground">
          把音频接到左侧「音轨1~6」输入端口，接入后按轨显示：每轨可单独试听、拖动进度、静音；
          打开顶部「同步播放」即六轨对齐同一时间轴播放；「独播」打开后一次只听一路，点该轨喇叭即可切换。
        </p>
      ) : (
        <div className="space-y-1.5">
          {activeIndexes.map((index) => (
            <TrackRow
              key={index}
              index={index}
              path={paths[index]}
              taskId={taskId}
              refreshKey={refreshKey}
              sync={sync}
              solo={solo}
              muted={muted[index]}
              playing={playing[index]}
              time={times[index] ?? 0}
              duration={durations[index] ?? 0}
              errored={errors[index] ?? false}
              onTogglePlay={() => toggleTrack(index)}
              onSeek={(seconds) => seekTo(index, seconds)}
              onToggleMute={() => toggleMute(index)}
              registerAudio={registerAudio}
              onTimeUpdate={handleTimeUpdate}
              onDuration={handleDuration}
              onPlayingChange={handlePlayingChange}
              onError={handleError}
            />
          ))}
        </div>
      )}
    </div>
  );
}
