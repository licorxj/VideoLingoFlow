import { useState } from "react";
import { Bot, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { voiceForgeApi } from "@/api/voiceforge";

interface AIChapter {
  title: string;
  text: string;
}

interface AIChapterSplitModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string;
  textContent: string;
  onApply: (chapters: AIChapter[]) => void;
}

export function AIChapterSplitModal({
  open,
  onOpenChange,
  projectId,
  textContent,
  onApply,
}: AIChapterSplitModalProps) {
  const [maxLength, setMaxLength] = useState(2000);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [chapters, setChapters] = useState<AIChapter[]>([]);

  const handleSplit = async () => {
    if (!textContent.trim()) {
      setError("当前项目没有可拆分的文本，请先导入文本。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const res = await voiceForgeApi.aiChapterPreview(projectId, {
        text: textContent,
        max_length: maxLength,
      });
      const list: AIChapter[] = res.data?.chapters ?? [];
      if (list.length === 0) {
        setError("AI 未返回章节结果，请稍后重试或调整文本。");
      }
      setChapters(list);
    } catch (err: unknown) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(typeof detail === "string" ? detail : "AI 分章节失败");
    } finally {
      setBusy(false);
    }
  };

  const updateTitle = (index: number, title: string) => {
    setChapters((prev) => prev.map((c, i) => (i === index ? { ...c, title } : c)));
  };

  const handleApply = () => {
    if (chapters.length === 0) return;
    onApply(chapters);
    onOpenChange(false);
    setChapters([]);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>AI 分章节</DialogTitle>
          <DialogDescription>
            使用大模型将文本自动拆分为章节，可编辑章节名后应用。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="flex items-end gap-2">
            <div className="flex-1">
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                每章最大字数
              </label>
              <Input
                type="number"
                min={20}
                max={5000}
                value={maxLength}
                onChange={(e) => setMaxLength(Number(e.target.value) || 2000)}
                className="h-8 text-sm"
              />
            </div>
            <Button onClick={handleSplit} disabled={busy}>
              {busy ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" /> : <Bot className="mr-1 h-3.5 w-3.5" />}
              {busy ? "拆分中…" : "开始拆分"}
            </Button>
          </div>

          {error && <div className="text-xs text-destructive">{error}</div>}

          {chapters.length > 0 && (
            <div className="max-h-72 space-y-2 overflow-y-auto">
              {chapters.map((chapter, idx) => (
                <div
                  key={idx}
                  className="rounded-md border border-border/60 bg-muted/20 p-2.5"
                >
                  <Input
                    value={chapter.title}
                    onChange={(e) => updateTitle(idx, e.target.value)}
                    className="mb-1 h-7 text-sm font-medium"
                  />
                  <div className="line-clamp-2 text-xs text-muted-foreground">
                    {chapter.text}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleApply} disabled={chapters.length === 0 || busy}>
            应用（{chapters.length} 章）
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
