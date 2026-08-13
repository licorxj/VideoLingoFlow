import { useState, useEffect } from "react";
import { Eraser, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface TextCleanModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onApply: (data: {
    chars_to_remove: string;
    wildcards: Array<{ open: string; close: string }>;
    find_text: string;
    replace_text: string;
    delete_empty: boolean;
  }) => void;
  busy: boolean;
}

const DEFAULT_WILDCARDS = [{ open: "「", close: "」" }];

export function TextCleanModal({
  open,
  onOpenChange,
  onApply,
  busy,
}: TextCleanModalProps) {
  const [charsToRemove, setCharsToRemove] = useState("");
  const [wildcards, setWildcards] = useState<Array<{ open: string; close: string }>>(DEFAULT_WILDCARDS);
  const [findText, setFindText] = useState("");
  const [replaceText, setReplaceText] = useState("");
  const [deleteEmpty, setDeleteEmpty] = useState(false);

  useEffect(() => {
    if (open) {
      setCharsToRemove("");
      setWildcards(DEFAULT_WILDCARDS);
      setFindText("");
      setReplaceText("");
      setDeleteEmpty(false);
    }
  }, [open]);

  const addWildcard = () =>
    setWildcards((prev) => [...prev, { open: "", close: "" }]);

  const removeWildcard = (index: number) =>
    setWildcards((prev) => prev.filter((_, i) => i !== index));

  const updateWildcard = (
    index: number,
    field: "open" | "close",
    value: string,
  ) =>
    setWildcards((prev) =>
      prev.map((w, i) => (i === index ? { ...w, [field]: value } : w)),
    );

  const handleApply = () => {
    onApply({
      chars_to_remove: charsToRemove,
      wildcards: wildcards.filter((w) => w.open || w.close),
      find_text: findText,
      replace_text: replaceText,
      delete_empty: deleteEmpty,
    });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Eraser className="h-5 w-5 text-muted-foreground" />
            文本清洗
          </DialogTitle>
          <DialogDescription>
            选择需要执行的清洗操作，可同时生效。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-5">
          {/* 逐字删除 */}
          <section className="space-y-2">
            <h4 className="text-sm font-medium">逐字删除</h4>
            <input
              value={charsToRemove}
              onChange={(e) => setCharsToRemove(e.target.value)}
              placeholder="输入要删除的字符，如：、（）"
              className="voice-input"
            />
          </section>

          {/* 通配符删除 */}
          <section className="space-y-2">
            <div className="flex items-center justify-between">
              <h4 className="text-sm font-medium">通配符删除</h4>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={addWildcard}
                className="h-7 gap-1 px-2 text-xs"
              >
                <Plus className="h-3 w-3" /> 添加
              </Button>
            </div>
            <div className="space-y-2">
              {wildcards.map((w, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <input
                    value={w.open}
                    onChange={(e) => updateWildcard(idx, "open", e.target.value)}
                    placeholder="开符"
                    className="voice-input w-20"
                  />
                  <span className="text-muted-foreground">→</span>
                  <input
                    value={w.close}
                    onChange={(e) => updateWildcard(idx, "close", e.target.value)}
                    placeholder="闭符"
                    className="voice-input w-20"
                  />
                  {wildcards.length > 1 && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-destructive"
                      onClick={() => removeWildcard(idx)}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  )}
                </div>
              ))}
            </div>
          </section>

          {/* 查找替换 */}
          <section className="space-y-2">
            <h4 className="text-sm font-medium">查找替换</h4>
            <div className="flex items-center gap-2">
              <input
                value={findText}
                onChange={(e) => setFindText(e.target.value)}
                placeholder="查找内容"
                className="voice-input flex-1"
              />
              <span className="text-muted-foreground">→</span>
              <input
                value={replaceText}
                onChange={(e) => setReplaceText(e.target.value)}
                placeholder="替换为"
                className="voice-input flex-1"
              />
            </div>
          </section>

          {/* 删除空行 */}
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={deleteEmpty}
              onChange={(e) => setDeleteEmpty(e.target.checked)}
              className="h-4 w-4 rounded border-input"
            />
            <span className="text-muted-foreground">删除空行</span>
          </label>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            取消
          </Button>
          <Button onClick={handleApply} disabled={busy}>
            {busy ? "处理中…" : "应用清洗"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
