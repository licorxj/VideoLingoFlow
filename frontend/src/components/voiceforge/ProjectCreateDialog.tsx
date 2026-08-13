import { useEffect, useState } from "react";
import { Captions, FileInput, FileText, FolderPlus, Loader2, X } from "lucide-react";
import { voiceForgeApi } from "@/api/voiceforge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";

type CreateMode = "subtitle" | "txt" | "paste";

const MODE_OPTIONS: Array<{ value: CreateMode; label: string; icon: any }> = [
  { value: "subtitle", label: "字幕导入", icon: Captions },
  { value: "txt", label: "txt 文档导入", icon: FileText },
  { value: "paste", label: "直接粘贴", icon: FileInput },
];

function errorText(error: any, fallback: string) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg;
  return error?.message || fallback;
}

export function ProjectCreateDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: (projectId: string) => void;
}) {
  const [name, setName] = useState("");
  const [mode, setMode] = useState<CreateMode>("paste");
  const [file, setFile] = useState<File | null>(null);
  const [pasteText, setPasteText] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");

  useEffect(() => {
    if (open) {
      setName("");
      setMode("paste");
      setFile(null);
      setPasteText("");
      setError("");
    }
  }, [open]);

  const switchMode = (value: CreateMode) => {
    setMode(value);
    setFile(null);
    setError("");
  };

  const create = async () => {
    if (!name.trim()) {
      setError("请输入项目名称");
      return;
    }
    setBusy("create");
    setError("");
    try {
      const response = await voiceForgeApi.createProject({ name: name.trim() });
      const projectId = response.data.project.id;
      const hasContent = mode === "paste" ? Boolean(pasteText.trim()) : Boolean(file);
      if (hasContent) {
        await voiceForgeApi.importContent(projectId, mode, file || undefined, pasteText);
      }
      onCreated(projectId);
    } catch (err) {
      setError(errorText(err, "创建项目失败"));
    } finally {
      setBusy("");
    }
  };

  return (
    <Dialog open={open} onOpenChange={(value) => !value && !busy && onClose()}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>新建项目</DialogTitle>
          <DialogDescription>输入项目名称，并按需选择导入方式创建初始内容。</DialogDescription>
        </DialogHeader>
        <div className="grid gap-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">项目名称 <span className="text-destructive">*</span></label>
            <input value={name} onChange={(event) => setName(event.target.value)} autoFocus placeholder="例如：第一章 · 重逢" className="voice-input" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-muted-foreground">创建方式</label>
            <div className="grid grid-cols-3 gap-2">
              {MODE_OPTIONS.map((option) => {
                const Icon = option.icon;
                const active = mode === option.value;
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => switchMode(option.value)}
                    className={`flex flex-col items-center gap-1.5 rounded-lg border px-3 py-2.5 text-sm ${active ? "border-primary/60 bg-primary/10 text-primary" : "border-border/60 text-muted-foreground hover:bg-accent"}`}
                  >
                    <Icon className="h-4 w-4" />
                    {option.label}
                  </button>
                );
              })}
            </div>
          </div>
          {mode === "paste" ? (
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">粘贴文本内容（留空则创建空项目）</label>
              <textarea
                value={pasteText}
                onChange={(event) => setPasteText(event.target.value)}
                placeholder="将小说、剧本等文本粘贴到这里，创建项目时自动按标点分句导入…"
                className="voice-input min-h-40 resize-y"
              />
            </div>
          ) : (
            <div>
              <label className="mb-1 block text-xs font-medium text-muted-foreground">
                {mode === "subtitle" ? "字幕文件（SRT / ASS / VTT）" : "文本文件（TXT，自动识别编码与分句）"}
              </label>
              <label className="flex cursor-pointer items-center justify-center gap-2 rounded-lg border border-dashed border-border/70 bg-muted/20 px-4 py-6 text-sm text-muted-foreground hover:border-primary/50 hover:bg-accent">
                {file ? (
                  <>
                    <span className="min-w-0 flex-1 truncate text-left">{file.name}</span>
                    <button
                      type="button"
                      onClick={(event) => { event.preventDefault(); event.stopPropagation(); setFile(null); }}
                      className="shrink-0 text-muted-foreground hover:text-destructive"
                      title="移除文件"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </>
                ) : (
                  <span className="flex items-center gap-2"><FolderPlus className="h-5 w-5" />点击选择{mode === "subtitle" ? "字幕" : "文本"}文件</span>
                )}
                <input
                  type="file"
                  accept={mode === "subtitle" ? ".srt,.ass,.vtt" : ".txt,.text,.md"}
                  className="hidden"
                  onChange={(event) => setFile(event.target.files?.[0] || null)}
                />
              </label>
            </div>
          )}
          {error && <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy === "create"}>取消</Button>
          <Button onClick={() => void create()} disabled={busy === "create" || !name.trim()}>
            {busy === "create" ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <FolderPlus className="mr-1.5 h-4 w-4" />}
            {busy === "create" ? "创建中…" : "新建项目"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
