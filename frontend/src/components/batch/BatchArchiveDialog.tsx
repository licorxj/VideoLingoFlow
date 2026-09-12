import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Archive,
  FolderOpen,
  X,
  FileVideo,
  FileText,
  FileImage,
  FileArchive,
  FileAudio,
  Folder,
  Loader2,
  CheckSquare,
  ListChecks,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { batchApi, BatchArchiveFile, BatchArchiveTaskFiles } from "@/api/batch";
import { nativeFileDialog } from "@/api/files";
import { useAlert } from "@/components/ui/AlertProvider";

const TARGET_DIR_STORAGE_KEY = "videolingo:batch-archive-target-dir";

const SECTIONS: {
  key: BatchArchiveFile["category"];
  title: string;
  icon: typeof FileVideo;
  accent: string;
}[] = [
  { key: "video", title: "视频文件", icon: FileVideo, accent: "text-blue-600" },
  { key: "subtitle", title: "字幕文件", icon: FileText, accent: "text-emerald-600" },
  { key: "image", title: "图片文件", icon: FileImage, accent: "text-purple-600" },
  { key: "audio", title: "音频文件", icon: FileAudio, accent: "text-rose-600" },
  { key: "other", title: "其他文件", icon: FileArchive, accent: "text-amber-600" },
];

function formatSize(bytes: number) {
  if (!bytes || bytes < 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value >= 100 || unit === 0 ? Math.round(value) : value.toFixed(1)} ${units[unit]}`;
}

const STATUS_LABELS: Record<string, string> = {
  created: "待执行",
  running: "执行中",
  completed: "已完成",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  paused: "已暂停",
  interrupted: "等待继续",
  archived: "已归档",
};

interface Props {
  batchId: string;
  batchName: string;
  onClose: () => void;
  onArchived: () => void;
}

export default function BatchArchiveDialog({ batchId, batchName, onClose, onArchived }: Props) {
  const { alert: showAlert, confirm: showConfirm } = useAlert();
  const [loading, setLoading] = useState(true);
  const [tasks, setTasks] = useState<BatchArchiveTaskFiles[]>([]);
  const [activeTaskId, setActiveTaskId] = useState("");
  const [selected, setSelected] = useState<Record<string, Set<string>>>({});
  const [targetDir, setTargetDir] = useState(() => localStorage.getItem(TARGET_DIR_STORAGE_KEY) || "");
  const [submitting, setSubmitting] = useState(false);

  // 仅按 batchId 加载一次，避免 AlertProvider 重渲染导致 showAlert 引用变化后重复拉取
  const showAlertRef = useRef(showAlert);
  showAlertRef.current = showAlert;

  const activeTask = useMemo(
    () => tasks.find((t) => t.task_id === activeTaskId) || tasks[0] || null,
    [tasks, activeTaskId],
  );

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      try {
        const res = await batchApi.getArchiveFiles(batchId);
        if (!alive) return;
        const list = res.tasks || [];
        setTasks(list);
        setActiveTaskId(list[0]?.task_id || "");
        // 默认全选所有文件
        const init: Record<string, Set<string>> = {};
        list.forEach((task) => {
          init[task.task_id] = new Set((task.files || []).map((file) => file.path));
        });
        setSelected(init);
      } catch (e: any) {
        if (alive) showAlertRef.current(e?.response?.data?.detail || e?.message || "加载归档产物失败");
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [batchId]);

  const pickTargetDir = useCallback(async () => {
    try {
      const picked = await nativeFileDialog("folder", "选择归档目标文件夹", [], false);
      const path = typeof picked === "string" ? picked : (Array.isArray(picked) ? picked[0] : "");
      if (path) setTargetDir(path);
    } catch (e: any) {
      showAlert(e?.response?.data?.detail || e?.message || "选择文件夹失败");
    }
  }, [showAlert]);

  const toggleFile = (taskId: string, file: BatchArchiveFile, checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev[taskId] || []);
      if (checked) next.add(file.path);
      else next.delete(file.path);
      // 必归档文件不允许取消
      if (file.required) next.add(file.path);
      return { ...prev, [taskId]: next };
    });
  };

  const toggleSection = (taskId: string, category: BatchArchiveFile["category"]) => {
    const files = (activeTask?.files || []).filter((f) => f.category === category);
    if (files.length === 0) return;
    setSelected((prev) => {
      const next = new Set(prev[taskId] || []);
      const allSelected = files.every((f) => f.required || next.has(f.path));
      files.forEach((f) => {
        if (f.required) {
          next.add(f.path);
        } else if (allSelected) {
          next.delete(f.path);
        } else {
          next.add(f.path);
        }
      });
      return { ...prev, [taskId]: next };
    });
  };

  const invertSection = (taskId: string, category: BatchArchiveFile["category"]) => {
    const files = (activeTask?.files || []).filter((f) => f.category === category);
    if (files.length === 0) return;
    setSelected((prev) => {
      const next = new Set(prev[taskId] || []);
      files.forEach((f) => {
        if (f.required) {
          next.add(f.path);
        } else if (next.has(f.path)) {
          next.delete(f.path);
        } else {
          next.add(f.path);
        }
      });
      return { ...prev, [taskId]: next };
    });
  };

  // 音频片段可能很多，按所在子文件夹聚合（如 cache/refe），勾选即对应该文件夹下全部音频
  const toggleAudioFolder = (taskId: string, folder: string) => {
    const files = (activeTask?.files || []).filter(
      (f) => f.category === "audio" && f.path.startsWith(folder + "/"),
    );
    if (files.length === 0) return;
    setSelected((prev) => {
      const next = new Set(prev[taskId] || []);
      const allSelected = files.every((f) => next.has(f.path));
      files.forEach((f) => {
        if (allSelected) next.delete(f.path);
        else next.add(f.path);
      });
      return { ...prev, [taskId]: next };
    });
  };

  const handleConfirm = async () => {
    const dir = targetDir.trim();
    if (!dir) {
      showAlert("请先选择归档目标文件夹");
      return;
    }
    const ok = await showConfirm(
      "归档之后将删除项目记录，并记录归档地址，后期可以从历史项目标签页下的已归档项目加载",
      { type: "warning", title: "确认归档", confirmLabel: "确认归档" },
    );
    if (!ok) return;

    setSubmitting(true);
    try {
      const payload: Record<string, string[]> = {};
      tasks.forEach((task) => {
        payload[task.task_id] = Array.from(selected[task.task_id] || new Set<string>());
      });
      localStorage.setItem(TARGET_DIR_STORAGE_KEY, dir);
      const res = await batchApi.archiveBatch(batchId, dir, payload);
      const archivedCount = res.archived?.length || 0;
      const blockedCount = res.blocked?.length || 0;
      const failedCount = res.failed?.length || 0;
      let message = `已归档 ${archivedCount} 个项目到 ${res.target_dir}`;
      if (blockedCount) message += `，${blockedCount} 个任务被跳过（执行中或已归档）`;
      if (failedCount) message += `，${failedCount} 个任务归档失败`;
      showAlert(message, failedCount ? "warning" : "success");
      onArchived();
      onClose();
    } catch (e: any) {
      showAlert(e?.response?.data?.detail || e?.message || "归档失败");
    } finally {
      setSubmitting(false);
    }
  };

  const activeSelected = activeTask ? selected[activeTask.task_id] || new Set<string>() : new Set<string>();

  // 音频按子文件夹聚合：key=相对父目录路径（如 cache/refe），value=该目录下音频文件列表
  const audioGroups = useMemo(() => {
    const files = (activeTask?.files || []).filter((f) => f.category === "audio");
    const map = new Map<string, BatchArchiveFile[]>();
    for (const f of files) {
      const idx = f.path.lastIndexOf("/");
      const folder = idx >= 0 ? f.path.slice(0, idx) : "";
      const arr = map.get(folder);
      if (arr) arr.push(f);
      else map.set(folder, [f]);
    }
    return Array.from(map.entries()).map(([folder, items]) => ({
      folder,
      items,
      size: items.reduce((sum, it) => sum + it.size, 0),
    }));
  }, [activeTask]);

  const audioFolderChecked = (folder: string) => {
    const items = audioGroups.find((g) => g.folder === folder)?.items || [];
    return items.length > 0 && items.every((f) => activeSelected.has(f.path));
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-card border border-border/50 rounded-2xl shadow-2xl w-[min(1080px,94vw)] h-[min(912px,94vh)] flex flex-col overflow-hidden animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border/40 flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-primary/10">
              <Archive className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h3 className="text-base font-bold">归档批次「{batchName}」</h3>
              <p className="text-xs text-muted-foreground mt-0.5">
                选择要归档的产物文件，归档后本地任务目录将被删除
              </p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-muted transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Target dir */}
        <div className="flex items-center gap-3 px-6 py-3 border-b border-border/40 bg-muted/20 flex-shrink-0">
          <span className="text-xs font-semibold text-muted-foreground flex-shrink-0">归档目标文件夹</span>
          <input
            value={targetDir}
            onChange={(e) => setTargetDir(e.target.value)}
            placeholder="请选择或输入归档目标文件夹，例如 D:\\VideoArchive"
            className="flex-1 px-3 py-1.5 text-sm rounded-lg border border-border/60 bg-background outline-none focus:border-primary/60"
          />
          <button
            onClick={pickTargetDir}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-border/60 hover:bg-accent transition-colors flex-shrink-0"
          >
            <FolderOpen className="w-3.5 h-3.5" />选择文件夹
          </button>
        </div>

        {/* Body */}
        {loading ? (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground gap-2">
            <Loader2 className="w-4 h-4 animate-spin" />正在读取归档产物…
          </div>
        ) : tasks.length === 0 ? (
          <div className="flex-1 flex items-center justify-center text-sm text-muted-foreground">
            该批次暂无可归档的任务
          </div>
        ) : (
          <div className="flex-1 flex min-h-0">
            {/* Task list */}
            <div className="w-[260px] border-r border-border/40 flex flex-col min-h-0">
              <div className="px-4 py-2 text-[11px] font-semibold text-muted-foreground bg-muted/20 border-b border-border/40">
                任务列表（{tasks.length}）
              </div>
              <div className="flex-1 overflow-y-auto p-2 space-y-1">
                {tasks.map((task) => {
                  const active = task.task_id === activeTask?.task_id;
                  const count = (task.files || []).length;
                  return (
                    <button
                      key={task.task_id}
                      onClick={() => setActiveTaskId(task.task_id)}
                      className={cn(
                        "w-full text-left px-3 py-2 rounded-lg border transition-colors",
                        active
                          ? "border-primary/50 bg-primary/10"
                          : "border-transparent hover:bg-accent/50",
                      )}
                    >
                      <div className="text-xs font-semibold truncate" title={task.task_name}>
                        {task.task_name}
                      </div>
                      <div className="mt-0.5 flex items-center gap-2 text-[10px] text-muted-foreground">
                        <span>{STATUS_LABELS[task.status] || task.status}</span>
                        <span>·</span>
                        <span>{task.exists ? `${count} 个文件` : "目录不存在"}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Product sections */}
            <div className="flex-1 min-h-0 overflow-y-auto p-4 space-y-4">
              {SECTIONS.map((section) => {
                const files = (activeTask?.files || []).filter((f) => f.category === section.key);
                const Icon = section.icon;
                const selectedCount = files.filter((f) => activeSelected.has(f.path)).length;
                return (
                  <div key={section.key} className="rounded-xl border border-border/50 overflow-hidden">
                    <div className="flex items-center justify-between px-3 py-2 bg-muted/30 border-b border-border/40">
                      <div className="flex items-center gap-2">
                        <Icon className={cn("w-3.5 h-3.5", section.accent)} />
                        <span className="text-xs font-bold">{section.title}</span>
                        <span className="text-[10px] text-muted-foreground">
                          已选 {selectedCount}/{files.length}
                        </span>
                      </div>
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => activeTask && toggleSection(activeTask.task_id, section.key)}
                          disabled={files.length === 0}
                          className="flex items-center gap-1 px-2 py-0.5 text-[11px] rounded-md hover:bg-accent transition-colors disabled:opacity-40"
                        >
                          <CheckSquare className="w-3 h-3" />全选
                        </button>
                        <button
                          onClick={() => activeTask && invertSection(activeTask.task_id, section.key)}
                          disabled={files.length === 0}
                          className="flex items-center gap-1 px-2 py-0.5 text-[11px] rounded-md hover:bg-accent transition-colors disabled:opacity-40"
                        >
                          <ListChecks className="w-3 h-3" />反选
                        </button>
                      </div>
                    </div>
                    {section.key === "audio" ? (
                      audioGroups.length === 0 ? (
                        <div className="px-3 py-3 text-[11px] text-muted-foreground/70">暂无{section.title}</div>
                      ) : (
                        <div className="divide-y divide-border/30 max-h-[220px] overflow-y-auto">
                          {audioGroups.map((group) => (
                            <label
                              key={group.folder}
                              className="flex items-center gap-2.5 px-3 py-1.5 hover:bg-accent/40 cursor-pointer"
                            >
                              <input
                                type="checkbox"
                                checked={audioFolderChecked(group.folder)}
                                onChange={(e) =>
                                  activeTask && toggleAudioFolder(activeTask.task_id, group.folder)
                                }
                                className="w-3.5 h-3.5 accent-primary flex-shrink-0"
                              />
                              <Folder className="w-3.5 h-3.5 text-rose-500 flex-shrink-0" />
                              <span className="text-xs truncate flex-1" title={group.folder}>
                                {group.folder}
                              </span>
                              <span className="text-[10px] text-muted-foreground flex-shrink-0">
                                {group.items.length} 个 · {formatSize(group.size)}
                              </span>
                            </label>
                          ))}
                        </div>
                      )
                    ) : files.length === 0 ? (
                      <div className="px-3 py-3 text-[11px] text-muted-foreground/70">暂无{section.title}</div>
                    ) : (
                      <div className="divide-y divide-border/30 max-h-[220px] overflow-y-auto">
                        {files.map((file) => {
                          const checked = activeSelected.has(file.path);
                          return (
                            <label
                              key={file.path}
                              className="flex items-center gap-2.5 px-3 py-1.5 hover:bg-accent/40 cursor-pointer"
                            >
                              <input
                                type="checkbox"
                                checked={checked}
                                disabled={file.required}
                                onChange={(e) =>
                                  activeTask && toggleFile(activeTask.task_id, file, e.target.checked)
                                }
                                className="w-3.5 h-3.5 accent-primary flex-shrink-0"
                              />
                              <span className="text-xs truncate flex-1" title={file.path}>
                                {file.path}
                              </span>
                              {file.required && (
                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary flex-shrink-0">
                                  必归档
                                </span>
                              )}
                              <span className="text-[10px] text-muted-foreground flex-shrink-0">
                                {formatSize(file.size)}
                              </span>
                            </label>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between px-6 py-4 border-t border-border/40 flex-shrink-0">
          <p className="text-[11px] text-muted-foreground">
            workflow.json / task.json 始终归档；每个任务以 task.json 中的 task_name 作为归档文件夹名
          </p>
          <div className="flex items-center gap-3">
            <button
              onClick={onClose}
              disabled={submitting}
              className="px-4 py-2 text-sm font-medium rounded-lg border border-border/60 hover:bg-accent transition-colors disabled:opacity-50"
            >
              取消
            </button>
            <button
              onClick={handleConfirm}
              disabled={submitting || loading || tasks.length === 0}
              className="flex items-center gap-1.5 px-5 py-2 text-sm font-semibold rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all active:scale-95"
            >
              {submitting ? <Loader2 className="w-4 h-4 animate-spin" /> : <Archive className="w-4 h-4" />}
              {submitting ? "归档中…" : "确认归档"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
