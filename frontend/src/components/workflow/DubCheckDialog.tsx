import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { MouseEvent as ReactMouseEvent } from "react";
import { createPortal } from "react-dom";
import {
  X, Loader2, RefreshCw, Play, Pause, AudioLines, Save, Music, Settings2,
  ChevronLeft, ChevronRight, CheckSquare, Square, AlertTriangle, Filter,
} from "lucide-react";
import client from "@/api/client";
import AudioSelectorDialog from "@/components/AudioSelectorDialog";
import { cn } from "@/lib/utils";

interface DubSegment {
  index: number;
  id: number;
  text: string;
  dub_text: string;
  read_text: string;
  read_tone_desc: string;
  ref_audio: string;
  ref_audio_exists: boolean;
  audio_file: string;
  audio_exists: boolean;
  original_duration: number;
  duration: number;
  real_duration: number;
  speed_ratio: number;
  start: number;
  end: number;
}

interface TtsInterface {
  id: string;
  name?: string;
  type?: string;
}

interface Props {
  open: boolean;
  taskId?: string;
  dubPath?: string;
  onClose: () => void;
}

const MODE_LABELS: Record<string, string> = {
  preset_voice: "预置音色",
  voice_design: "音色设计",
  clone: "声音克隆",
  controllable_clone: "指令克隆",
};

const PAGE_SIZES = [10, 20, 50, 100];

// 速率筛选默认值：找出过快(>1.3)或过慢(<0.9)的异常条目
const DEFAULT_MIN_RATIO = "1.3";
const DEFAULT_MAX_RATIO = "0.9";

// 审听播放倍数
const AUDITION_RATES = [0.75, 1, 1.25, 1.5, 2];

/** 任务内文件流地址（带 task_id 与 cache-bust，重生后 tick 变化即刷新音频）。 */
function fileUrl(path: string, taskId?: string, tick?: number): string {
  if (!path) return "";
  const params = new URLSearchParams({ path });
  if (taskId) params.set("task_id", taskId);
  params.set("t", String(tick ?? Date.now()));
  return `/api/files/stream?${params.toString()}`;
}

function fmt(sec: number): string {
  const v = Number(sec) || 0;
  return `${v.toFixed(2)}s`;
}

/** 变速比率 = 配音时长 / 原始时长（实时由两列时长计算，缺时长时回退速度字段）。 */
function computeRatio(seg: DubSegment): number {
  const original = Number(seg.original_duration || seg.duration || 0);
  const real = Number(seg.real_duration || 0);
  if (original > 0 && real > 0) return real / original;
  return Number(seg.speed_ratio) || 1;
}

export default function DubCheckDialog({ open, taskId, dubPath, onClose }: Props) {
  const [segments, setSegments] = useState<DubSegment[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);
  const [busy, setBusy] = useState(false);

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [selected, setSelected] = useState<Record<number, boolean>>({});
  const [speeds, setSpeeds] = useState<Record<number, number>>({});
  const [dirty, setDirty] = useState<Record<number, boolean>>({});

  // TTS 接口设置
  const [interfaces, setInterfaces] = useState<TtsInterface[]>([]);
  const [modes, setModes] = useState<string[]>([]);
  const [voices, setVoices] = useState<string[]>([]);
  const [engine, setEngine] = useState("");
  const [mode, setMode] = useState("");
  const [voice, setVoice] = useState("");
  const [refAudio, setRefAudio] = useState("");
  const [batchSpeed, setBatchSpeed] = useState(1);
  const [showTts, setShowTts] = useState(true);

  // 参考音频选择器（行级）
  const [refPickerIndex, setRefPickerIndex] = useState<number | null>(null);
  const [showGlobalRefPicker, setShowGlobalRefPicker] = useState(false);

  // 速率筛选（按变速比率过滤条目）；默认找出过快(>1.3)或过慢(<0.9)的异常条目
  const [minRatioInput, setMinRatioInput] = useState(DEFAULT_MIN_RATIO);
  const [maxRatioInput, setMaxRatioInput] = useState(DEFAULT_MAX_RATIO);
  const [ratioFilter, setRatioFilter] = useState<{ min: number | null; max: number | null } | null>(null);

  // 审听控制套件（连贯播放列表片段）
  const [auditionOn, setAuditionOn] = useState(false);
  const [auditionIndex, setAuditionIndex] = useState<number | null>(null);
  const [auditionRate, setAuditionRate] = useState(1);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const rowRefs = useRef<Record<number, HTMLTableRowElement | null>>({});
  const tableScrollRef = useRef<HTMLDivElement | null>(null);
  const pendingScrollTop = useRef<number | null>(null);

  const load = useCallback(async () => {
    if (!dubPath) {
      setError("未找到配音任务 JSON，请先运行上游配音节点或连接 json 输入");
      return;
    }
    setLoading(true);
    setError("");
    try {
      const res = await client.post("/api/dub-check/load", { path: dubPath, task_id: taskId || "" });
      const data = res.data || {};
      setSegments(data.segments || []);
      setPage(1);
      setSelected({});
      setDirty({});
      // 重新载入时停止审听
      setAuditionOn(false);
      setAuditionIndex(null);
      // 重生速率默认值 = 当前变速比率（配音时长 / 原始时长）
      setSpeeds(
        Object.fromEntries(
          (data.segments || []).map((s: DubSegment) => [s.index, computeRatio(s)])
        )
      );
      setTick(Date.now());
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "读取配音任务失败");
    } finally {
      setLoading(false);
    }
  }, [dubPath, taskId]);

  // 打开时载入配音任务与 TTS 接口列表
  useEffect(() => {
    if (!open) return;
    load();
    client
      .get("/api/tts-interfaces/enabled")
      .then((res) => setInterfaces((res.data?.interfaces || []) as TtsInterface[]))
      .catch(() => setInterfaces([]));
  }, [open, load]);

  // 切换引擎：拉取该引擎支持的模式与音色
  useEffect(() => {
    if (!engine) {
      setModes([]);
      setVoices([]);
      return;
    }
    client
      .get(`/api/tts-interfaces/capabilities/${encodeURIComponent(engine)}`)
      .then((res) => setModes(res.data?.supported_modes || []))
      .catch(() => setModes([]));
    client
      .get(`/api/tts-interfaces/${encodeURIComponent(engine)}/voices`)
      .then((res) => setVoices(res.data?.voices || []))
      .catch(() => setVoices([]));
  }, [engine]);

  // 筛选模式：下限 > 上限 时按「区间外」筛选（保留过快或过慢的异常条目）
  const outsideMode = ratioFilter
    ? ratioFilter.min !== null && ratioFilter.max !== null && ratioFilter.min > ratioFilter.max
    : false;

  // 按变速比率筛选后的条目（未筛选时等于全部）
  const filteredSegments = useMemo(() => {
    if (!ratioFilter) return segments;
    const { min, max } = ratioFilter;
    return segments.filter((s) => {
      const ratio = computeRatio(s);
      if (outsideMode) {
        if (min !== null && ratio > min) return true;
        if (max !== null && ratio < max) return true;
        return false;
      }
      if (min !== null && ratio < min) return false;
      if (max !== null && ratio > max) return false;
      return true;
    });
  }, [segments, ratioFilter, outsideMode]);

  const filterDesc = useMemo(() => {
    if (!ratioFilter) return "";
    const { min, max } = ratioFilter;
    if (outsideMode && min !== null && max !== null) {
      return `比率 > ${min.toFixed(2)} 或 < ${max.toFixed(2)}`;
    }
    if (min !== null && max !== null) return `${min.toFixed(2)} ≤ 比率 ≤ ${max.toFixed(2)}`;
    if (min !== null) return `比率 ≥ ${min.toFixed(2)}`;
    if (max !== null) return `比率 ≤ ${max.toFixed(2)}`;
    return "";
  }, [ratioFilter, outsideMode]);

  const totalPages = Math.max(1, Math.ceil(filteredSegments.length / pageSize));
  const pageSegments = useMemo(
    () => filteredSegments.slice((page - 1) * pageSize, page * pageSize),
    [filteredSegments, page, pageSize]
  );
  const selectedIndices = useMemo(
    () => Object.keys(selected).filter((k) => selected[Number(k)]).map(Number),
    [selected]
  );

  const applyRatioFilter = () => {
    const minRaw = minRatioInput.trim();
    const maxRaw = maxRatioInput.trim();
    const min = minRaw === "" ? null : Number(minRaw);
    const max = maxRaw === "" ? null : Number(maxRaw);
    if ((min !== null && !Number.isFinite(min)) || (max !== null && !Number.isFinite(max))) {
      setError("速率筛选值必须是数字");
      return;
    }
    setError("");
    setRatioFilter(min === null && max === null ? null : { min, max });
    setPage(1);
  };

  const clearRatioFilter = () => {
    setRatioFilter(null);
    setMinRatioInput(DEFAULT_MIN_RATIO);
    setMaxRatioInput(DEFAULT_MAX_RATIO);
    setPage(1);
  };

  // 筛选/数据变化导致页码越界时回到最后一页
  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  // 重生等整体替换数据后，还原表格滚动位置，避免跳回顶部
  useLayoutEffect(() => {
    if (pendingScrollTop.current !== null && tableScrollRef.current) {
      tableScrollRef.current.scrollTop = pendingScrollTop.current;
      pendingScrollTop.current = null;
    }
  }, [pageSegments]);

  // ---------------- 审听控制（连贯播放列表中所有片段） ----------------
  const auditionPos = useMemo(
    () => filteredSegments.findIndex((s) => s.index === auditionIndex),
    [filteredSegments, auditionIndex]
  );

  const stopAudition = useCallback(() => {
    const el = audioRef.current;
    if (el) {
      el.pause();
      try { el.currentTime = 0; } catch { /* ignore */ }
    }
    setAuditionOn(false);
    setAuditionIndex(null);
  }, []);

  const startAudition = useCallback((target?: number) => {
    if (filteredSegments.length === 0) return;
    setAuditionIndex(target ?? auditionIndex ?? filteredSegments[0].index);
    setAuditionOn(true);
  }, [filteredSegments, auditionIndex]);

  const nextAudition = useCallback(() => {
    const order = filteredSegments;
    const pos = order.findIndex((s) => s.index === auditionIndex);
    const nextPos = pos + 1;
    if (nextPos >= order.length) {
      stopAudition();
      return;
    }
    setAuditionIndex(order[nextPos].index);
  }, [filteredSegments, auditionIndex, stopAudition]);

  // 切换片段/倍数：加载并播放；片段缺音频时自动跳到下一条
  useEffect(() => {
    const el = audioRef.current;
    if (!el || !auditionOn || auditionIndex === null) return;
    const seg = segments.find((s) => s.index === auditionIndex);
    if (!seg || !seg.audio_exists) {
      nextAudition();
      return;
    }
    const url = fileUrl(seg.audio_file, taskId, tick);
    if (el.dataset.auditionSrc !== url) {
      el.dataset.auditionSrc = url;
      el.src = url;
      el.load();
    }
    el.playbackRate = auditionRate;
    el.play().catch(() => undefined);
  }, [auditionOn, auditionIndex, auditionRate, tick, segments, taskId, nextAudition]);

  // 列表自动跟随：翻到当前片段所在页并滚动到该行
  useEffect(() => {
    if (auditionIndex === null) return;
    const pos = filteredSegments.findIndex((s) => s.index === auditionIndex);
    if (pos < 0) return;
    const targetPage = Math.floor(pos / pageSize) + 1;
    setPage((p) => (p === targetPage ? p : targetPage));
    rowRefs.current[auditionIndex]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [auditionIndex, filteredSegments, pageSize, page]);

  const pauseAudition = () => {
    audioRef.current?.pause();
    setAuditionOn(false);
  };

  const changeAuditionRate = (rate: number) => {
    setAuditionRate(rate);
    if (audioRef.current) audioRef.current.playbackRate = rate;
  };

  // 空格键：播放 / 暂停切换（输入框、下拉、可编辑区聚焦时不拦截，避免干扰输入）
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.code !== "Space" && e.key !== " ") return;
      const t = e.target as HTMLElement | null;
      if (
        t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable)
      ) {
        return;
      }
      e.preventDefault();
      if (auditionOn) pauseAudition();
      else startAudition();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [auditionOn, pauseAudition, startAudition]);

  // 总进度（以总句数为基数：当前句序 / 总句数）
  const auditionPct = filteredSegments.length > 0 && auditionPos >= 0
    ? ((auditionPos + 1) / filteredSegments.length) * 100
    : 0;

  // 点击总进度条跳转到对应片段
  const seekAudition = (e: ReactMouseEvent<HTMLDivElement>) => {
    const total = filteredSegments.length;
    if (total === 0) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const frac = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    const pos = Math.min(total - 1, Math.floor(frac * total));
    startAudition(filteredSegments[pos].index);
  };

  const patchSegment = (index: number, patch: Partial<DubSegment>) => {
    setSegments((prev) => prev.map((s) => (s.index === index ? { ...s, ...patch } : s)));
    setDirty((prev) => ({ ...prev, [index]: true }));
  };

  const saveRows = async (indices: number[]) => {
    if (!dubPath || indices.length === 0) return;
    const items = segments
      .filter((s) => indices.includes(s.index))
      .map((s) => ({
        index: s.index,
        read_text: s.read_text,
        read_tone_desc: s.read_tone_desc,
        ref_audio: s.ref_audio,
        speed_ratio: computeRatio(s),
      }));
    await client.post("/api/dub-check/update", { path: dubPath, task_id: taskId || "", items });
    setDirty((prev) => {
      const next = { ...prev };
      indices.forEach((i) => delete next[i]);
      return next;
    });
  };

  const regenerate = async (indices: number[], speedsOverride?: Record<number, number>) => {
    if (!dubPath || indices.length === 0) return;
    // 克隆类模式必须有参考音频，否则 TTS 引擎会直接 400，提前拦截并给出明确提示
    if (mode === "clone" || mode === "controllable_clone") {
      const hasGlobalRef = !!refAudio.trim();
      const anyRowRef = indices.some((i) => !!segments.find((s) => s.index === i)?.ref_audio_exists);
      if (!hasGlobalRef && !anyRowRef) {
        setBusy(false);
        setError("克隆模式需要参考音频：请先在「全局参考音频」填写，或在该行「参考音频」列选择后再重生");
        return;
      }
    }
    setBusy(true);
    setError("");
    try {
      // 连同前端已编辑的朗读文本/指令一起提交：后端写回后用最新文本合成
      const items = indices.map((i) => {
        const seg = segments.find((s) => s.index === i);
        return {
          index: i,
          speed: (speedsOverride || speeds)[i] ?? batchSpeed,
          read_text: seg?.read_text,
          read_tone_desc: seg?.read_tone_desc,
        };
      });
      const res = await client.post("/api/dub-check/regenerate", {
        path: dubPath,
        task_id: taskId || "",
        indices,
        items,
        engine,
        mode,
        voice,
        ref_audio: refAudio,
      });
      const data = res.data || {};
      const nextSegments = (data.segments || segments) as DubSegment[];
      pendingScrollTop.current = tableScrollRef.current?.scrollTop ?? 0;
      setSegments(nextSegments);
      // 重生后按新的变速比率刷新这些行的重生速率默认值
      setSpeeds((prev) => {
        const next = { ...prev };
        nextSegments.forEach((s) => {
          if (indices.includes(s.index)) next[s.index] = computeRatio(s);
        });
        return next;
      });
      setTick(Date.now());
      // 编辑内容已随重生写回，清除这些行的未保存标记
      setDirty((prev) => {
        const next = { ...prev };
        indices.forEach((i) => delete next[i]);
        return next;
      });
      const failed = (data.results || []).filter((r: any) => !r.success);
      if (failed.length) {
        setError(`${failed.length} 条重生失败：${failed.map((f: any) => `#${f.index}`).join("、")}`);
      }
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || "重生失败");
    } finally {
      setBusy(false);
    }
  };

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/60 p-4" onMouseDown={onClose}>
      <div
        className="flex h-[90vh] w-[95vw] max-w-[2250px] flex-col overflow-hidden rounded-2xl border-2 border-violet-400/80 bg-background shadow-2xl ring-4 ring-violet-500/15 dark:border-violet-500/60 dark:ring-violet-400/20"
        onMouseDown={(e) => e.stopPropagation()}
      >
        {/* 顶部：标题 + 统计 + 操作 */}
        <div className="flex items-center justify-between gap-3 border-b border-violet-500/20 bg-gradient-to-r from-violet-500/15 via-fuchsia-500/5 to-teal-500/10 px-4 py-3 dark:from-violet-500/20 dark:via-fuchsia-500/10 dark:to-teal-500/15">
          <div className="flex min-w-0 items-center gap-3">
            <span className="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-violet-500 to-fuchsia-500 text-white shadow-sm">
              <AudioLines className="h-5 w-5" />
            </span>
            <span className="text-[19px] font-semibold text-foreground">配音审听和微调</span>
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="rounded-full border border-border/70 bg-background px-2.5 py-0.5 text-[14px] text-muted-foreground shadow-sm">
                共 {segments.length} 条
              </span>
              {ratioFilter && (
                <span className="rounded-full border border-primary/30 bg-primary/10 px-2.5 py-0.5 text-[14px] text-primary shadow-sm">
                  已筛选 {filteredSegments.length} 条（{filterDesc}）
                </span>
              )}
              <span className="rounded-full border border-border/70 bg-background px-2.5 py-0.5 text-[14px] text-muted-foreground shadow-sm">
                已选 {selectedIndices.length} 条
              </span>
              {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
            </div>
          </div>
          <div className="flex flex-shrink-0 items-center gap-2">
            <button
              type="button"
              onClick={() => setShowTts((v) => !v)}
              className={cn(
                "inline-flex h-9 items-center gap-1.5 rounded-lg border px-3 text-[16px] shadow-sm transition-colors",
                showTts
                  ? "border-primary/40 bg-primary/10 text-primary hover:bg-primary/20"
                  : "border-border/70 bg-background hover:bg-accent"
              )}
            >
              <Settings2 className="h-4 w-4" />
              {showTts ? "收起TTS设置" : "TTS接口设置"}
            </button>
            <button
              type="button"
              onClick={load}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-border/70 bg-background px-3 text-[16px] shadow-sm hover:bg-accent"
            >
              <RefreshCw className="h-4 w-4" />
              重新载入
            </button>
            <button
              type="button"
              onClick={onClose}
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-border/70 bg-background text-muted-foreground shadow-sm hover:bg-accent hover:text-foreground"
              title="关闭"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* 设置区：TTS 接口 + 审听控制 + 速率筛选 */}
        <div className="space-y-3 border-b border-violet-500/20 bg-gradient-to-b from-muted/30 to-muted/10 px-4 py-3">
          {showTts && (
            <section className="rounded-xl border border-violet-500/25 bg-card p-3 shadow-sm dark:border-violet-500/20">
              <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-[15px] text-muted-foreground">TTS 接口</span>
              <select
                value={engine}
                onChange={(e) => { setEngine(e.target.value); setMode(""); setVoice(""); }}
                className="h-9 min-w-[150px] rounded-lg border border-border/70 bg-background px-2.5 text-[16px] shadow-sm outline-none focus:border-primary/60"
              >
                <option value="">未选择（沿用任务配置）</option>
                {interfaces.map((it) => (
                  <option key={it.id} value={it.id}>{it.name || it.id}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[15px] text-muted-foreground">模式</span>
              <select
                value={mode}
                onChange={(e) => setMode(e.target.value)}
                className="h-9 min-w-[110px] rounded-lg border border-border/70 bg-background px-2.5 text-[16px] shadow-sm outline-none focus:border-primary/60"
              >
                <option value="">未选择</option>
                {modes.map((m) => (
                  <option key={m} value={m}>{MODE_LABELS[m] || m}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[15px] text-muted-foreground">音色</span>
              <select
                value={voice}
                onChange={(e) => setVoice(e.target.value)}
                className="h-9 min-w-[150px] rounded-lg border border-border/70 bg-background px-2.5 text-[16px] shadow-sm outline-none focus:border-primary/60"
              >
                <option value="">默认</option>
                {voices.map((v) => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </select>
            </label>
            <div className="flex flex-col gap-1">
              <span className="text-[15px] text-muted-foreground">全局参考音频</span>
              <div className="flex items-center gap-1">
                <input
                  value={refAudio}
                  onChange={(e) => setRefAudio(e.target.value)}
                  placeholder="未设置（克隆模式需指定）"
                  className="h-9 w-[220px] rounded-lg border border-border/70 bg-background px-2.5 text-[16px] shadow-sm outline-none focus:border-primary/60"
                />
                <button
                  type="button"
                  onClick={() => setShowGlobalRefPicker(true)}
                  className="h-9 rounded-lg border border-border/70 bg-background px-2.5 text-[16px] shadow-sm hover:bg-accent"
                >
                  选择
                </button>
                {refAudio && (
                  <audio controls preload="none" src={fileUrl(refAudio, taskId)} className="h-9 w-[160px]" />
                )}
              </div>
            </div>
            <label className="flex flex-col gap-1">
              <span className="text-[15px] text-muted-foreground">批量重生速率</span>
              <input
                type="number"
                step={0.05}
                min={0.5}
                max={3}
                value={batchSpeed}
                onChange={(e) => setBatchSpeed(Number(e.target.value) || 1)}
                className="h-9 w-[90px] rounded-lg border border-border/70 bg-background px-2.5 text-[16px] shadow-sm outline-none focus:border-primary/60"
              />
            </label>
            <button
              type="button"
              disabled={busy || selectedIndices.length === 0}
              onClick={() => regenerate(selectedIndices)}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg bg-violet-600 px-3.5 text-[16px] font-medium text-white shadow-sm transition-colors hover:bg-violet-500 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-violet-500 dark:hover:bg-violet-400"
            >
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              批量重生（{selectedIndices.length}）
            </button>
              </div>
            </section>
          )}

          <div className="grid gap-3 xl:grid-cols-[1.7fr_1fr]">
            {/* 审听控制套件 */}
            <section className="rounded-xl border border-primary/30 bg-gradient-to-br from-primary/[0.06] to-transparent p-3 shadow-sm dark:border-primary/25">
              <div className="mb-2.5 flex items-center gap-1.5 text-[15px] font-semibold text-foreground/80">
                <Music className="h-4 w-4 text-primary" />
                审听控制
                <span className="font-normal text-muted-foreground">连贯试听全部片段</span>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    title="播放 / 继续（空格）"
                    onClick={() => startAudition()}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border/70 bg-background shadow-sm hover:border-primary/40 hover:bg-primary/15 hover:text-primary"
                  >
                    <Play className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    title="暂停（保留位置，空格）"
                    onClick={pauseAudition}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border/70 bg-background shadow-sm hover:bg-accent"
                  >
                    <Pause className="h-4 w-4" />
                  </button>
                  <button
                    type="button"
                    title="停止（回到开头）"
                    onClick={stopAudition}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-border/70 bg-background shadow-sm hover:border-destructive/40 hover:bg-destructive/10 hover:text-destructive"
                  >
                    <Square className="h-4 w-4" />
                  </button>
                </div>
                <div className="flex items-center gap-0.5">
                  {AUDITION_RATES.map((r) => (
                    <button
                      key={r}
                      type="button"
                      onClick={() => changeAuditionRate(r)}
                      className={cn(
                        "rounded-md px-2 py-0.5 text-[15px] transition-colors",
                        auditionRate === r
                          ? "bg-primary font-medium text-primary-foreground shadow-sm"
                          : "border border-border/70 bg-background shadow-sm hover:bg-accent"
                      )}
                    >
                      {r}x
                    </button>
                  ))}
                </div>
                <span className="whitespace-nowrap font-mono">
                  当前 <b>#{auditionIndex ?? "—"}</b>
                </span>
                <span className="whitespace-nowrap text-muted-foreground">
                  {auditionPos >= 0 ? `${auditionPos + 1}/${filteredSegments.length}` : `- / ${filteredSegments.length}`}
                </span>
              </div>
              {/* 总进度条：以总句数为基数，可点击跳转 */}
              <div
                role="slider"
                aria-label="审听总进度"
                aria-valuemin={0}
                aria-valuemax={filteredSegments.length}
                aria-valuenow={auditionPos >= 0 ? auditionPos + 1 : 0}
                title="点击跳转到对应配音片段"
                onClick={seekAudition}
                className="group relative mt-3 h-2.5 w-full cursor-pointer overflow-hidden rounded-full bg-muted ring-1 ring-inset ring-border/60"
              >
                <div
                  className="h-full rounded-full bg-gradient-to-r from-teal-500 to-violet-500 transition-[width] duration-150 dark:from-teal-400 dark:to-violet-400"
                  style={{ width: `${auditionPct}%` }}
                />
              </div>
            </section>

            {/* 速率筛选 */}
            <section className="rounded-xl border border-amber-500/30 bg-gradient-to-br from-amber-500/[0.06] to-transparent p-3 shadow-sm dark:border-amber-500/25">
              <div className="mb-2.5 flex items-center gap-1.5 text-[15px] font-semibold text-foreground/80">
                <Filter className="h-4 w-4 text-amber-500 dark:text-amber-400" />
                速率筛选
                <span className="font-normal text-muted-foreground">按变速比率过滤条目</span>
              </div>
              <div className="flex flex-wrap items-end gap-2">
              <label className="flex flex-col gap-1">
                <span className="text-[15px] text-muted-foreground">速率大于</span>
                <input
                  type="number"
                  step={0.01}
                  value={minRatioInput}
                  onChange={(e) => setMinRatioInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") applyRatioFilter(); }}
                  placeholder="如 1.30"
                  className="h-9 w-[100px] rounded-lg border border-border/70 bg-background px-2.5 text-[16px] shadow-sm outline-none focus:border-primary/60"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-[15px] text-muted-foreground">速率小于</span>
                <input
                  type="number"
                  step={0.01}
                  value={maxRatioInput}
                  onChange={(e) => setMaxRatioInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") applyRatioFilter(); }}
                  placeholder="如 0.90"
                  className="h-9 w-[100px] rounded-lg border border-border/70 bg-background px-2.5 text-[16px] shadow-sm outline-none focus:border-primary/60"
                />
              </label>
              <button
                type="button"
                onClick={applyRatioFilter}
                className="inline-flex h-9 items-center gap-1 rounded-md border border-primary/40 bg-primary/10 px-3 text-[16px] font-medium text-primary hover:bg-primary/20"
              >
                <Filter className="h-4 w-4" />
                一键筛选
              </button>
              {ratioFilter && (
                <button
                  type="button"
                  onClick={clearRatioFilter}
                  className="inline-flex h-9 items-center rounded-md border border-border/60 px-3 text-[16px] hover:bg-accent"
                >
                  清除筛选
                </button>
              )}
              </div>
            </section>
          </div>
        </div>

        {error && (
          <div className="flex items-center gap-2 border-b border-amber-500/30 bg-amber-500/10 px-4 py-2.5 text-[16px] font-medium text-amber-600 dark:text-amber-300">
            <AlertTriangle className="h-3.5 w-3.5" />
            {error}
          </div>
        )}

        {/* 列表 */}
        <div ref={tableScrollRef} className="min-h-0 flex-1 overflow-auto scroll-pt-12 bg-background">
          <table className="w-full min-w-[2050px] table-fixed border-collapse text-[16px]">
            <colgroup>
              <col style={{ width: 40 }} />
              <col style={{ width: 56 }} />
              <col style={{ width: 260 }} />
              <col style={{ width: 260 }} />
              <col style={{ width: 330 }} />
              <col style={{ width: 200 }} />
              <col style={{ width: 236 }} />
              <col style={{ width: 90 }} />
              <col style={{ width: 90 }} />
              <col style={{ width: 84 }} />
              <col style={{ width: 212 }} />
              <col style={{ width: 96 }} />
              <col style={{ width: 96 }} />
            </colgroup>
            <thead className="sticky top-0 z-10 border-b border-violet-500/20 bg-gradient-to-b from-muted/90 to-muted/60 backdrop-blur">
              <tr className="text-left text-[15px] font-semibold tracking-wide text-muted-foreground">
                <th className="px-3 py-2.5">
                  <button
                    type="button"
                    onClick={() => {
                      const allOn = pageSegments.length > 0 && pageSegments.every((s) => selected[s.index]);
                      const next = { ...selected };
                      pageSegments.forEach((s) => { next[s.index] = !allOn; });
                      setSelected(next);
                    }}
                    className="text-muted-foreground"
                    title="全选/取消本页"
                  >
                    {pageSegments.length > 0 && pageSegments.every((s) => selected[s.index])
                      ? <CheckSquare className="h-3.5 w-3.5" />
                      : <Square className="h-3.5 w-3.5" />}
                  </button>
                </th>
                <th className="px-3 py-2.5">ID</th>
                <th className="px-3 py-2.5">原始文本</th>
                <th className="px-3 py-2.5">配音文本</th>
                <th className="px-3 py-2.5">朗读文本</th>
                <th className="px-3 py-2.5">朗读指令</th>
                <th className="px-3 py-2.5">参考音频</th>
                <th className="whitespace-nowrap px-3 py-2.5">原始时长</th>
                <th className="whitespace-nowrap px-3 py-2.5">配音时长</th>
                <th className="whitespace-nowrap px-3 py-2.5">变速比率</th>
                <th className="px-3 py-2.5">配音片段</th>
                <th className="whitespace-nowrap px-3 py-2.5">重生速率</th>
                <th className="whitespace-nowrap px-3 py-2.5">操作</th>
              </tr>
            </thead>
            <tbody>
              {pageSegments.map((seg) => (
                <tr
                  key={seg.index}
                  ref={(el) => { rowRefs.current[seg.index] = el; }}
                  className={cn(
                    "border-t border-border/50 align-top transition-colors hover:bg-primary/5 odd:bg-muted/20",
                    seg.index === auditionIndex && "bg-primary/10 ring-1 ring-inset ring-primary/25"
                  )}
                >
                  <td className="px-3 py-2.5">
                    <input
                      type="checkbox"
                      checked={!!selected[seg.index]}
                      onChange={(e) => setSelected((prev) => ({ ...prev, [seg.index]: e.target.checked }))}
                    />
                  </td>
                  <td className="px-3 py-2.5 font-mono text-muted-foreground">{seg.id}</td>
                  <td className="px-3 py-2.5">
                    <div className="max-h-20 overflow-auto whitespace-pre-wrap text-muted-foreground">{seg.text}</div>
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="max-h-20 overflow-auto whitespace-pre-wrap">{seg.dub_text || "—"}</div>
                  </td>
                  <td className="px-3 py-2.5">
                    <textarea
                      value={seg.read_text}
                      onChange={(e) => patchSegment(seg.index, { read_text: e.target.value })}
                      className="h-20 w-full resize-none rounded-lg border border-border/70 bg-background px-2 py-1.5 text-[16px] shadow-sm outline-none focus:border-primary/60 focus:ring-2 focus:ring-primary/10"
                    />
                  </td>
                  <td className="px-3 py-2.5">
                    <textarea
                      value={seg.read_tone_desc}
                      onChange={(e) => patchSegment(seg.index, { read_tone_desc: e.target.value })}
                      placeholder="语气/指令"
                      className="h-20 w-full resize-none rounded-lg border border-border/70 bg-background px-2 py-1.5 text-[16px] shadow-sm outline-none focus:border-primary/60 focus:ring-2 focus:ring-primary/10"
                    />
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-1">
                      {seg.ref_audio && seg.ref_audio_exists ? (
                        <audio controls preload="none" src={fileUrl(seg.ref_audio, taskId, tick)} className="h-9 w-[150px]" />
                      ) : (
                        <span className="text-[15px] text-muted-foreground/70">无</span>
                      )}
                      <button
                        type="button"
                        onClick={() => setRefPickerIndex(seg.index)}
                        className="shrink-0 rounded-md border border-border/70 bg-background px-1.5 py-0.5 text-[15px] shadow-sm hover:bg-accent"
                      >
                        更换
                      </button>
                    </div>
                    {seg.ref_audio && (
                      <div className="mt-0.5 max-w-[212px] truncate text-[15px] text-muted-foreground" title={seg.ref_audio}>
                        {seg.ref_audio.split(/[\\/]/).pop()}
                      </div>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 font-mono">{fmt(seg.original_duration || seg.duration)}</td>
                  <td className="whitespace-nowrap px-3 py-2.5 font-mono">
                    <span className={cn(seg.real_duration > (seg.duration || 0) && "text-amber-600 dark:text-amber-400")}>
                      {fmt(seg.real_duration)}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2.5 font-mono">{computeRatio(seg).toFixed(2)}</td>
                  <td className="px-3 py-2.5">
                    {seg.audio_file && seg.audio_exists ? (
                      <audio controls preload="none" src={fileUrl(seg.audio_file, taskId, tick)} className="h-9 w-[192px]" />
                    ) : (
                      <span className="flex items-center gap-1 text-[15px] text-amber-600 dark:text-amber-400">
                        <AlertTriangle className="h-3 w-3" />未生成
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    <input
                      type="number"
                      step={0.05}
                      min={0.5}
                      max={3}
                      value={speeds[seg.index] ?? 1}
                      onChange={(e) => setSpeeds((prev) => ({ ...prev, [seg.index]: Number(e.target.value) }))}
                      className="h-9 w-[74px] rounded-lg border border-border/70 bg-background px-2 text-[16px] shadow-sm outline-none focus:border-primary/60"
                    />
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-col gap-1">
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => regenerate([seg.index], { [seg.index]: speeds[seg.index] ?? batchSpeed })}
                        className="inline-flex items-center justify-center gap-1 rounded-md border border-violet-500/40 bg-violet-500/10 px-2 py-1 text-[15px] font-medium text-violet-600 shadow-sm hover:bg-violet-500/20 disabled:opacity-50 dark:text-violet-300"
                      >
                        <RefreshCw className="h-3 w-3" />
                        重生
                      </button>
                      <button
                        type="button"
                        disabled={busy || !dirty[seg.index]}
                        onClick={() => { if (dirty[seg.index]) saveRows([seg.index]); }}
                        className={cn(
                          "inline-flex items-center justify-center gap-1 rounded-md border px-2 py-1 text-[15px] shadow-sm",
                          dirty[seg.index]
                            ? "border-primary/40 bg-primary/10 text-primary hover:bg-primary/20"
                            : "border-border/50 bg-background text-muted-foreground/40"
                        )}
                      >
                        <Save className="h-3 w-3" />
                        保存
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {pageSegments.length === 0 && !loading && (
                <tr>
                  <td colSpan={13} className="px-4 py-10 text-center text-muted-foreground">
                    {ratioFilter ? "没有符合速率筛选条件的配音条目" : "暂无配音条目"}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* 底部分页 */}
        <div className="flex items-center justify-between border-t border-violet-500/20 bg-gradient-to-r from-teal-500/[0.06] to-violet-500/[0.06] px-4 py-2.5 text-[16px]">
          <div className="flex items-center gap-2 text-muted-foreground">
            <Music className="h-4 w-4" />
            <span>
              第 {page} / {totalPages} 页
            </span>
            <select
              value={pageSize}
              onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
              className="h-9 rounded-lg border border-border/70 bg-background px-2 text-[16px] shadow-sm outline-none focus:border-primary/60"
            >
              {PAGE_SIZES.map((s) => (
                <option key={s} value={s}>{s} 条/页</option>
              ))}
            </select>
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="inline-flex h-9 items-center gap-1 rounded-md border border-border/60 bg-background px-3 text-[16px] text-foreground hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ChevronLeft className="h-4 w-4" />
              上一页
            </button>
            <button
              type="button"
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              className="inline-flex h-9 items-center gap-1 rounded-md border border-border/60 bg-background px-3 text-[16px] text-foreground hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40"
            >
              下一页
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
          <div className="text-muted-foreground">共 {filteredSegments.length} / {segments.length} 条</div>
        </div>
      </div>

      {/* 审听播放器（隐藏，由审听控制套件驱动） */}
      <audio
        ref={audioRef}
        preload="none"
        className="hidden"
        onEnded={nextAudition}
        onLoadedMetadata={(e) => {
          e.currentTarget.playbackRate = auditionRate;
        }}
      />

      {/* 行级参考音频选择 */}
      {refPickerIndex !== null && (
        <AudioSelectorDialog
          open
          onClose={() => setRefPickerIndex(null)}
          onSelect={(path) => {
            const idx = refPickerIndex;
            setRefPickerIndex(null);
            if (idx === null) return;
            patchSegment(idx, { ref_audio: path, ref_audio_exists: true });
            const target = segments.find((s) => s.index === idx);
            if (target && dubPath) {
              client.post("/api/dub-check/update", {
                path: dubPath,
                task_id: taskId || "",
                items: [{
                  index: idx,
                  read_text: target.read_text,
                  read_tone_desc: target.read_tone_desc,
                  ref_audio: path,
                  speed_ratio: computeRatio(target),
                }],
              }).then(() => setDirty((prev) => {
                const next = { ...prev };
                delete next[idx];
                return next;
              })).catch(() => undefined);
            }
          }}
        />
      )}

      {/* 全局参考音频选择 */}
      {showGlobalRefPicker && (
        <AudioSelectorDialog
          open
          onClose={() => setShowGlobalRefPicker(false)}
          onSelect={(path) => {
            setRefAudio(path);
            setShowGlobalRefPicker(false);
          }}
        />
      )}
    </div>,
    document.body
  );
}
