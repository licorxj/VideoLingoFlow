import { useEffect, useMemo, useState } from "react";
import { Check, FileAudio, FileImage, FileText, Film, Loader2, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { type EditorAsset, type EditorTask, editorApi } from "@/api/editor";
import { cn } from "@/lib/utils";

const categoryLabels: Record<string, string> = { video: "视频", audio: "配音与音频", subtitle: "字幕", cover: "封面图片", other: "其他素材" };

function formatBytes(value: number) {
  if (value < 1024 * 1024) return `${Math.max(1, Math.round(value / 1024))} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function MediaIcon({ type }: { type: EditorAsset["type"] }) {
  const Icon = type === "video" ? Film : type === "audio" ? FileAudio : type === "subtitle" ? FileText : FileImage;
  return <Icon className="h-4 w-4" />;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onImported: (taskId: string) => void;
}

export default function TaskImportDialog({ open, onOpenChange, onImported }: Props) {
  const [tasks, setTasks] = useState<EditorTask[]>([]);
  const [selectedTask, setSelectedTask] = useState<EditorTask | null>(null);
  const [candidates, setCandidates] = useState<EditorAsset[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [coverId, setCoverId] = useState<string>();
  const [useDubSegments, setUseDubSegments] = useState(false);
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    if (!open) return;
    setSelectedTask(null);
    setCandidates([]);
    setSelectedIds([]);
    setCoverId(undefined);
    setUseDubSegments(false);
    setLoading(true);
    editorApi.listTasks().then((response) => setTasks(response.data.tasks)).catch(() => setTasks([])).finally(() => setLoading(false));
  }, [open]);

  const visibleTasks = useMemo(() => tasks.filter((task) => task.task_name.toLowerCase().includes(query.toLowerCase())), [query, tasks]);
  const grouped = useMemo(() => candidates.reduce<Record<string, EditorAsset[]>>((result, item) => {
    const key = item.category || "other";
    (result[key] ||= []).push(item);
    return result;
  }, {}), [candidates]);

  const chooseTask = async (task: EditorTask) => {
    setSelectedTask(task);
    setLoading(true);
    try {
      const response = await editorApi.getCandidates(task.id);
      setCandidates(response.data.candidates);
      setSelectedIds(response.data.candidates.filter((item) => item.selected && item.category !== "cover").map((item) => item.id));
      setCoverId(response.data.candidates.find((item) => item.category === "cover" && item.selected)?.id);
      setUseDubSegments(false);
    } finally {
      setLoading(false);
    }
  };

  const toggle = (id: string) => setSelectedIds((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]);
  const selectVideo = (id: string) => setSelectedIds((current) => [...current.filter((item) => candidates.find((candidate) => candidate.id === item)?.category !== "video"), id]);
  const toggleCover = (id: string) => setCoverId((current) => current === id ? undefined : id);
  const toggleDubSegments = (enabled: boolean) => {
    setUseDubSegments(enabled);
    if (enabled) setSelectedIds((current) => current.filter((id) => candidates.find((candidate) => candidate.id === id)?.category !== "audio"));
  };
  const importTask = async () => {
    if (!selectedTask) return;
    const candidateIds = candidates.filter((item) => {
      if (item.category === "cover") return item.id === coverId;
      return selectedIds.includes(item.id);
    }).map((item) => item.id);
    if (!candidateIds.length && !useDubSegments) return;
    setImporting(true);
    try {
      await editorApi.importAssets(selectedTask.id, { candidate_ids: candidateIds, use_dub_segments: useDubSegments });
      onOpenChange(false);
      onImported(selectedTask.id);
    } finally {
      setImporting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[min(720px,calc(100vh-2rem))] max-w-5xl flex-col overflow-hidden p-0">
        <DialogHeader className="border-b border-border/70 p-6 pr-12">
          <DialogTitle>导入历史任务素材</DialogTitle>
          <DialogDescription>选择一个已完成任务，再确认要加入剪辑项目的视频、配音、字幕和封面素材。</DialogDescription>
        </DialogHeader>
        <div className="grid min-h-0 flex-1 grid-cols-[minmax(240px,0.8fr)_minmax(0,1.4fr)]">
          <section className="flex min-h-0 flex-col border-r border-border/70 p-4">
            <div className="relative mb-3"><Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" /><Input value={query} onChange={(event) => setQuery(event.target.value)} className="pl-9" placeholder="搜索任务" /></div>
            {loading && !selectedTask ? <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin" /></div> : <div className="min-h-0 flex-1 space-y-1.5 overflow-y-auto pr-1">
              {visibleTasks.map((task) => <button key={task.id} onClick={() => chooseTask(task)} className={cn("w-full rounded-lg border px-3 py-3 text-left transition-colors", selectedTask?.id === task.id ? "border-primary bg-primary/10" : "border-transparent hover:bg-muted") }>
                <div className="flex items-center justify-between gap-2"><span className="truncate text-sm font-semibold">{task.task_name}</span>{task.has_project && <span className="text-[10px] text-primary">已编辑</span>}</div>
                <div className="mt-1 truncate text-xs text-muted-foreground">{task.id} · {task.status === "completed" || task.status === "succeeded" ? "已完成" : "已失败"}</div>
              </button>)}
              {!visibleTasks.length && <p className="px-2 py-8 text-center text-sm text-muted-foreground">没有可导入的历史任务</p>}
            </div>}
          </section>
          <section className="flex min-h-0 min-w-0 flex-col overflow-hidden">
            {!selectedTask ? <div className="flex flex-1 items-center justify-center p-10 text-sm text-muted-foreground">从左侧选择任务以查看自动识别的素材。</div> : <>
              <div className="border-b border-border/70 px-6 py-4"><div className="text-sm font-semibold">{selectedTask.task_name}</div><div className="mt-1 text-xs text-muted-foreground">默认选择最终输出素材，你可以按需增减。</div></div>
              <div className="flex-1 space-y-5 overflow-y-auto p-6">
                {loading ? <div className="flex justify-center py-12"><Loader2 className="h-5 w-5 animate-spin" /></div> : Object.entries(grouped).map(([category, items]) => <div key={category}><h3 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">{categoryLabels[category]}</h3><div className="space-y-1">{items.map((item) => {
                  const selected = category === "cover" ? coverId === item.id : selectedIds.includes(item.id);
                  const singleSelect = category === "video" || category === "cover";
                  return <button key={item.id} onClick={() => category === "cover" ? toggleCover(item.id) : category === "video" ? selectVideo(item.id) : toggle(item.id)} className={cn("flex w-full items-center gap-3 rounded-lg border px-3 py-2.5 text-left", selected ? "border-primary/50 bg-primary/10" : "border-border/60 hover:bg-muted/70") }><span className={cn("flex h-5 w-5 items-center justify-center border", singleSelect ? "rounded-full" : "rounded", selected ? "border-primary bg-primary text-primary-foreground" : "border-muted-foreground/40")}>{selected && <Check className="h-3.5 w-3.5" />}</span><span className="text-muted-foreground"><MediaIcon type={item.type} /></span><span className="min-w-0 flex-1"><span className="block truncate text-sm">{item.name}</span><span className="block truncate text-xs text-muted-foreground">{item.relative_path} · {formatBytes(item.size)}</span></span></button>;
                })}</div></div>)}
              </div>
              <div className="flex items-center justify-between border-t border-border/70 px-6 py-3"><span className="text-sm">使用配音片段作为音频</span><Switch checked={useDubSegments} onCheckedChange={toggleDubSegments} aria-label="使用配音片段作为音频" /></div>
              <div className="flex items-center justify-between border-t border-border/70 px-6 py-4"><span className="text-sm text-muted-foreground">已选择 {selectedIds.length + (coverId ? 1 : 0)} 个素材</span><Button disabled={!(selectedIds.length || coverId || useDubSegments) || importing} onClick={importTask}>{importing && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}导入剪辑项目</Button></div>
            </>}
          </section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
