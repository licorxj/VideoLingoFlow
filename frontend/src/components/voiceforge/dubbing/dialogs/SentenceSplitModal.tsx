import { useState, useEffect } from "react";
import { Scissors } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface SentenceSplitModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onApply: (symbols: string[]) => void;
  busy: boolean;
}

const PRESETS: Array<{ key: string; label: string; symbols: string[] }> = [
  { key: "zh", label: "中文标点", symbols: ["。", "！", "？", "；", "…"] },
  { key: "mix", label: "中英混合", symbols: ["。", "！", "？", "；", "…", ".", "!", "?", ";"] },
  { key: "custom", label: "自定义", symbols: [] },
];

export function SentenceSplitModal({
  open,
  onOpenChange,
  onApply,
  busy,
}: SentenceSplitModalProps) {
  const [selected, setSelected] = useState("zh");
  const [customText, setCustomText] = useState("");

  useEffect(() => {
    if (open) {
      setSelected("zh");
      setCustomText("");
    }
  }, [open]);

  const handleApply = () => {
    if (selected === "custom") {
      const symbols = [...new Set(customText.split("").filter(Boolean))];
      if (symbols.length) onApply(symbols);
    } else {
      const preset = PRESETS.find((p) => p.key === selected);
      if (preset) onApply(preset.symbols);
    }
  };

  const currentSymbols =
    selected === "custom"
      ? [...new Set(customText.split("").filter(Boolean))]
      : PRESETS.find((p) => p.key === selected)?.symbols ?? [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Scissors className="h-5 w-5 text-muted-foreground" />
            句子拆分符号
          </DialogTitle>
          <DialogDescription>
            选择用于拆分句子的标点符号集。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {PRESETS.map((preset) => (
            <label
              key={preset.key}
              className={`flex items-start gap-3 rounded-lg border p-3 transition ${
                selected === preset.key
                  ? "border-primary/60 bg-primary/5"
                  : "border-border/60 hover:bg-accent"
              }`}
            >
              <input
                type="radio"
                name="split-preset"
                value={preset.key}
                checked={selected === preset.key}
                onChange={() => setSelected(preset.key)}
                className="mt-0.5 h-4 w-4 accent-primary"
              />
              <div className="flex-1">
                <span className="text-sm font-medium">{preset.label}</span>
                {preset.key !== "custom" && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {preset.symbols.join("  ")}
                  </p>
                )}
                {preset.key === "custom" && selected === "custom" && (
                  <textarea
                    value={customText}
                    onChange={(e) => setCustomText(e.target.value)}
                    placeholder="逐个输入标点符号，如：。，！？"
                    className="voice-input mt-2 min-h-16 resize-none text-xs"
                  />
                )}
              </div>
            </label>
          ))}
        </div>

        {currentSymbols.length > 0 && (
          <p className="text-xs text-muted-foreground">
            将使用 {currentSymbols.length} 个符号拆分：
            <span className="ml-1 font-mono">{currentSymbols.join(" ")}</span>
          </p>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            取消
          </Button>
          <Button onClick={handleApply} disabled={busy || currentSymbols.length === 0}>
            {busy ? "处理中…" : "应用拆分"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
