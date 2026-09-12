import { useEffect, useMemo, useState } from "react";
import {
  ArchiveRestore,
  CheckSquare,
  ListChecks,
  Loader2,
  X,
  FolderArchive,
  AlertTriangle,
} from "lucide-react";
import { historyApi, type ArchivedTask } from "@/api/history";
import { Button } from "@/components/ui/button";
import { useAlert } from "@/components/ui/AlertProvider";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  onClose: () => void;
  /** 载回成功后回调（用于刷新历史项目列表） */
  onRestored: () => void;
}

const formatTime = (iso: string | null) => {
  if (!iso) return "";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
};

export default function ArchivedProjectsDialog({ open, onClose, onRestored }: Props) {
  const { alert: showAlert, confirm: showConfirm } = useAlert();
  const [tasks, setTasks] = useState<ArchivedTask[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await historyApi.listArchived();
      setTasks(res.data.tasks || []);
    } catch (e: any) {
      showAlert(e?.response?.data?.detail || e?.message || "加载已归档项目失败", "error");
      setTasks([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!open) return;
    setSelected(new Set());
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // 仅归档文件夹仍存在的项目可载回
  const selectable = useMemo(() => tasks.filter((t) => t.exists), [tasks]);
  const allSelected =
    selectable.length > 0 && selectable.every((t) => selected.has(t.task_id));

  const toggle = (id: string, checked: boolean) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const handleSelectAll = () => {
    if (selectable.length === 0) return;
    setSelected((prev) => {
      const next = new Set(prev);
      if (allSelected) selectable.forEach((t) => next.delete(t.task_id));
      else selectable.forEach((t) => next.add(t.task_id));
      return next;
    });
  };

  const handleInvert = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      selectable.forEach((t) => {
        if (next.has(t.task_id)) next.delete(t.task_id);
        else next.add(t.task_id);
      });
      return next;
    });
  };

  const handleRestore = async () => {
    if (selected.size === 0) {
      showAlert("请先选择要载回的已归档项目", "warning");
      return;
    }
    const ok = await showConfirm(
      `将载回选中的 ${selected.size} 个项目：以任务ID新建项目目录并复制归档文件，随后删除归档文件夹。`,
      { type: "warning", title: "确认载回", confirmLabel: "确认载回" },
    );
    if (!ok) return;

    setSubmitting(true);
    try {
      const res = await historyApi.restore([...selected]);
      const restored = res.data.restored?.length || 0;
      const failed = res.data.failed || [];
      if (failed.length > 0) {
        showAlert(
          `成功载回 ${restored} 个，失败 ${failed.length} 个：${failed.map((f) => f.error).join("；")}`,
          "warning",
        );
      } else {
        showAlert(`已成功载回 ${restored} 个项目`, "success");
      }
      onRestored();
      onClose();
    } catch (e: any) {
      showAlert(e?.response?.data?.detail || e?.message || "载回失败", "error");
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="bg-card border border-border/50 rounded-2xl shadow-2xl w-[min(820px,94vw)] max-h-[min(640px,88vh)] flex flex-col overflow-hidden animate-scale-in"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border/40 flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-primary/10">
              <ArchiveRestore className="w-5 h-5 text-primary" />
            </div>
            <div>
              <h3 className="text-base font-bold">加载已归档项目</h3>
              <p className="text-xs text-muted-foreground mt-0.5">
                载回后按任务ID重建本地目录，并删除对应归档文件夹
              </p>
            </div>
          </div>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-muted transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Toolbar */}
        <div className="flex items-center justify-between px-6 py-2.5 border-b border-border/40 bg-muted/20 flex-shrink-0">
          <span className="text-xs text-muted-foreground">
            共 {tasks.length} 个已归档项目，可载回 {selectable.length} 个
            {selected.size > 0 && <span className="ml-2 text-primary font-semibold">已选 {selected.size}</span>}
          </span>
          <div className="flex items-center gap-1.5">
            <Button variant="outline" size="sm" onClick={handleSelectAll} disabled={selectable.length === 0}>
              <CheckSquare className="mr-1.5 h-3.5 w-3.5" />
              {allSelected ? "取消全选" : "全选"}
            </Button>
            <Button variant="outline" size="sm" onClick={handleInvert} disabled={selectable.length === 0}>
              <ListChecks className="mr-1.5 h-3.5 w-3.5" />
              反选
            </Button>
          </div>
        </div>

        {/* List */}
        <div className="flex-1 min-h-0 overflow-y-auto p-3">
          {loading ? (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
              <Loader2 className="w-4 h-4 animate-spin" />
              正在加载已归档项目…
            </div>
          ) : tasks.length === 0 ? (
            <div className="flex flex-col items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
              <FolderArchive className="w-8 h-8 text-muted-foreground/40" />
              暂无已归档项目
            </div>
          ) : (
            <div className="space-y-2">
              {tasks.map((task) => {
                const checked = selected.has(task.task_id);
                const disabled = !task.exists;
                return (
                  <label
                    key={task.task_id}
                    className={cn(
                      "flex items-start gap-3 rounded-xl border px-3 py-2.5 transition-colors",
                      disabled
                        ? "border-border/30 bg-muted/20 opacity-60 cursor-not-allowed"
                        : checked
                          ? "border-primary/50 bg-primary/5 cursor-pointer"
                          : "border-border/50 hover:bg-accent/40 cursor-pointer",
                    )}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={disabled}
                      onChange={(e) => toggle(task.task_id, e.target.checked)}
                      className="mt-0.5 w-4 h-4 accent-primary flex-shrink-0"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-semibold truncate" title={task.task_name}>
                          {task.task_name}
                        </span>
                        {task.workflow_name && (
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground flex-shrink-0">
                            {task.workflow_name}
                          </span>
                        )}
                        {disabled && (
                          <span className="flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded bg-destructive/10 text-destructive flex-shrink-0">
                            <AlertTriangle className="w-3 h-3" />
                            归档文件夹不存在
                          </span>
                        )}
                      </div>
                      <div className="mt-1 flex items-center gap-2 text-[11px] text-muted-foreground">
                        <span className="font-mono truncate flex-1" title={task.archive_path}>
                          {task.archive_path || "（未记录归档路径）"}
                        </span>
                        {task.archived_at && (
                          <span className="flex-shrink-0">归档于 {formatTime(task.archived_at)}</span>
                        )}
                      </div>
                    </div>
                  </label>
                );
              })}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 px-6 py-3.5 border-t border-border/40 flex-shrink-0">
          <Button variant="outline" size="sm" onClick={onClose} disabled={submitting}>
            取消
          </Button>
          <Button size="sm" onClick={handleRestore} disabled={submitting || selected.size === 0}>
            {submitting ? (
              <>
                <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
                载回中…
              </>
            ) : (
              <>
                <ArchiveRestore className="mr-1.5 h-4 w-4" />
                载回选中
                {selected.size > 0 && (
                  <span className="ml-1 rounded-md bg-primary-foreground/20 px-1.5 py-0.5 text-[11px] font-semibold">
                    {selected.size}
                  </span>
                )}
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );
}
