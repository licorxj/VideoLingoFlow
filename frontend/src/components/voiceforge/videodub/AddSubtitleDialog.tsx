import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowLeftRight, Captions, FileText, FileUp, Languages, Loader2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useVideoDubStore } from "./store";
import { formatTimecode, parseSrt, readTextSmart, splitBilingualCue } from "./media";
import { SubtitlePair, uid } from "./types";

type ImportMode = "bilingual" | "dual" | "single";
type LoadTarget = "main" | "second";

const MODE_OPTIONS: Array<{ value: ImportMode; label: string; icon: any; detail: string }> = [
  {
    value: "bilingual",
    label: "双语字幕",
    icon: Languages,
    detail: "一个文件每条字幕含两行（原文 + 译文），自动拆分到字幕轨与翻译轨",
  },
  {
    value: "dual",
    label: "两个单语字幕",
    icon: Captions,
    detail: "分别导入两份单语 SRT，按行对齐合并为双语",
  },
  {
    value: "single",
    label: "单个单语字幕",
    icon: FileText,
    detail: "只导入一份单语字幕，仅填充字幕轨",
  },
];

export function AddSubtitleDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const addPairs = useVideoDubStore((state) => state.addPairs);
  const hasPairs = useVideoDubStore((state) => state.pairs.length > 0);

  const [mode, setMode] = useState<ImportMode>("bilingual");
  const [textMain, setTextMain] = useState("");
  const [textSecond, setTextSecond] = useState("");
  const [mainFirst, setMainFirst] = useState(true);
  const [replace, setReplace] = useState(true);
  const [loadTarget, setLoadTarget] = useState<LoadTarget>("main");
  const [error, setError] = useState("");
  const [loadingFile, setLoadingFile] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setTextMain("");
      setTextSecond("");
      setMainFirst(true);
      setReplace(true);
      setError("");
    }
  }, [open]);

  const mainCues = useMemo(() => parseSrt(textMain), [textMain]);
  const secondCues = useMemo(() => parseSrt(textSecond), [textSecond]);
  const dualMismatch = mode === "dual" && mainCues.length > 0 && secondCues.length > 0 && mainCues.length !== secondCues.length;

  const pickFile = (target: LoadTarget) => {
    setLoadTarget(target);
    fileRef.current?.click();
  };

  const loadFile = async (file: File) => {
    setLoadingFile(true);
    try {
      const text = await readTextSmart(file);
      if (loadTarget === "main") setTextMain(text);
      else setTextSecond(text);
      setError("");
    } finally {
      setLoadingFile(false);
    }
  };

  const buildPairs = (): SubtitlePair[] => {
    if (mode === "bilingual") {
      return mainCues.map((cue) => {
        const split = splitBilingualCue(cue, !mainFirst);
        return { id: uid(), ...split };
      });
    }
    if (mode === "single") {
      return mainCues.map((cue) => ({ id: uid(), start: cue.start, end: cue.end, text: cue.text, translation: "" }));
    }
    const total = Math.max(mainCues.length, secondCues.length);
    const pairs: SubtitlePair[] = [];
    for (let index = 0; index < total; index += 1) {
      const main = mainCues[index];
      const second = secondCues[index];
      const start = main?.start ?? second?.start ?? 0;
      const end = main?.end ?? second?.end ?? start;
      if (!main && !second) continue;
      pairs.push({ id: uid(), start, end, text: main?.text || "", translation: second?.text || "" });
    }
    return pairs;
  };

  const confirm = () => {
    const pairs = buildPairs();
    if (!pairs.length) {
      setError("未能解析出字幕，请检查内容是否为有效的 SRT 格式。");
      return;
    }
    addPairs(pairs, replace);
    onOpenChange(false);
  };

  const slot = (target: LoadTarget, title: string, text: string, setText: (value: string) => void, cues: number) => (
    <div className="flex min-h-0 flex-1 flex-col gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-medium text-foreground/80">{title}</span>
        <Button type="button" size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={() => pickFile(target)} disabled={loadingFile}>
          {loadingFile ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : <FileUp className="mr-1 h-3 w-3" />}
          载入 SRT 文件
        </Button>
      </div>
      <textarea
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          setError("");
        }}
        placeholder={"粘贴 SRT 内容，例如：\n1\n00:00:01,000 --> 00:00:03,500\n字幕文本"}
        className="min-h-32 flex-1 resize-none rounded-lg border border-border bg-background p-2.5 font-mono text-xs leading-5 outline-none focus:ring-2 focus:ring-primary/30"
      />
      <p className="text-[11px] text-muted-foreground">
        {text.trim() ? `已识别 ${cues} 条字幕` : "支持直接粘贴或从文件载入（自动识别 UTF-8 / GBK 编码）"}
      </p>
    </div>
  );

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] max-w-2xl flex-col">
        <DialogHeader>
          <DialogTitle>添加字幕</DialogTitle>
          <DialogDescription>导入后自动解析到「字幕」「翻译字幕」两条轨道。</DialogDescription>
        </DialogHeader>

        <div className="grid gap-2 sm:grid-cols-3">
          {MODE_OPTIONS.map((option) => {
            const Icon = option.icon;
            const active = mode === option.value;
            return (
              <button
                key={option.value}
                type="button"
                onClick={() => setMode(option.value)}
                className={`rounded-lg border p-2.5 text-left transition-colors ${
                  active ? "border-primary/60 bg-primary/10" : "border-border bg-background hover:border-primary/40"
                }`}
              >
                <span className={`flex items-center gap-1.5 text-sm font-medium ${active ? "text-primary" : ""}`}>
                  <Icon className="h-4 w-4" />
                  {option.label}
                </span>
                <span className="mt-1 block text-[11px] leading-4 text-muted-foreground">{option.detail}</span>
              </button>
            );
          })}
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-3 py-1">
          {mode === "dual" ? (
            <div className="grid min-h-0 flex-1 gap-3 sm:grid-cols-2">
              {slot("main", "字幕 A（原文轨）", textMain, setTextMain, mainCues.length)}
              {slot("second", "字幕 B（翻译轨）", textSecond, setTextSecond, secondCues.length)}
            </div>
          ) : (
            slot("main", mode === "bilingual" ? "双语字幕内容" : "单语字幕内容", textMain, setTextMain, mainCues.length)
          )}

          {dualMismatch && (
            <p className="flex items-center gap-1.5 rounded-lg border border-warning/40 bg-warning/10 px-2.5 py-1.5 text-xs text-warning">
              <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
              两份字幕行数不一致（{mainCues.length} 条 / {secondCues.length} 条），将按序号对齐，缺失的一侧留空。
            </p>
          )}

          {mode === "bilingual" && (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-muted-foreground">行顺序：</span>
              <div className="flex overflow-hidden rounded-md border border-border">
                <button
                  type="button"
                  onClick={() => setMainFirst(true)}
                  className={`px-2.5 py-1 ${mainFirst ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-muted"}`}
                >
                  第 1 行为原文
                </button>
                <button
                  type="button"
                  onClick={() => setMainFirst(false)}
                  className={`px-2.5 py-1 ${!mainFirst ? "bg-primary/15 text-primary" : "text-muted-foreground hover:bg-muted"}`}
                >
                  第 1 行为译文
                </button>
              </div>
              <ArrowLeftRight className="h-3.5 w-3.5 text-muted-foreground" />
            </div>
          )}

          {hasPairs && (
            <label className="flex w-fit items-center gap-2 text-xs text-muted-foreground">
              <input type="checkbox" checked={replace} onChange={(event) => setReplace(event.target.checked)} />
              替换现有字幕（取消勾选则追加到列表末尾）
            </label>
          )}

          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={confirm} disabled={!textMain.trim() || (mode === "dual" && !textSecond.trim())}>
            <Upload className="mr-1.5 h-4 w-4" />
            解析并导入
          </Button>
        </DialogFooter>

        <input
          ref={fileRef}
          type="file"
          accept=".srt,.vtt,.txt"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            if (file) void loadFile(file);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}

/** 供外部展示已导入字幕的概要（如工具栏提示）。 */
export function summarizePairs(pairs: SubtitlePair[]) {
  if (!pairs.length) return "尚未导入字幕";
  const last = pairs[pairs.length - 1];
  return `${pairs.length} 条字幕 · 结束于 ${formatTimecode(last.end)}`;
}
