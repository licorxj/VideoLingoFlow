import { useState, useEffect } from "react";
import { Eraser, Search, Replace, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface EditOriginalModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  chapterName: string;
  initialText: string;
  onSave: (text: string) => Promise<void>;
}

export function EditOriginalModal({
  open,
  onOpenChange,
  chapterName,
  initialText,
  onSave,
}: EditOriginalModalProps) {
  const [text, setText] = useState("");
  const [showFindReplace, setShowFindReplace] = useState(false);
  const [findText, setFindText] = useState("");
  const [replaceText, setReplaceText] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setText(initialText);
      setShowFindReplace(false);
      setFindText("");
      setReplaceText("");
    }
  }, [open, initialText]);

  const clearSpaces = () =>
    setText((prev) => prev.replace(/[\t ]+/g, " ").replace(/^\s+|\s+$/gm, ""));

  const clearEmptyLines = () =>
    setText((prev) => prev.replace(/\n{3,}/g, "\n\n"));

  const doFindReplace = () => {
    if (!findText) return;
    setText((prev) => prev.split(findText).join(replaceText));
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(text);
      onOpenChange(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[90vw] max-h-[90vh]">
        <DialogHeader>
          <DialogTitle className="truncate">
            编辑原文 — {chapterName}
          </DialogTitle>
          <DialogDescription>直接编辑该章节的原始文本内容。</DialogDescription>
        </DialogHeader>

        {/* Toolbar */}
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" onClick={clearSpaces} className="gap-1.5">
            <Eraser className="h-3.5 w-3.5" />
            清除空格
          </Button>
          <Button variant="outline" size="sm" onClick={clearEmptyLines} className="gap-1.5">
            <Eraser className="h-3.5 w-3.5" />
            清除空行
          </Button>
          <Button
            variant={showFindReplace ? "default" : "outline"}
            size="sm"
            onClick={() => setShowFindReplace((v) => !v)}
            className="gap-1.5"
          >
            <Search className="h-3.5 w-3.5" />
            查找替换
          </Button>
        </div>

        {/* Find / Replace row */}
        {showFindReplace && (
          <div className="flex items-center gap-2 rounded-lg border border-border/60 bg-muted/20 p-2">
            <input
              value={findText}
              onChange={(e) => setFindText(e.target.value)}
              placeholder="查找"
              className="voice-input flex-1"
            />
            <Replace className="h-4 w-4 shrink-0 text-muted-foreground" />
            <input
              value={replaceText}
              onChange={(e) => setReplaceText(e.target.value)}
              placeholder="替换为"
              className="voice-input flex-1"
            />
            <Button size="sm" onClick={doFindReplace} disabled={!findText}>
              全部替换
            </Button>
          </div>
        )}

        {/* Textarea */}
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="voice-input min-h-[60vh] resize-y font-mono text-sm leading-relaxed"
        />

        {/* Character count + actions */}
        <div className="flex items-center justify-between">
          <span className="text-xs text-muted-foreground">
            共 {text.length} 字符
          </span>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            取消
          </Button>
          <Button onClick={handleSave} disabled={saving}>
            {saving ? "保存中…" : <><Save className="mr-1.5 h-4 w-4" />保存</>}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
