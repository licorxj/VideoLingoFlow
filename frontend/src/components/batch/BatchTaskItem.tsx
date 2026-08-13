import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Play, RotateCcw, Square, FolderOpen, Pencil } from "lucide-react";
import client from "@/api/client";
import NodeProgressBar from "./NodeProgressBar";
import { STATUS_META } from "@/components/task/TaskCard";

interface BatchTaskData {
  task_id: string;
  task_name?: string;
  index: number;
  status: string;
  nodes: Record<string, {
    nodeType: string;
    label: string;
    status: string;
    progress: number;
    message: string;
    error: string;
  }>;
  started_at: string;
  finished_at: string;
  error: string;
}

interface Props {
  task: BatchTaskData;
  batchId: string;
  workflowNodes: { id: string; nodeType: string; label: string }[];
  selected: boolean;
  onSelect: (taskId: string, checked: boolean) => void;
  onResume: (taskId: string) => void;
  onRetry: (taskId: string) => void;
  onCancel: (taskId: string) => void;
}

const STATUS_BADGE: Record<string, { label: string; cls: string }> = Object.fromEntries(
  Object.entries(STATUS_META).map(([status, meta]) => [
    status,
    { label: meta.label, cls: cn(meta.bg, meta.color) },
  ])
);

function formatTime(ts: string) {
  if (!ts) return "-";
  try {
    return ts.replace("T", " ").substring(0, 19);
  } catch {
    return ts;
  }
}

export default function BatchTaskItem({ task, workflowNodes, selected, onSelect, onResume, onRetry, onCancel }: Props) {
  const navigate = useNavigate();
  const badge = STATUS_BADGE[task.status] || STATUS_BADGE.created;

  const handleOpenFolder = async () => {
    try {
      await client.post("/api/tasks/open-file", { file_path: task.task_id });
    } catch {}
  };

  const handleEdit = () => {
    navigate("/?task=" + task.task_id);
  };

  return (
    <div className={cn(
      "flex flex-col gap-2 px-4 py-3 border border-border/50 rounded-xl bg-card/50 hover:bg-card/80 transition-colors",
      selected && "ring-2 ring-primary/30 border-primary/30"
    )}>
      {/* Top row: checkbox + task name + task id + status + time + actions */}
      <div className="flex items-center gap-3">
        <input
          type="checkbox"
          checked={selected}
          onChange={(e) => onSelect(task.task_id, e.target.checked)}
          className="w-4 h-4 rounded border-border/60 cursor-pointer accent-primary flex-shrink-0"
        />

        {/* Task name as primary label */}
        <span className="text-sm font-medium truncate" title={task.task_name || task.task_id}>
          {task.task_name || task.task_id.substring(0, 8)}
        </span>

        {/* Task ID as small badge */}
        <span className="text-[10px] font-mono text-muted-foreground/60 bg-muted/50 px-1.5 py-0.5 rounded flex-shrink-0" title={task.task_id}>
          {task.task_id.substring(0, 8)}
        </span>

        <span className={cn("text-[10px] font-semibold px-1.5 py-0.5 rounded-md flex-shrink-0", badge.cls)}>
          {badge.label}
        </span>

        <span className="text-xs text-muted-foreground flex-1 text-right">
          {formatTime(task.started_at)} {task.finished_at ? `→ ${formatTime(task.finished_at)}` : ""}
        </span>

        {/* Action buttons */}
        <div className="flex items-center gap-1 flex-shrink-0">
          <button
            onClick={handleOpenFolder}
            className="p-1.5 rounded-lg hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
            title="打开任务文件夹"
          >
            <FolderOpen className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={handleEdit}
            className="p-1.5 rounded-lg hover:bg-accent transition-colors text-muted-foreground hover:text-primary"
            title="编辑工作流"
          >
            <Pencil className="w-3.5 h-3.5" />
          </button>
          <span className="w-px h-4 bg-border/40" />
          {/* 断点继续 (resume from checkpoint) */}
          {(task.status === "created" || task.status === "paused" || task.status === "failed" || task.status === "cancelled") && (
            <button
              onClick={() => onResume(task.task_id)}
              className="p-1.5 rounded-lg hover:bg-emerald-50 dark:hover:bg-emerald-950 transition-colors text-muted-foreground hover:text-emerald-500"
              title="断点继续"
            >
              <Play className="w-3.5 h-3.5" />
            </button>
          )}
          {/* 从头执行 (restart from scratch) */}
          {(task.status === "failed" || task.status === "cancelled") && (
            <button
              onClick={() => onRetry(task.task_id)}
              className="p-1.5 rounded-lg hover:bg-accent transition-colors text-muted-foreground hover:text-foreground"
              title="从头执行"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>
          )}
          {/* running → 停止 */}
          {task.status === "running" && (
            <button
              onClick={() => onCancel(task.task_id)}
              className="p-1.5 rounded-lg hover:bg-red-50 dark:hover:bg-red-950 transition-colors text-muted-foreground hover:text-red-500"
              title="停止"
            >
              <Square className="w-3.5 h-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Bottom row: progress bar */}
      <NodeProgressBar nodes={task.nodes} workflowNodes={workflowNodes} />

      {/* Error message if failed */}
      {task.error && (
        <p className="text-[11px] text-red-500 truncate">{task.error}</p>
      )}
    </div>
  );
}