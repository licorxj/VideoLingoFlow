import React, { useCallback, useRef } from "react";
import {
  GripVertical,
  Check,
  X,
  Play,
  RefreshCw,
  Plus,
  Loader2,
} from "lucide-react";
import type { VoiceForgeSentence } from "@/api/voiceforge";

const BUILT_IN_EMOTIONS = [
  "neutral",
  "happy",
  "sad",
  "angry",
  "excited",
  "fear",
  "tender",
  "serious",
  "humorous",
];

const EMOTION_LABELS: Record<string, string> = {
  neutral: "自然",
  happy: "开心",
  sad: "悲伤",
  angry: "愤怒",
  excited: "兴奋",
  fear: "恐惧",
  tender: "温柔",
  serious: "严肃",
  humorous: "幽默",
};

export interface SentenceRowProps {
  sentence: VoiceForgeSentence;
  index: number;
  characters: Array<{ id: string; name: string }>;
  emotionTags: Array<{ id: string; name: string; color?: string }>;
  isSelected: boolean;
  isPlaying: boolean;
  onToggleSelect: () => void;
  onUpdate: (patch: Record<string, unknown>) => void;
  onPlay: () => void;
  onRegenerate: () => void;
  onAddAfter: () => void;
  queueUpdate: (id: string, patch: Record<string, unknown>) => void;
  draggable?: boolean;
  onDragStart?: (e: React.DragEvent) => void;
  onDragOver?: (e: React.DragEvent) => void;
  onDrop?: (e: React.DragEvent) => void;
}

function statusIcon(status: string) {
  switch (status) {
    case "done":
      return <Check className="h-4 w-4 text-green-500" />;
    case "error":
      return <X className="h-4 w-4 text-red-500" />;
    case "generating":
      return <Loader2 className="h-4 w-4 animate-spin text-yellow-500" />;
    default:
      return <Play className="h-4 w-4 text-muted-foreground" />;
  }
}

function SentenceRowInner({
  sentence,
  index,
  characters,
  emotionTags,
  isSelected,
  isPlaying,
  onToggleSelect,
  onUpdate,
  onPlay,
  onRegenerate,
  onAddAfter,
  queueUpdate,
  draggable,
  onDragStart,
  onDragOver,
  onDrop,
}: SentenceRowProps) {
  const textTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const toneTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const handleTextChange = useCallback(
    (value: string) => {
      if (textTimerRef.current) clearTimeout(textTimerRef.current);
      textTimerRef.current = setTimeout(() => {
        queueUpdate(sentence.id, { edited_text: value });
      }, 450);
    },
    [sentence.id, queueUpdate],
  );

  const handleToneChange = useCallback(
    (value: string) => {
      if (toneTimerRef.current) clearTimeout(toneTimerRef.current);
      toneTimerRef.current = setTimeout(() => {
        queueUpdate(sentence.id, { tone_description: value });
      }, 450);
    },
    [sentence.id, queueUpdate],
  );

  return (
    <tr
      className={`border-t border-border/50 align-top transition-colors hover:bg-muted/30 ${
        isSelected ? "bg-purple-500/8" : ""
      }`}
      onDragOver={onDragOver}
      onDrop={onDrop}
    >
      {/* 1. 拖拽手柄 */}
      <td className="w-8 px-1.5 py-1.5">
        <span
          draggable={draggable}
          onDragStart={onDragStart}
          className="flex h-6 cursor-grab items-center justify-center text-muted-foreground hover:text-foreground"
          title="拖拽排序"
        >
          <GripVertical className="h-4 w-4" />
        </span>
      </td>

      {/* 2. 勾选框 */}
      <td className="w-8 px-1.5 py-1.5">
        <button
          type="button"
          onClick={onToggleSelect}
          className={`flex h-5 w-5 items-center justify-center rounded border transition-colors ${
            isSelected
              ? "border-primary bg-primary text-primary-foreground"
              : "border-border bg-background text-transparent hover:border-primary/50"
          }`}
        >
          <Check className="h-3 w-3" />
        </button>
      </td>

      {/* 3. 序号 */}
      <td className="w-12 px-1.5 py-1.5 text-center">
        <span className="font-mono text-xs text-muted-foreground min-w-[1.5rem] inline-block">
          {index + 1}
        </span>
      </td>

      {/* 4. 文本 */}
      <td className="min-w-64 px-1.5 py-1.5 text-left">
        <textarea
          defaultValue={sentence.edited_text || sentence.text}
          onChange={(e) => handleTextChange(e.target.value)}
          rows={1}
          className="voice-input block w-full resize-none !px-1.5 !py-0.5 text-sm leading-snug"
          style={{ minHeight: "1.5rem", maxHeight: "7rem" }}
        />
      </td>

      {/* 5. 语速 */}
      <td className="px-1.5 py-1.5">
        <div className="flex flex-col items-center gap-0.5">
          <span className="text-[10px] text-muted-foreground">语速</span>
          <input
            type="range"
            min="0.5"
            max="2.0"
            step="0.1"
            defaultValue={sentence.speed}
            onChange={(e) =>
              queueUpdate(sentence.id, { speed: Number(e.target.value) })
            }
            className="h-1 w-[70px] cursor-pointer accent-primary"
          />
          <span className="font-mono text-[10px] text-muted-foreground">
            {sentence.speed.toFixed(1)}
          </span>
        </div>
      </td>

      {/* 6. 角色 */}
      <td className="w-[120px] px-1.5 py-1.5">
        <select
          value={sentence.character_id || ""}
          onChange={(e) =>
            onUpdate({ character_id: e.target.value || null })
          }
          className="voice-input !h-7 !w-full !px-1.5 !py-0 text-sm"
        >
          <option value="">无角色</option>
          {characters.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
      </td>

      {/* 7. 情绪 */}
      <td className="w-[120px] px-1.5 py-1.5">
        <select
          value={sentence.emotion}
          onChange={(e) => onUpdate({ emotion: e.target.value })}
          className="voice-input !h-7 !w-full !px-1.5 !py-0 text-sm"
        >
          {BUILT_IN_EMOTIONS.map((em) => (
            <option key={em} value={em}>
              {EMOTION_LABELS[em] || em}
            </option>
          ))}
          {emotionTags.length > 0 && (
            <optgroup label="自定义标签">
              {emotionTags.map((tag) => (
                <option key={tag.id} value={tag.name}>
                  {tag.name}
                </option>
              ))}
            </optgroup>
          )}
        </select>
      </td>

      {/* 8. 语气 */}
      <td className="w-[120px] px-1.5 py-1.5">
        <input
          type="text"
          defaultValue={sentence.tone_description || ""}
          onChange={(e) => handleToneChange(e.target.value)}
          placeholder="语气"
          className="voice-input !h-7 !w-full !px-1.5 !py-0 text-sm"
        />
      </td>

      {/* 9. 状态图标 - 已完成时显示为可点击的播放按钮 */}
      <td className="w-9 px-1 py-1.5 text-center">
        {isPlaying ? (
          <button
            type="button"
            onClick={onPlay}
            className="inline-flex h-6 w-6 items-center justify-center rounded-full text-primary hover:bg-primary/10"
            title="停止播放"
          >
            <Play className="h-4 w-4 animate-pulse" />
          </button>
        ) : sentence.status === "done" ? (
          <button
            type="button"
            onClick={onPlay}
            className="inline-flex h-6 w-6 items-center justify-center rounded-full text-green-500 hover:bg-green-500/10"
            title="播放已生成的配音"
          >
            <Play className="h-4 w-4" />
          </button>
        ) : (
          <span
            title={sentence.error_message || sentence.status}
            className="inline-flex h-6 w-6 items-center justify-center"
          >
            {statusIcon(sentence.status)}
          </span>
        )}
      </td>

      {/* 10. 重新生成 */}
      <td className="w-8 px-1.5 py-1.5 text-center">
        <button
          type="button"
          onClick={onRegenerate}
          className="inline-flex items-center justify-center text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100"
          title="重新生成"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </td>

      {/* 11. 句后停顿 */}
      <td className="px-1.5 py-1.5">
        <div className="flex flex-col items-center gap-0.5">
          <input
            type="range"
            min="0"
            max="3"
            step="0.1"
            defaultValue={sentence.pause_after ?? 0}
            onChange={(e) =>
              queueUpdate(sentence.id, {
                pause_after: Number(e.target.value),
              })
            }
            className="h-1 w-[50px] cursor-pointer accent-primary"
          />
          <span className="font-mono text-[10px] text-muted-foreground">
            {(sentence.pause_after ?? 0).toFixed(1)}s
          </span>
        </div>
      </td>

      {/* 12. 添加按钮 */}
      <td className="w-8 px-1.5 py-1.5 text-center">
        <button
          type="button"
          onClick={onAddAfter}
          className="inline-flex items-center justify-center text-muted-foreground hover:text-foreground"
          title="在此句后添加"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </td>
    </tr>
  );
}

export const SentenceRow = React.memo(
  SentenceRowInner,
  (prev, next) =>
    prev.sentence.id === next.sentence.id &&
    prev.sentence.text === next.sentence.text &&
    prev.sentence.edited_text === next.sentence.edited_text &&
    prev.sentence.speed === next.sentence.speed &&
    prev.sentence.emotion === next.sentence.emotion &&
    prev.sentence.tone_description === next.sentence.tone_description &&
    prev.sentence.character_id === next.sentence.character_id &&
    prev.sentence.pause_after === next.sentence.pause_after &&
    prev.sentence.status === next.sentence.status &&
    prev.sentence.error_message === next.sentence.error_message &&
    prev.sentence.version === next.sentence.version &&
    prev.isSelected === next.isSelected &&
    prev.isPlaying === next.isPlaying &&
    prev.index === next.index,
);

SentenceRow.displayName = "SentenceRow";
