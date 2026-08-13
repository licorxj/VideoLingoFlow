import { useState, useRef, useEffect } from "react";
import { FileText, Upload, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

type TabKey = "paste" | "upload";

interface ImportTextModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImportText: (text: string, chapterTitle: string) => void;
  onImportFile: (file: File, type: "txt" | "subtitle") => void;
  busy: boolean;
}

function detectFileType(file: File): "txt" | "subtitle" {
  const ext = file.name.split(".").pop()?.toLowerCase();
  if (ext === "srt" || ext === "ass" || ext === "vtt") return "subtitle";
  return "txt";
}

export function ImportTextModal({
  open,
  onOpenChange,
  onImportText,
  onImportFile,
  busy,
}: ImportTextModalProps) {
  const [tab, setTab] = useState<TabKey>("paste");
  const [pasteText, setPasteText] = useState("");
  const [chapterTitle, setChapterTitle] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setTab("paste");
      setPasteText("");
      setChapterTitle("");
      setFile(null);
      setDragOver(false);
    }
  }, [open]);

  const handlePasteImport = () => {
    if (pasteText.trim()) onImportText(pasteText.trim(), chapterTitle.trim());
  };

  const handleFileImport = () => {
    if (!file) return;
    onImportFile(file, detectFileType(file));
  };

  const handleFileDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) setFile(dropped);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) setFile(selected);
  };

  const tabs: Array<{ key: TabKey; label: string; icon: typeof FileText }> = [
    { key: "paste", label: "粘贴文本", icon: FileText },
    { key: "upload", label: "上传文件", icon: Upload },
  ];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>导入文本</DialogTitle>
          <DialogDescription>
            粘贴文本内容或上传文件来导入内容。
          </DialogDescription>
        </DialogHeader>

        {/* Tab 切换 */}
        <div className="flex gap-2 border-b border-border/60 pb-2">
          {tabs.map((t) => {
            const Icon = t.icon;
            return (
              <button
                key={t.key}
                type="button"
                onClick={() => setTab(t.key)}
                className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition ${
                  tab === t.key
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-accent"
                }`}
              >
                <Icon className="h-4 w-4" />
                {t.label}
              </button>
            );
          })}
        </div>

        {tab === "paste" && (
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                章节标题
              </label>
              <input
                value={chapterTitle}
                onChange={(e) => setChapterTitle(e.target.value)}
                placeholder="例如：第一章 · 重逢（可留空）"
                className="voice-input"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                文本内容
              </label>
              <textarea
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
                placeholder="将小说、剧本等文本粘贴到这里…"
                className="voice-input min-h-40 resize-y"
              />
            </div>
          </div>
        )}

        {tab === "upload" && (
          <div
            className={`flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition ${
              dragOver
                ? "border-primary bg-primary/5"
                : "border-border/60 hover:border-primary/40"
            }`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleFileDrop}
          >
            {file ? (
              <div className="flex flex-col items-center gap-2">
                <FileText className="h-8 w-8 text-primary" />
                <p className="text-sm font-medium">{file.name}</p>
                <p className="text-xs text-muted-foreground">
                  类型：{detectFileType(file) === "subtitle" ? "字幕文件" : "文本文件"}
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setFile(null)}
                  className="text-xs text-muted-foreground"
                >
                  更换文件
                </Button>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2">
                <Upload className="h-8 w-8 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">
                  拖拽文件到这里，或点击选择
                </p>
                <p className="text-xs text-muted-foreground">
                  支持 .txt / .srt / .ass / .vtt
                </p>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => fileRef.current?.click()}
                  className="mt-1"
                >
                  选择文件
                </Button>
              </div>
            )}
            <input
              ref={fileRef}
              type="file"
              accept=".txt,.srt,.ass,.vtt,.text,.md"
              className="hidden"
              onChange={handleFileChange}
            />
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            取消
          </Button>
          <Button
            onClick={tab === "paste" ? handlePasteImport : handleFileImport}
            disabled={busy || (tab === "paste" ? !pasteText.trim() : !file)}
          >
            {busy && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
            {busy ? "导入中…" : "导入"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
