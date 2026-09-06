import { useEffect, useLayoutEffect, useMemo, useRef, type MouseEvent as ReactMouseEvent } from "react";
import { AudioLines, Captions, CircleAlert, ListPlus, Loader2, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { useVideoDubStore, activePairAt } from "./store";
import { formatTimecode, parseTimeInput } from "./media";
import { clamp, SubtitlePair } from "./types";
import { useDubbing } from "./useDubbing";

/** 高度随内容自适应的 textarea。 */
function AutoTextarea({
  value,
  onChange,
  placeholder,
  className,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${element.scrollHeight}px`;
  }, [value]);
  return (
    <textarea
      ref={ref}
      rows={1}
      value={value}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
      className={cn(
        "w-full resize-none rounded border border-transparent bg-transparent px-1.5 py-1 text-sm leading-5 outline-none hover:border-border focus:border-primary/60 focus:bg-background",
        className,
      )}
    />
  );
}

/** 起始/结束时间的小输入框：外部值变化时通过 key 重挂载刷新显示。 */
function TimeInput({
  pairId,
  seconds,
  onCommit,
  label,
}: {
  pairId: string;
  seconds: number;
  onCommit: (value: number | null) => void;
  label: string;
}) {
  const commit = (event: React.FocusEvent<HTMLInputElement>) => {
    const parsed = parseTimeInput(event.target.value);
    onCommit(parsed);
  };
  return (
    <input
      key={`${pairId}-${seconds}`}
      defaultValue={formatTimecode(seconds)}
      onBlur={commit}
      onKeyDown={(event) => {
        if (event.key === "Enter") event.currentTarget.blur();
        if (event.key === "Escape") {
          event.currentTarget.value = formatTimecode(seconds);
          event.currentTarget.blur();
        }
      }}
      aria-label={label}
      className="w-[72px] rounded border border-border/70 bg-background px-1 py-0.5 text-center font-mono text-[11px] tabular-nums outline-none focus:border-primary/60"
    />
  );
}

/** 行级配音生成按钮：按状态显示生成 / 进行中 / 重生成 / 失败重试。 */
function DubButton({
  pair,
  modeLabel,
  onGenerate,
}: {
  pair: SubtitlePair;
  modeLabel: string;
  onGenerate: () => void;
}) {
  const status = pair.dubStatus || "idle";
  const hasText = Boolean(pair.text.trim());
  const disabled = !hasText || status === "generating";
  const label =
    status === "generating"
      ? "生成中…"
      : status === "error"
        ? "生成失败，点击重试"
        : status === "done"
          ? `重新生成${pair.dubDuration ? ` · ${pair.dubDuration.toFixed(1)}s` : ""}`
          : `生成配音`;
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onGenerate}
      title={
        status === "error" && pair.dubError
          ? pair.dubError
          : status === "done"
            ? `已生成配音，点击用当前模式「${modeLabel}」重新生成`
            : `点击以「${modeLabel}」模式调用 TTS 合成该句配音`
      }
      className={cn(
        "inline-flex items-center gap-1 rounded border border-dashed px-1.5 py-0.5 text-[11px] transition-colors disabled:cursor-not-allowed disabled:opacity-60",
        status === "error"
          ? "border-destructive/40 text-destructive hover:bg-destructive/10"
          : status === "done"
            ? "border-emerald-500/40 text-emerald-600 hover:bg-emerald-500/10 dark:text-emerald-400"
            : "border-border text-muted-foreground hover:border-primary/50 hover:text-primary",
      )}
    >
      {status === "generating" ? (
        <Loader2 className="h-3 w-3 animate-spin" />
      ) : status === "error" ? (
        <CircleAlert className="h-3 w-3" />
      ) : (
        <AudioLines className="h-3 w-3" />
      )}
      {label}
    </button>
  );
}

export function SubtitlePanel() {
  const pairs = useVideoDubStore((state) => state.pairs);
  const tracks = useVideoDubStore((state) => state.tracks);
  const currentTime = useVideoDubStore((state) => state.currentTime);
  const playing = useVideoDubStore((state) => state.playing);
  const seek = useVideoDubStore((state) => state.seek);
  const selectPair = useVideoDubStore((state) => state.selectPair);
  const selectedPairId = useVideoDubStore((state) => state.selectedPairId);
  const insertPair = useVideoDubStore((state) => state.insertPair);
  const updatePair = useVideoDubStore((state) => state.updatePair);
  const removePair = useVideoDubStore((state) => state.removePair);
  const dubMode = useVideoDubStore((state) => state.dubMode);
  const { generateOne, generateBatch, batch } = useDubbing();

  const modeLabel = dubMode === "clone" ? "克隆" : dubMode === "tts_interface" ? "接口音色" : "音色";

  const showTranslation = tracks.includes("subtitle_translation") || pairs.some((pair) => pair.translation);
  const activePair = useMemo(() => activePairAt(pairs, currentTime), [pairs, currentTime]);

  const rowRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const lastAutoScrollId = useRef<string | null>(null);

  // 播放 / 定位时，让激活行保持可见
  useEffect(() => {
    const target = activePair?.id || selectedPairId;
    if (!target || target === lastAutoScrollId.current) return;
    const shouldScroll = playing || target === selectedPairId;
    if (!shouldScroll) return;
    lastAutoScrollId.current = target;
    rowRefs.current.get(target)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activePair?.id, selectedPairId, playing]);

  const registerRow = (id: string) => (element: HTMLDivElement | null) => {
    if (element) rowRefs.current.set(id, element);
    else rowRefs.current.delete(id);
  };

  const locate = (pair: SubtitlePair) => {
    selectPair(pair.id);
    seek(pair.start + 0.01);
  };

  /** 点击行的空白处定位；点在输入框 / 按钮上时保持原生编辑行为。 */
  const handleRowClick = (pair: SubtitlePair) => (event: ReactMouseEvent<HTMLDivElement>) => {
    const target = event.target as HTMLElement;
    if (target.closest("textarea, input, button")) return;
    locate(pair);
  };

  const nudgeStart = (pair: SubtitlePair, delta: number) => {
    updatePair(pair.id, { start: clamp(pair.start + delta, 0, pair.end - 0.05) });
  };

  const addRow = () => {
    insertPair(Math.round(currentTime * 100) / 100);
  };

  return (
    <section className="flex h-full flex-col overflow-hidden rounded-xl border border-border/60 bg-card">
      <header className="flex flex-none flex-col gap-2 border-b border-border/60 px-3 py-2">
        <div className="flex items-center gap-2">
          <Captions className="h-4 w-4 text-primary" />
          <span className="text-sm font-semibold">字幕列表</span>
          <span className="text-xs text-muted-foreground">{pairs.length} 条</span>
          <Button size="sm" variant="ghost" className="ml-auto h-7 px-2 text-xs" onClick={addRow} title="在当前时间指针处新增一行">
            <Plus className="h-3.5 w-3.5" />
            添加行
          </Button>
        </div>
        <div className="flex items-center gap-2">
          <span className="flex-none text-[11px] text-muted-foreground">模式</span>
          <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[11px] font-medium text-primary">{modeLabel}</span>
          <Button
            size="sm"
            variant="ai-soft"
            className="ml-auto h-7 flex-none px-2 text-xs"
            disabled={batch.running || !pairs.some((pair) => pair.text.trim())}
            onClick={() => void generateBatch(pairs)}
            title={batch.running ? "正在生成…" : `以「${modeLabel}」模式为所有未在生成中的字幕行合成配音（并发 2 路）`}
          >
            {batch.running ? (
              <>
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                {batch.done}/{batch.total}
              </>
            ) : (
              <>
                <AudioLines className="mr-1 h-3 w-3" />
                全部生成配音
              </>
            )}
          </Button>
        </div>
      </header>

      {!pairs.length ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center text-muted-foreground">
          <ListPlus className="h-8 w-8 opacity-50" />
          <p className="text-sm">暂无字幕</p>
          <p className="text-xs">点击顶部「添加字幕」导入 SRT，或用上方「添加行」手动新建。</p>
        </div>
      ) : (
        <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto p-2">
          {pairs.map((pair, index) => {
            const isActive = activePair?.id === pair.id;
            const isSelected = selectedPairId === pair.id;
            return (
              <div
                key={pair.id}
                ref={registerRow(pair.id)}
                onClick={handleRowClick(pair)}
                className={cn(
                  "cursor-pointer rounded-lg border p-2 transition-colors",
                  isActive
                    ? "border-primary/60 bg-primary/10 shadow-[inset_2px_0_0_hsl(var(--primary))]"
                    : isSelected
                      ? "border-primary/40 bg-muted/40"
                      : "border-border/60 bg-background hover:border-border hover:bg-muted/20",
                )}
              >
                <div className="flex items-center gap-1.5">
                  <span
                    className={cn(
                      "flex h-5 w-7 flex-none cursor-pointer items-center justify-center rounded text-[11px] font-medium tabular-nums",
                      isActive ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
                    )}
                    title="点击定位到该句起始时间"
                  >
                    {index + 1}
                  </span>
                  <TimeInput
                    pairId={pair.id}
                    seconds={pair.start}
                    label="起始时间"
                    onCommit={(value) => {
                      if (value != null) updatePair(pair.id, { start: clamp(value, 0, pair.end - 0.05) });
                    }}
                  />
                  <span className="text-[11px] text-muted-foreground">→</span>
                  <TimeInput
                    pairId={pair.id}
                    seconds={pair.end}
                    label="结束时间"
                    onCommit={(value) => {
                      if (value != null) updatePair(pair.id, { end: Math.max(value, pair.start + 0.05) });
                    }}
                  />
                  <span className="ml-auto flex items-center gap-0.5">
                    {(
                      [
                        [-0.5, "−0.5s"],
                        [-0.1, "−0.1s"],
                        [0.1, "+0.1s"],
                        [0.5, "+0.5s"],
                      ] as Array<[number, string]>
                    ).map(([delta, label]) => (
                      <button
                        key={label}
                        type="button"
                        title={`起始时间 ${label}`}
                        onClick={() => nudgeStart(pair, delta)}
                        className="rounded border border-border/60 bg-background px-1 py-0.5 font-mono text-[10px] text-muted-foreground hover:border-primary/50 hover:text-primary"
                      >
                        {label}
                      </button>
                    ))}
                    <button
                      type="button"
                      title="删除此行"
                      onClick={() => removePair(pair.id)}
                      className="ml-0.5 rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </span>
                </div>
                <div className="mt-1">
                  <AutoTextarea
                    value={pair.text}
                    onChange={(value) => updatePair(pair.id, { text: value })}
                    placeholder="字幕内容"
                  />
                  {showTranslation ? (
                    <AutoTextarea
                      value={pair.translation}
                      onChange={(value) => updatePair(pair.id, { translation: value })}
                      placeholder="翻译字幕"
                      className="text-[13px] text-muted-foreground"
                    />
                  ) : null}
                  <div className="mt-0.5">
                    <DubButton
                      pair={pair}
                      modeLabel={modeLabel}
                      onGenerate={() => void generateOne(pair)}
                    />
                    {(pair.characterId !== undefined || pair.readCharacterId !== undefined || pair.dialect || pair.toneDesc) && (
                      <div className="mt-1 flex flex-wrap gap-1 text-[10px] leading-4 text-muted-foreground">
                        {pair.characterId !== undefined && pair.characterId !== "" && (
                          <span className="rounded bg-muted px-1 py-0.5" title="配音角色 ID">
                            角色 {String(pair.characterId)}
                          </span>
                        )}
                        {pair.readCharacterId !== undefined && pair.readCharacterId !== "" && String(pair.readCharacterId) !== String(pair.characterId) && (
                          <span className="rounded bg-muted px-1 py-0.5" title="朗读角色 ID">
                            朗读 {String(pair.readCharacterId)}
                          </span>
                        )}
                        {pair.dialect ? (
                          <span className="rounded bg-muted px-1 py-0.5" title="方言">
                            {pair.dialect}
                          </span>
                        ) : null}
                        {pair.toneDesc ? (
                          <span className="max-w-[150px] truncate rounded bg-muted px-1 py-0.5" title={pair.toneDesc}>
                            {pair.toneDesc}
                          </span>
                        ) : null}
                      </div>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
