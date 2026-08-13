import { useEffect, useState } from "react";
import { SplitSquareVertical, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

/* ── Types ─────────────────────────────────────────────────────────── */

interface SplitPoint {
  lineIndex: number;
  lineText: string;
}

type RuleType = "empty-line" | "keyword";

const KEYWORD_TEMPLATES = [
  { label: "第*章", value: "第{num}章" },
  { label: "第*回", value: "第{num}回" },
  { label: "第（*）章", value: "第（{num}）章" },
  { label: "第（*）回", value: "第（{num}）回" },
];

const DIGIT_PATTERNS: Record<string, string> = {
  digits: "[\\d]+",
  chinese: "[一二三四五六七八九十百千万]+",
};

/* ── Helpers ───────────────────────────────────────────────────────── */

function findSplitPoints(
  text: string,
  rule: RuleType,
  emptyLineCount: number,
  keywordTemplate: string,
  numType: "digits" | "chinese",
): SplitPoint[] {
  const lines = text.split("\n");
  const result: SplitPoint[] = [];

  if (rule === "empty-line") {
    let emptyStart = -1;
    for (let i = 0; i < lines.length; i++) {
      if (lines[i].trim() === "") {
        if (emptyStart === -1) emptyStart = i;
      } else {
        if (emptyStart !== -1 && i - emptyStart >= emptyLineCount) {
          result.push({ lineIndex: i, lineText: lines[i].trim().slice(0, 80) });
        }
        emptyStart = -1;
      }
    }
  } else {
    const numPattern = DIGIT_PATTERNS[numType] || DIGIT_PATTERNS.digits;
    const escaped = keywordTemplate
      .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
      .replace(/\\{num\\}/, numPattern);
    const regex = new RegExp(escaped);
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i].trim();
      if (line && regex.test(line)) {
        result.push({ lineIndex: i, lineText: line.slice(0, 80) });
      }
    }
    // Ensure the very first line is a split point if there are matches after it
    if (result.length > 0 && result[0].lineIndex > 0) {
      result.unshift({
        lineIndex: 0,
        lineText: lines[0]?.trim().slice(0, 80) || "（开头）",
      });
    }
  }

  return result;
}

/* ── Component ─────────────────────────────────────────────────────── */

interface RuleChapterSplitModalProps {
  open: boolean;
  textContent: string;
  onClose: () => void;
  onApply: (
    chapters: Array<{
      chapterName: string;
      textContent: string;
      charCount: number;
    }>,
  ) => void;
}

export function RuleChapterSplitModal({
  open,
  textContent,
  onClose,
  onApply,
}: RuleChapterSplitModalProps) {
  const [rule, setRule] = useState<RuleType>("empty-line");
  const [emptyLineCount, setEmptyLineCount] = useState(2);
  const [keywordTemplate, setKeywordTemplate] = useState("第{num}章");
  const [numType, setNumType] = useState<"digits" | "chinese">("digits");
  const [customKeyword, setCustomKeyword] = useState("");
  const [useCustomKeyword, setUseCustomKeyword] = useState(false);
  const [splitPoints, setSplitPoints] = useState<SplitPoint[]>([]);

  useEffect(() => {
    if (open) {
      setSplitPoints([]);
      setRule("empty-line");
      setEmptyLineCount(2);
      setKeywordTemplate("第{num}章");
      setNumType("digits");
      setCustomKeyword("");
      setUseCustomKeyword(false);
    }
  }, [open]);

  const handleScan = () => {
    const template = useCustomKeyword ? customKeyword : keywordTemplate;
    if (rule === "keyword" && !template) {
      alert("请输入或选择关键词模板");
      return;
    }
    const points = findSplitPoints(
      textContent,
      rule,
      emptyLineCount,
      template,
      numType,
    );
    if (points.length === 0) {
      alert("未匹配到任何分割点，请调整规则");
    }
    setSplitPoints(points);
  };

  const handleConfirm = () => {
    const lines = textContent.split("\n");
    const sorted = [...splitPoints].sort((a, b) => a.lineIndex - b.lineIndex);
    const chapters: Array<{
      chapterName: string;
      textContent: string;
      charCount: number;
    }> = [];

    for (let i = 0; i < sorted.length; i++) {
      const start = sorted[i].lineIndex;
      const end =
        i < sorted.length - 1 ? sorted[i + 1].lineIndex : lines.length;
      const content = lines.slice(start, end).join("\n").trim();
      chapters.push({
        chapterName: sorted[i].lineText || `第${i + 1}章`,
        textContent: content,
        charCount: content.length,
      });
    }

    if (chapters.length === 0) {
      const content = textContent.trim();
      chapters.push({
        chapterName: "第一章",
        textContent: content,
        charCount: content.length,
      });
    }

    onApply(chapters);
    onClose();
  };

  const template = useCustomKeyword ? customKeyword : keywordTemplate;

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-[650px]">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <SplitSquareVertical className="h-5 w-5 text-green-500" />
            规则拆分章
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {/* Rule selector */}
          <div className="flex gap-2">
            <Button
              size="sm"
              variant={rule === "empty-line" ? "default" : "outline"}
              onClick={() => setRule("empty-line")}
            >
              空行分章
            </Button>
            <Button
              size="sm"
              variant={rule === "keyword" ? "default" : "outline"}
              onClick={() => setRule("keyword")}
            >
              关键词分章
            </Button>
          </div>

          {/* Empty-line options */}
          {rule === "empty-line" && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <span>连续空行数 ≥</span>
              <input
                type="number"
                min={1}
                max={20}
                value={emptyLineCount}
                onChange={(e) =>
                  setEmptyLineCount(Math.max(1, Number(e.target.value) || 2))
                }
                className="h-8 w-16 rounded border border-border bg-background px-2 text-sm"
              />
              <span className="text-xs text-muted-foreground/60">
                （遇到 N 行及以上连续空行即分割）
              </span>
            </div>
          )}

          {/* Keyword options */}
          {rule === "keyword" && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <span className="whitespace-nowrap text-sm text-muted-foreground">
                  关键词模板:
                </span>
                <select
                  value={useCustomKeyword ? "__custom__" : keywordTemplate}
                  onChange={(e) => {
                    if (e.target.value === "__custom__") {
                      setUseCustomKeyword(true);
                    } else {
                      setUseCustomKeyword(false);
                      setKeywordTemplate(e.target.value);
                    }
                  }}
                  className="h-8 rounded border border-border bg-background px-2 text-sm"
                >
                  {KEYWORD_TEMPLATES.map((k) => (
                    <option key={k.value} value={k.value}>
                      {k.label}
                    </option>
                  ))}
                  <option value="__custom__">自定义</option>
                </select>
                {useCustomKeyword && (
                  <Input
                    value={customKeyword}
                    onChange={(e) => setCustomKeyword(e.target.value)}
                    placeholder="如 第{num}章"
                    className="h-8 w-48"
                  />
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="whitespace-nowrap text-sm text-muted-foreground">
                  序号类型:
                </span>
                <Button
                  size="sm"
                  variant={numType === "digits" ? "default" : "outline"}
                  onClick={() => setNumType("digits")}
                >
                  数字 (1,2,3…)
                </Button>
                <Button
                  size="sm"
                  variant={numType === "chinese" ? "default" : "outline"}
                  onClick={() => setNumType("chinese")}
                >
                  汉字 (一,二,三…)
                </Button>
              </div>
              <p className="text-xs text-muted-foreground/60">
                实际正则:{" "}
                {template
                  ? template.replace(
                      "{num}",
                      `[${numType === "digits" ? "\\d" : "一二三四五六七八九十百千万"}]+`,
                    )
                  : "（未选择）"}
              </p>
            </div>
          )}

          {/* Scan button */}
          <Button variant="secondary" onClick={handleScan}>
            扫描匹配
          </Button>

          {/* Split points list */}
          {splitPoints.length > 0 && (
            <div className="max-h-64 space-y-1 overflow-y-auto rounded-lg border border-border/60 bg-muted/20 p-2">
              <div className="mb-1 flex items-center justify-between">
                <span className="text-xs text-muted-foreground">
                  匹配结果 ({splitPoints.length} 个分割点)
                </span>
                <button
                  type="button"
                  onClick={() => setSplitPoints([])}
                  className="text-xs text-destructive hover:underline"
                >
                  清除全部
                </button>
              </div>
              {splitPoints.map((pt, idx) => (
                <div
                  key={idx}
                  className="flex items-center gap-2 rounded border-b border-border/30 py-1 text-sm last:border-b-0"
                >
                  <span className="w-10 text-center font-mono text-xs text-muted-foreground/60">
                    L{pt.lineIndex + 1}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{pt.lineText}</span>
                  <button
                    type="button"
                    onClick={() =>
                      setSplitPoints((prev) => prev.filter((_, i) => i !== idx))
                    }
                    className="p-1 text-destructive/70 hover:text-destructive"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ))}
            </div>
          )}

          <p className="text-xs text-muted-foreground/60">
            文本 {textContent.length} 字 · {textContent.split("\n").length} 行
          </p>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            取消
          </Button>
          <Button
            onClick={handleConfirm}
            disabled={splitPoints.length === 0}
          >
            确认拆分 ({splitPoints.length} 章)
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
