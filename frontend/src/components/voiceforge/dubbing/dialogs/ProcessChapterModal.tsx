import { Scissors, Bot } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface ProcessChapterModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  chapterName: string;
  onRuleSplit: () => void;
  onAIDialogue: () => void;
}

export function ProcessChapterModal({
  open,
  onOpenChange,
  chapterName,
  onRuleSplit,
  onAIDialogue,
}: ProcessChapterModalProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>处理章节</DialogTitle>
          <DialogDescription>
            章节「{chapterName}」尚未拆分为句子，请选择处理方式。
          </DialogDescription>
        </DialogHeader>

        <div className="grid gap-3 py-2">
          <button
            type="button"
            onClick={onRuleSplit}
            className="flex items-center gap-3 rounded-lg border border-border/60 bg-accent/30 p-3 text-left transition-colors hover:bg-accent/60"
          >
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <Scissors className="h-4 w-4" />
            </div>
            <div>
              <div className="text-sm font-medium">按照规则断句</div>
              <div className="text-xs text-muted-foreground">
                按换行、中文标点或引号规则把文本拆分为句子
              </div>
            </div>
          </button>

          <button
            type="button"
            onClick={onAIDialogue}
            className="flex items-center gap-3 rounded-lg border border-border/60 bg-accent/30 p-3 text-left transition-colors hover:bg-accent/60"
          >
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
              <Bot className="h-4 w-4" />
            </div>
            <div>
              <div className="text-sm font-medium">AI 提取对话</div>
              <div className="text-xs text-muted-foreground">
                用大模型识别说话人并提取对话句子
              </div>
            </div>
          </button>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
