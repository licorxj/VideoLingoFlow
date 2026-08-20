import { cn } from "@/lib/utils";
import {
  Trash2,
  Clock,
  Loader2,
  CheckCircle2,
  XCircle,
  PauseCircle,
  FolderOpen,
  Workflow,
  ListTodo,
} from "lucide-react";
import client from "@/api/client";

export const STATUS_META: Record<
  string,
  { icon: any; color: string; bg: string; label: string }
> = {
  created: {
    icon: Clock,
    color: "text-amber-500",
    bg: "bg-amber-500/10",
    label: "待执行",
  },
  queued: {
    icon: Clock,
    color: "text-slate-500",
    bg: "bg-slate-500/10",
    label: "排队中",
  },
  running: {
    icon: Loader2,
    color: "text-blue-500",
    bg: "bg-blue-500/10",
    label: "执行中",
  },
  paused: {
    icon: PauseCircle,
    color: "text-amber-500",
    bg: "bg-amber-500/10",
    label: "已暂停",
  },
  interrupted: {
    icon: PauseCircle,
    color: "text-orange-500",
    bg: "bg-orange-500/10",
    label: "等待继续",
  },
  stopping: {
    icon: Loader2,
    color: "text-orange-500",
    bg: "bg-orange-500/10",
    label: "停止中",
  },
  cancelled: {
    icon: XCircle,
    color: "text-zinc-500",
    bg: "bg-zinc-500/10",
    label: "已取消",
  },
  completed: {
    icon: CheckCircle2,
    color: "text-emerald-500",
    bg: "bg-emerald-500/10",
    label: "已完成",
  },
  succeeded: {
    icon: CheckCircle2,
    color: "text-emerald-500",
    bg: "bg-emerald-500/10",
    label: "已完成",
  },
  failed: {
    icon: XCircle,
    color: "text-red-500",
    bg: "bg-red-500/10",
    label: "失败",
  },
  deleting: {
    icon: Loader2,
    color: "text-orange-500",
    bg: "bg-orange-500/10",
    label: "删除中",
  },
  deleted: {
    icon: XCircle,
    color: "text-zinc-500",
    bg: "bg-zinc-500/10",
    label: "已删除",
  },
};

const TASK_TYPE_LABEL: Record<string, string> = {
  normal: "一般任务",
  batch: "批量任务",
  workflow: "工作流编排任务",
};

function formatTime(ts?: string) {
  if (!ts) return "-";
  try {
    return ts.replace("T", " ").substring(0, 19);
  } catch {
    return ts;
  }
}

interface TaskCardProps {
  task: any;
  selected?: boolean;
  onSelect?: (taskId: string, checked: boolean) => void;
  onSelectCard?: (taskId: string) => void;
  onDelete?: (taskId: string) => void;
}

export default function TaskCard({
  task,
  selected,
  onSelect,
  onSelectCard,
  onDelete,
}: TaskCardProps) {
  const cfg = STATUS_META[task.status] || STATUS_META.created;
  const Icon = cfg.icon;
  const name = task.task_name || task.id;
  const taskType =
    TASK_TYPE_LABEL[task.task_type] || task.task_type || "一般任务";

  const handleOpenFolder = async () => {
    try {
      await client.post("/api/tasks/open-file", { file_path: task.id });
    } catch {}
  };

  return (
    <div
      onClick={() => onSelectCard?.(task.id)}
      className={cn(
        "rounded-2xl border border-border/50 bg-card/70 p-4 cursor-pointer transition-all duration-250 card-hover group",
        "hover:border-border",
        selected && "ring-2 ring-primary/40 border-primary/40"
      )}
    >
      {/* Row 1: checkbox + name + task id + status */}
      <div className="flex items-start justify-between mb-2.5">
        <div className="flex items-start gap-2 min-w-0">
          {onSelect && (
            <input
              type="checkbox"
              checked={!!selected}
              onClick={(e) => e.stopPropagation()}
              onChange={(e) => onSelect(task.id, e.target.checked)}
              className="mt-0.5 w-4 h-4 rounded border-border/60 cursor-pointer accent-primary flex-shrink-0"
            />
          )}
          <div className="min-w-0">
            <h3
              className="font-semibold text-sm truncate pr-2 group-hover:text-primary transition-colors duration-200"
              title={name}
            >
              {name}
            </h3>
            <p
              className="text-[11px] font-mono text-muted-foreground/60 truncate mt-0.5"
              title={task.id}
            >
              {task.id}
            </p>
          </div>
        </div>
        <span
          className={cn(
            "flex items-center gap-1 text-[11px] font-medium px-2 py-0.5 rounded-md flex-shrink-0",
            cfg.bg,
            cfg.color
          )}
        >
          <Icon
            className={cn(
              "w-3 h-3",
              ["running", "stopping", "deleting"].includes(task.status) && "animate-spin"
            )}
            strokeWidth={2.5}
          />
          {cfg.label}
        </span>
      </div>

      {/* Row 2: workflow name + task type (single line, truncate overflow) */}
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span
          className="inline-flex items-center gap-1 bg-muted/60 px-2 py-0.5 rounded-md min-w-0"
          title={task.workflow_name || "null"}
        >
          <Workflow className="w-3 h-3 flex-shrink-0" />
          <span className="truncate">{task.workflow_name || "null"}</span>
        </span>
        <span
          className="inline-flex items-center gap-1 bg-muted/60 px-2 py-0.5 rounded-md flex-shrink-0 max-w-[45%]"
          title={taskType}
        >
          <ListTodo className="w-3 h-3 flex-shrink-0" />
          <span className="truncate">{taskType}</span>
        </span>
      </div>

      {/* Row 3: created / finished time */}
      <div className="flex items-center justify-between gap-2 mt-2 text-xs text-muted-foreground/80">
        <span className="flex items-center gap-1 min-w-0">
          <Clock className="w-3 h-3 flex-shrink-0" />
          <span className="truncate font-mono">
            {formatTime(task.created_at)}
          </span>
        </span>
        <span className="flex items-center gap-1 min-w-0">
          <CheckCircle2 className="w-3 h-3 flex-shrink-0" />
          <span className="truncate font-mono">
            {formatTime(task.finished_at)}
          </span>
        </span>
      </div>

      {/* Row 4: action buttons */}
      <div className="flex items-center justify-end gap-1 mt-3 pt-2.5 border-t border-border/40">
        <button
          onClick={(e) => {
            e.stopPropagation();
            handleOpenFolder();
          }}
          className="flex items-center gap-1 text-xs font-semibold text-emerald-600 border border-emerald-400 bg-emerald-500/10 hover:bg-emerald-500/20 px-2 py-1 rounded-md transition-colors duration-200"
          title="打开任务文件夹"
        >
          <FolderOpen className="w-3.5 h-3.5" />
          打开文件夹
        </button>
        {onDelete && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              onDelete(task.id);
            }}
            className="flex items-center gap-1 text-xs font-semibold text-red-600 border border-red-400 bg-red-500/10 hover:bg-red-500/20 px-2 py-1 rounded-md transition-colors duration-200"
            title="删除任务"
          >
            <Trash2 className="w-3.5 h-3.5" />
            删除
          </button>
        )}
      </div>
    </div>
  );
}
