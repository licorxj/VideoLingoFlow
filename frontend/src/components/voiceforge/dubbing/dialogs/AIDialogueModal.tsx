import { useEffect, useState } from "react";
import { Bot, Loader2, Mic, BookOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { voiceForgeApi } from "@/api/voiceforge";

type ModeTab = "dialogue" | "narration";

interface AIDialogueModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  text: string;
  characterNames: string[];
  emotionTags: Array<{ id: string; name: string }>;
  onApply: (
    dialogues: Array<{
      speaker: string;
      text: string;
      emotion: string;
      tone_description: string;
    }>,
  ) => void;
  busy: boolean;
}

const NARRATION_STYLES = [
  "标准播音腔",
  "古典说书风",
  "纪录片旁白",
  "悬疑惊悚",
  "温情治愈",
  "武侠江湖",
  "都市言情",
  "历史厚重",
  "青春校园",
  "科幻未来",
  "自定义",
];

interface DialogueResult {
  speaker: string;
  text: string;
  emotion: string;
  tone_description: string;
  selected: boolean;
}

export function AIDialogueModal({
  open,
  onOpenChange,
  projectId,
  text: sourceText,
  characterNames,
  emotionTags,
  onApply,
  busy,
}: AIDialogueModalProps) {
  const [mode, setMode] = useState<ModeTab>("dialogue");
  const [narrationStyle, setNarrationStyle] = useState("标准播音腔");
  const [customStyle, setCustomStyle] = useState("");
  const [inputText, setInputText] = useState(sourceText);
  const [results, setResults] = useState<DialogueResult[]>([]);
  const [extracting, setExtracting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (open) {
      setInputText(sourceText);
      setResults([]);
      setError("");
    }
  }, [open, sourceText]);

  const handleExtract = async () => {
    if (!inputText.trim()) return;
    setExtracting(true);
    setError("");
    try {
      const res = await voiceForgeApi.aiDialoguePreview(projectId, {
        text: inputText,
        character_names: characterNames,
        narration_mode: mode === "narration",
        narration_style:
          mode === "narration" ? customStyle || narrationStyle : "标准播音腔",
      });
      const sentences: Array<{
        speaker?: string;
        text?: string;
        emotion?: string;
        tone_description?: string;
      }> = res.data?.sentences ?? [];
      const parsed: DialogueResult[] = sentences
        .filter((s) => (s.text ?? "").trim())
        .map((s) => ({
          speaker: s.speaker || "旁白",
          text: (s.text ?? "").trim(),
          emotion: s.emotion || "neutral",
          tone_description: s.tone_description || "",
          selected: true,
        }));
      if (parsed.length === 0) {
        setError("AI 未提取到可用对话");
      }
      setResults(parsed);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "AI 对话提取失败");
    } finally {
      setExtracting(false);
    }
  };

  const toggleSelect = (index: number) =>
    setResults((prev) =>
      prev.map((r, i) => (i === index ? { ...r, selected: !r.selected } : r)),
    );

  const toggleAll = () => {
    const allSelected = results.every((r) => r.selected);
    setResults((prev) => prev.map((r) => ({ ...r, selected: !allSelected })));
  };

  const handleApply = () => {
    const selected = results.filter((r) => r.selected);
    if (selected.length) {
      onApply(
        selected.map(({ speaker, text, emotion, tone_description }) => ({
          speaker,
          text,
          emotion,
          tone_description,
        })),
      );
    }
  };

  const handleOpenChange = (value: boolean) => {
    if (!value) setResults([]);
    onOpenChange(value);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Bot className="h-5 w-5 text-purple-400" />
            AI 提取对话
          </DialogTitle>
          <DialogDescription>
            从文本中提取对话和旁白，分配角色与情绪标签。
          </DialogDescription>
        </DialogHeader>

        {/* Mode tabs */}
        <div className="flex gap-2 border-b border-border/60 pb-2">
          <button
            type="button"
            onClick={() => setMode("dialogue")}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition ${
              mode === "dialogue"
                ? "bg-purple-500/10 text-purple-400"
                : "text-muted-foreground hover:bg-accent"
            }`}
          >
            <Mic className="h-4 w-4" />
            仅对话
          </button>
          <button
            type="button"
            onClick={() => setMode("narration")}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition ${
              mode === "narration"
                ? "bg-purple-500/10 text-purple-400"
                : "text-muted-foreground hover:bg-accent"
            }`}
          >
            <BookOpen className="h-4 w-4" />
            旁白模式
          </button>
        </div>

        {/* Narration style */}
        {mode === "narration" && (
          <div className="space-y-2">
            <label className="text-xs font-medium text-muted-foreground">
              旁白风格
            </label>
            <div className="flex flex-wrap gap-1.5">
              {NARRATION_STYLES.map((style) => (
                <button
                  key={style}
                  type="button"
                  onClick={() => setNarrationStyle(style)}
                  className={`rounded-full border px-2.5 py-1 text-xs transition ${
                    narrationStyle === style
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border/60 text-muted-foreground hover:bg-accent"
                  }`}
                >
                  {style}
                </button>
              ))}
            </div>
            {narrationStyle === "自定义" && (
              <input
                value={customStyle}
                onChange={(e) => setCustomStyle(e.target.value)}
                placeholder="输入自定义旁白风格描述"
                className="voice-input"
              />
            )}
          </div>
        )}

        {/* Emotion tags display */}
        {emotionTags.length > 0 && (
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">
              可用情绪标签
            </label>
            <div className="flex flex-wrap gap-1.5">
              {emotionTags.map((tag) => (
                <span
                  key={tag.id}
                  className="rounded-full border border-border/60 bg-muted/30 px-2 py-0.5 text-xs text-muted-foreground"
                >
                  {tag.name}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Source text input */}
        <div>
          <label className="mb-1 block text-xs font-medium text-muted-foreground">
            源文本
          </label>
          <textarea
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
            placeholder="粘贴需要提取对话的文本…"
            className="voice-input min-h-28 resize-y"
          />
        </div>

        {error && <div className="text-xs text-destructive">{error}</div>}

        {/* Extract button */}
        <Button
          onClick={handleExtract}
          disabled={extracting || busy || !inputText.trim()}
          className="w-full gap-2 border-purple-500/30 bg-purple-500/20 text-purple-400 hover:bg-purple-500/30"
          variant="outline"
        >
          {extracting || busy ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Bot className="h-4 w-4" />
          )}
          {extracting || busy ? "提取中…" : "提取"}
        </Button>

        {/* Results table */}
        {results.length > 0 && (
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-medium">
                提取结果{" "}
                <span className="text-muted-foreground">
                  ({results.filter((r) => r.selected).length}/{results.length})
                </span>
              </h4>
              <Button
                variant="ghost"
                size="sm"
                onClick={toggleAll}
                className="h-7 text-xs text-muted-foreground"
              >
                {results.every((r) => r.selected) ? "取消全选" : "全选"}
              </Button>
            </div>

            <div className="max-h-60 overflow-y-auto rounded-lg border border-border/60">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-background/95 backdrop-blur">
                  <tr className="border-b border-border/60 text-xs text-muted-foreground">
                    <th className="w-10 p-2"></th>
                    <th className="w-10 p-2 text-center">#</th>
                    <th className="p-2 text-left">说话人</th>
                    <th className="p-2 text-left">文本</th>
                    <th className="p-2 text-left">情绪</th>
                    <th className="p-2 text-left">语气描述</th>
                  </tr>
                </thead>
                <tbody>
                  {results.map((r, idx) => (
                    <tr
                      key={idx}
                      className={`border-b border-border/30 transition ${
                        r.selected ? "bg-primary/5" : "opacity-60"
                      }`}
                    >
                      <td className="p-2 text-center">
                        <input
                          type="checkbox"
                          checked={r.selected}
                          onChange={() => toggleSelect(idx)}
                          className="h-4 w-4 rounded border-input"
                        />
                      </td>
                      <td className="p-2 text-center text-muted-foreground">
                        {idx + 1}
                      </td>
                      <td className="p-2">
                        <span
                          className={`text-sm font-medium ${
                            r.speaker === "旁白"
                              ? "text-blue-400"
                              : "text-purple-400"
                          }`}
                        >
                          {r.speaker}
                        </span>
                      </td>
                      <td className="max-w-[200px] truncate p-2 text-sm">
                        {r.text}
                      </td>
                      <td className="p-2">
                        <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs">
                          {r.emotion}
                        </span>
                      </td>
                      <td className="max-w-[120px] truncate p-2 text-xs text-muted-foreground">
                        {r.tone_description}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => handleOpenChange(false)}>
            取消
          </Button>
          {results.length > 0 && (
            <Button
              onClick={handleApply}
              disabled={!results.some((r) => r.selected)}
            >
              <Bot className="mr-1.5 h-4 w-4" />
              应用选中 ({results.filter((r) => r.selected).length})
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
