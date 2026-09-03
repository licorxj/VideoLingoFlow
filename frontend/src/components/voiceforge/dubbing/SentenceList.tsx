import { useCallback, useRef } from "react";
import type { VoiceForgeSentence } from "@/api/voiceforge";
import { SentenceRow } from "./SentenceRow";
import { useDubbingContext } from "./DubbingContext";

function formatEta(sec: number | null | undefined): string {
  if (sec == null || !Number.isFinite(sec)) return "—";
  if (sec < 60) return `${Math.ceil(sec)} 秒`;
  const m = Math.floor(sec / 60);
  const s = Math.ceil(sec % 60);
  return `${m} 分 ${s} 秒`;
}

export interface SentenceListProps {
  sentences: VoiceForgeSentence[];
  characters: Array<{ id: string; name: string }>;
  emotionTags: Array<{ id: string; name: string; color?: string }>;
  selectedIds: Set<string>;
  isPlaying: boolean;
  playingId: string | null;
  onToggleSelect: (id: string) => void;
  onUpdateSentence: (id: string, patch: Record<string, unknown>) => void;
  onPlay: (id: string) => void;
  onRegenerate: (id: string) => void;
  onAddAfter: (index: number) => void;
  onReorder: (orderedIds: string[]) => void;
  queueUpdate: (id: string, patch: Record<string, unknown>) => void;
}

export function SentenceList({
  sentences,
  characters,
  emotionTags,
  selectedIds,
  isPlaying,
  playingId,
  onToggleSelect,
  onUpdateSentence,
  onPlay,
  onRegenerate,
  onAddAfter,
  onReorder,
  queueUpdate,
}: SentenceListProps) {
  const dragState = useRef({ dragIndex: -1, overIndex: -1 });
  const { state } = useDubbingContext();
  // 项目级进度汇总优先来自 WebSocket 实时推送，未连接时回退到本地统计
  const progress = state.projectProgress;

  const handleDragStart = useCallback(
    (index: number) => (e: React.DragEvent) => {
      dragState.current.dragIndex = index;
      e.dataTransfer.effectAllowed = "move";
      e.dataTransfer.setData("text/plain", String(index));
    },
    [],
  );

  const handleDragOver = useCallback(
    (_index: number) => (e: React.DragEvent) => {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
    },
    [],
  );

  const handleDrop = useCallback(
    (index: number) => (e: React.DragEvent) => {
      e.preventDefault();
      const fromIndex = dragState.current.dragIndex;
      if (fromIndex < 0 || fromIndex === index) return;

      const ids = sentences.map((s) => s.id);
      const [moved] = ids.splice(fromIndex, 1);
      ids.splice(index, 0, moved);
      dragState.current.dragIndex = -1;
      onReorder(ids);
    },
    [sentences, onReorder],
  );

  // 空状态
  if (!sentences.length) {
    return (
      <div className="flex h-64 items-center justify-center border border-border/60 bg-card text-sm text-muted-foreground">
        请选择左侧章节以加载配音文本
      </div>
    );
  }

  // 进度统计
  const doneCount = sentences.filter((s) => s.status === "done").length;
  const totalCount = sentences.length;
  const percentage = totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0;

  return (
    <div className="flex flex-col border border-border/60 bg-card">
      {/* 可滚动列表区域 */}
      <div className="max-h-[calc(100vh-330px)] overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="sticky top-0 z-10 bg-muted/90 text-xs text-muted-foreground">
            <tr>
              <th className="w-8 px-1.5 py-1.5" />
              <th className="w-8 px-1.5 py-1.5" />
              <th className="w-12 px-1.5 py-1.5">#</th>
              <th className="min-w-64 px-1.5 py-1.5 text-left">文本</th>
              <th className="px-1.5 py-1.5">语速</th>
              <th className="w-[120px] px-1.5 py-1.5">角色</th>
              <th className="w-[120px] px-1.5 py-1.5">情绪</th>
              <th className="w-[120px] px-1.5 py-1.5">语气</th>
              <th className="w-9 px-1 py-1.5">状态</th>
              <th className="w-8 px-1.5 py-1.5" />
              <th className="px-1.5 py-1.5">停顿</th>
              <th className="w-8 px-1.5 py-1.5" />
            </tr>
          </thead>
          <tbody>
            {sentences.map((sentence, index) => (
              <SentenceRow
                key={sentence.id}
                sentence={sentence}
                index={index}
                characters={characters}
                emotionTags={emotionTags}
                isSelected={selectedIds.has(sentence.id)}
                isPlaying={isPlaying && playingId === sentence.id}
                onToggleSelect={() => onToggleSelect(sentence.id)}
                onUpdate={(patch) => onUpdateSentence(sentence.id, patch)}
                onPlay={() => onPlay(sentence.id)}
                onRegenerate={() => onRegenerate(sentence.id)}
                onAddAfter={() => onAddAfter(index)}
                queueUpdate={queueUpdate}
                draggable
                onDragStart={handleDragStart(index)}
                onDragOver={handleDragOver(index)}
                onDrop={handleDrop(index)}
              />
            ))}
          </tbody>
        </table>
      </div>

      {/* 底部进度条 */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border/50 px-4 py-2">
        <span className="whitespace-nowrap text-xs text-muted-foreground">
          已完成 {progress ? progress.done : doneCount}/{progress ? progress.total : totalCount}
          {progress && progress.error > 0 ? ` · 失败 ${progress.error}` : ""}
        </span>
        <div className="h-2 min-w-[120px] flex-1 overflow-hidden rounded-full bg-muted/50">
          <div
            className="h-full rounded-full bg-green-500 transition-all duration-300"
            style={{ width: `${progress ? progress.progress_pct : percentage}%` }}
          />
        </div>
        <span className="whitespace-nowrap font-mono text-xs text-muted-foreground">
          {progress ? progress.progress_pct : percentage}%
        </span>
        <span className="whitespace-nowrap text-xs text-muted-foreground">
          在途 {progress ? progress.in_flight : 0}/{progress ? progress.concurrency : "—"}
        </span>
        <span className="whitespace-nowrap text-xs text-muted-foreground">
          预计剩余 {formatEta(progress?.eta_seconds)}
        </span>
      </div>
    </div>
  );
}
