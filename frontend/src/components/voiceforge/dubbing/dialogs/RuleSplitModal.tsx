import { useMemo, useState } from "react";
import { Scissors } from "lucide-react";
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

type RuleMode = "newline" | "chinese_punct" | "quotes" | "custom";

interface RuleSplitModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  textContent: string;
  onApplySplit: (sentences: string[]) => void;
}

const MODES: Array<{ key: RuleMode; label: string }> = [
  { key: "newline", label: "按换行" },
  { key: "chinese_punct", label: "按中文标点" },
  { key: "quotes", label: "提取引号内容" },
  { key: "custom", label: "自定义符号" },
];

function escapeRegExp(input: string): string {
  return input.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function computeSentences(text: string, mode: RuleMode, customSymbols: string): string[] {
  const trimFilter = (parts: string[]) =>
    parts.map((p) => p.trim()).filter((p) => p.length > 0);

  switch (mode) {
    case "newline":
      return trimFilter(text.split(/\r?\n+/));
    case "chinese_punct":
      return trimFilter(text.match(/[^。！？；…]*[。！？；…]|[^。！？；…]+/g) || []);
    case "quotes":
      return trimFilter(
        text.match(/"[^"]*"|“[^”]*”|「[^」]*」|『[^』]*』|‘[^’]*’|（[^）]*）|\([^)]*\)/g) || [],
      );
    case "custom": {
      const symbols = customSymbols.trim();
      if (!symbols) return [];
      const re = new RegExp(`[${escapeRegExp(symbols)}]+`);
      return trimFilter(text.split(re));
    }
    default:
      return [];
  }
}

export function RuleSplitModal({
  open,
  onOpenChange,
  textContent,
  onApplySplit,
}: RuleSplitModalProps) {
  const [mode, setMode] = useState<RuleMode>("chinese_punct");
  const [customSymbols, setCustomSymbols] = useState("。！？；");

  const preview = useMemo(
    () => computeSentences(textContent, mode, customSymbols),
    [textContent, mode, customSymbols],
  );

  const handleApply = () => {
    if (preview.length === 0) return;
    onApplySplit(preview);
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>按照规则断句</DialogTitle>
          <DialogDescription>
            选择拆分规则，将当前章节文本拆分为句子。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Rule selector */}
          <div className="flex flex-wrap gap-2">
            {MODES.map((m) => (
              <button
                key={m.key}
                type="button"
                onClick={() => setMode(m.key)}
                className={`rounded-md border px-3 py-1.5 text-sm transition-colors ${
                  mode === m.key
                    ? "border-primary bg-primary/10 text-primary"
                    : "border-border/60 text-muted-foreground hover:bg-accent/60"
                }`}
              >
                {m.label}
              </button>
            ))}
          </div>

          {/* Custom symbols input */}
          {mode === "custom" && (
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                自定义拆分符号（如：。！？）
              </label>
              <Input
                value={customSymbols}
                onChange={(e) => setCustomSymbols(e.target.value)}
                className="h-8 text-sm"
              />
            </div>
          )}

          {/* Preview */}
          <div>
            <div className="mb-1 flex items-center justify-between">
              <label className="flex items-center gap-1 text-xs font-medium text-muted-foreground">
                <Scissors className="h-3 w-3" />
                拆分预览
              </label>
              <span className="text-xs text-muted-foreground">{preview.length} 句</span>
            </div>
            <div className="max-h-64 overflow-y-auto rounded-md border border-border/60 bg-muted/20 p-2">
              {preview.length === 0 ? (
                <div className="py-4 text-center text-xs text-muted-foreground">
                  暂无匹配结果
                </div>
              ) : (
                <ol className="list-decimal space-y-1 pl-5">
                  {preview.map((sentence, idx) => (
                    <li key={idx} className="text-xs leading-relaxed">
                      {sentence}
                    </li>
                  ))}
                </ol>
              )}
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleApply} disabled={preview.length === 0}>
            应用拆分
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
