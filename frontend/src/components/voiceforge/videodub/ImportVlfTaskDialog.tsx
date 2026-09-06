import { useEffect, useState } from "react";
import { FileJson, Film, Import, Loader2, Search } from "lucide-react";
import { historyApi } from "@/api/history";
import { videodubApi } from "@/api/videodub";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { useVideoDubStore } from "./store";
import { uid } from "./types";

type HistoryTask = {
  id: string;
  task_name?: string | null;
  workflow_name?: string | null;
  status: string;
  created_at?: string | null;
};

type VlfFileInfo = { path: string; name: string; size: number; mtime: number };
type VlfFiles = { dubTables: VlfFileInfo[]; videos: VlfFileInfo[] };

type VlfImportPayload = {
  video: { path: string; name: string } | null;
  pairs: Array<{ index: number; start: number; end: number; text: string; translation: string; characterId?: number | string; readCharacterId?: number | string; toneDesc?: string; dialect?: string }>;
  dubClips: Array<{ index: number; path: string; name: string; start: number; duration: number; source: string }>;
  originalClips: Array<{ index: number; path: string; name: string; start: number; duration: number }>;
  stats: { segments: number; missingDub: number; missingRef: number };
};

function formatSize(bytes: number) {
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function formatDateTime(value: number | string | null | undefined) {
  if (value == null) return "";
  const date = typeof value === "number" ? new Date(value * 1000) : new Date(String(value).replace(" ", "T"));
  return Number.isNaN(date.getTime())
    ? ""
    : new Intl.DateTimeFormat("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

/** 导入 vlf 任务：选历史任务 → 选配音任务表与视频 → 解析落轨到当前工作区。 */
export function ImportVlfTaskDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [tasks, setTasks] = useState<HistoryTask[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [tasksError, setTasksError] = useState("");
  const [selectedTaskId, setSelectedTaskId] = useState("");

  const [files, setFiles] = useState<VlfFiles | null>(null);
  const [filesLoading, setFilesLoading] = useState(false);
  const [filesError, setFilesError] = useState("");
  const [selectedDubTable, setSelectedDubTable] = useState("");
  const [selectedVideo, setSelectedVideo] = useState("");

  const [importing, setImporting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    setTasksLoading(true);
    setTasksError("");
    setSelectedTaskId("");
    setFiles(null);
    setError("");
    historyApi
      .list()
      .then((result) => setTasks(result.data.tasks || []))
      .catch(() => setTasksError("历史任务加载失败，请确认主后端已启动"))
      .finally(() => setTasksLoading(false));
  }, [open]);

  const selectTask = async (taskId: string) => {
    setSelectedTaskId(taskId);
    setFiles(null);
    setSelectedDubTable("");
    setSelectedVideo("");
    setFilesError("");
    setFilesLoading(true);
    try {
      const result = await videodubApi.vlfFiles(taskId);
      setFiles(result.data);
      setSelectedDubTable(result.data.dubTables[0]?.path || "");
      setSelectedVideo(result.data.videos[0]?.path || "");
    } catch {
      setFilesError("任务文件列表加载失败（任务工作区可能不存在）");
    } finally {
      setFilesLoading(false);
    }
  };

  const confirmImport = async () => {
    if (!selectedTaskId || !selectedDubTable) return;
    setImporting(true);
    setError("");
    try {
      const result = await videodubApi.vlfImport({
        task_id: selectedTaskId,
        dub_table: selectedDubTable,
        video_path: selectedVideo || undefined,
      });
      const payload = result.data as VlfImportPayload;
      const mediaUrl = (path: string) => videodubApi.vlfMediaUrl(selectedTaskId, path);
      // 视频时长先用最大句尾时间兜底（部分 mkv 元数据加载慢或为 Infinity）
      const estimatedDuration = payload.pairs.reduce((max, pair) => Math.max(max, pair.end), 0);
      // 先构建音频片段数组，再按 index 对齐建立 dubClipId 关联
      const dubbingClips = payload.dubClips.map((clip) => ({
        id: uid(),
        name: clip.name,
        start: clip.start,
        duration: clip.duration,
        url: mediaUrl(clip.path),
        originalDuration: clip.duration,
        source: { taskId: selectedTaskId, path: clip.path },
      }));
      const originalClips = payload.originalClips.map((clip) => ({
        id: uid(),
        name: clip.name,
        start: clip.start,
        duration: clip.duration,
        url: mediaUrl(clip.path),
        source: { taskId: selectedTaskId, path: clip.path },
      }));
      // 建立 dubClipId 关联（按 index 对齐）
      const pairs = payload.pairs.map((pair, idx) => {
        const clip = dubbingClips[idx];
        return {
          id: uid(),
          ...pair,
          dubClipId: clip ? clip.id : undefined,
          dubDuration: clip ? clip.duration : undefined,
          dubStatus: clip ? ("done" as const) : ("idle" as const),
          dubVoiceId: undefined,
        };
      });
      useVideoDubStore.getState().applyVlfImport({
        video: payload.video
          ? { name: payload.video.name, url: mediaUrl(payload.video.path), duration: estimatedDuration, width: 0, height: 0 }
          : null,
        pairs,
        dubbing: dubbingClips,
        originalAudio: originalClips,
      });
      if (payload.stats.missingDub || payload.stats.missingRef) {
        const parts = [`已导入 ${payload.stats.segments} 句`];
        if (payload.stats.missingDub) parts.push(`${payload.stats.missingDub} 句缺配音片段`);
        if (payload.stats.missingRef) parts.push(`${payload.stats.missingRef} 句缺原文片段`);
        window.alert(parts.join("，"));
      }
      onOpenChange(false);
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || "导入失败，请重试");
    } finally {
      setImporting(false);
    }
  };

  const selectedTask = tasks.find((task) => task.id === selectedTaskId);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[85vh] max-w-4xl flex-col">
        <DialogHeader>
          <DialogTitle>导入 vlf 任务</DialogTitle>
          <DialogDescription>选择工作流历史任务，解析其配音任务表（dub_task_*.json），字幕、配音与原文片段将落到当前工作区。</DialogDescription>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 gap-3">
          {/* 左栏：历史任务列表（与历史项目页签同源） */}
          <aside className="flex w-56 flex-none flex-col overflow-hidden rounded-lg border border-border/60 bg-background">
            <div className="flex items-center gap-1.5 border-b border-border/60 px-2.5 py-2 text-xs font-semibold text-foreground/80">
              <Search className="h-3.5 w-3.5 text-muted-foreground" />
              历史任务
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
              {tasksLoading ? (
                <p className="flex items-center justify-center gap-2 py-6 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  加载中…
                </p>
              ) : tasksError ? (
                <p className="p-3 text-xs text-destructive">{tasksError}</p>
              ) : !tasks.length ? (
                <p className="p-3 text-xs text-muted-foreground">暂无历史任务</p>
              ) : (
                tasks.map((task) => (
                  <button
                    key={task.id}
                    type="button"
                    onClick={() => void selectTask(task.id)}
                    className={cn(
                      "mb-1 w-full rounded-md px-2 py-1.5 text-left transition-colors",
                      selectedTaskId === task.id ? "bg-primary/15 ring-1 ring-primary/40" : "hover:bg-muted",
                    )}
                  >
                    <span className="block truncate text-xs font-medium">{task.task_name || task.workflow_name || task.id.slice(0, 8)}</span>
                    <span className="mt-0.5 block truncate text-[10px] text-muted-foreground">
                      {task.workflow_name || "工作流任务"} · {formatDateTime(task.created_at)}
                    </span>
                  </button>
                ))
              )}
            </div>
          </aside>

          {/* 右栏：上下两栏文件选择 */}
          <div className="flex min-h-0 flex-1 flex-col gap-2">
            {!selectedTaskId ? (
              <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed border-border/60 text-sm text-muted-foreground">
                先在左侧选择一个历史任务
              </div>
            ) : filesLoading ? (
              <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                正在扫描任务文件…
              </div>
            ) : filesError ? (
              <div className="flex flex-1 items-center justify-center text-sm text-destructive">{filesError}</div>
            ) : (
              <>
                {/* 上栏：配音任务表 */}
                <section className="flex min-h-0 flex-[2] flex-col overflow-hidden rounded-lg border border-border/60 bg-background">
                  <div className="flex items-center gap-1.5 border-b border-border/60 px-2.5 py-1.5 text-xs font-semibold text-foreground/80">
                    <FileJson className="h-3.5 w-3.5 text-primary" />
                    配音任务表文件（cache/dub_task_*.json）
                  </div>
                  <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
                    {!files?.dubTables.length ? (
                      <p className="p-4 text-xs leading-5 text-muted-foreground">
                        未生成配音任务表，请在工作流中执行生成配音任务表节点后再导入。
                      </p>
                    ) : (
                      files.dubTables.map((file) => (
                        <label
                          key={file.path}
                          className={cn(
                            "mb-1 flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs transition-colors",
                            selectedDubTable === file.path ? "bg-primary/15" : "hover:bg-muted",
                          )}
                        >
                          <input
                            type="radio"
                            name="vlf-dub-table"
                            checked={selectedDubTable === file.path}
                            onChange={() => setSelectedDubTable(file.path)}
                          />
                          <span className="min-w-0 flex-1 truncate font-mono">{file.name}</span>
                          <span className="flex-none text-[10px] text-muted-foreground">
                            {formatSize(file.size)} · {formatDateTime(file.mtime)}
                          </span>
                        </label>
                      ))
                    )}
                  </div>
                </section>

                {/* 下栏：视频文件 */}
                <section className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-border/60 bg-background">
                  <div className="flex items-center gap-1.5 border-b border-border/60 px-2.5 py-1.5 text-xs font-semibold text-foreground/80">
                    <Film className="h-3.5 w-3.5 text-primary" />
                    任务视频文件（默认：adjusted_ &gt; input_ &gt; 最新生成）
                  </div>
                  <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
                    {!files?.videos.length ? (
                      <p className="p-4 text-xs text-muted-foreground">任务文件夹内未检测到视频文件。</p>
                    ) : (
                      files.videos.map((file) => (
                        <label
                          key={file.path}
                          className={cn(
                            "mb-1 flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs transition-colors",
                            selectedVideo === file.path ? "bg-primary/15" : "hover:bg-muted",
                          )}
                        >
                          <input type="radio" name="vlf-video" checked={selectedVideo === file.path} onChange={() => setSelectedVideo(file.path)} />
                          <span className="min-w-0 flex-1 truncate" title={file.path}>
                            {file.name}
                          </span>
                          <span className="flex-none text-[10px] text-muted-foreground">
                            {formatSize(file.size)} · {formatDateTime(file.mtime)}
                          </span>
                        </label>
                      ))
                    )}
                  </div>
                </section>
              </>
            )}
          </div>
        </div>

        {error ? <p className="mt-2 text-xs text-destructive">{error}</p> : null}

        <div className="mt-2 flex items-center justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={() => void confirmImport()} disabled={!selectedDubTable || importing}>
            {importing ? <Loader2 className="mr-1.5 h-4 w-4 animate-spin" /> : <Import className="mr-1.5 h-4 w-4" />}
            解析并导入工作区
          </Button>
        </div>
        {selectedTask?.status === "failed" ? (
          <p className="text-[11px] text-muted-foreground">注意：该任务状态为失败，可导入的产物可能不完整。</p>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
